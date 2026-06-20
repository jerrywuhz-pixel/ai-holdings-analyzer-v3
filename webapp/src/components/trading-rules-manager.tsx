'use client';

import { FormEvent, useMemo, useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { StatusPill } from '@/components/p0-ui';
import type { DisciplineCheck, TradingRule, TradingRuleAction, TradingRuleSource } from '@/lib/trading-rules';

const fieldClass =
  'mt-1 w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition focus:border-[#d71920]';
const labelClass = 'text-xs font-medium text-[#6f686b]';

function actionLabel(action: TradingRuleAction) {
  if (action === 'block') return '阻止继续';
  if (action === 'require_confirmation') return '需要确认';
  return '提醒我';
}

function resultLabel(result: string) {
  if (result === 'blocked') return '已阻止';
  if (result === 'requires_confirmation') return '待确认';
  if (result === 'warned') return '已提醒';
  return '已通过';
}

function resultTone(result: string): 'positive' | 'warning' | 'danger' | 'muted' {
  if (result === 'blocked') return 'danger';
  if (result === 'requires_confirmation' || result === 'warned') return 'warning';
  if (result === 'passed') return 'positive';
  return 'muted';
}

function conditionSummary(rule: TradingRule) {
  const condition = rule.condition ?? {};
  const symbols = Array.isArray(condition.symbol_patterns) ? condition.symbol_patterns.join(', ') : '';
  const names = Array.isArray(condition.match_name_keywords) ? condition.match_name_keywords.join(', ') : '';
  const sourceTiers = Array.isArray(condition.source_tiers) ? condition.source_tiers.join(', ') : '';
  const parts = [
    rule.markets.length ? `市场 ${rule.markets.join('/')}` : '',
    rule.instruments.length ? `品种 ${rule.instruments.join('/')}` : '',
    symbols ? `代码 ${symbols}` : '',
    names ? `名称 ${names}` : '',
    sourceTiers ? `来源 ${sourceTiers}` : '',
    condition.forbid_extended_hours ? '盘前盘后时段' : '',
    typeof condition.min_cash_buffer_pct === 'number' ? `现金缓冲低于 ${condition.min_cash_buffer_pct}%` : '',
  ].filter(Boolean);
  return parts.join(' · ') || '按规则范围检查';
}

function sourceLabel(source: string) {
  if (source === 'system') return '系统默认';
  if (source === 'wechat_channel' || source === 'wechat') return '微信渠道';
  return 'Web 侧写入';
}

function sourceTone(source: string): 'positive' | 'warning' | 'danger' | 'muted' {
  if (source === 'wechat_channel' || source === 'wechat') return 'positive';
  if (source === 'system') return 'muted';
  return 'warning';
}

export default function TradingRulesManager({
  initialRules,
  recentChecks,
}: {
  initialRules: TradingRule[];
  recentChecks: DisciplineCheck[];
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState('');
  const [ruleType, setRuleType] = useState('blocklist');
  const [action, setAction] = useState<TradingRuleAction>('warn');
  const [source, setSource] = useState<TradingRuleSource>('webapp');
  const [scope, setScope] = useState('manual_position');
  const [markets, setMarkets] = useState('US,HK,CN');
  const [symbols, setSymbols] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const sortedRules = useMemo(
    () => [...initialRules].sort((left, right) => Number(right.isActive) - Number(left.isActive) || left.priority - right.priority),
    [initialRules]
  );

  async function mutateRule(ruleId: string, payload: Record<string, unknown>) {
    setError('');
    setNotice('');
    const response = await fetch(`/api/rules/${ruleId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      setError(result.error || '规则更新失败');
      return;
    }
    setNotice('规则已更新');
    startTransition(() => router.refresh());
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setNotice('');

    const symbolPatterns = symbols
      .split(/[\n,，]/)
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
    const condition: Record<string, unknown> = {};
    if (symbolPatterns.length) condition.symbol_patterns = symbolPatterns;
    if (scope === 'manual_position') condition.source_tiers = ['user_confirmed', 'estimated'];

    const response = await fetch('/api/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        ruleType,
        actionOnViolation: action,
        scopes: [scope],
        markets,
        instruments: ['stock', 'etf', 'option_contract'],
        condition,
        message,
        priority: 60,
        source,
      }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      setError(result.error || '规则创建失败');
      return;
    }

    setNotice('规则已创建');
    setCreateOpen(false);
    setName('');
    setRuleType('blocklist');
    setAction('warn');
    setSource('webapp');
    setScope('manual_position');
    setMarkets('US,HK,CN');
    setSymbols('');
    setMessage('');
    startTransition(() => router.refresh());
  }

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="font-medium text-[#171417]">规则列表</p>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-[#6f686b]">
              规则按当前登录账号的 tenant 隔离保存。后续 cron 只扫描本账号启用规则，并通过已绑定微信渠道主动提醒。
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setError('');
              setNotice('');
              setCreateOpen(true);
            }}
            className="rounded-lg bg-[#d71920] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#bd151b]"
          >
            新增规则
          </button>
        </div>

        {notice ? <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</p> : null}
        {error && !createOpen ? <p className="mt-3 rounded-lg border border-[#f0c8c5] bg-[#fff0ef] p-3 text-sm text-[#d71920]">{error}</p> : null}

        <div className="mt-4 space-y-3">
          {sortedRules.map((rule) => (
            <div key={rule.id} className="rounded-lg border border-[#e5ddd9] bg-[#fffaf8] p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-[#171417]">{rule.name}</p>
                    <StatusPill tone={rule.isActive ? 'positive' : 'muted'}>{rule.isActive ? '已启用' : '已停用'}</StatusPill>
                    <StatusPill tone={sourceTone(rule.source)}>{sourceLabel(rule.source)}</StatusPill>
                    <StatusPill tone={rule.actionOnViolation === 'block' ? 'danger' : rule.actionOnViolation === 'require_confirmation' ? 'warning' : 'muted'}>
                      {actionLabel(rule.actionOnViolation)}
                    </StatusPill>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-[#6f686b]">{rule.message}</p>
                  <p className="mt-2 text-xs leading-5 text-[#8a817d]">{conditionSummary(rule)}</p>
                  <p className="mt-2 text-xs text-[#8a817d]">
                    最近触发 {rule.triggerCount} 次{rule.lastTriggeredAt ? ` · ${new Date(rule.lastTriggeredAt).toLocaleString('zh-CN')}` : ''}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={rule.actionOnViolation}
                    onChange={(event) => mutateRule(rule.id, { actionOnViolation: event.target.value })}
                    className="rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition focus:border-[#d71920]"
                  >
                    <option value="warn">提醒我</option>
                    <option value="require_confirmation">需要确认</option>
                    <option value="block">阻止继续</option>
                  </select>
                  <button
                    type="button"
                    disabled={isPending}
                    onClick={() => mutateRule(rule.id, { isActive: !rule.isActive })}
                    className="rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#4f494c] transition hover:border-[#d71920] disabled:opacity-60"
                  >
                    {rule.isActive ? '停用' : '启用'}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {createOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[#171417]/35 px-4 py-6"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setCreateOpen(false);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-trading-rule-title"
            className="w-full max-w-3xl rounded-lg border border-[#e5ddd9] bg-white shadow-[0_24px_80px_rgba(23,20,23,0.18)]"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b border-[#eee6e2] px-5 py-4">
              <div>
                <h2 id="new-trading-rule-title" className="text-lg font-semibold text-[#171417]">
                  新增纪律规则
                </h2>
                <p className="mt-1 text-sm text-[#6f686b]">配置来源、检查场景和命中后的处理动作，保存后立即写入当前账号规则列表。</p>
              </div>
              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                className="rounded-lg border border-[#e5ddd9] px-3 py-2 text-sm text-[#4f494c] transition hover:border-[#d71920]"
              >
                关闭
              </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-4 px-5 py-5">
              <label className="block">
                <span className={labelClass}>规则名称</span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  required
                  placeholder="例如 不买高杠杆 ETF"
                  className={fieldClass}
                />
              </label>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className={labelClass}>规则引入来源</span>
                  <select value={source} onChange={(event) => setSource(event.target.value as TradingRuleSource)} className={fieldClass}>
                    <option value="webapp">Web 侧写入</option>
                    <option value="wechat_channel">微信渠道</option>
                  </select>
                </label>
                <label className="block">
                  <span className={labelClass}>规则类型</span>
                  <select value={ruleType} onChange={(event) => setRuleType(event.target.value)} className={fieldClass}>
                    <option value="blocklist">禁买/慎买名单</option>
                    <option value="confirmation_required">需要确认</option>
                    <option value="risk_budget">资金纪律</option>
                    <option value="time_window">交易时段</option>
                    <option value="custom">自定义</option>
                  </select>
                </label>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className={labelClass}>命中后动作</span>
                  <select value={action} onChange={(event) => setAction(event.target.value as TradingRuleAction)} className={fieldClass}>
                    <option value="warn">提醒我</option>
                    <option value="require_confirmation">需要确认</option>
                    <option value="block">阻止继续</option>
                  </select>
                </label>
                <label className="block">
                  <span className={labelClass}>检查场景</span>
                  <select value={scope} onChange={(event) => setScope(event.target.value)} className={fieldClass}>
                    <option value="manual_position">记录持仓</option>
                    <option value="trade_draft">交易草稿</option>
                    <option value="sell_put">Sell Put 策略</option>
                    <option value="stock">股票/ETF</option>
                  </select>
                </label>
              </div>

              <label className="block">
                <span className={labelClass}>适用市场</span>
                <input value={markets} onChange={(event) => setMarkets(event.target.value.toUpperCase())} className={fieldClass} />
              </label>

              <label className="block">
                <span className={labelClass}>标的代码</span>
                <textarea
                  value={symbols}
                  onChange={(event) => setSymbols(event.target.value)}
                  rows={3}
                  placeholder="多个代码可用换行或逗号分隔，例如 600519, HK00700"
                  className={fieldClass}
                />
              </label>

              <label className="block">
                <span className={labelClass}>提醒文案</span>
                <textarea
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  rows={3}
                  placeholder="例如 这类标的不符合我的交易纪律，除非有明确复盘理由。"
                  className={fieldClass}
                />
              </label>

              <div className="rounded-lg border border-[#e5ddd9] bg-[#fffaf8] p-3 text-sm leading-6 text-[#6f686b]">
                保存后规则会写入当前登录账号 tenant；后续定时任务可以按来源与启用状态筛选规则，并通过微信渠道主动提醒。
              </div>

              {error ? <p className="rounded-lg border border-[#f0c8c5] bg-[#fff0ef] p-3 text-sm text-[#d71920]">{error}</p> : null}

              <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  onClick={() => setCreateOpen(false)}
                  className="rounded-lg border border-[#e5ddd9] px-4 py-2 text-sm text-[#4f494c] transition hover:border-[#d71920]"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={isPending}
                  className="rounded-lg bg-[#d71920] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#bd151b] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  保存规则
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <p className="font-medium text-[#171417]">最近纪律检查</p>
          <StatusPill tone="muted">{recentChecks.length} 条记录</StatusPill>
        </div>
        <div className="space-y-2">
          {recentChecks.length ? (
            recentChecks.map((check) => (
              <div key={check.id} className="flex flex-col gap-2 rounded-lg border border-[#e5ddd9] bg-[#fffaf8] px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-[#4f494c]">
                    {check.symbol || '未指定标的'} · {check.actionType}
                  </p>
                  <p className="mt-1 text-xs text-[#8a817d]">{new Date(check.createdAt).toLocaleString('zh-CN')}</p>
                </div>
                <StatusPill tone={resultTone(check.result)}>{resultLabel(check.result)}</StatusPill>
              </div>
            ))
          ) : (
            <p className="text-sm text-[#6f686b]">还没有纪律检查记录。记录持仓或生成交易草稿后，这里会显示命中情况。</p>
          )}
        </div>
      </div>
    </div>
  );
}
