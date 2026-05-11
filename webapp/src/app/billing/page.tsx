import { requireUser } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
interface Subscription {
  id: string;
  plan: string;
  status: string;
  current_period_end: string | null;
}

interface QuotaTracking {
  daily_writes: number;
  daily_reads: number;
  daily_ai_calls: number;
  quota_reset_at: string | null;
}

interface AddonPack {
  id: string;
  name: string;
  action: string;
  extra_quota: number;
  price: number;
  status: string;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */
const PLAN_FEATURES: Record<string, { label: string; price: string; features: string[]; highlight?: boolean }> = {
  free: {
    label: '免费版',
    price: '¥0',
    features: [
      '10 次/月 AI 分析',
      '5 条/月 交易记录',
      '50 次/月 数据读取',
      '最多 10 只持仓',
      '基础行情数据',
    ],
  },
  basic: {
    label: '标准版',
    price: '¥29/月',
    highlight: true,
    features: [
      '200 次/月 AI 分析',
      '50 条/月 交易记录',
      '500 次/月 数据读取',
      '最多 100 只持仓',
      '全部行情数据源',
      '周报自动生成',
    ],
  },
  pro: {
    label: '专业版',
    price: '¥99/月',
    features: [
      '无限 AI 分析',
      '无限交易记录',
      '无限数据读取',
      '无限持仓',
      '全部数据源 + 深度数据',
      '周报 + 月报自动生成',
      '专属客服支持',
    ],
  },
};

const PLAN_LIMITS: Record<string, Record<string, number>> = {
  free: { ai_analysis: 10, trade_write: 5, data_read: 50 },
  basic: { ai_analysis: 200, trade_write: 50, data_read: 500 },
  pro: { ai_analysis: -1, trade_write: -1, data_read: -1 },
};

const ADDON_CATALOG = [
  { name: 'AI 分析加量包', action: 'ai_analysis', extra_quota: 50, price: 9.9, stripe_price_id: 'price_placeholder_ai_50' },
  { name: '交易记录加量包', action: 'trade_write', extra_quota: 20, price: 4.9, stripe_price_id: 'price_placeholder_trade_20' },
  { name: '数据读取加量包', action: 'data_read', extra_quota: 200, price: 6.9, stripe_price_id: 'price_placeholder_data_200' },
];

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
  });
}

