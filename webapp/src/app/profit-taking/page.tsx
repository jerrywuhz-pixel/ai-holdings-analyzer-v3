import { requireUser } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

interface ProfitTakingPlan {
  id: string;
  symbol: string;
  stock_name: string | null;
  market: string;
  plan_date: string;
  action: 'HOLD' | 'WATCH_TARGET' | 'TAKE_PROFIT';
  target_price: number | null;
  stop_price: number | null;
  reduce_ratio: number | null;
  today_reach_probability: 'low' | 'medium' | 'high';
  backtest_summary: {
    validated?: boolean;
    sample_size?: number;
    win_rate?: number;
    avg_avoided_drawdown?: number;
  } | null;
  metrics: {
    profit_pct?: number;
    rsi14?: number;
    atr14?: number;
    market_regime?: { regime?: string; reason?: string };
  } | null;
  reason: string | null;
  instruction: string | null;
  delivery_status: string;
  created_at: string;
}

function formatPrice(value: number | null | undefined): string {
  if (value == null) return '-';
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPercent(value: number | null | undefined): string {
  if (value == null) return '-';
  return `${(value * 100).toFixed(1)}%`;
}

function actionBadge(action: ProfitTakingPlan['action']): { label: string; className: string } {
  switch (action) {
    case 'TAKE_PROFIT':
      return { label: '执行止盈', className: 'bg-red-100 text-red-800' };
    case 'WATCH_TARGET':
      return { label: '目标观察', className: 'bg-amber-100 text-amber-800' };
    default:
      return { label: '继续持有', className: 'bg-gray-100 text-gray-700' };
  }
}

function probabilityLabel(value: ProfitTakingPlan['today_reach_probability']): string {
  const map = { low: '低', medium: '中', high: '高' };
  return map[value] || value;
}

export default async function ProfitTakingPage() {
  const { supabase } = await requireUser();

  const { data, error } = await supabase
    .from('profit_taking_plans')
    .select('id, symbol, stock_name, market, plan_date, action, target_price, stop_price, reduce_ratio, today_reach_probability, backtest_summary, metrics, reason, instruction, delivery_status, created_at')
    .order('plan_date', { ascending: false })
    .order('created_at', { ascending: false })
    .limit(50);

  if (error) {
    return (
      <div className="mx-auto max-w-6xl">
        <h1 className="text-2xl font-bold text-gray-900">止盈计划</h1>
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          数据加载失败：{error.message}
        </div>
      </div>
    );
  }

  const plans: ProfitTakingPlan[] = data ?? [];
  const actionableCount = plans.filter((p) => p.action !== 'HOLD').length;

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">止盈计划</h1>
          <p className="mt-1 text-sm text-gray-500">
            查看每日 9 点生成的持仓止盈行动建议。
          </p>
        </div>
        <div className="rounded-lg bg-white px-4 py-3 text-sm shadow-sm">
          <span className="text-gray-500">待关注</span>
          <span className="ml-2 text-lg font-semibold text-gray-900">{actionableCount}</span>
        </div>
      </div>

      {plans.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white py-16">
          <svg className="h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-gray-900">暂无止盈计划</h3>
          <p className="mt-1 text-sm text-gray-500">定时任务执行后会在这里显示每日行动建议。</p>
        </div>
      ) : (
        <div className="space-y-4">
          {plans.map((plan) => {
            const badge = actionBadge(plan.action);
            const backtest = plan.backtest_summary ?? {};
            const metrics = plan.metrics ?? {};
            const regime = metrics.market_regime?.regime || 'neutral';
            return (
              <div key={plan.id} className="rounded-lg bg-white p-5 shadow">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-lg font-semibold text-gray-900">
                        {plan.stock_name || plan.symbol}
                      </h2>
                      <span className="text-sm text-gray-400">{plan.symbol}</span>
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${badge.className}`}>
                        {badge.label}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-gray-500">
                      {plan.plan_date} · {plan.market} · 大盘状态 {regime}
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                    <Metric label="目标价" value={formatPrice(plan.target_price)} />
                    <Metric label="保护价" value={formatPrice(plan.stop_price)} />
                    <Metric label="浮盈" value={formatPercent(metrics.profit_pct)} />
                    <Metric label="触达概率" value={probabilityLabel(plan.today_reach_probability)} />
                  </div>
                </div>

                {plan.instruction && (
                  <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm leading-6 text-gray-700">
                    {plan.instruction}
                  </div>
                )}

                <div className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-4">
                  <Metric label="回测有效" value={backtest.validated ? '是' : '否'} />
                  <Metric label="样本数" value={String(backtest.sample_size ?? '-')} />
                  <Metric label="胜率" value={formatPercent(backtest.win_rate)} />
                  <Metric label="推送状态" value={plan.delivery_status} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 font-medium text-gray-900">{value}</p>
    </div>
  );
}
