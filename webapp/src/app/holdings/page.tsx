import Link from 'next/link';
import {
  ActionabilityPill,
  DataStateView,
  DegradationBanner,
  DisciplinePill,
  FreshnessPill,
  StatusPill,
} from '@/components/p0-ui';
import {
  getWorkspaceSnapshot,
  resolvePageState,
  type ActionItem,
  type EquityHolding,
  type OptionHolding,
  type RiskItem,
} from '@/lib/p0';

export const dynamic = 'force-dynamic';

type CategoryTone = 'core' | 'attack' | 'elastic' | 'defense';

type DisciplineCategory = {
  label: string;
  tone: CategoryTone;
  note: string;
};

type DisciplineBucket = {
  label: string;
  target: string;
  current: string;
  tone: CategoryTone;
  detail: string;
};

function parsePercent(value: string) {
  const parsed = Number(value.replace('%', ''));
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatPercent(value: number) {
  if (!Number.isFinite(value)) return '--';
  return `${value.toFixed(value >= 10 ? 0 : 1)}%`;
}

function parseMoney(value: string | undefined) {
  if (!value || value === '--') return undefined;
  const parsed = Number(value.replace(/[^0-9.-]/g, ''));
  return Number.isFinite(parsed) ? parsed : undefined;
}

function pnlClassName(value: string) {
  if (value.trim().startsWith('+')) return 'text-[#d71920]';
  if (value.trim().startsWith('-')) return 'text-emerald-700';
  return 'text-[#4f494c]';
}

function categoryClassName(tone: CategoryTone) {
  if (tone === 'core') return 'border-[#f0c8c5] bg-[#fff4f1] text-[#a8181e]';
  if (tone === 'attack') return 'border-amber-200 bg-amber-50 text-amber-800';
  if (tone === 'elastic') return 'border-fuchsia-200 bg-fuchsia-50 text-fuchsia-800';
  return 'border-sky-200 bg-sky-50 text-sky-800';
}

function classifyHolding(holding: EquityHolding): DisciplineCategory {
  const concentration = parsePercent(holding.concentration);
  if (concentration >= 15) {
    return {
      label: '核心主线',
      tone: 'core',
      note: '仓位较高，核心问题是主线是否仍被数据验证。',
    };
  }
  if (concentration >= 8) {
    return {
      label: '进攻加速',
      tone: 'attack',
      note: '适合跟踪突破、放量、财报和主线加速确认。',
    };
  }
  if (holding.market === 'US' || concentration < 5) {
    return {
      label: '高弹性',
      tone: 'elastic',
      note: '波动贡献高于仓位贡献，需要清晰止损和复核日。',
    };
  }
  return {
    label: '进攻加速',
    tone: 'attack',
    note: '中等仓位，继续观察趋势强度和纪律命中。',
  };
}

function buildDisciplineBuckets(
  equity: EquityHolding[],
  options: OptionHolding[],
  totalAssetValue?: string,
  cashValue?: string
): DisciplineBucket[] {
  const grouped = equity.reduce(
    (acc, holding) => {
      const category = classifyHolding(holding);
      acc[category.tone] += parsePercent(holding.concentration);
      return acc;
    },
    { core: 0, attack: 0, elastic: 0, defense: 0 } satisfies Record<CategoryTone, number>
  );

  if (options.length) {
    grouped.elastic = Math.max(grouped.elastic, 10);
  }

  const cash = parseMoney(cashValue);
  const total = parseMoney(totalAssetValue);
  grouped.defense = cash !== undefined && total && total > 0 ? (cash / total) * 100 : 0;

  return [
    {
      label: '核心主线',
      target: '40%-50%',
      current: formatPercent(grouped.core),
      tone: 'core',
      detail: '高仓位主线要看趋势、财报和硬科技验证，不因小波动轻易卖飞。',
    },
    {
      label: '进攻加速',
      target: '20%-30%',
      current: formatPercent(grouped.attack),
      tone: 'attack',
      detail: '突破、放量、财报确认后放大收益；超配时优先做复核。',
    },
    {
      label: '高弹性',
      target: '10%-15%',
      current: options.length ? `${formatPercent(grouped.elastic)}+期权` : formatPercent(grouped.elastic),
      tone: 'elastic',
      detail: '期权、高波动票和弹性小票必须有硬止损、到期日和最大亏损。',
    },
    {
      label: '现金与防守',
      target: '15%-25%',
      current: grouped.defense ? formatPercent(grouped.defense) : cashValue || '--',
      tone: 'defense',
      detail: '保留分歧日再进攻能力，避免因流动性不足被迫减仓。',
    },
  ];
}

function actionTone(item: ActionItem) {
  if (item.severity === 'critical') return 'danger';
  if (item.severity === 'warning') return 'warning';
  return 'muted';
}

function riskTone(item: RiskItem) {
  if (item.level === 'high') return 'danger';
  if (item.level === 'medium') return 'warning';
  return 'muted';
}

export default async function HoldingsPage({
  searchParams,
}: {
  searchParams?: Promise<{ state?: string; view?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const state = resolvePageState(params.state);
  const snapshot = await getWorkspaceSnapshot({ state, viewId: params.view });
  const views = snapshot.data?.chrome.views ?? [];
  const activeView = snapshot.data?.chrome.activeViewId;
  const activeViewRecord = views.find((view) => view.id === activeView) ?? views[0];

  const dashboardMetrics = snapshot.data?.dashboard.metrics ?? [];
  const totalAssetValue = dashboardMetrics.find((metric) => metric.label === '总资产')?.value;
  const cashValue = dashboardMetrics.find((metric) => metric.label === '可用现金')?.value;
  const disciplineBuckets = snapshot.data
    ? buildDisciplineBuckets(snapshot.data.holdings.equity, snapshot.data.holdings.options, totalAssetValue, cashValue)
    : [];
  const actionAndRiskItems = snapshot.data
    ? [
        ...snapshot.data.dashboard.actions.map((item) => ({ kind: 'action' as const, item })),
        ...snapshot.data.holdings.riskRadar.map((item) => ({ kind: 'risk' as const, item })),
      ].slice(0, 5)
    : [];

  return (
    <div className="space-y-4 md:space-y-5">
      <div className="flex flex-col gap-4 border-b border-[#e5ddd9] pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-[0.22em] text-[#d71920]">持仓</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[#171417] md:text-3xl">
            股票 / ETF 与 Sell Put 统一资产视图
          </h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-[#4f494c]">
            主内容优先展示持仓、仓位纪律和需要处理的风险；行情金额按页面币种巡检展示，不等同交易账户结单。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {views.map((view) => (
            <Link
              key={view.id}
              href={`/holdings?view=${view.id}`}
              className={[
                'rounded-full border px-3 py-1.5 text-sm transition',
                view.id === activeView
                  ? 'border-[#efb5b2] bg-[#fff0ef] text-[#a8181e]'
                  : 'border-[#e5ddd9] bg-white text-[#4f494c] hover:bg-[#fff4f1]',
              ].join(' ')}
            >
              {view.name}
            </Link>
          ))}
        </div>
      </div>

      <DataStateView
        state={snapshot.state}
        errorMessage={snapshot.errorMessage}
        emptyTitle="当前资产视图没有持仓"
        emptyDetail="等待首次账户更新、手工录入或截图 / 语音修正确认后再展示。"
      />

      {snapshot.data ? (
        <>
          <section className="grid grid-cols-2 gap-2 md:grid-cols-4 md:gap-3">
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-3 md:p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[#8a817d]">资产视图</p>
              <p className="mt-2 text-lg font-semibold text-[#171417]">{activeViewRecord?.name ?? '默认持仓'}</p>
              <p className="mt-1 text-sm text-[#6f686b]">
                {activeViewRecord?.baseCurrency ?? 'USD'} · {activeViewRecord?.scope ?? '股票 / ETF / 期权'}
              </p>
            </div>
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-3 md:p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[#8a817d]">股票 / ETF</p>
              <p className="mt-2 text-lg font-semibold text-[#171417]">{snapshot.data.holdings.equity.length}</p>
              <p className="mt-1 hidden text-sm text-[#6f686b] sm:block">按代码、名称、仓位、盈亏和纪律展示。</p>
            </div>
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-3 md:p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[#8a817d]">期权持仓</p>
              <p className="mt-2 text-lg font-semibold text-[#171417]">{snapshot.data.holdings.options.length}</p>
              <p className="mt-1 hidden text-sm text-[#6f686b] sm:block">Sell Put 独立展示现金占用和到期风险。</p>
            </div>
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-3 md:p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[#8a817d]">总资产 / 现金</p>
              <p className="mt-2 text-lg font-semibold text-[#171417]">{totalAssetValue ?? '--'}</p>
              <p className="mt-1 text-sm text-[#6f686b]">可用现金 {cashValue ?? '--'}</p>
            </div>
          </section>

          <section className="grid gap-3 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-[#171417]">今日行动与风险雷达</h2>
                  <p className="mt-1 text-sm text-[#6f686b]">把待处理事项、集中度、到期和数据风险放在同一队列里处理。</p>
                </div>
                <Link
                  href="/ops"
                  className="rounded-full border border-[#f0c8c5] bg-[#fff4f1] px-3 py-1.5 text-xs font-medium text-[#a8181e] transition hover:border-[#efb5b2] hover:bg-[#ffe9e7]"
                >
                  消息与处理状态
                </Link>
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {actionAndRiskItems.map(({ kind, item }) => (
                  <Link
                    key={`${kind}-${item.id}`}
                    href={kind === 'action' ? item.href : '/holdings'}
                    className="rounded-lg border border-[#e5ddd9] bg-[#fffaf8] p-4 transition hover:border-[#d8ccc7] hover:bg-[#f8f3ef]"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusPill tone={kind === 'action' ? actionTone(item) : riskTone(item)}>
                        {kind === 'action' ? item.badge || '行动' : item.badge}
                      </StatusPill>
                      <span className="text-xs text-[#8a817d]">{kind === 'action' ? '今日行动' : '风险雷达'}</span>
                    </div>
                    <p className="mt-3 font-medium text-[#171417]">{item.title}</p>
                    <p className="mt-2 text-sm leading-6 text-[#6f686b]">{item.detail}</p>
                  </Link>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <h2 className="text-base font-semibold text-[#171417]">交易纪律分层</h2>
              <p className="mt-1 text-sm text-[#6f686b]">按仓位比例对照纪律模板，提示当前组合偏向。</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {disciplineBuckets.map((bucket) => (
                  <div key={bucket.label} className="rounded-lg border border-[#e5ddd9] bg-[#fffaf8] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className={['rounded-full border px-2.5 py-1 text-xs font-medium', categoryClassName(bucket.tone)].join(' ')}>
                        {bucket.label}
                      </span>
                      <span className="text-xs text-[#8a817d]">目标 {bucket.target}</span>
                    </div>
                    <p className="mt-3 text-xl font-semibold text-[#171417]">{bucket.current}</p>
                    <p className="mt-2 text-xs leading-5 text-[#6f686b]">{bucket.detail}</p>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="min-w-0">
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-[#171417]">股票 / ETF 持仓</h2>
                <p className="mt-1 text-sm text-[#6f686b]">红色为盈利，绿色为亏损；标的分类用于提示仓位纪律，不替代交易决策。</p>
              </div>
              <StatusPill tone="muted">{snapshot.data.holdings.equity.length} 条</StatusPill>
            </div>

            <div className="space-y-3 md:hidden">
              {snapshot.data.holdings.equity.map((holding) => {
                const category = classifyHolding(holding);
                return (
                  <div key={holding.symbol} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <Link href={`/holdings/${holding.symbol}`} className="font-medium text-[#171417] hover:text-[#d71920]">
                          {holding.symbol} · {holding.name && holding.name !== holding.symbol ? holding.name : '名称待补齐'}
                        </Link>
                        <p className="mt-1 text-xs text-[#8a817d]">{holding.market}</p>
                      </div>
                      <span className={['rounded-full border px-2.5 py-1 text-xs font-medium', categoryClassName(category.tone)].join(' ')}>
                        {category.label}
                      </span>
                    </div>
                    <div className="mt-4 grid gap-3 text-sm text-[#4f494c] sm:grid-cols-2">
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-[#8a817d]">数量</p>
                        <p className="mt-1">{holding.quantity}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-[#8a817d]">集中度</p>
                        <p className="mt-1">{holding.concentration}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-[#8a817d]">市值</p>
                        <p className="mt-1">{holding.marketValue}</p>
                        {holding.marketValueDetail ? (
                          <p className="mt-1 text-xs text-[#8a817d]">{holding.marketValueDetail}</p>
                        ) : null}
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-[#8a817d]">盈亏</p>
                        <p className={['mt-1 font-semibold', pnlClassName(holding.pnl)].join(' ')}>{holding.pnl}</p>
                      </div>
                    </div>
                    <p className="mt-3 text-xs leading-5 text-[#8a817d]">{category.note}</p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <DisciplinePill state={holding.discipline} />
                      <StatusPill tone="muted">{holding.source}</StatusPill>
                      <FreshnessPill source={{ freshnessLabel: holding.freshness, status: holding.source.includes('腾讯') ? 'stale' : 'fresh' }} />
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="hidden overflow-x-auto rounded-lg border border-[#e5ddd9] md:block">
              <table className="min-w-full divide-y divide-[#e5ddd9] text-sm">
                <thead className="bg-white text-left text-[#6f686b]">
                  <tr>
                    <th className="px-4 py-3 font-medium">标的</th>
                    <th className="px-4 py-3 font-medium">分类</th>
                    <th className="px-4 py-3 font-medium">数量</th>
                    <th className="px-4 py-3 font-medium">市值</th>
                    <th className="px-4 py-3 font-medium">盈亏</th>
                    <th className="px-4 py-3 font-medium">集中度</th>
                    <th className="px-4 py-3 font-medium">纪律</th>
                    <th className="px-4 py-3 font-medium">来源</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#e5ddd9]">
                  {snapshot.data.holdings.equity.map((holding) => {
                    const category = classifyHolding(holding);
                    return (
                      <tr key={holding.symbol} className="bg-[#fffaf8]">
                        <td className="px-4 py-3">
                          <Link href={`/holdings/${holding.symbol}`} className="font-medium text-[#171417] hover:text-[#d71920]">
                            {holding.symbol} · {holding.name && holding.name !== holding.symbol ? holding.name : '名称待补齐'}
                          </Link>
                          <p className="text-xs text-[#8a817d]">{holding.market}</p>
                        </td>
                        <td className="px-4 py-3">
                          <span className={['rounded-full border px-2.5 py-1 text-xs font-medium', categoryClassName(category.tone)].join(' ')}>
                            {category.label}
                          </span>
                          <p className="mt-2 max-w-[220px] text-xs leading-5 text-[#8a817d]">{category.note}</p>
                        </td>
                        <td className="px-4 py-3 text-[#4f494c]">{holding.quantity}</td>
                        <td className="px-4 py-3 text-[#4f494c]">
                          <p>{holding.marketValue}</p>
                          {holding.marketValueDetail ? (
                            <p className="mt-1 text-xs text-[#8a817d]">{holding.marketValueDetail}</p>
                          ) : null}
                          {holding.valuationBasis ? (
                            <p className="mt-1 text-xs text-[#8a817d]">{holding.valuationBasis}</p>
                          ) : null}
                        </td>
                        <td className={['px-4 py-3 font-semibold', pnlClassName(holding.pnl)].join(' ')}>
                          {holding.pnl}
                        </td>
                        <td className="px-4 py-3 text-[#4f494c]">{holding.concentration}</td>
                        <td className="px-4 py-3">
                          <DisciplinePill state={holding.discipline} />
                        </td>
                        <td className="px-4 py-3">
                          <div className="space-y-2">
                            <StatusPill tone="muted">{holding.source}</StatusPill>
                            <FreshnessPill source={{ freshnessLabel: holding.freshness, status: holding.source.includes('腾讯') ? 'stale' : 'fresh' }} />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="border-t border-[#e5ddd9] pt-5">
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-[#171417]">Sell Put 持仓</h2>
                <p className="mt-1 text-sm text-[#6f686b]">期权归入高弹性预算，独立展示现金、保证金、到期和行动状态。</p>
              </div>
              <StatusPill tone="muted">{snapshot.data.holdings.options.length} 份</StatusPill>
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {snapshot.data.holdings.options.map((option) => (
                <div key={option.id} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-medium text-[#171417]">{option.contract}</p>
                      <p className="mt-1 text-sm text-[#6f686b]">{option.underlying} · 权利金 {option.premium}</p>
                    </div>
                    <ActionabilityPill state={option.actionability} />
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-[#4f494c]">
                    <div>
                      <p className="text-xs uppercase tracking-[0.22em] text-[#8a817d]">到期天数 / delta</p>
                      <p className="mt-1">{option.dte} / {option.delta}</p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.22em] text-[#8a817d]">IV</p>
                      <p className="mt-1">{option.iv}</p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.22em] text-[#8a817d]">期权市值</p>
                      <p className={['mt-1 font-semibold', pnlClassName(option.optionMarketValue)].join(' ')}>
                        {option.optionMarketValue}
                      </p>
                      {option.optionMarketValueDetail ? (
                        <p className="mt-1 text-xs text-[#8a817d]">{option.optionMarketValueDetail}</p>
                      ) : null}
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.22em] text-[#8a817d]">现金 / 保证金</p>
                      <p className="mt-1">{option.cashRequired} / {option.marginRequired}</p>
                    </div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <span className={['rounded-full border px-2.5 py-1 text-xs font-medium', categoryClassName('elastic')].join(' ')}>
                      高弹性
                    </span>
                    <StatusPill tone={option.risk === 'high' ? 'danger' : 'warning'}>{option.assignment}</StatusPill>
                    <FreshnessPill source={{ freshnessLabel: option.freshness, status: option.actionability === 'ready' ? 'fresh' : 'degraded' }} />
                  </div>
                  {option.valuationBasis ? (
                    <p className="mt-3 text-xs text-[#8a817d]">{option.valuationBasis}</p>
                  ) : null}
                </div>
              ))}
            </div>
          </section>

          <section className="border-t border-[#e5ddd9] pt-5">
            <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
              <div>
                <h2 className="text-base font-semibold text-[#171417]">页面数据状态</h2>
                <p className="mt-2 text-sm leading-6 text-[#6f686b]">
                  {snapshot.liveData?.detail}
                  {snapshot.liveData?.valuationDetail ? ` ${snapshot.liveData.valuationDetail}` : ''}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <StatusPill tone={snapshot.liveData?.mode === 'live' ? 'positive' : 'warning'}>
                    {snapshot.liveData?.label ?? '等待数据'}
                  </StatusPill>
                  {snapshot.liveData?.baseCurrency ? (
                    <StatusPill tone="muted">展示币种 {snapshot.liveData.baseCurrency}</StatusPill>
                  ) : null}
                  {snapshot.liveData?.updatedAt ? (
                    <StatusPill tone="muted">数据时间 {snapshot.liveData.updatedAt}</StatusPill>
                  ) : null}
                </div>
                <div className="mt-4">
                  <DegradationBanner sources={snapshot.data.chrome.sources} compact />
                </div>
              </div>
              <div>
                <h2 className="text-base font-semibold text-[#171417]">来源明细</h2>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  {snapshot.data.holdings.sources.map((source) => (
                    <div key={source.id} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="font-medium text-[#171417]">{source.label}</p>
                          <p className="mt-1 text-sm text-[#6f686b]">{source.lineage}</p>
                        </div>
                        <StatusPill tone="muted">{source.type}</StatusPill>
                      </div>
                      <div className="mt-3 grid gap-2 text-sm text-[#4f494c] md:grid-cols-3">
                        <p>{source.priority}</p>
                        <p>可信度 {source.confidence}</p>
                        <p>更新 {source.freshness}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