/* ------------------------------------------------------------------ */
/*  Page                                                                */
/* ------------------------------------------------------------------ */
export default async function BillingPage() {
  const { supabase } = await requireUser();

  /* ---------- fetch ---------- */
  const [subRes, quotaRes, addonRes] = await Promise.all([
    supabase
      .from('subscriptions')
      .select('id, plan, status, current_period_end')
      .eq('status', 'active')
      .limit(1),
    supabase
      .from('quota_tracking')
      .select('daily_writes, daily_reads, daily_ai_calls, quota_reset_at')
      .limit(1),
    supabase
      .from('addon_packs')
      .select('id, name, action, extra_quota, price, status')
      .eq('status', 'active')
      .limit(20),
  ]);

  const subscription: Subscription | null = subRes.data?.[0] ?? null;
  const quota: QuotaTracking | null = quotaRes.data?.[0] ?? null;
  const addonPacks: AddonPack[] = addonRes.data ?? [];

  const currentPlan = subscription?.plan || 'free';

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">套餐与计费</h1>
        <p className="mt-1 text-sm text-gray-500">
          管理您的订阅套餐、查看用量与购买增值包。
        </p>
      </div>

      {/* Current Plan */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">当前套餐</h2>
        <div className="mt-4 flex items-center gap-4">
          <div className={`flex h-14 w-14 items-center justify-center rounded-full ${
            currentPlan === 'pro' ? 'bg-purple-100' :
            currentPlan === 'basic' ? 'bg-blue-100' :
            'bg-gray-100'
          }`}>
            <svg className={`h-7 w-7 ${
              currentPlan === 'pro' ? 'text-purple-600' :
              currentPlan === 'basic' ? 'text-blue-600' :
              'text-gray-600'
            }`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
            </svg>
          </div>
          <div className="flex-1">
            <p className="text-lg font-semibold text-gray-900">{PLAN_FEATURES[currentPlan]?.label || '未知'}</p>
            <p className="text-sm text-gray-500">
              {subscription?.current_period_end
                ? `有效期至 ${formatDateTime(subscription.current_period_end)}`
                : '免费版无到期时间'}
            </p>
          </div>
          <a
            href="#plans"
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600"
          >
            {currentPlan === 'pro' ? '管理订阅' : '升级套餐'}
          </a>
        </div>
      </div>

      {/* Current Usage vs Limits */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">当月用量</h2>
        {currentPlan === 'pro' ? (
          <div className="mt-4 rounded-md border border-purple-200 bg-purple-50 p-4 text-sm text-purple-700">
            专业版用户享有无限额度，无需担心用量限制。
          </div>
        ) : (
          <div className="mt-4 space-y-4">
            <UsageBar
              label="AI 分析"
              used={quota?.daily_ai_calls || 0}
              limit={PLAN_LIMITS[currentPlan]?.ai_analysis || 0}
            />
            <UsageBar
              label="交易记录"
              used={quota?.daily_writes || 0}
              limit={PLAN_LIMITS[currentPlan]?.trade_write || 0}
            />
            <UsageBar
              label="数据读取"
              used={quota?.daily_reads || 0}
              limit={PLAN_LIMITS[currentPlan]?.data_read || 0}
            />
          </div>
        )}
        {quota?.quota_reset_at && (
          <p className="mt-3 text-xs text-gray-400">
            配额重置时间：{formatDateTime(quota.quota_reset_at)}
          </p>
        )}
      </div>

      {/* Plan Comparison */}
      <div className="mb-6" id="plans">
        <h2 className="text-lg font-medium text-gray-900">套餐对比</h2>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {Object.entries(PLAN_FEATURES).map(([planKey, plan]) => {
            const isCurrent = planKey === currentPlan;
            return (
              <div
                key={planKey}
                className={`rounded-lg border-2 bg-white p-6 shadow-sm ${
                  plan.highlight
                    ? 'border-primary'
                    : isCurrent
                    ? 'border-green-500'
                    : 'border-gray-200'
                }`}
              >
                {plan.highlight && (
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-primary">推荐</p>
                )}
                <p className="text-lg font-bold text-gray-900">{plan.label}</p>
                <p className="mt-1 text-2xl font-semibold text-gray-900">{plan.price}</p>
                <ul className="mt-4 space-y-2">
                  {plan.features.map((feature, i) => (
                    <li key={i} className="flex items-start text-sm text-gray-600">
                      <svg className="mr-2 mt-0.5 h-4 w-4 flex-shrink-0 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                      {feature}
                    </li>
                  ))}
                </ul>
                <div className="mt-6">
                  {isCurrent ? (
                    <button
                      disabled
                      className="w-full rounded-md border border-gray-300 bg-gray-50 px-4 py-2 text-sm font-medium text-gray-500"
                    >
                      当前套餐
                    </button>
                  ) : (
                    <a
                      href={`/api/billing/checkout?plan=${planKey}`}
                      className={`block w-full rounded-md px-4 py-2 text-center text-sm font-medium text-white transition-colors ${
                        plan.highlight
                          ? 'bg-primary hover:bg-primary-600'
                          : 'bg-gray-800 hover:bg-gray-700'
                      }`}
                    >
                      {planKey === 'free' ? '降级' : '升级'}
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Addon Packs */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">增值包</h2>
        <p className="mt-1 text-sm text-gray-500">当月额度不足时，可购买增值包临时增加额度。</p>

        {/* Already purchased */}
        {addonPacks.length > 0 && (
          <div className="mt-4 space-y-2">
            <p className="text-sm font-medium text-gray-700">已购增值包</p>
            {addonPacks.map((addon) => (
              <div key={addon.id} className="flex items-center justify-between rounded-md border border-green-200 bg-green-50 px-4 py-2">
                <div>
                  <p className="text-sm font-medium text-gray-900">{addon.name}</p>
                  <p className="text-xs text-gray-500">额外 +{addon.extra_quota} 次</p>
                </div>
                <span className="text-sm font-medium text-green-700">¥{addon.price}</span>
              </div>
            ))}
          </div>
        )}

        {/* Catalog */}
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {ADDON_CATALOG.map((item) => (
            <div key={item.action} className="rounded-md border border-gray-200 p-4">
              <p className="text-sm font-medium text-gray-900">{item.name}</p>
              <p className="mt-1 text-xs text-gray-500">+{item.extra_quota} 次/{item.action === 'ai_analysis' ? 'AI分析' : item.action === 'trade_write' ? '交易记录' : '数据读取'}</p>
              <div className="mt-3 flex items-center justify-between">
                <p className="text-lg font-semibold text-gray-900">¥{item.price}</p>
                <a
                  href={`/api/billing/checkout?addon=${item.stripe_price_id}`}
                  className="rounded-md bg-gray-800 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-gray-700"
                >
                  购买
                </a>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Stripe Portal */}
      <div className="mb-6 rounded-lg border border-gray-200 bg-gray-50 p-6">
        <div className="flex items-center gap-3">
          <svg className="h-8 w-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
          </svg>
          <div className="flex-1">
            <p className="font-medium text-gray-900">管理支付方式</p>
            <p className="text-sm text-gray-500">通过 Stripe 客户门户管理您的支付方式与发票</p>
          </div>
          <a
            href="/api/billing/portal"
            className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            管理支付
          </a>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                      */
/* ------------------------------------------------------------------ */

function UsageBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
  const isWarning = pct >= 80;
  const isCritical = pct >= 100;

  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-gray-700">{label}</span>
        <span className={`font-medium ${isCritical ? 'text-red-600' : isWarning ? 'text-yellow-600' : 'text-gray-900'}`}>
          {used} / {limit === -1 ? '∞' : limit}
        </span>
      </div>
      <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          className={`h-2 rounded-full transition-all ${
            isCritical ? 'bg-red-500' : isWarning ? 'bg-yellow-500' : 'bg-primary'
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
