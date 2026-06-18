import {
  DataStateView,
  MetricCard,
  PageHeader,
  Panel,
  StatusPill,
} from '@/components/p0-ui';
import { getWorkspaceSnapshot, resolveDemoState } from '@/lib/p0';

export const dynamic = 'force-dynamic';

const taskStatusLabel = {
  queued: '等待中',
  running: '处理中',
  failed: '失败',
  ready: '已完成',
} as const;

const syncStatusLabel = {
  success: '正常',
  warning: '需注意',
  failed: '失败',
  running: '更新中',
} as const;

const recoveryStatusLabel: Record<string, string> = {
  pending: '待处理',
  blocked: '需你处理',
};

export default async function OpsPage({
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
        eyebrow="处理中心"
        title="查看处理进度、消息提醒和账户更新状态"
        description="这里用于发现异常、查看处理进度，并确认哪些事项需要你继续处理。普通投资决策仍回到总览、持仓和 Sell Put 页面。"
      />

      <DataStateView
        state={snapshot.state}
        errorMessage={snapshot.errorMessage}
        emptyTitle="当前没有需要关注的处理事项"
        emptyDetail="有分析任务、推送失败、账户更新异常或等待继续处理的事项时，会在这里显示。"
      />

      {snapshot.data ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {snapshot.data.ops.summary.map((metric) => (
              <MetricCard key={metric.label} metric={metric} />
            ))}
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
            <Panel title="处理进度" description="展示研究、账户更新、重算等事项的当前进度。">
              <div className="space-y-3">
                {snapshot.data.ops.jobs.map((job) => (
                  <div key={job.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="font-medium text-white">{job.lane}</p>
                      <StatusPill
                        tone={
                          job.status === 'failed'
                            ? 'danger'
                            : job.status === 'running'
                              ? 'warning'
                              : job.status === 'ready'
                                ? 'positive'
                                : 'muted'
                        }
                      >
                        {taskStatusLabel[job.status]}
                      </StatusPill>
                    </div>
                    <p className="mt-2 text-sm text-slate-400">由 {job.owner} 处理 · 更新时间 {job.updatedAt}</p>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="消息与系统行情" description="微信提醒、系统行情源和自动补发状态统一展示。">
              <div className="space-y-3">
                {snapshot.data.ops.deliveries.map((item) => (
                  <div key={item.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="font-medium text-white">{item.channel}</p>
                      <StatusPill tone="warning">等待重试</StatusPill>
                    </div>
                    <p className="mt-2 text-sm text-slate-400">{item.reason}</p>
                    <p className="mt-2 text-xs text-slate-500">
                      {item.lastAttempt} · {item.recovery}
                    </p>
                  </div>
                ))}
                {snapshot.data.ops.brokerSyncs.map((item) => (
                  <div key={item.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="font-medium text-white">{item.title}</p>
                      <StatusPill tone={item.status === 'failed' ? 'danger' : item.status === 'success' ? 'positive' : 'warning'}>
                        {syncStatusLabel[item.status]}
                      </StatusPill>
                    </div>
                    <p className="mt-2 text-sm text-slate-400">{item.detail}</p>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <Panel title="等待继续处理" description="确认提交、来源冲突或账户更新异常后，需要继续更新数字的事项会出现在这里。">
            <div className="grid gap-3 md:grid-cols-2">
              {snapshot.data.ops.replayQueue.map((item) => (
                <div key={item.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="font-medium text-white">{item.objectType}</p>
                    <StatusPill tone={item.status === 'blocked' ? 'danger' : 'warning'}>
                      {recoveryStatusLabel[item.status] ?? item.status}
                    </StatusPill>
                  </div>
                  <p className="mt-2 text-sm text-slate-400">{item.reason}</p>
                </div>
              ))}
            </div>
          </Panel>
        </>
      ) : null}
    </div>
  );
}
