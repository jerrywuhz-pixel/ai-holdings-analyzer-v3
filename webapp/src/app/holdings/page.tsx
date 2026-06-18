import Link from 'next/link';
import {
  ActionabilityPill,
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

export default async function HoldingsPage({
  searchParams,
}: {
  searchParams?: Promise<{ state?: string; view?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const state = resolveDemoState(params.state);
  const snapshot = await getWorkspaceSnapshot({ state, viewId: params.view });
  const views = snapshot.data?.chrome.views ?? [];
  const activeView = snapshot.data?.chrome.activeViewId;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="持仓"
        title="统一资产视图里拆开股票 / ETF 与 Sell Put"
        description="持仓页不是总览页的重复。这里优先回答我持有什么、来源是什么、风险在哪里，以及金额当前按什么币种展示。页面金额用于巡检，不等同交易账户结单。"
        actions={<InlineLink href="/confirmations">高风险动作进入确认中心</InlineLink>}
      />

      <LiveDataBanner dataState={snapshot.liveData} />

      <div className="flex flex-wrap gap-2">
        {views.map((view) => (
          <Link
            key={view.id}
            href={`/holdings?view=${view.id}`}
            className={[
              'rounded-full border px-3 py-1.5 text-sm transition',
              view.id === activeView
                ? 'border-red-400/30 bg-red-500/10 text-red-100'
                : 'border-white/10 bg-white/[0.03] text-slate-300 hover:bg-white/[0.05]',
            ].join(' ')}
          >
            {view.name}
          </Link>
        ))}
      </div>

      <DataStateView
        state={snapshot.state}
        errorMessage={snapshot.errorMessage}
        emptyTitle="当前资产视图没有持仓"
        emptyDetail="等待首次账户更新、手工录入或截图 / 语音修正确认后再展示。"
      />

      {snapshot.data ? (
        <>
          <DegradationBanner sources={snapshot.data.chrome.sources} compact />

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {snapshot.data.holdings.metrics.map((metric) => (
              <MetricCard key={metric.label} metric={metric} />
            ))}
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
            <Panel
              title="股票 / ETF"
              description="每个数字都展示来源、更新时间、原币种与页面折算口径。"
              aside={<StatusPill tone="muted">{snapshot.data.holdings.equity.length} 条</StatusPill>}
            >
              <div className="space-y-3 md:hidden">
                {snapshot.data.holdings.equity.map((holding) => (
                  <div key={holding.symbol} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <Link href={`/holdings/${holding.symbol}`} className="font-medium text-white hover:text-red-200">
                          {holding.name && holding.name !== holding.symbol ? holding.name : holding.symbol}
                        </Link>
                        <p className="mt-1 text-xs text-slate-500">
                          {holding.name && holding.name !== holding.symbol
                            ? `${holding.market} · ${holding.symbol}`
                            : holding.market}
                        </p>
                      </div>
                      <DisciplinePill state={holding.discipline} />
                    </div>
                    <div className="mt-4 grid gap-3 text-sm text-slate-300 sm:grid-cols-2">
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">数量</p>
                        <p className="mt-1">{holding.quantity}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">集中度</p>
                        <p className="mt-1">{holding.concentration}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">市值</p>
                        <p className="mt-1">{holding.marketValue}</p>
                        {holding.marketValueDetail ? (
                          <p className="mt-1 text-xs text-slate-500">{holding.marketValueDetail}</p>
                        ) : null}
                        {holding.valuationBasis ? (
                          <p className="mt-1 text-xs text-slate-500">{holding.valuationBasis}</p>
                        ) : null}
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">盈亏</p>
                        <p className="mt-1">{holding.pnl}</p>
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <StatusPill tone="muted">{holding.source}</StatusPill>
                      <FreshnessPill source={{ freshnessLabel: holding.freshness, status: holding.source.includes('腾讯') ? 'stale' : 'fresh' }} />
                    </div>
                  </div>
                ))}
              </div>

              <div className="hidden overflow-x-auto md:block">
                <table className="min-w-full divide-y divide-white/8 text-sm">
                  <thead className="text-left text-slate-400">
                    <tr>
                      <th className="px-3 py-3 font-medium">标的</th>
                      <th className="px-3 py-3 font-medium">数量</th>
                      <th className="px-3 py-3 font-medium">市值</th>
                      <th className="px-3 py-3 font-medium">盈亏</th>
                      <th className="px-3 py-3 font-medium">集中度</th>
                      <th className="px-3 py-3 font-medium">纪律</th>
                      <th className="px-3 py-3 font-medium">来源</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/8">
                    {snapshot.data.holdings.equity.map((holding) => (
                      <tr key={holding.symbol}>
                        <td className="px-3 py-3">
                          <Link href={`/holdings/${holding.symbol}`} className="font-medium text-white hover:text-red-200">
                            {holding.name && holding.name !== holding.symbol ? holding.name : holding.symbol}
                          </Link>
                          <p className="text-xs text-slate-500">
                            {holding.name && holding.name !== holding.symbol
                              ? `${holding.market} · ${holding.symbol}`
                              : holding.market}
                          </p>
                        </td>
                        <td className="px-3 py-3 text-slate-200">{holding.quantity}</td>
                        <td className="px-3 py-3 text-slate-200">
                          <p>{holding.marketValue}</p>
                          {holding.marketValueDetail ? (
                            <p className="mt-1 text-xs text-slate-500">{holding.marketValueDetail}</p>
                          ) : null}
                          {holding.valuationBasis ? (
                            <p className="mt-1 text-xs text-slate-500">{holding.valuationBasis}</p>
                          ) : null}
                        </td>
                        <td className="px-3 py-3 text-slate-200">{holding.pnl}</td>
                        <td className="px-3 py-3 text-slate-200">{holding.concentration}</td>
                        <td className="px-3 py-3">
                          <DisciplinePill state={holding.discipline} />
                        </td>
                        <td className="px-3 py-3">
                          <div className="space-y-2">
                            <StatusPill tone="muted">{holding.source}</StatusPill>
                            <FreshnessPill source={{ freshnessLabel: holding.freshness, status: holding.source.includes('腾讯') ? 'stale' : 'fresh' }} />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel title="风险雷达" description="持仓页直接展示仓位、期权与数据更新三类风险。">
              <div className="space-y-3">
                {snapshot.data.holdings.riskRadar.map((risk) => (
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

          <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
            <Panel title="Sell Put 持仓" description="期权持仓独立卡片展示，不混入股票长表；金额会说明原币与折算口径。">
              <div className="grid gap-3 md:grid-cols-2">
                {snapshot.data.holdings.options.map((option) => (
                  <div key={option.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-medium text-white">{option.contract}</p>
                        <p className="mt-1 text-sm text-slate-400">{option.underlying} · 权利金 {option.premium}</p>
                      </div>
                      <ActionabilityPill state={option.actionability} />
                    </div>
                    <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-300">
                      <div>
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-500">到期天数 / delta</p>
                        <p className="mt-1">{option.dte} / {option.delta}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-500">IV</p>
                        <p className="mt-1">{option.iv}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-500">期权市值</p>
                        <p className="mt-1">{option.optionMarketValue}</p>
                        {option.optionMarketValueDetail ? (
                          <p className="mt-1 text-xs text-slate-500">{option.optionMarketValueDetail}</p>
                        ) : null}
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-500">现金 / 保证金</p>
                        <p className="mt-1">{option.cashRequired} / {option.marginRequired}</p>
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <StatusPill tone={option.risk === 'high' ? 'danger' : 'warning'}>{option.assignment}</StatusPill>
                      <StatusPill tone="muted">{option.source}</StatusPill>
                      <FreshnessPill source={{ freshnessLabel: option.freshness, status: option.actionability === 'ready' ? 'fresh' : 'degraded' }} />
                    </div>
                    {option.valuationBasis ? (
                      <p className="mt-3 text-xs text-slate-500">{option.valuationBasis}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="来源明细" description="展示每类持仓数据的来源、可信度和更新时间，方便回溯数字从哪里来。">
              <div className="space-y-3">
                {snapshot.data.holdings.sources.map((source) => (
                  <div key={source.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="font-medium text-white">{source.label}</p>
                        <p className="mt-1 text-sm text-slate-400">{source.lineage}</p>
                      </div>
                      <StatusPill tone="muted">{source.type}</StatusPill>
                    </div>
                    <div className="mt-3 grid gap-2 text-sm text-slate-300 md:grid-cols-3">
                      <p>优先级 {source.priority}</p>
                      <p>可信度 {source.confidence}</p>
                      <p>更新 {source.freshness}</p>
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
