import { requireUser } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
interface JobRun {
  id: string;
  job_type: string;
  status: string;
  config: Record<string, unknown> | null;
  result_summary: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  retry_count: number;
  created_at: string;
}

interface DeliveryRun {
  id: string;
  job_run_id: string;
  channel: string;
  status: string;
  sent_at: string | null;
  error_message: string | null;
  retry_count: number;
  created_at: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
function statusBadge(status: string): { class: string; label: string } {
  switch (status) {
    case 'PENDING':
      return { class: 'bg-yellow-100 text-yellow-800', label: '等待中' };
    case 'RUNNING':
      return { class: 'bg-blue-100 text-blue-800', label: '运行中' };
    case 'SUCCESS':
      return { class: 'bg-green-100 text-green-800', label: '成功' };
    case 'FAILED':
      return { class: 'bg-red-100 text-red-800', label: '失败' };
    case 'TIMED_OUT':
      return { class: 'bg-orange-100 text-orange-800', label: '超时' };
    case 'ABANDONED':
      return { class: 'bg-gray-100 text-gray-800', label: '已放弃' };
    case 'CANCELLED':
      return { class: 'bg-gray-100 text-gray-800', label: '已取消' };
    default:
      return { class: 'bg-gray-100 text-gray-800', label: status };
  }
}

function channelLabel(channel: string): string {
  switch (channel) {
    case 'wechat_claw': return '微信 Claw';
    case 'email': return '邮件';
    case 'sms': return '短信';
    case 'push': return '推送';
    default: return channel;
  }
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '-';
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function jobTypeLabel(type: string): string {
  const map: Record<string, string> = {
    'position-aggregate': '持仓聚合',
    'daily-analysis': '每日分析',
    'broker-parse': '券商解析',
    'trade-input': '交易录入',
    'weekly-report': '周报生成',
    'profit_taking': '止盈计划',
    'daily-profit-taking': '止盈计划',
  };
  return map[type] || type;
}

/* ------------------------------------------------------------------ */
/*  Page                                                                */
/* ------------------------------------------------------------------ */
export default async function JobsPage() {
  const { supabase } = await requireUser();

  const { data: jobs, error } = await supabase
    .from('job_runs')
    .select('id, job_type, status, config, result_summary, started_at, completed_at, error_message, retry_count, created_at')
    .order('created_at', { ascending: false })
    .limit(50);

  if (error) {
    return (
      <div className="mx-auto max-w-6xl">
        <h1 className="text-2xl font-bold text-gray-900">任务状态</h1>
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          数据加载失败：{error.message}
        </div>
      </div>
    );
  }

  const jobRuns: JobRun[] = jobs ?? [];

  /* Fetch delivery runs for each job */
  const jobIds = jobRuns.map((j) => j.id);
  const { data: deliveries } = await supabase
    .from('delivery_runs')
    .select('id, job_run_id, channel, status, sent_at, error_message, retry_count, created_at')
    .in('job_run_id', jobIds.length > 0 ? jobIds : ['00000000-0000-0000-0000-000000000000'])
    .order('created_at', { ascending: false });

  const deliveryMap = new Map<string, DeliveryRun[]>();
  for (const d of deliveries ?? []) {
    const list = deliveryMap.get(d.job_run_id) ?? [];
    list.push(d);
    deliveryMap.set(d.job_run_id, list);
  }

  /* Status summary */
  const statusCounts: Record<string, number> = {};
  for (const j of jobRuns) {
    statusCounts[j.status] = (statusCounts[j.status] || 0) + 1;
  }

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">任务状态</h1>
        <p className="mt-1 text-sm text-gray-500">
          查看系统后台任务执行状态。
        </p>
      </div>

      {/* Status summary */}
      {jobRuns.length > 0 && (
        <div className="mb-6 flex flex-wrap gap-3">
          {Object.entries(statusCounts).map(([status, count]) => {
            const badge = statusBadge(status);
            return (
              <div key={status} className="flex items-center gap-2 rounded-lg bg-white px-4 py-2 shadow-sm">
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${badge.class}`}>
                  {badge.label}
                </span>
                <span className="text-sm font-medium text-gray-700">{count}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Table */}
      {jobRuns.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white py-16">
          <svg className="h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-gray-900">暂无任务记录</h3>
          <p className="mt-1 text-sm text-gray-500">系统尚未执行任何后台任务。</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg bg-white shadow">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">任务类型</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">状态</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">开始时间</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">完成时间</th>
                  <th className="px-6 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">重试</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">错误信息</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {jobRuns.map((job) => {
                  const badge = statusBadge(job.status);
                  const deliveries = deliveryMap.get(job.id) ?? [];
                  return (
                    <JobRow
                      key={job.id}
                      job={job}
                      badge={badge}
                      deliveries={deliveries}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                      */
/* ------------------------------------------------------------------ */

function JobRow({
  job,
  badge,
  deliveries,
}: {
  job: JobRun;
  badge: { class: string; label: string };
  deliveries: DeliveryRun[];
}) {
  return (
    <>
      <tr className="hover:bg-gray-50">
        <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-gray-900">{jobTypeLabel(job.job_type)}</td>
        <td className="whitespace-nowrap px-6 py-4 text-sm">
          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${badge.class}`}>
            {badge.label}
          </span>
        </td>
        <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">{formatDateTime(job.started_at)}</td>
        <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">{formatDateTime(job.completed_at)}</td>
        <td className="whitespace-nowrap px-6 py-4 text-center text-sm text-gray-900">{job.retry_count}</td>
        <td className="max-w-[250px] truncate px-6 py-4 text-sm text-red-600" title={job.error_message || undefined}>
          {job.error_message || '-'}
        </td>
      </tr>
      {deliveries.length > 0 && (
        <tr className="bg-gray-50">
          <td colSpan={6} className="px-6 py-3">
            <div className="ml-4 flex flex-wrap gap-2">
              <span className="text-xs font-medium text-gray-500">投递记录：</span>
              {deliveries.map((d) => {
                const dBadge = statusBadge(d.status);
                return (
                  <span key={d.id} className="inline-flex items-center gap-1 rounded-md border border-gray-200 bg-white px-2 py-1 text-xs">
                    <span className="text-gray-600">{channelLabel(d.channel)}</span>
                    <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${dBadge.class}`}>{dBadge.label}</span>
                  </span>
                );
              })}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
