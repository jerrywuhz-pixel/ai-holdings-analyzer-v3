import { requireUser } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
interface TradeEvent {
  id: string;
  symbol: string;
  stock_name: string | null;
  side: 'BUY' | 'SELL';
  price: number;
  quantity: number;
  trade_amount: number | null;
  trade_date: string;
  source: string;
  market: string;
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

function sourceLabel(source: string): string {
  switch (source) {
    case 'manual': return '手动录入';
    case 'broker_wechat': return '券商微信';
    case 'ocr': return '截图识别';
    case 'batch_import': return '批量导入';
    default: return source;
  }
}

/* ------------------------------------------------------------------ */
/*  Page                                                                */
/* ------------------------------------------------------------------ */
export default async function TransactionsPage({
  searchParams,
}: {
  searchParams: Promise<{ side?: string; market?: string; from?: string; to?: string }>;
}) {
  const { supabase } = await requireUser();
  const resolvedSearchParams = await searchParams;
  const sideFilter = resolvedSearchParams.side || 'all';
  const marketFilter = resolvedSearchParams.market || 'all';
  const fromDate = resolvedSearchParams.from || '';
  const toDate = resolvedSearchParams.to || '';

  /* ---------- build query ---------- */
  let query = supabase
    .from('trade_events')
    .select('id, symbol, stock_name, side, price, quantity, trade_amount, trade_date, source, market')
    .order('trade_date', { ascending: false });

  if (sideFilter !== 'all') {
    query = query.eq('side', sideFilter);
  }
  if (marketFilter !== 'all') {
    query = query.eq('market', marketFilter);
  }
  if (fromDate) {
    query = query.gte('trade_date', fromDate);
  }
  if (toDate) {
    query = query.lte('trade_date', toDate);
  }

  const { data, error } = await query.limit(200);

  if (error) {
    return (
      <div className="mx-auto max-w-6xl">
        <h1 className="text-2xl font-bold text-gray-900">交易记录</h1>
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          数据加载失败：{error.message}
        </div>
      </div>
    );
  }

  const trades: TradeEvent[] = data ?? [];

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">交易记录</h1>
        <p className="mt-1 text-sm text-gray-500">
          查看所有历史交易明细。
        </p>
      </div>

      {/* Filters */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        {/* Side filter */}
        <div className="flex rounded-lg border border-gray-200 bg-white">
          <FilterPill href={buildHref({ side: 'all' })} label="全部" active={sideFilter === 'all'} />
          <FilterPill href={buildHref({ side: 'BUY' })} label="买入" active={sideFilter === 'BUY'} />
          <FilterPill href={buildHref({ side: 'SELL' })} label="卖出" active={sideFilter === 'SELL'} />
        </div>

        {/* Market filter */}
        <div className="flex rounded-lg border border-gray-200 bg-white">
          <FilterPill href={buildHref({ market: 'all' })} label="全部市场" active={marketFilter === 'all'} />
          <FilterPill href={buildHref({ market: 'CN' })} label="A股" active={marketFilter === 'CN'} />
          <FilterPill href={buildHref({ market: 'US' })} label="美股" active={marketFilter === 'US'} />
          <FilterPill href={buildHref({ market: 'HK' })} label="港股" active={marketFilter === 'HK'} />
        </div>

        {/* Date range */}
        <form className="flex items-center gap-2 text-sm" action="/transactions" method="GET">
          {marketFilter !== 'all' && <input type="hidden" name="market" value={marketFilter} />}
          {sideFilter !== 'all' && <input type="hidden" name="side" value={sideFilter} />}
          <input
            type="date"
            name="from"
            defaultValue={fromDate}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <span className="text-gray-400">至</span>
          <input
            type="date"
            name="to"
            defaultValue={toDate}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <button
            type="submit"
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-600"
          >
            筛选
          </button>
        </form>
      </div>

      {/* Table */}
      {trades.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white py-16">
          <svg className="h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-gray-900">暂无交易记录</h3>
          <p className="mt-1 text-sm text-gray-500">当前筛选条件下没有交易数据。</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg bg-white shadow">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">日期</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">股票代码</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">名称</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">方向</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">价格</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">数量</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">金额</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">来源</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {trades.map((t) => (
                  <tr key={t.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-900">{t.trade_date}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-primary">
                      <a href={`/positions/${t.symbol}`} className="hover:text-primary-600">{t.symbol}</a>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-900">{t.stock_name || '-'}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${t.side === 'BUY' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                        {t.side === 'BUY' ? '买入' : '卖出'}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-right text-sm text-gray-900">{formatCurrency(t.price, t.market)}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-right text-sm text-gray-900">{t.quantity.toLocaleString()}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-right text-sm text-gray-900">{t.trade_amount != null ? formatCurrency(t.trade_amount, t.market) : '-'}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">{sourceLabel(t.source)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {trades.length >= 200 && (
        <p className="mt-3 text-center text-xs text-gray-400">显示最近 200 条记录，请使用筛选条件缩小范围。</p>
      )}
    </div>
  );

  /* ---------- helper: build filter href ---------- */
  function buildHref(overrides: { side?: string; market?: string }): string {
    const s = overrides.side ?? sideFilter;
    const m = overrides.market ?? marketFilter;
    const params = new URLSearchParams();
    if (s !== 'all') params.set('side', s);
    if (m !== 'all') params.set('market', m);
    if (fromDate) params.set('from', fromDate);
    if (toDate) params.set('to', toDate);
    const qs = params.toString();
    return qs ? `/transactions?${qs}` : '/transactions';
  }
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                      */
/* ------------------------------------------------------------------ */

function FilterPill({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <a
      href={href}
      className={`px-3 py-1.5 text-sm font-medium transition-colors ${
        active
          ? 'bg-primary text-white'
          : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
      }`}
    >
      {label}
    </a>
  );
}
