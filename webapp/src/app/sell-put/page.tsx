import {
  ActionabilityPill,
  DataStateView,
  DegradationBanner,
  FreshnessPill,
  InlineLink,
  LiveDataBanner,
  MetricCard,
  PageHeader,
  Panel,
  StatusPill,
} from '@/components/p0-ui';
import { getWorkspaceSnapshot, resolvePageState } from '@/lib/p0';

export const dynamic = 'force-dynamic';

export default async function SellPutPage({
  searchParams,
}: {
  searchParams?: Promise<{ state?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const state = resolvePageState(params.state);
  const snapshot = await getWorkspaceSnapshot({ state });

  return (
    <div className="space-y-4 md:space-y-6">
      <PageHeader
        eyebrow="Sell Put"
        title="围绕现金占用、到期天数、波动率和纪律的独立工作台"
        description="Sell Put 工作台聚焦现金占用、保证金、到期天数、波动率和交易纪律。候选满足规则时只生成草稿，仍需你确认。"
        actions={
          <>
            <InlineLink href="/rules">查看阈值配置</InlineLink>
            <InlineLink href="/ops">查看微信处理状态</InlineLink>
          </>
        }
      />

      <LiveDataBanner dataState={snapshot.liveData} />

      <DataStateView
        state={snapshot.state}
        errorMessage={snapshot.errorMessage}
        emptyTitle="暂无 Sell Put 数据"
        emptyDetail="等待期权持仓、现金余额与期权链行情更新后展示。"
      />

      {snapshot.data ? (
        <>
          <DegradationBanner sources={snapshot.data.chrome.sources} />

          <div className="grid grid-cols-2 gap-2 md:gap-4 xl:grid-cols-3">
            {snapshot.data.sellPut.metrics.map((metric) => (
              <MetricCard key={metric.label} metric={metric} />
            ))}
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
            <Panel title="当前持仓" description="每张卖出认沽独立展示到期天数、delta、IV、现金占用和可操作状态。">
              {snapshot.data.sellPut.positions.length ? (
                <div className="space-y-3">
                  {snapshot.data.sellPut.positions.map((position) => (
                    <div key={position.id} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="font-medium text-[#171417]">{position.contract}</p>
                          <p className="mt-1 text-sm text-[#6f686b]">
                            权利金 {position.premium} · 期权市值 {position.optionMarketValue}
                          </p>
                        </div>
                        <ActionabilityPill state={position.actionability} />
                      </div>
                      <div className="mt-4 grid gap-3 text-sm text-[#4f494c] md:grid-cols-4">
                        <p>到期 {position.dte} 天</p>
                        <p>delta {position.delta}</p>
                        <p>IV {position.iv}</p>
                        <p>现金占用 {position.cashRequired}</p>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <StatusPill tone={position.risk === 'high' ? 'danger' : 'warning'}>{position.assignment}</StatusPill>
                        <StatusPill tone="muted">{position.source}</StatusPill>
                        <FreshnessPill source={{ freshnessLabel: position.freshness, status: position.actionability === 'ready' ? 'fresh' : 'degraded' }} />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-[#d8ccc7] bg-white p-5 text-sm text-[#6f686b]">
                  当前账号没有真实 Sell Put 持仓。
                </div>
              )}
            </Panel>

            <Panel title="资金占用结构" description="总览与持仓页都必须拆开期权市值、现金担保 / 保证金和可用现金。">
              <div className="grid gap-3 text-sm text-[#4f494c]">
                {snapshot.data.sellPut.ladder.map((bucket) => (
                  <div key={bucket.bucket} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-medium text-[#171417]">{bucket.bucket}</p>
                      <StatusPill tone="muted">{bucket.contracts} 份合约</StatusPill>
                    </div>
                    <p className="mt-2 text-[#6f686b]">现金占用 {bucket.exposure}</p>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
            <Panel title="候选行权价对比" description="按现金占用、到期天数、delta、IV 和纪律规则筛选候选，限制原因会直接展示。">
              {snapshot.data.sellPut.candidates.length ? (
                <>
                  <div className="space-y-3 md:hidden">
                    {snapshot.data.sellPut.candidates.map((candidate) => (
                      <div key={candidate.id} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <p className="font-medium text-[#171417]">{candidate.underlying}</p>
                            <p className="mt-1 text-sm text-[#6f686b]">{candidate.strike} · {candidate.expiry}</p>
                          </div>
                          <ActionabilityPill state={candidate.result} />
                        </div>
                        <div className="mt-4 grid gap-3 text-sm text-[#4f494c] sm:grid-cols-2">
                          <p>现金占用 {candidate.cashRequired}</p>
                          <p>到期 {candidate.dte}</p>
                          <p>delta / IV {candidate.delta} / {candidate.iv}</p>
                          <p>权利金 {candidate.premium}</p>
                        </div>
                        <p className="mt-3 text-sm leading-6 text-[#6f686b]">{candidate.note}</p>
                      </div>
                    ))}
                  </div>

                  <div className="hidden overflow-x-auto md:block">
                    <table className="min-w-full divide-y divide-[#e5ddd9] text-sm">
                      <thead className="text-left text-[#6f686b]">
                        <tr>
                          <th className="px-3 py-3 font-medium">标的</th>
                          <th className="px-3 py-3 font-medium">行权价 / 到期日</th>
                          <th className="px-3 py-3 font-medium">到期天数</th>
                          <th className="px-3 py-3 font-medium">delta / IV</th>
                          <th className="px-3 py-3 font-medium">权利金</th>
                          <th className="px-3 py-3 font-medium">结果</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#e5ddd9]">
                        {snapshot.data.sellPut.candidates.map((candidate) => (
                          <tr key={candidate.id}>
                            <td className="px-3 py-3">
                              <p className="font-medium text-[#171417]">{candidate.underlying}</p>
                              <p className="text-xs text-[#8a817d]">现金占用 {candidate.cashRequired}</p>
                            </td>
                            <td className="px-3 py-3 text-[#4f494c]">
                              {candidate.strike}
                              <p className="text-xs text-[#8a817d]">{candidate.expiry}</p>
                            </td>
                            <td className="px-3 py-3 text-[#4f494c]">{candidate.dte}</td>
                            <td className="px-3 py-3 text-[#4f494c]">
                              {candidate.delta} / {candidate.iv}
                            </td>
                            <td className="px-3 py-3 text-[#4f494c]">{candidate.premium}</td>
                            <td className="px-3 py-3">
                              <div className="space-y-2">
                                <ActionabilityPill state={candidate.result} />
                                <p className="max-w-xs text-xs leading-5 text-[#6f686b]">{candidate.note}</p>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <div className="rounded-lg border border-dashed border-[#d8ccc7] bg-white p-5 text-sm text-[#6f686b]">
                  暂无来自真实期权链和账户规则的 Sell Put 候选；不会展示占位标的。
                </div>
              )}
            </Panel>

            <Panel title="策略阈值" description="Sell Put 的默认阈值来自账户规则；页面只展示当前规则，不在这里直接修改。">
              <div className="space-y-3">
                {snapshot.data.sellPut.thresholds.map((item) => (
                  <div key={item.label} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="font-medium text-[#171417]">{item.label}</p>
                      <StatusPill tone="muted">{item.value}</StatusPill>
                    </div>
                    <p className="mt-2 text-sm text-[#6f686b]">
                      来源 {item.source} · 可在 {item.mutableVia} 调整
                    </p>
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
