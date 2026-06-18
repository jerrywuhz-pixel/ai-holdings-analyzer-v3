'use client';

import { FormEvent, useMemo, useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { StatusPill } from '@/components/p0-ui';
import type { DisciplineCheck, TradingRule, TradingRuleAction } from '@/lib/trading-rules';

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

export default function TradingRulesManager({
  initialRules,
  recentChecks,
}: {
  initialRules: TradingRule[];
  recentChecks: DisciplineCheck[];
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [name, setName] = useState('');
  const [ruleType, setRuleType] = useState('blocklist');
  const [action, setAction] = useState<TradingRuleAction>('warn');
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
      }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      setError(result.error || '规则创建失败');
      return;
    }

    setNotice('规则已创建');
    setName('');
    setSymbols('');
    setMessage('');
    startTransition(() => router.refresh());
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-3">
          {sortedRules.map((rule) => (
            <div key={rule.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-white">{rule.name}</p>
                    <StatusPill tone={rule.isActive ? 'positive' : 'muted'}>{rule.isActive ? '已启用' : '已停用'}</StatusPill>
                    <StatusPill tone={rule.actionOnViolation === 'block' ? 'danger' : rule.actionOnViolation === 'require_confirmation' ? 'warning' : 'muted'}>
                      {actionLabel(rule.actionOnViolation)}
                    </StatusPill>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-slate-400">{rule.message}</p>
                  <p className="mt-2 text-xs leading-5 text-slate-500">{conditionSummary(rule)}</p>
                  <p className="mt-2 text-xs text-slate-500">
                    最近触发 {rule.triggerCount} 次{rule.lastTriggeredAt ? ` · ${new Date(rule.lastTriggeredAt).toLocaleString('zh-CN')}` : ''}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={rule.actionOnViolation}
                    onChange={(event) => mutateRule(rule.id, { actionOnViolation: event.target.value })}
                    className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
                  >
                    <option value="warn">提醒我</option>
                    <option value="require_confirmation">需要确认</option>
                    <option value="block">阻止继续</option>
                  </select>
                  <button
                    type="button"
                    disabled={isPending}
                    onClick={() => mutateRule(rule.id, { isActive: !rule.isActive })}
                    className="rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-100 transition hover:border-red-300/60 disabled:opacity-60"
                  >
                    {rule.isActive ? '停用' : '启用'}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        <form onSubmit={handleCreate} className="space-y-3 rounded-xl border border-white/8 bg-white/[0.03] p-4">
          <div>
            <p className="font-medium text-white">新增纪律规则</p>
            <p className="mt-1 text-sm text-slate-400">适合记录禁买标的、特殊提醒和需要确认的操作边界。</p>
          </div>
          <label className="block">
            <span className="text-xs font-medium text-slate-400">规则名称</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              placeholder="例如 不买高杠杆 ETF"
              className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="text-xs font-medium text-slate-400">规则类型</span>
              <select
                value={ruleType}
                onChange={(event) => setRuleType(event.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
              >
                <option value="blocklist">禁买/慎买名单</option>
                <option value="confirmation_required">需要确认</option>
                <option value="risk_budget">资金纪律</option>
                <option value="time_window">交易时段</option>
                <option value="custom">自定义</option>
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-medium text-slate-400">命中后动作</span>
              <select
                value={action}
                onChange={(event) => setAction(event.target.value as TradingRuleAction)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
              >
                <option value="warn">提醒我</option>
                <option value="require_confirmation">需要确认</option>
                <option value="block">阻止继续</option>
              </select>
            </label>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="text-xs font-medium text-slate-400">检查场景</span>
              <select
                value={scope}
                onChange={(event) => setScope(event.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
              >
                <option value="manual_position">记录持仓</option>
                <option value="trade_draft">交易草稿</option>
                <option value="sell_put">Sell Put 策略</option>
                <option value="stock">股票/ETF</option>
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-medium text-slate-400">适用市场</span>
              <input
                value={markets}
                onChange={(event) => setMarkets(event.target.value.toUpperCase())}
                className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
              />
            </label>
          </div>
          <label className="block">
            <span className="text-xs font-medium text-slate-400">标的代码</span>
            <textarea
              value={symbols}
              onChange={(event) => setSymbols(event.target.value)}
              rows={3}
              placeholder="多个代码可用换行或逗号分隔，例如 BABA, PDD"
              className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-400">提醒文案</span>
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              rows={3}
              placeholder="例如 这类标的不符合我的交易纪律，除非有明确复盘理由。"
              className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
            />
          </label>
          {notice ? <p className="rounded-xl border border-emerald-400/20 bg-emerald-500/10 p-3 text-sm text-emerald-100">{notice}</p> : null}
          {error ? <p className="rounded-xl border border-red-400/20 bg-red-500/10 p-3 text-sm text-red-100">{error}</p> : null}
          <button
            type="submit"
            disabled={isPending}
            className="rounded-xl bg-red-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-60"
          >
            保存规则
          </button>
        </form>
      </div>

      <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <p className="font-medium text-white">最近纪律检查</p>
          <StatusPill tone="muted">{recentChecks.length} 条记录</StatusPill>
        </div>
        <div className="space-y-2">
          {recentChecks.length ? (
            recentChecks.map((check) => (
              <div key={check.id} className="flex flex-col gap-2 rounded-lg border border-white/8 bg-black/20 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-slate-200">
                    {check.symbol || '未指定标的'} · {check.actionType}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">{new Date(check.createdAt).toLocaleString('zh-CN')}</p>
                </div>
                <StatusPill tone={resultTone(check.result)}>{resultLabel(check.result)}</StatusPill>
              </div>
            ))
          ) : (
            <p className="text-sm text-slate-400">还没有纪律检查记录。记录持仓或生成交易草稿后，这里会显示命中情况。</p>
          )}
        </div>
      </div>
    </div>
  );
}
