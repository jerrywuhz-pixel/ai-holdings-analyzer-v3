import Link from 'next/link';
import { requireUser } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
interface PositionRow {
  id: string;
  symbol: string;
  provider_symbol: string;
  market: string;
  exchange: string;
  stock_name: string | null;
  total_quantity: number;
  average_cost: number | null;
  total_cost: number | null;
  snapshot_date: string;
  tenant_id: string;
  source_tier: string | null;
  source_actionability: string | null;
  source_lineage: Record<string, unknown> | null;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
function formatCurrency(value: number | null | undefined, market?: string): string {
  if (value == null) return '-';
  const prefix = market === 'US' ? '$' : '¥';
  const sign = value < 0 ? '-' : '';
  return `${sign}${prefix}${Math.abs(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function marketLabel(market: string): string {
  switch (market) {
    case 'CN': return 'A股';
    case 'US': return '美股';
    case 'HK': return '港股';
    default: return market;
  }
}

function marketBadgeClass(market: string): string {
  switch (market) {
    case 'CN': return 'bg-red-100 text-red-800';
    case 'US': return 'bg-blue-100 text-blue-800';
    case 'HK': return 'bg-orange-100 text-orange-800';
    default: return 'bg-gray-100 text-gray-800';
  }
}

function actionabilityLabel(value: string | null | undefined): string {
  if (value === 'trade_draft') return '可生成草稿';
  if (value === 'blocked') return '已阻断';
  return '仅供分析';
}

function sourceTierLabel(value: string | null | undefined): string {
  if (value === 'broker_verified') return '券商确认';
  if (value === 'user_confirmed') return '用户确认';
  if (value === 'estimated') return '估算';
  return value || '未知来源';
}

function requiresSymbolReview(position: PositionRow): boolean {
  const lineage = position.source_lineage;
  if (!lineage || typeof lineage !== 'object') return false;
  return lineage.requires_symbol_review === true;
}

/* ------------------------------------------------------------------ */
/*  Page                                                                */
/* ------------------------------------------------------------------ */
export default async function PositionsPage({
  searchParams,
}: {
  searchParams: Promise<{ market?: string }>;
}) {
  const { supabase } = await requireUser();
  const resolvedSearchParams = await searchParams;
  const marketFilter = resolvedSearchParams.market || 'all';

  /* ---------- fetch latest snapshots per symbol ---------- */
  const { data: snapshots, error } = await supabase
    .from('position_snapshots')
    .select('id, symbol, provider_symbol, market, exchange, stock_name, total_quantity, average_cost, total_cost, snapshot_date, tenant_id, source_tier, source_actionability, source_lineage')
    .order('snapshot_date', { ascending: false });

  if (error) {
    return (
      <div className="mx-auto max-w-6xl">
        <h1 className="text-2xl font-bold text-gray-900">持仓组合</h1>
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          数据加载失败：{error.message}
        </div>
      </div>
    );
  }

  /* Deduplicate: keep latest snapshot per symbol */
  const seen = new Set<string>();
  const latestPositions: PositionRow[] = [];
  for (const row of snapshots ?? []) {
    const key = `${row.tenant_id}:${row.symbol}`;
    if (!seen.has(key)) {
      seen.add(key);
      latestPositions.push(row);
    }
  }

  /* Filter by market */
  const filtered = marketFilter === 'all'
    ? latestPositions
    : latestPositions.filter((p) => p.market === marketFilter);

  /* Active positions only (quantity > 0) */
  const activePositions = filtered.filter((p) => p.total_quantity > 0);

  /* Total value */
  const totalValue = activePositions.reduce((sum, p) => sum + (p.total_cost ?? 0), 0);

  /* Market counts for tabs */
  const marketCounts: Record<string, number> = { CN: 0, US: 0, HK: 0 };
  latestPositions
    .filter((p) => p.total_quantity > 0)
    .forEach((p) => {
      if (marketCounts[p.market] !== undefined) {
        marketCounts[p.market]++;
      }
    });

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">持仓组合</h1>
          <p className="mt-1 text-sm text-gray-500">
            查看和管理您的投资组合与持仓详情。
          </p>
        </div>
        <div className="text-right">
          <p className="text-sm text-gray-500">总持仓市值</p>
          <p className="text-2xl font-semibold text-gray-900">
            {formatCurrency(totalValue)}
          </p>
        </div>
      </div>

      {/* Market filter tabs */}
      <div className="mb-6 border-b border-gray-200">
        <nav className="-mb-px flex space-x-8" aria-label="市场筛选">
          <MarketTab href="/positions" label="全部" active={marketFilter === 'all'} />
          <MarketTab href="/positions?market=CN" label={`A股 (${marketCounts.CN})`} active={marketFilter === 'CN'} />
          <MarketTab href="/positions?market=US" label={`美股 (${marketCounts.US})`} active={marketFilter === 'US'} />
          <MarketTab href="/positions?market=HK" label={`港股 (${marketCounts.HK})`} active={marketFilter === 'HK'} />
        </nav>
      </div>

      {/* Table */}
      {activePositions.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white py-16">
          <svg className="h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-gray-900">暂无持仓数据</h3>
          <p className="mt-1 text-sm text-gray-500">
            {marketFilter === 'all' ? '您的投资组合当前没有持仓记录。' : `没有${marketLabel(marketFilter)}持仓记录。`}
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg bg-white shadow">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">股票代码</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">股票名称</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">市场</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">持仓数量</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">平均成本</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">总成本</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">来源状态</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">快照日期</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {activePositions.map((p) => (
                  <tr key={p.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-primary">
                      <Link href={`/positions/${p.symbol}`}>{p.symbol}</Link>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-900">
                      <Link href={`/positions/${p.symbol}`} className="hover:text-primary">
                        {p.stock_name || '-'}
                      </Link>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${marketBadgeClass(p.market)}`}>
                        {marketLabel(p.market)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-right text-sm text-gray-900">{p.total_quantity.toLocaleString()}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-right text-sm text-gray-900">{formatCurrency(p.average_cost, p.market)}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-right text-sm font-medium text-gray-900">{formatCurrency(p.total_cost, p.market)}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-600">
                      <div className="flex flex-col gap-1">
                        <span>{sourceTierLabel(p.source_tier)} · {actionabilityLabel(p.source_actionability)}</span>
                        {requiresSymbolReview(p) ? (
                          <span className="inline-flex w-fit items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                            需补证券代码
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">{p.snapshot_date}</td>
                  </tr>
                ))}
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

function MarketTab({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      className={`whitespace-nowrap border-b-2 px-1 pb-3 text-sm font-medium transition-colors ${
        active
          ? 'border-primary text-primary'
          : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
      }`}
    >
      {label}
    </Link>
  );
}
