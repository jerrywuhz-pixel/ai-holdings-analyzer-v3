import Link from 'next/link';
import { requireUser } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
interface PositionSnapshot {
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
}

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
  note: string | null;
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

function sourceLabel(source: string): string {
  switch (source) {
    case 'manual': return '手动录入';
    case 'broker_wechat': return '交易消息';
    case 'ocr': return '截图识别';
    case 'batch_import': return '批量导入';
    default: return source;
  }
}

/* ------------------------------------------------------------------ */
/*  Page                                                                */
/* ------------------------------------------------------------------ */
export default async function PositionDetailPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { supabase } = await requireUser();
  const { symbol } = await params;

  /* ---------- fetch position snapshot (latest) ---------- */
  const { data: snapshots } = await supabase
    .from('position_snapshots')
    .select('id, symbol, provider_symbol, market, exchange, stock_name, total_quantity, average_cost, total_cost, snapshot_date, tenant_id')
    .eq('symbol', symbol)
    .order('snapshot_date', { ascending: false })
    .limit(1);

  const position: PositionSnapshot | null = snapshots?.[0] ?? null;

  /* ---------- fetch trade events for this symbol ---------- */
  const { data: trades } = await supabase
    .from('trade_events')
    .select('id, symbol, stock_name, side, price, quantity, trade_amount, trade_date, source, market, note')
    .eq('symbol', symbol)
    .order('trade_date', { ascending: false });

  const tradeEvents: TradeEvent[] = trades ?? [];

  /* ---------- not found ---------- */
  if (!position) {
    return (
      <div className="mx-auto max-w-4xl">
        <Link href="/positions" className="mb-4 inline-flex items-center text-sm text-primary hover:text-primary-600">
          <svg className="mr-1 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          返回持仓列表
        </Link>
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white py-16">
          <svg className="h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-gray-900">未找到持仓</h3>
          <p className="mt-1 text-sm text-gray-500">股票代码 {symbol} 没有持仓记录。</p>
        </div>
      </div>
    );
  }

  const market = position.market;

  return (
    <div className="mx-auto max-w-4xl">
      {/* Back link */}
      <Link href="/positions" className="mb-4 inline-flex items-center text-sm text-primary hover:text-primary-600">
        <svg className="mr-1 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        返回持仓列表
      </Link>

      {/* Position summary card */}
      <div className="rounded-lg bg-white shadow">
        <div className="px-6 py-5">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">{position.stock_name || symbol}</h1>
            <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-800">
              {symbol}
            </span>
            <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-800">
              {marketLabel(market)}
            </span>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            交易所：{position.exchange} · 快照日期：{position.snapshot_date}
          </p>
        </div>

        <div className="border-t border-gray-200">
          <dl className="grid grid-cols-1 divide-y divide-gray-200 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            <div className="px-6 py-4">
              <dt className="text-sm font-medium text-gray-500">持仓数量</dt>
              <dd className="mt-1 text-2xl font-semibold text-gray-900">{position.total_quantity.toLocaleString()}</dd>
            </div>
            <div className="px-6 py-4">
              <dt className="text-sm font-medium text-gray-500">平均成本</dt>
              <dd className="mt-1 text-2xl font-semibold text-gray-900">{formatCurrency(position.average_cost, market)}</dd>
            </div>
            <div className="px-6 py-4">
              <dt className="text-sm font-medium text-gray-500">总成本</dt>
              <dd className="mt-1 text-2xl font-semibold text-gray-900">{formatCurrency(position.total_cost, market)}</dd>
            </div>
          </dl>
        </div>
      </div>

      {/* Trade history */}
      <div className="mt-8">
        <h2 className="text-lg font-medium text-gray-900">交易历史</h2>
        {tradeEvents.length === 0 ? (
          <div className="mt-4 rounded-lg border-2 border-dashed border-gray-300 bg-white py-10 text-center text-sm text-gray-500">
            暂无交易记录
          </div>
        ) : (
          <div className="mt-4 overflow-hidden rounded-lg bg-white shadow">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">日期</th>
                    <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">方向</th>
                    <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">价格</th>
                    <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">数量</th>
                    <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">金额</th>
                    <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">来源</th>
                    <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">备注</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {tradeEvents.map((t) => (
                    <tr key={t.id} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-900">{t.trade_date}</td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm">
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${t.side === 'BUY' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                          {t.side === 'BUY' ? '买入' : '卖出'}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-6 py-4 text-right text-sm text-gray-900">{formatCurrency(t.price, t.market)}</td>
                      <td className="whitespace-nowrap px-6 py-4 text-right text-sm text-gray-900">{t.quantity.toLocaleString()}</td>
                      <td className="whitespace-nowrap px-6 py-4 text-right text-sm text-gray-900">{t.trade_amount != null ? formatCurrency(t.trade_amount, t.market) : '-'}</td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">{sourceLabel(t.source)}</td>
                      <td className="max-w-[200px] truncate px-6 py-4 text-sm text-gray-500">{t.note || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
