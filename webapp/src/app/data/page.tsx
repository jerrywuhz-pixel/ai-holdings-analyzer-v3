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
import { getWorkspaceSnapshot, resolvePageState } from '@/lib/p0';
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
  const state = resolvePageState(params.state);
  const session = await requireUser();
  const [account, snapshot] = await Promise.all([
    ensureUserAccount(session.user),
    getWorkspaceSnapshot({ state }),
  ]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="数据与账户"
        title="数据来源、最近更新和数字口径都在这里"
        description="这里说明当前账号的数据来源、最近更新时间和页面金额口径。系统行情源由管理员统一维护，不代表普通用户自己的富途账户同步。"
      />

      <LiveDataBanner dataState={snapshot.liveData} />

      <DataStateView
        state={snapshot.state}
        errorMessage={snapshot.errorMessage}
        emptyTitle="暂无可用数据来源"
        emptyDetail="等待资产来源、系统行情或最近更新记录接入。"
      />

      {snapshot.data ? (
        <>
          <DegradationBanner sources={snapshot.data.chrome.sources} compact />

          <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
            <Panel title="账户工作区" description="每个登录账号都有独立的 account_id、tenant_id、资产视图和数据来源。">
              <div className="grid gap-3 text-sm text-[#4f494c]">
                <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-[#8a817d]">account_id</p>
                  <p className="mt-2 break-all font-mono text-[#171417]">{account.accountId}</p>
                </div>
                <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-[#8a817d]">tenant_id</p>
                  <p className="mt-2 break-all font-mono text-[#171417]">{account.tenantId}</p>
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                    <p className="text-xs text-[#8a817d]">资产视图</p>
                    <p className="mt-1 text-lg font-semibold text-[#171417]">{account.portfolioViews.length}</p>
                  </div>
                  <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                    <p className="text-xs text-[#8a817d]">关注清单</p>
                    <p className="mt-1 text-lg font-semibold text-[#171417]">{account.followView?.itemCount ?? 0}</p>
                  </div>
                  <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                    <p className="text-xs text-[#8a817d]">清仓回溯</p>
                    <p className="mt-1 text-lg font-semibold text-[#171417]">{account.listView?.itemCount ?? 0}</p>
                  </div>
                </div>
              </div>
            </Panel>

            <Panel title="手工录入持仓" description="适合先把交易 App 里看到的持仓录进来；系统会记录来源并刷新当前账号的持仓快照。">
              <ManualPositionForm />
            </Panel>
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {snapshot.data.data.summary.map((metric) => (
              <MetricCard key={metric.label} metric={metric} />
            ))}
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
            <Panel title="系统行情源" description="这里只说明系统级行情源是否可用；普通用户持仓和现金不从个人 Futu 账号自动同步。">
              <div className="space-y-3">
                {snapshot.data.data.connections.map((connection) => (
                  <div key={connection.id} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="font-medium text-[#171417]">{connection.provider}</p>
                        <p className="mt-1 text-sm text-[#6f686b]">{connection.accountLabel}</p>
                      </div>
                      <StatusPill tone={connection.authStatus === 'connected' ? 'positive' : 'warning'}>
                        {connectionStatusLabel[connection.authStatus] ?? connection.authStatus}
                      </StatusPill>
                    </div>
                    <div className="mt-3 grid gap-2 text-sm text-[#4f494c]">
                      <p>权限 {connection.permissionScope}</p>
                      <p>最近更新 {connection.lastSync}</p>
                      <p>更新 {connection.freshness}</p>
                    </div>
                    {connection.degradation ? (
                      <p className="mt-3 text-sm text-amber-700">{connection.degradation}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="最近更新记录" description="告诉你最近一次拿到新数据的时间，以及当前还有哪些字段待补齐。">
              <div className="space-y-3">
                {snapshot.data.data.syncEvents.map((event) => (
                  <div key={event.id} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="font-medium text-[#171417]">{event.title}</p>
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
                    <p className="mt-2 text-sm text-[#6f686b]">{event.detail}</p>
                    <p className="mt-2 text-xs text-[#8a817d]">开始时间 {event.startedAt}</p>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <Panel title="资产数据来源" description="展示系统行情、手工录入、截图识别以及多币种折算口径的优先级、可信度和更新时间。">
            <div className="space-y-3 md:hidden">
              {snapshot.data.data.assetSources.map((source) => (
                <div key={source.id} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-medium text-[#171417]">{source.label}</p>
                      <p className="mt-1 text-sm text-[#6f686b]">{source.type}</p>
                    </div>
                    <StatusPill tone="muted">{source.priority}</StatusPill>
                  </div>
                  <div className="mt-4 grid gap-3 text-sm text-[#4f494c] sm:grid-cols-2">
                    <p>可信度 {source.confidence}</p>
                    <p>数据更新 {source.freshness}</p>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-[#6f686b]">{source.lineage}</p>
                </div>
              ))}
            </div>

            <div className="hidden overflow-x-auto md:block">
              <table className="min-w-full divide-y divide-[#e5ddd9] text-sm">
                <thead className="text-left text-[#6f686b]">
                  <tr>
                    <th className="px-3 py-3 font-medium">来源</th>
                    <th className="px-3 py-3 font-medium">类型</th>
                    <th className="px-3 py-3 font-medium">优先级</th>
                    <th className="px-3 py-3 font-medium">可信度</th>
                    <th className="px-3 py-3 font-medium">数据更新</th>
                    <th className="px-3 py-3 font-medium">来源说明</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#e5ddd9]">
                  {snapshot.data.data.assetSources.map((source) => (
                    <tr key={source.id}>
                      <td className="px-3 py-3 font-medium text-[#171417]">{source.label}</td>
                      <td className="px-3 py-3 text-[#4f494c]">{source.type}</td>
                      <td className="px-3 py-3 text-[#4f494c]">{source.priority}</td>
                      <td className="px-3 py-3 text-[#4f494c]">{source.confidence}</td>
                      <td className="px-3 py-3 text-[#4f494c]">{source.freshness}</td>
                      <td className="px-3 py-3 text-[#6f686b]">{source.lineage}</td>
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
