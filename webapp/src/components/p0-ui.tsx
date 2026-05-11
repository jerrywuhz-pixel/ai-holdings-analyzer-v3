'use client';

import Link from 'next/link';
import { DemoState, SourceStatus } from '@/lib/p0';
import type { P0ApiDataState } from '@/lib/p0-api';

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(' ');
}

function actionabilityLabel(state: SourceStatus['actionability']) {
  if (state === 'ready') return '可生成草稿';
  if (state === 'analysis_only') return '仅供参考';
  return '暂不建议操作';
}

function sourceTierLabel(tier: SourceStatus['tier']) {
  if (tier === 'L1') return '主要来源';
  if (tier === 'L2') return '备用来源';
  return '参考来源';
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 border-b border-white/10 pb-5 md:flex-row md:items-end md:justify-between">
      <div className="space-y-2">
        {eyebrow ? <p className="text-xs uppercase tracking-[0.28em] text-red-300/80">{eyebrow}</p> : null}
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white md:text-3xl">{title}</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">{description}</p>
        </div>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
    </div>
  );
}

export function Panel({
  title,
  description,
  aside,
  children,
  className,
}: {
  title: string;
  description?: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cx(
        'min-w-0 rounded-2xl border border-white/10 bg-[linear-gradient(180deg,rgba(24,27,31,0.96),rgba(12,14,18,0.96))] p-4 shadow-[0_18px_60px_rgba(0,0,0,0.28)] md:p-5',
        className
      )}
    >
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-base font-semibold text-white">{title}</h2>
          {description ? <p className="mt-1 text-sm text-slate-400">{description}</p> : null}
        </div>
        {aside ? <div className="shrink-0">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function MetricCard({
  metric,
}: {
  metric: { label: string; value: string; hint: string; tone?: 'default' | 'positive' | 'warning' | 'danger' };
}) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
      <p className="text-xs uppercase tracking-[0.24em] text-slate-400">{metric.label}</p>
      <p
        className={cx(
          'mt-3 text-2xl font-semibold tracking-tight',
          metric.tone === 'danger' && 'text-red-300',
          metric.tone === 'warning' && 'text-amber-300',
          metric.tone === 'positive' && 'text-emerald-300',
          !metric.tone && 'text-white'
        )}
      >
        {metric.value}
      </p>
      <p className="mt-2 text-sm text-slate-400">{metric.hint}</p>
    </div>
  );
}

export function StatusPill({
  children,
  tone = 'default',
}: {
  children: React.ReactNode;
  tone?: 'default' | 'positive' | 'warning' | 'danger' | 'muted';
}) {
  return (
    <span
      className={cx(
        'inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium',
        tone === 'default' && 'border-red-400/20 bg-red-400/10 text-red-200',
        tone === 'positive' && 'border-emerald-400/20 bg-emerald-400/10 text-emerald-200',
        tone === 'warning' && 'border-amber-400/20 bg-amber-400/10 text-amber-200',
        tone === 'danger' && 'border-red-500/30 bg-red-500/10 text-red-200',
        tone === 'muted' && 'border-white/10 bg-white/5 text-slate-300'
      )}
    >
      {children}
    </span>
  );
}

export function FreshnessPill({
  source,
}: {
  source: SourceStatus | { freshnessLabel: string; status?: 'fresh' | 'stale' | 'degraded' };
}) {
  const tone = source.status === 'degraded' ? 'danger' : source.status === 'stale' ? 'warning' : 'positive';
  return <StatusPill tone={tone}>更新 {source.freshnessLabel}</StatusPill>;
}

export function DisciplinePill({ state }: { state: 'clear' | 'watch' | 'blocked' }) {
  return (
    <StatusPill tone={state === 'clear' ? 'positive' : state === 'watch' ? 'warning' : 'danger'}>
      {state === 'clear' ? '纪律通过' : state === 'watch' ? '需要关注' : '纪律阻断'}
    </StatusPill>
  );
}

export function ActionabilityPill({ state }: { state: 'ready' | 'analysis_only' | 'blocked' }) {
  return (
    <StatusPill tone={state === 'ready' ? 'positive' : state === 'analysis_only' ? 'warning' : 'danger'}>
      {state === 'ready' ? '可生成草稿' : state === 'analysis_only' ? '仅供参考' : '已阻断'}
    </StatusPill>
  );
}

