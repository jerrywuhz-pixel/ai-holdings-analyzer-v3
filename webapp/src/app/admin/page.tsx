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

interface TenantAccount {
  tenant_id: string;
  display_name: string | null;
  account_status: string;
}

interface ChannelBindingRow {
  tenant_id: string;
  binding_status: string | null;
  channel_account_id: string | null;
  openclaw_account_id: string | null;
  is_primary: boolean;
  bound_at: string | null;
  last_seen_at: string | null;
}

interface WechatAuthSessionRow {
  tenant_id: string;
  status: string;
  created_at: string;
  confirmed_at: string | null;
  conversation_verified_at: string | null;
  expires_at: string | null;
}

interface BrokerConnectorRow {
  tenant_id: string;
  heartbeat_status: string;
  broker: string;
  last_seen_at: string | null;
}

interface HermesHeartbeatRow {
  instance_id: string;
  hermes_status: string;
  reported_at: string;
}

interface TenantHealth {
  tenant_id: string;
  displayName: string;
  accountStatus: string;
  wechatBinding: {
    status: string;
    accountId: string | null;
    lastSeenAt: string | null;
    boundAt: string | null;
  };
  wechatAuthStatus: string;
  broker: {
    total: number;
    online: number;
    lastSeenAt: string | null;
  };
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

function statusBadgeColor(status: string): string {
  switch (status) {
    case '健康':
    case '已绑定':
      return 'bg-green-100 text-green-800';
    case '部分健康':
    case '待绑定':
    case '未接入':
      return 'bg-yellow-100 text-yellow-800';
    default:
      return 'bg-gray-100 text-gray-800';
  }
}

function pickLatestByTime<T extends { tenant_id: string } & Record<string, any>>(
  rows: T[],
  getTime: (row: T) => string
): Map<string, T> {
  const map = new Map<string, T>();
  for (const row of rows) {
    const prev = map.get(row.tenant_id);
    if (!prev || new Date(getTime(row)).getTime() > new Date(getTime(prev)).getTime()) {
      map.set(row.tenant_id, row);
    }
  }
  return map;
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
    tenantAccountsRes,
    channelBindingRes,
    wechatAuthRes,
    brokerConnectorRes,
    hermesHeartbeatRes,
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
    supabaseAdmin
      .from('tenant_accounts')
      .select('tenant_id, display_name, account_status')
      .order('tenant_id'),
    supabaseAdmin
      .from('channel_bindings')
      .select('tenant_id, binding_status, channel_account_id, openclaw_account_id, is_primary, bound_at, last_seen_at')
      .in('channel', ['hermes_wechat', 'openclaw_wechat'])
      .order('tenant_id'),
    supabaseAdmin
      .from('wechat_clawbot_auth_sessions')
      .select('tenant_id, status, created_at, confirmed_at, conversation_verified_at, expires_at')
      .order('created_at', { ascending: false }),
    supabaseAdmin
      .from('broker_connector_instances')
      .select('tenant_id, heartbeat_status, broker, last_seen_at')
      .order('tenant_id'),
    supabaseAdmin
      .from('hermes_heartbeat')
      .select('instance_id, hermes_status, reported_at')
      .order('reported_at', { ascending: false })
      .limit(3),
  ]);

  const auditLogs: AuditLog[] = auditRes.data ?? [];
  const subscriptions: Subscription[] = subsRes.data ?? [];
  const usageRecords: UsageRecord[] = usageRes.data ?? [];
  const tenantAccounts: TenantAccount[] = tenantAccountsRes.data ?? [];
  const channelBindings: ChannelBindingRow[] = channelBindingRes.data ?? [];
  const wechatAuthSessions: WechatAuthSessionRow[] = wechatAuthRes.data ?? [];
  const brokerConnectorRows: BrokerConnectorRow[] = brokerConnectorRes.data ?? [];
  const hermesHeartbeats: HermesHeartbeatRow[] = hermesHeartbeatRes.data ?? [];

  const latestChannelBindingByTenant = new Map<string, ChannelBindingRow>();
  for (const row of channelBindings) {
    const current = latestChannelBindingByTenant.get(row.tenant_id);
    if (!current || (row.is_primary && !current.is_primary)) {
      latestChannelBindingByTenant.set(row.tenant_id, row);
      continue;
    }
    if (current.is_primary && !row.is_primary) {
      continue;
    }
    if (row.binding_status === 'active' && current.binding_status !== 'active') {
      latestChannelBindingByTenant.set(row.tenant_id, row);
    }
  }

  const latestWechatAuthByTenant = pickLatestByTime(wechatAuthSessions, (row) => row.created_at);

  const brokerStatusByTenant = new Map<
    string,
    { total: number; online: number; lastSeenAt: string | null }
  >();
  for (const row of brokerConnectorRows) {
    const current = brokerStatusByTenant.get(row.tenant_id) || { total: 0, online: 0, lastSeenAt: null };
    current.total += 1;
    if (row.heartbeat_status === 'online') {
      current.online += 1;
    }
    if (!current.lastSeenAt || (row.last_seen_at && new Date(row.last_seen_at) > new Date(current.lastSeenAt))) {
      current.lastSeenAt = row.last_seen_at;
    }
    brokerStatusByTenant.set(row.tenant_id, current);
  }

  const tenantHealths: TenantHealth[] = tenantAccounts.map((tenant) => {
    const binding = latestChannelBindingByTenant.get(tenant.tenant_id);
    const auth = latestWechatAuthByTenant.get(tenant.tenant_id) || null;
    const broker = brokerStatusByTenant.get(tenant.tenant_id) || { total: 0, online: 0, lastSeenAt: null };
    const wechatStatus = binding && binding.binding_status === 'active' ? '已绑定' : '待绑定';
    return {
      tenant_id: tenant.tenant_id,
      displayName: tenant.display_name || tenant.tenant_id.slice(0, 8),
      accountStatus: tenant.account_status || 'unknown',
      wechatBinding: {
        status: wechatStatus,
        accountId: binding?.channel_account_id || binding?.openclaw_account_id || null,
        lastSeenAt: binding?.last_seen_at || null,
        boundAt: binding?.bound_at || null,
      },
      wechatAuthStatus: auth?.status || '未授权',
      broker: {
        total: broker.total,
        online: broker.online,
        lastSeenAt: broker.lastSeenAt,
      },
    };
  });

  const wechatBoundCount = tenantHealths.filter((row) => row.wechatBinding.status === '已绑定').length;
  const brokerConnectedCount = tenantHealths.filter((row) => row.broker.total > 0).length;
  const authVerifiedCount = tenantHealths.filter((row) => row.wechatAuthStatus === 'conversation_verified').length;
  const latestHermes = hermesHeartbeats[0] || null;
  const gatewayStatus = latestHermes?.hermes_status || 'unknown';
  const gatewayPluginStatus = 'hermes-only';

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

      <div className="mb-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          title="已绑定微信租户"
          value={String(wechatBoundCount)}
          subtitle="当前有有效微信绑定的租户"
        />
        <SummaryCard
          title="微信会话已核验"
          value={String(authVerifiedCount)}
          subtitle="会话核验状态为 conversation_verified"
        />
        <SummaryCard
          title="已接入券商连接"
          value={String(brokerConnectedCount)}
          subtitle="有 broker_connector_instances 的租户数"
        />
        <SummaryCard
          title="Hermes运行状态"
          value={gatewayStatus}
          subtitle={`运行模式：${gatewayPluginStatus}`}
        />
      </div>

      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">租户健康总览（只读）</h2>
        {tenantHealths.length === 0 ? (
          <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            暂无租户健康数据。
          </div>
        ) : (
          <div className="mt-4 overflow-hidden rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">租户</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">账号状态</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">微信绑定</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">微信会话</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">券商实例</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">券商最近在线</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {tenantHealths.map((row) => {
                  const brokerLabel = `${row.broker.online}/${row.broker.total}`;
                  return (
                    <tr key={row.tenant_id} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-900">
                        <div className="font-medium">{row.displayName}</div>
                        <div className="text-xs text-gray-500">{row.tenant_id}</div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-500">{row.accountStatus}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-sm">
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${statusBadgeColor(row.wechatBinding.status)}`}>
                          {row.wechatBinding.status}
                        </span>
                        <div className="mt-1 text-xs text-gray-500">
                          {row.wechatBinding.accountId || '-'}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-500">{row.wechatAuthStatus}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-sm">
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          statusBadgeColor(
                            row.broker.total === 0
                              ? '未接入'
                              : row.broker.online === row.broker.total
                                ? '健康'
                                : row.broker.online > 0
                                  ? '部分健康'
                                  : '离线',
                          )
                        }`}>
                          {row.broker.total === 0
                            ? '未接入'
                            : row.broker.online === row.broker.total
                              ? '健康'
                              : row.broker.online > 0
                                ? '部分健康'
                                : '离线'}
                        </span>
                        <div className="mt-1 text-xs text-gray-500">在线数：{brokerLabel}</div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-500">{formatDateTime(row.broker.lastSeenAt)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
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
