import { requireUser } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
interface HeartbeatRecord {
  deployment_mode: string;
  instance_id: string;
  gateway_status: string;
  last_cron_run_at: string | null;
  active_skills: string[] | null;
  claw_plugin_status: string | null;
  memory_usage_mb: number | null;
  cpu_usage_percent: number | null;
  reported_at: string;
}

interface DataSourceHealth {
  source_name: string;
  display_name: string;
  status: string;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error_message: string | null;
  consecutive_failures: number;
  total_requests: number;
  total_failures: number;
  avg_response_ms: number | null;
}

interface QuotaTracking {
  daily_writes: number;
  daily_reads: number;
  daily_ai_calls: number;
  quota_reset_at: string | null;
  updated_at: string | null;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
function statusIndicator(status: string): { color: string; label: string } {
  switch (status) {
    case 'healthy':
    case 'connected':
      return { color: 'bg-green-500', label: '正常' };
    case 'degraded':
      return { color: 'bg-yellow-500', label: '降级' };
    case 'down':
    case 'error':
    case 'disconnected':
      return { color: 'bg-red-500', label: '异常' };
    case 'unknown':
    default:
      return { color: 'bg-gray-400', label: '未知' };
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

function timeAgo(iso: string | null): string {
  if (!iso) return '从未';
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return '刚刚';
  if (diffMin < 60) return `${diffMin} 分钟前`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} 小时前`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay} 天前`;
}

function normalizeFeatureLabel(value: string): string {
  const lower = value.toLowerCase();
  if (lower.includes('ocr')) return '截图识别修正';
  if (lower.includes('asr') || lower.includes('voice')) return '语音识别修正';
  if (lower.includes('wechat') || lower.includes('wx')) return '微信提醒';
  if (lower.includes('confirm')) return '确认中心';
  if (lower.includes('sell-put') || lower.includes('sell_put')) return 'Sell Put 分析';
  if (lower.includes('broker') || lower.includes('sync')) return '账户数据更新';
  return value.replaceAll('_', ' ').replaceAll('-', ' ');
}

/* ------------------------------------------------------------------ */
/*  Page                                                                */
/* ------------------------------------------------------------------ */
export default async function SettingsPage() {
  const { supabase } = await requireUser();

  /* ---------- parallel fetch ---------- */
  const [heartbeatRes, healthRes, quotaRes] = await Promise.all([
    supabase
      .from('openclaw_heartbeat')
      .select('deployment_mode, instance_id, gateway_status, last_cron_run_at, active_skills, claw_plugin_status, memory_usage_mb, cpu_usage_percent, reported_at')
      .order('reported_at', { ascending: false })
      .limit(1),
    supabase
      .from('data_source_health')
      .select('source_name, display_name, status, last_success_at, last_failure_at, last_error_message, consecutive_failures, total_requests, total_failures, avg_response_ms')
      .order('source_name'),
    supabase
      .from('quota_tracking')
      .select('daily_writes, daily_reads, daily_ai_calls, quota_reset_at, updated_at')
      .limit(1),
  ]);

  const heartbeat: HeartbeatRecord | null = heartbeatRes.data?.[0] ?? null;
  const dataSources: DataSourceHealth[] = healthRes.data ?? [];
  const quota: QuotaTracking | null = quotaRes.data?.[0] ?? null;

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">设置</h1>
        <p className="mt-1 text-sm text-gray-500">
          账户、数据连接与消息提醒的状态。
        </p>
      </div>

      {/* User info placeholder */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">用户信息</h2>
        <div className="mt-4 flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary text-white">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          </div>
          <div>
            <p className="font-medium text-gray-900">演示用户</p>
            <p className="text-sm text-gray-500">登录与账户管理会在后续版本开放</p>
          </div>
        </div>
      </div>

      {/* Channel status */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">微信提醒</h2>
        {!heartbeat ? (
          <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            暂未收到微信提醒状态，消息推送可能尚未连接。
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <StatusItem
              label="提醒服务"
              indicator={statusIndicator(heartbeat.gateway_status)}
            />
            <StatusItem
              label="微信连接"
              indicator={statusIndicator(heartbeat.claw_plugin_status || 'unknown')}
            />
            <div className="rounded-md border border-gray-200 p-3">
              <p className="text-xs font-medium text-gray-500">运行环境</p>
              <p className="mt-1 text-sm text-gray-900">{heartbeat.deployment_mode === 'cloud' ? '云端' : '本地'}</p>
            </div>
            <div className="rounded-md border border-gray-200 p-3">
              <p className="text-xs font-medium text-gray-500">连接编号</p>
              <p className="mt-1 break-all text-sm font-mono text-gray-900">{heartbeat.instance_id}</p>
            </div>
            <div className="rounded-md border border-gray-200 p-3">
              <p className="text-xs font-medium text-gray-500">最近自动检查</p>
              <p className="mt-1 text-sm text-gray-900">{timeAgo(heartbeat.last_cron_run_at)}</p>
            </div>
            <div className="rounded-md border border-gray-200 p-3">
              <p className="text-xs font-medium text-gray-500">最近状态回报</p>
              <p className="mt-1 text-sm text-gray-900">{timeAgo(heartbeat.reported_at)}</p>
            </div>
            {heartbeat.active_skills && heartbeat.active_skills.length > 0 && (
              <div className="col-span-full rounded-md border border-gray-200 p-3">
                <p className="mb-1 text-xs font-medium text-gray-500">已启用功能</p>
                <div className="flex flex-wrap gap-1">
                  {heartbeat.active_skills.map((skill) => (
                    <span key={skill} className="inline-flex items-center rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                      {normalizeFeatureLabel(skill)}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {(heartbeat.memory_usage_mb != null || heartbeat.cpu_usage_percent != null) && (
              <div className="col-span-full rounded-md border border-gray-200 p-3">
                <p className="mb-1 text-xs font-medium text-gray-500">资源使用</p>
                <div className="flex flex-wrap gap-4 text-sm text-gray-900">
                  {heartbeat.memory_usage_mb != null && <span>内存: {heartbeat.memory_usage_mb} MB</span>}
                  {heartbeat.cpu_usage_percent != null && <span>CPU: {heartbeat.cpu_usage_percent}%</span>}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Data source status */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">数据来源状态</h2>
        {dataSources.length === 0 ? (
          <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            暂无数据来源状态记录。
          </div>
        ) : (
          <>
            <div className="mt-4 space-y-3 md:hidden">
              {dataSources.map((ds) => (
                <div key={ds.source_name} className="rounded-lg border border-gray-200 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-medium text-gray-900">{ds.display_name}</p>
                      <p className="mt-1 text-sm text-gray-500">最近成功 {timeAgo(ds.last_success_at)}</p>
                    </div>
                    <StatusIndicator status={ds.status} />
                  </div>
                  <div className="mt-4 grid gap-2 text-sm text-gray-700 sm:grid-cols-2">
                    <p>累计请求 {ds.total_requests}</p>
                    <p>累计失败 {ds.total_failures}</p>
                    <p>平均响应 {ds.avg_response_ms != null ? `${ds.avg_response_ms}ms` : '-'}</p>
                    <p>连续失败 {ds.consecutive_failures}</p>
                  </div>
                  {ds.last_error_message ? (
                    <p className="mt-3 text-sm leading-6 text-amber-700">{ds.last_error_message}</p>
                  ) : null}
                </div>
              ))}
            </div>

            <div className="mt-4 hidden overflow-hidden rounded-lg border border-gray-200 md:block">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">数据源</th>
                    <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">状态</th>
                    <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">累计请求</th>
                    <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">累计失败</th>
                    <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">平均响应</th>
                    <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">上次成功</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {dataSources.map((ds) => (
                    <tr key={ds.source_name} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-2 text-sm font-medium text-gray-900">{ds.display_name}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-sm">
                        <StatusIndicator status={ds.status} />
                      </td>
                      <td className="whitespace-nowrap px-4 py-2 text-right text-sm text-gray-900">{ds.total_requests}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-right text-sm text-gray-900">{ds.total_failures}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-right text-sm text-gray-900">{ds.avg_response_ms != null ? `${ds.avg_response_ms}ms` : '-'}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-500">{timeAgo(ds.last_success_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {/* Quota tracking */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">用量统计</h2>
        {!quota ? (
          <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            暂无用量数据。
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <QuotaCard label="今日写入" value={quota.daily_writes} />
            <QuotaCard label="今日读取" value={quota.daily_reads} />
            <QuotaCard label="今日分析次数" value={quota.daily_ai_calls} />
          </div>
        )}
        {quota?.quota_reset_at && (
          <p className="mt-3 text-xs text-gray-400">
            用量重置时间：{formatDateTime(quota.quota_reset_at)}
          </p>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                      */
/* ------------------------------------------------------------------ */

function StatusItem({ label, indicator }: { label: string; indicator: { color: string; label: string } }) {
  return (
    <div className="rounded-md border border-gray-200 p-3">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <div className="mt-1 flex items-center gap-2">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${indicator.color}`} />
        <span className="text-sm font-medium text-gray-900">{indicator.label}</span>
      </div>
    </div>
  );
}

function StatusIndicator({ status }: { status: string }) {
  const indicator = statusIndicator(status);
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block h-2 w-2 rounded-full ${indicator.color}`} />
      <span className="text-xs font-medium text-gray-700">{indicator.label}</span>
    </span>
  );
}

function QuotaCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-gray-200 p-4 text-center">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-gray-900">{value.toLocaleString()}</p>
    </div>
  );
}