export function DegradationBanner({
  sources,
  compact = false,
}: {
  sources: SourceStatus[];
  compact?: boolean;
}) {
  const degraded = sources.filter((source) => source.status !== 'fresh');
  if (!degraded.length) return null;

  return (
    <div className={cx('rounded-xl border border-amber-500/30 bg-amber-500/10 p-4', compact && 'p-3')}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-amber-200">数据状态提醒</p>
          <p className="mt-1 text-sm text-amber-100/85">
            当前有数据更新延迟或质量不足的来源。系统会说明原因，并把相关建议限制在合适范围内。
          </p>
        </div>
        <StatusPill tone="warning">{degraded.length} 个需注意来源</StatusPill>
      </div>
      <div className="mt-3 space-y-2 text-sm text-amber-100/90">
        {degraded.map((source) => (
          <div key={source.key} className="rounded-lg border border-amber-400/15 bg-black/10 px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>{source.label}</span>
              <span className="font-mono text-xs uppercase">
                {sourceTierLabel(source.tier)} · {actionabilityLabel(source.actionability)}
              </span>
            </div>
            {source.reason ? <p className="mt-1 text-xs text-amber-100/70">{source.reason}</p> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

export function LiveDataBanner({ dataState }: { dataState?: P0ApiDataState }) {
  if (!dataState) return null;

  const tone =
    dataState.mode === 'live'
      ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-100'
      : dataState.mode === 'partial'
        ? 'border-amber-500/25 bg-amber-500/10 text-amber-100'
        : 'border-red-500/25 bg-red-500/10 text-red-100';

  return (
    <div className={cx('rounded-2xl border p-4', tone)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium">{dataState.label}</p>
          <p className="mt-1 text-sm leading-6 opacity-90">{dataState.detail}</p>
          {dataState.valuationDetail && dataState.valuationDetail !== dataState.detail ? (
            <p className="mt-2 text-xs opacity-80">{dataState.valuationDetail}</p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusPill tone={dataState.mode === 'live' ? 'positive' : dataState.mode === 'partial' ? 'warning' : 'danger'}>
            {dataState.mode === 'live' ? '实时优先' : dataState.mode === 'partial' ? '部分实时' : '参考视图'}
          </StatusPill>
          {dataState.baseCurrency ? <StatusPill tone="muted">展示币种 {dataState.baseCurrency}</StatusPill> : null}
          {dataState.usesEstimatedFx ? <StatusPill tone="warning">估算汇率</StatusPill> : null}
        </div>
      </div>
      {dataState.updatedAt ? (
        <p className="mt-3 text-xs opacity-75">最近数据时间 {dataState.updatedAt}</p>
      ) : null}
    </div>
  );
}

export function DataStateView({
  state,
  emptyTitle = '暂无数据',
  emptyDetail = '等待首次同步或录入后再展示。',
  errorMessage,
}: {
  state: DemoState;
  emptyTitle?: string;
  emptyDetail?: string;
  errorMessage?: string;
}) {
  if (state === 'loading') {
    return (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="h-28 animate-pulse rounded-2xl border border-white/8 bg-white/[0.04]" />
        ))}
      </div>
    );
  }

  if (state === 'error') {
    return (
      <div className="rounded-2xl border border-red-500/25 bg-red-500/10 p-5">
        <p className="text-sm font-medium text-red-200">页面数据加载失败</p>
        <p className="mt-2 text-sm leading-6 text-red-100/85">{errorMessage}</p>
      </div>
    );
  }

  if (state === 'empty') {
    return (
      <div className="rounded-2xl border border-dashed border-white/15 bg-white/[0.03] px-5 py-10 text-center">
        <p className="text-base font-medium text-white">{emptyTitle}</p>
        <p className="mt-2 text-sm text-slate-400">{emptyDetail}</p>
      </div>
    );
  }

  return null;
}

export function InlineLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center rounded-full border border-red-400/20 bg-red-400/10 px-3 py-1.5 text-xs font-medium text-red-100 transition hover:border-red-300/30 hover:bg-red-400/15"
    >
      {children}
    </Link>
  );
}
