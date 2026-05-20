import {
  DataStateView,
  DegradationBanner,
  LiveDataBanner,
  MetricCard,
  PageHeader,
  Panel,
  StatusPill,
} from '@/components/p0-ui';
import ManualPositionForm from '@/components/manual-position-form';
import { ensureUserAccount } from '@/lib/account-store';
import { getWorkspaceSnapshot, resolveDemoState } from '@/lib/p0';
import { requireUser } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

const connectionStatusLabel: Record<string, string> = {
  connected: '已连接',
  degraded: '需注意',
};

const syncStatusLabel = {
  success: '已完成',
  warning: '需注意',
  failed: '失败',
  running: '更新中',
} as const;

export default async function DataPage({
  searchParams,
}: {
  searchParams?: Promise<{ state?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const state = resolveDemoState(params.state);
  const session = await requireUser();
  const [account, snapshot] = await Promise.all([
    ensureUserAccount(session.user),
    getWorkspaceSnapshot({ state }),
  ]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="数据与账户"
        title="账户连接、最近更新和数字来源都在这里"
        description="这里优先说明 Futu 账户是否连通、最近什么时候拿到新数据，以及页面金额当前按什么币种展示。若存在估算汇率折算，会在这里明确提示。"
      />

      <LiveDataBanner dataState={snapshot.liveData} />

      <DataStateView
        state={snapshot.state}
        errorMessage={snapshot.errorMessage}
        emptyTitle="暂无可用数据连接"
        emptyDetail="等待账户连接、资产来源或最近更新记录接入。"
      />

      {snapshot.data ? (
        <>
          <DegradationBanner sources={snapshot.data.chrome.sources} compact />

          <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
            <Panel title="账户工作区" description="每个登录账号都有独立的 account_id、tenant_id、资产视图和数据来源。">
              <div className="grid gap-3 text-sm text-slate-300">
                <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-slate-500">account_id</p>
                  <p className="mt-2 break-all font-mono text-white">{account.accountId}</p>
                </div>
                <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-slate-500">tenant_id</p>
                  <p className="mt-2 break-all font-mono text-white">{account.tenantId}</p>
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <p className="text-xs text-slate-500">资产视图</p>
                    <p className="mt-1 text-lg font-semibold text-white">{account.portfolioViews.length}</p>
                  </div>
                  <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <p className="text-xs text-slate-500">关注清单</p>
                    <p className="mt-1 text-lg font-semibold text-white">{account.followView?.itemCount ?? 0}</p>
                  </div>
                  <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <p className="text-xs text-slate-500">清仓回溯</p>
                    <p className="mt-1 text-lg font-semibold text-white">{account.listView?.itemCount ?? 0}</p>
                  </div>
                </div>
              </div>
            </Panel>

            <Panel title="手工录入持仓" description="适合先把券商 App 里看到的持仓录进来；系统会记录来源并刷新当前账号的持仓快照。">
              <ManualPositionForm />
            </Panel>
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {snapshot.data.data.summary.map((metric) => (
              <MetricCard key={metric.label} metric={metric} />
            ))}
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
            <Panel title="Futu 账户连接" description="这里只说明是否成功读到持仓和资金，不会在这里触发下单。">
              <div className="space-y-3">
                {snapshot.data.data.connections.map((connection) => (
                  <div key={connection.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="font-medium text-white">{connection.provider}</p>
                        <p className="mt-1 text-sm text-slate-400">{connection.accountLabel}</p>
                      </div>
                      <StatusPill tone={connection.authStatus === 'connected' ? 'positive' : 'warning'}>
                        {connectionStatusLabel[connection.authStatus] ?? connection.authStatus}
                      </StatusPill>
                    </div>
                    <div className="mt-3 grid gap-2 text-sm text-slate-300">
                      <p>权限 {connection.permissionScope}</p>
                      <p>最近更新 {connection.lastSync}</p>
                      <p>更新 {connection.freshness}</p>
                    </div>
                    {connection.degradation ? (
                      <p className="mt-3 text-sm text-amber-300">{connection.degradation}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="最近更新记录" description="告诉你最近一次拿到新数据的时间，以及当前为什么可能还在使用参考数据。">
              <div className="space-y-3">
                {snapshot.data.data.syncEvents.map((event) => (
                  <div key={event.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="font-medium text-white">{event.title}</p>
                      <StatusPill
                        tone={
                          event.status === 'success'
                            ? 'positive'
                            : event.status === 'failed'
                              ? 'danger'
                              : event.status === 'warning'
                                ? 'warning'
                                : 'muted'
                        }
                      >
                        {syncStatusLabel[event.status]}
                      </StatusPill>
                    </div>
                    <p className="mt-2 text-sm text-slate-400">{event.detail}</p>
                    <p className="mt-2 text-xs text-slate-500">开始时间 {event.startedAt}</p>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <Panel title="资产数据来源" description="展示券商、手工录入、截图识别以及多币种折算口径的优先级、可信度和更新时间。">
            <div className="space-y-3 md:hidden">
              {snapshot.data.data.assetSources.map((source) => (
                <div key={source.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-medium text-white">{source.label}</p>
                      <p className="mt-1 text-sm text-slate-400">{source.type}</p>
                    </div>
                    <StatusPill tone="muted">{source.priority}</StatusPill>
                  </div>
                  <div className="mt-4 grid gap-3 text-sm text-slate-300 sm:grid-cols-2">
                    <p>可信度 {source.confidence}</p>
                    <p>数据更新 {source.freshness}</p>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-slate-400">{source.lineage}</p>
                </div>
              ))}
            </div>

            <div className="hidden overflow-x-auto md:block">
              <table className="min-w-full divide-y divide-white/8 text-sm">
                <thead className="text-left text-slate-400">
                  <tr>
                    <th className="px-3 py-3 font-medium">来源</th>
                    <th className="px-3 py-3 font-medium">类型</th>
                    <th className="px-3 py-3 font-medium">优先级</th>
                    <th className="px-3 py-3 font-medium">可信度</th>
                    <th className="px-3 py-3 font-medium">数据更新</th>
                    <th className="px-3 py-3 font-medium">来源说明</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/8">
                  {snapshot.data.data.assetSources.map((source) => (
                    <tr key={source.id}>
                      <td className="px-3 py-3 font-medium text-white">{source.label}</td>
                      <td className="px-3 py-3 text-slate-300">{source.type}</td>
                      <td className="px-3 py-3 text-slate-300">{source.priority}</td>
                      <td className="px-3 py-3 text-slate-300">{source.confidence}</td>
                      <td className="px-3 py-3 text-slate-300">{source.freshness}</td>
                      <td className="px-3 py-3 text-slate-400">{source.lineage}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      ) : null}
    </div>
  );
}
