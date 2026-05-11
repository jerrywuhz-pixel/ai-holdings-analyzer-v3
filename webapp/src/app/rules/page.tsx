import {
  DataStateView,
  MetricCard,
  PageHeader,
  Panel,
  StatusPill,
} from '@/components/p0-ui';
import { getWorkspaceSnapshot, resolveDemoState } from '@/lib/p0';

export const dynamic = 'force-dynamic';

export default async function RulesPage({
  searchParams,
}: {
  searchParams?: Promise<{ state?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const state = resolveDemoState(params.state);
  const snapshot = await getWorkspaceSnapshot({ state });

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="交易纪律"
        title="纪律规则和 Sell Put 阈值集中管理"
        description="这里展示你的交易规则、最近触发记录和 Sell Put 阈值。任何影响资金口径或高风险动作的修改都应走确认中心。"
      />

      <DataStateView
        state={snapshot.state}
        errorMessage={snapshot.errorMessage}
        emptyTitle="暂无规则数据"
        emptyDetail="等待账户规则或例外记录同步后展示。"
      />

      {snapshot.data ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {snapshot.data.rules.summary.map((metric) => (
              <MetricCard key={metric.label} metric={metric} />
            ))}
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
            <Panel title="纪律规则" description="仓位集中、财报前限制、Sell Put 现金占用等规则统一展示。">
              <div className="space-y-3">
                {snapshot.data.rules.rules.map((rule) => (
                  <div key={rule.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="font-medium text-white">{rule.title}</p>
                        <p className="mt-1 text-sm text-slate-400">{rule.condition}</p>
                      </div>
                      <StatusPill tone={rule.severity === 'high' ? 'danger' : rule.severity === 'medium' ? 'warning' : 'muted'}>
                        {rule.scope}
                      </StatusPill>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-sm text-slate-300">
                      <span>最近触发 {rule.latestHit}</span>
                      {rule.overrideRequired ? <StatusPill tone="warning">需要例外说明</StatusPill> : null}
                    </div>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="例外说明 / 策略阈值" description="Sell Put 阈值和高影响视图变更都需要保留记录，必要时进入确认中心。">
              <div className="space-y-3">
                {snapshot.data.rules.thresholdGroups.map((item) => (
                  <div key={item.label} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="font-medium text-white">{item.label}</p>
                      <StatusPill tone="muted">{item.value}</StatusPill>
                    </div>
                    <p className="mt-2 text-sm text-slate-400">
                      {item.source} · {item.mutableVia}
                    </p>
                  </div>
                ))}
                {snapshot.data.rules.overrides.map((item) => (
                  <div key={item.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <p className="font-medium text-white">{item.object}</p>
                    <p className="mt-2 text-sm text-slate-400">{item.reason}</p>
                    <p className="mt-2 text-xs text-slate-500">
                      {item.actor} · {item.createdAt}
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
