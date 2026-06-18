import Link from 'next/link';
import {
  DataStateView,
  DegradationBanner,
  DisciplinePill,
  FreshnessPill,
  InlineLink,
  LiveDataBanner,
  MetricCard,
  PageHeader,
  Panel,
  StatusPill,
} from '@/components/p0-ui';
import { getWorkspaceSnapshot, resolveDemoState } from '@/lib/p0';

export const dynamic = 'force-dynamic';

export default async function HomePage({
  searchParams,
}: {
  searchParams?: Promise<{ state?: string; view?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const state = resolveDemoState(params.state);
  const snapshot = await getWorkspaceSnapshot({ state, viewId: params.view });

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="总览"
        title="30 秒看清资产、风险和今天该处理什么"
        description="总览优先展示资产、Sell Put 资金占用、数据更新状态与待处理事项。多币种金额按当前展示币种统一口径汇总，用于巡检与比较，不等同交易账户结单净资产。"
        actions={
          <>
            <InlineLink href="/confirmations">待处理确认</InlineLink>
            <InlineLink href="/sell-put">Sell Put 工作台</InlineLink>
          </>
        }
      />

      <LiveDataBanner dataState={snapshot.liveData} />

      <DataStateView
        state={snapshot.state}
        errorMessage={snapshot.errorMessage}
        emptyTitle="尚未生成资产总览"
        emptyDetail="等待首次账户更新、手工录入或截图 / 语音确认后显示。"
      />

      {snapshot.data ? (
        <>
          <DegradationBanner sources={snapshot.data.chrome.sources} />

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {snapshot.data.dashboard.metrics.map((metric) => (
              <MetricCard key={metric.label} metric={metric} />
            ))}
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.25fr_0.95fr]">
            <Panel
              title="今日行动"
              description="优先级遵循：待确认 / 冲突 > 高风险到期 > Sell Put 到期 > 异动提醒。"
              aside={<StatusPill tone="danger">{snapshot.data.dashboard.actions.length} 项待处理</StatusPill>}
            >
              <div className="space-y-3">
                {snapshot.data.dashboard.actions.map((item) => (
                  <Link
                    key={item.id}
                    href={item.href}
                    className="flex flex-col gap-2 rounded-xl border border-white/8 bg-white/[0.03] p-4 transition hover:border-red-400/20 hover:bg-white/[0.05] md:flex-row md:items-start md:justify-between"
                  >
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-white">{item.title}</p>
                        {item.badge ? <StatusPill tone="danger">{item.badge}</StatusPill> : null}
                      </div>
                      <p className="mt-1 text-sm text-slate-400">{item.detail}</p>
                    </div>
                    <StatusPill
                      tone={
                        item.severity === 'critical'
                          ? 'danger'
                          : item.severity === 'warning'
                            ? 'warning'
                            : 'muted'
                      }
                    >
                      {item.severity === 'critical' ? '重要' : item.severity === 'warning' ? '需关注' : '普通'}
                    </StatusPill>
                  </Link>
                ))}
              </div>
            </Panel>

            <Panel title="风险雷达" description="集中度、到期、交易纪律与数据更新风险集中展示。">
              <div className="space-y-3">
                {snapshot.data.dashboard.riskRadar.map((risk) => (
                  <div key={risk.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium text-white">{risk.title}</p>
                      <StatusPill tone={risk.level === 'high' ? 'danger' : risk.level === 'medium' ? 'warning' : 'muted'}>
                        {risk.badge}
                      </StatusPill>
                    </div>
                    <p className="mt-2 text-sm text-slate-400">{risk.detail}</p>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
            <Panel
              title="重点持仓"
              description="股票 / ETF 与期权分开展示；金额会标明原币与页面折算口径，避免误读为交易账户净资产精确值。"
              aside={<InlineLink href="/holdings">查看完整持仓</InlineLink>}
            >
              <div className="space-y-3 md:hidden">
                {snapshot.data.dashboard.holdingsPreview.map((holding) => (
                  <div key={holding.symbol} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <Link href={`/holdings/${holding.symbol}`} className="font-medium text-white hover:text-red-200">
                          {holding.symbol}
                        </Link>
                        <p className="mt-1 text-xs text-slate-500">{holding.name}</p>
                      </div>
                      <DisciplinePill state={holding.discipline} />
                    </div>
                    <div className="mt-4 grid gap-3 text-sm text-slate-300 sm:grid-cols-2">
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">市值</p>
                        <p className="mt-1 text-slate-200">{holding.marketValue}</p>
                        {holding.marketValueDetail ? (
                          <p className="mt-1 text-xs text-slate-500">{holding.marketValueDetail}</p>
                        ) : null}
                        {holding.valuationBasis ? (
                          <p className="mt-1 text-xs text-slate-500">{holding.valuationBasis}</p>
                        ) : null}
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">盈亏</p>
                        <p className="mt-1 text-slate-200">{holding.pnl}</p>
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <FreshnessPill source={{ freshnessLabel: holding.freshness, status: holding.source.includes('腾讯') ? 'stale' : 'fresh' }} />
                    </div>
                  </div>
                ))}
              </div>

              <div className="hidden overflow-x-auto rounded-xl border border-white/8 md:block">
                <table className="min-w-full divide-y divide-white/8 text-sm">
                  <thead className="bg-white/[0.03] text-left text-slate-400">
                    <tr>
                      <th className="px-4 py-3 font-medium">标的</th>
                      <th className="px-4 py-3 font-medium">市值</th>
                      <th className="px-4 py-3 font-medium">盈亏</th>
                      <th className="px-4 py-3 font-medium">纪律</th>
                      <th className="px-4 py-3 font-medium">数据更新</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/8">
                    {snapshot.data.dashboard.holdingsPreview.map((holding) => (
                      <tr key={holding.symbol} className="bg-black/10">
                        <td className="px-4 py-3">
                          <Link href={`/holdings/${holding.symbol}`} className="font-medium text-white hover:text-red-200">
                            {holding.symbol}
                          </Link>
                          <p className="text-xs text-slate-500">{holding.name}</p>
                        </td>
                        <td className="px-4 py-3 text-slate-200">
                          <p>{holding.marketValue}</p>
                          {holding.marketValueDetail ? (
                            <p className="mt-1 text-xs text-slate-500">{holding.marketValueDetail}</p>
                          ) : null}
                          {holding.valuationBasis ? (
                            <p className="mt-1 text-xs text-slate-500">{holding.valuationBasis}</p>
                          ) : null}
                        </td>
                        <td className="px-4 py-3 text-slate-200">{holding.pnl}</td>
                        <td className="px-4 py-3">
                          <DisciplinePill state={holding.discipline} />
                        </td>
                        <td className="px-4 py-3">
                          <FreshnessPill source={{ freshnessLabel: holding.freshness, status: holding.source.includes('腾讯') ? 'stale' : 'fresh' }} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel title="Sell Put 摘要" description="候选、资金占用、近到期风险优先于趋势图。">
              <div className="space-y-3">
                {snapshot.data.dashboard.optionsPreview.map((option) => (
                  <div key={option.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="font-medium text-white">{option.contract}</p>
                        <p className="mt-1 text-sm text-slate-400">
                          现金占用 {option.cashRequired} · 期权市值 {option.optionMarketValue}
                        </p>
                      </div>
                      <StatusPill tone={option.risk === 'high' ? 'danger' : 'warning'}>{option.assignment}</StatusPill>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <StatusPill tone="muted">到期 {option.dte} 天</StatusPill>
                      <StatusPill tone="muted">delta {option.delta}</StatusPill>
                      <StatusPill tone="muted">IV {option.iv}</StatusPill>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </>
      ) : null}
    </div>
  );
}
