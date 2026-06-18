'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';

interface ManualPositionApiResult {
  message?: string;
  error?: string;
  discipline?: {
    result?: string;
    hits?: Array<{ name: string; message: string; actionOnViolation: string }>;
    message?: string;
  };
}

export default function ManualPositionForm() {
  const router = useRouter();
  const [symbol, setSymbol] = useState('');
  const [name, setName] = useState('');
  const [market, setMarket] = useState('US');
  const [instrumentType, setInstrumentType] = useState('stock');
  const [quantity, setQuantity] = useState('');
  const [averageCost, setAverageCost] = useState('');
  const [marketPrice, setMarketPrice] = useState('');
  const [currency, setCurrency] = useState('USD');
  const [note, setNote] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  function handleMarketChange(nextMarket: string) {
    setMarket(nextMarket);
    if (nextMarket === 'HK') setCurrency('HKD');
    else if (nextMarket === 'CN') setCurrency('CNY');
    else setCurrency('USD');
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setMessage('');
    setLoading(true);

    const response = await fetch('/api/positions/manual', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol,
        name,
        market,
        instrumentType,
        quantity: Number(quantity),
        averageCost: averageCost ? Number(averageCost) : null,
        marketPrice: marketPrice ? Number(marketPrice) : null,
        currency,
        note,
      }),
    });
    const result = (await response.json().catch(() => ({}))) as ManualPositionApiResult;
    setLoading(false);

    if (!response.ok) {
      setError(result.error || '持仓录入失败');
      return;
    }

    const disciplineHits = result.discipline?.hits ?? [];
    const disciplineMessage = disciplineHits.length
      ? ` 纪律提醒：${disciplineHits.map((hit) => `${hit.name}：${hit.message}`).join('；')}`
      : '';
    setMessage(`${result.message || '持仓已记录'}${disciplineMessage}`);
    setSymbol('');
    setName('');
    setQuantity('');
    setAverageCost('');
    setMarketPrice('');
    setNote('');
    router.refresh();
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2">
        <label className="block">
          <span className="text-xs font-medium text-slate-400">标的代码</span>
          <input
            value={symbol}
            onChange={(event) => setSymbol(event.target.value.toUpperCase())}
            required
            placeholder="例如 AAPL / 0700.HK"
            className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-slate-400">股票名称</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如 Apple / 腾讯控股"
            className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
          />
        </label>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <label className="block">
          <span className="text-xs font-medium text-slate-400">市场</span>
          <select
            value={market}
            onChange={(event) => handleMarketChange(event.target.value)}
            className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
          >
            <option value="US">美股</option>
            <option value="HK">港股</option>
            <option value="CN">A 股</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-medium text-slate-400">品种</span>
          <select
            value={instrumentType}
            onChange={(event) => setInstrumentType(event.target.value)}
            className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
          >
            <option value="stock">股票</option>
            <option value="etf">ETF</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-medium text-slate-400">数量</span>
          <input
            type="number"
            min="0"
            step="0.0001"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            required
            className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-slate-400">币种</span>
          <input
            value={currency}
            onChange={(event) => setCurrency(event.target.value.toUpperCase())}
            className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
          />
        </label>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <label className="block">
          <span className="text-xs font-medium text-slate-400">成本价</span>
          <input
            type="number"
            min="0"
            step="0.0001"
            value={averageCost}
            onChange={(event) => setAverageCost(event.target.value)}
            placeholder="可选"
            className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-slate-400">当前价</span>
          <input
            type="number"
            min="0"
            step="0.0001"
            value={marketPrice}
            onChange={(event) => setMarketPrice(event.target.value)}
            placeholder="不填则按成本价估算"
            className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
          />
        </label>
      </div>

      <label className="block">
        <span className="text-xs font-medium text-slate-400">备注</span>
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={3}
          placeholder="例如：从交易 App 或结单人工核对录入"
          className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-400/50"
        />
      </label>

      {message ? <p className="rounded-xl border border-emerald-400/20 bg-emerald-500/10 p-3 text-sm text-emerald-100">{message}</p> : null}
      {error ? <p className="rounded-xl border border-red-400/20 bg-red-500/10 p-3 text-sm text-red-100">{error}</p> : null}

      <button
        type="submit"
        disabled={loading}
        className="rounded-xl bg-red-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {loading ? '记录中...' : '记录持仓'}
      </button>
    </form>
  );
}
