import { requireAdmin } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
interface AuditLog {
  id: string;
  tenant_id: string;
  skill_name: string | null;
  table_name: string | null;
  action: string;
  record_id: string | null;
  created_at: string;
}

interface Subscription {
  id: string;
  tenant_id: string;
  plan: string;
  status: string;
  created_at: string;
  current_period_end: string | null;
}

interface UsageRecord {
  tenant_id: string;
  action: string;
  month_key: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
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

function planLabel(plan: string): string {
  switch (plan) {
    case 'pro':
      return '专业版';
    case 'basic':
      return '标准版';
    case 'free':
      return '免费版';
    default:
      return plan;
  }
}

function planBadgeColor(plan: string): string {
  switch (plan) {
    case 'pro':
      return 'bg-purple-100 text-purple-800';
    case 'basic':
      return 'bg-blue-100 text-blue-800';
    default:
      return 'bg-gray-100 text-gray-800';
  }
}

/* ------------------------------------------------------------------ */
/*  Page                                                                */
/* ------------------------------------------------------------------ */
export default async function AdminPage() {
  const { supabaseAdmin } = await requireAdmin();

  /* ---------- parallel fetch ---------- */
  const [
    auditRes,
    subsRes,
    usageRes,
  ] = await Promise.all([
    supabaseAdmin
      .from('audit_logs')
      .select('id, tenant_id, skill_name, table_name, action, record_id, created_at')
      .order('created_at', { ascending: false })
      .limit(50),
    supabaseAdmin
      .from('subscriptions')
      .select('id, tenant_id, plan, status, created_at, current_period_end')
      .order('created_at', { ascending: false })
      .limit(200),
    supabaseAdmin
      .from('usage_records')
      .select('tenant_id, action, month_key')
      .limit(500),
  ]);

  const auditLogs: AuditLog[] = auditRes.data ?? [];
  const subscriptions: Subscription[] = subsRes.data ?? [];
  const usageRecords: UsageRecord[] = usageRes.data ?? [];

  /* ---------- derive stats ---------- */
  // Subscription counts by plan
  const planCounts: Record<string, number> = {};
  for (const sub of subscriptions) {
    const plan = sub.plan || 'free';
    planCounts[plan] = (planCounts[plan] || 0) + 1;
  }

  // Usage distribution by tenant
  const tenantUsageMap: Record<string, Record<string, number>> = {};
  for (const rec of usageRecords) {
    if (!tenantUsageMap[rec.tenant_id]) {
      tenantUsageMap[rec.tenant_id] = {};
    }
    tenantUsageMap[rec.tenant_id][rec.action] = (tenantUsageMap[rec.tenant_id][rec.action] || 0) + 1;
  }
  const usageDistribution = Object.entries(tenantUsageMap).map(([tenant_id, actions]) => ({
    tenant_id,
    actions,
    total: Object.values(actions).reduce((a, b) => a + b, 0),
  }));
  usageDistribution.sort((a, b) => b.total - a.total);

  // Revenue summary
  const planPrices: Record<string, number> = { free: 0, basic: 29, pro: 99 };
  const subscriptionRevenue = Object.entries(planCounts).reduce(
    (sum, [plan, count]) => sum + (planPrices[plan] || 0) * count,
    0
  );

  /* ---------- render ---------- */
  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">管理后台</h1>
        <p className="mt-1 text-sm text-gray-500">
          系统管理面板：用量统计、订阅概览、审计日志与营收汇总。
        </p>
      </div>

      {/* Revenue & Subscription Summary */}
      <div className="mb-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          title="总用户数"
          value={String(subscriptions.length)}
          subtitle="所有订阅用户"
        />
        <SummaryCard
          title="免费版"
          value={String(planCounts['free'] || 0)}
          subtitle="免费用户"
          color="gray"
        />
        <SummaryCard
          title="标准版"
          value={String(planCounts['basic'] || 0)}
          subtitle="29元/月"
          color="blue"
        />
        <SummaryCard
          title="专业版"
          value={String(planCounts['pro'] || 0)}
          subtitle="99元/月"
          color="purple"
        />
      </div>

      {/* Revenue */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">营收概览</h2>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="rounded-md border border-gray-200 p-4 text-center">
            <p className="text-sm font-medium text-gray-500">月度订阅收入</p>
            <p className="mt-1 text-3xl font-semibold text-gray-900">¥{subscriptionRevenue.toLocaleString()}</p>
          </div>
          <div className="rounded-md border border-gray-200 p-4 text-center">
            <p className="text-sm font-medium text-gray-500">付费用户数</p>
            <p className="mt-1 text-3xl font-semibold text-gray-900">
              {(planCounts['basic'] || 0) + (planCounts['pro'] || 0)}
            </p>
          </div>
        </div>
      </div>

      {/* Usage Distribution */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">用量分布</h2>
        {usageDistribution.length === 0 ? (
          <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            暂无用量记录。
          </div>
        ) : (
          <div className="mt-4 overflow-hidden rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">租户 ID</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">AI 分析</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">交易写入</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">数据读取</th>
                  <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">总计</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {usageDistribution.slice(0, 20).map((item) => (
                  <tr key={item.tenant_id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-2 text-sm font-mono text-gray-900">{item.tenant_id.slice(0, 8)}...</td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-900">{item.actions['ai_analysis'] || 0}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-900">{item.actions['trade_write'] || 0}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-900">{item.actions['data_read'] || 0}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-right text-sm font-medium text-gray-900">{item.total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Subscriptions List */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">订阅列表</h2>
        {subscriptions.length === 0 ? (
          <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            暂无订阅记录。
          </div>
        ) : (
          <div className="mt-4 overflow-hidden rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">租户 ID</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">套餐</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">状态</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">创建时间</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">到期时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {subscriptions.map((sub) => (
                  <tr key={sub.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-2 text-sm font-mono text-gray-900">{sub.tenant_id.slice(0, 8)}...</td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${planBadgeColor(sub.plan)}`}>
                        {planLabel(sub.plan)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${sub.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}`}>
                        {sub.status === 'active' ? '活跃' : sub.status === 'canceled' ? '已取消' : sub.status}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-500">{formatDateTime(sub.created_at)}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-500">{formatDateTime(sub.current_period_end)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Audit Logs */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">审计日志</h2>
        {auditLogs.length === 0 ? (
          <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            暂无审计记录。
          </div>
        ) : (
          <div className="mt-4 overflow-hidden rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">时间</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">租户</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">技能</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">表</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">操作</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">记录 ID</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {auditLogs.map((log) => (
                  <tr key={log.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-500">{formatDateTime(log.created_at)}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm font-mono text-gray-900">{log.tenant_id?.slice(0, 8) || '-'}...</td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-900">{log.skill_name || '-'}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-900">{log.table_name || '-'}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                        log.action === 'INSERT' ? 'bg-green-100 text-green-800' :
                        log.action === 'UPDATE' ? 'bg-yellow-100 text-yellow-800' :
                        log.action === 'DELETE' ? 'bg-red-100 text-red-800' :
                        'bg-gray-100 text-gray-800'
                      }`}>
                        {log.action}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-sm font-mono text-gray-500">{log.record_id?.slice(0, 8) || '-'}...</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                      */
/* ------------------------------------------------------------------ */

function SummaryCard({
  title,
  value,
  subtitle,
  color,
}: {
  title: string;
  value: string;
  subtitle: string;
  color?: 'gray' | 'blue' | 'purple';
}) {
  const borderColor = {
    gray: 'border-l-gray-400',
    blue: 'border-l-blue-500',
    purple: 'border-l-purple-500',
  }[color || 'gray'];

  return (
    <div className={`overflow-hidden rounded-lg bg-white shadow border-l-4 ${borderColor}`}>
      <div className="p-5">
        <p className="truncate text-sm font-medium text-gray-500">{title}</p>
        <p className="mt-1 text-2xl font-semibold text-gray-900">{value}</p>
      </div>
      <div className="bg-gray-50 px-5 py-3">
        <p className="text-sm text-gray-500">{subtitle}</p>
      </div>
    </div>
  );
}
