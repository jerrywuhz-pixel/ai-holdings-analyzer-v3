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
          <span className="text-xs font-medium text-[#6f686b]">标的代码</span>
          <input
            value={symbol}
            onChange={(event) => setSymbol(event.target.value.toUpperCase())}
            required
            placeholder="例如 600519 / HK00700"
            className="mt-1 w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition focus:border-[#d71920]"
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-[#6f686b]">股票名称</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如 Apple / 腾讯控股"
            className="mt-1 w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition focus:border-[#d71920]"
          />
        </label>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <label className="block">
          <span className="text-xs font-medium text-[#6f686b]">市场</span>
          <select
            value={market}
            onChange={(event) => handleMarketChange(event.target.value)}
            className="mt-1 w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition focus:border-[#d71920]"
          >
            <option value="US">美股</option>
            <option value="HK">港股</option>
            <option value="CN">A 股</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-medium text-[#6f686b]">品种</span>
          <select
            value={instrumentType}
            onChange={(event) => setInstrumentType(event.target.value)}
            className="mt-1 w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition focus:border-[#d71920]"
          >
            <option value="stock">股票</option>
            <option value="etf">ETF</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-medium text-[#6f686b]">数量</span>
          <input
            type="number"
            min="0"
            step="0.0001"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            required
            className="mt-1 w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition focus:border-[#d71920]"
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-[#6f686b]">币种</span>
          <input
            value={currency}
            onChange={(event) => setCurrency(event.target.value.toUpperCase())}
            className="mt-1 w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition focus:border-[#d71920]"
          />
        </label>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <label className="block">
          <span className="text-xs font-medium text-[#6f686b]">成本价</span>
          <input
            type="number"
            min="0"
            step="0.0001"
            value={averageCost}
            onChange={(event) => setAverageCost(event.target.value)}
            placeholder="可选"
            className="mt-1 w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition focus:border-[#d71920]"
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-[#6f686b]">当前价</span>
          <input
            type="number"
            min="0"
            step="0.0001"
            value={marketPrice}
            onChange={(event) => setMarketPrice(event.target.value)}
            placeholder="不填则按成本价估算"
            className="mt-1 w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition focus:border-[#d71920]"
          />
        </label>
      </div>

      <label className="block">
        <span className="text-xs font-medium text-[#6f686b]">备注</span>
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={3}
          placeholder="例如：从交易 App 或结单人工核对录入"
          className="mt-1 w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition focus:border-[#d71920]"
        />
      </label>

      {message ? <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{message}</p> : null}
      {error ? <p className="rounded-lg border border-[#f0c8c5] bg-[#fff0ef] p-3 text-sm text-[#d71920]">{error}</p> : null}

      <button
        type="submit"
        disabled={loading}
        className="rounded-lg bg-[#d71920] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#bd151b] disabled:cursor-not-allowed disabled:opacity-60"
      >
        {loading ? '记录中...' : '记录持仓'}
      </button>
    </form>
  );
}
