import { notFound } from 'next/navigation';
import {
  DataStateView,
  DisciplinePill,
  InlineLink,
  MetricCard,
  PageHeader,
  Panel,
  StatusPill,
} from '@/components/p0-ui';
import { findEquityBySymbol, getWorkspaceSnapshot, resolvePageState } from '@/lib/p0';

export const dynamic = 'force-dynamic';

export default async function HoldingDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ symbol: string }>;
  searchParams?: Promise<{ state?: string }>;
}) {
  const { symbol } = await params;
  const query = (await searchParams) ?? {};
  const state = resolvePageState(query.state);
  const snapshot = await getWorkspaceSnapshot({ state });

  if (snapshot.state === 'error' || snapshot.state === 'loading' || snapshot.state === 'empty') {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="标的详情"
          title={`${symbol} 下钻`}
          description="股票 / ETF 详情页保留策略、纪律、来源与确认入口，不直接写交易事实。"
          actions={<InlineLink href="/holdings">返回持仓</InlineLink>}
        />
        <DataStateView state={snapshot.state} errorMessage={snapshot.errorMessage} />
      </div>
    );
  }

  const data = snapshot.data;
  if (!data) notFound();

  const holding = findEquityBySymbol(data, symbol);
  if (!holding) notFound();

  const metrics = [
    { label: '持仓数量', value: holding.quantity, hint: '来自最近一次持仓同步' },
    { label: '持仓市值', value: holding.marketValue, hint: '按当前资产视图折算' },
    { label: '浮动盈亏', value: holding.pnl, hint: '收益路径待真实行情接入' },
    { label: '集中度', value: holding.concentration, hint: '纪律检查的一部分' },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="标的详情"
        title={`${holding.name} / ${holding.symbol}`}
        description="单标的详情回答三件事：赚亏从哪里来、纪律冲突在哪里、下一步应观察还是生成草稿。"
        actions={
          <>
            <InlineLink href="/holdings">返回持仓</InlineLink>
            <InlineLink href="/ops">查看微信处理状态</InlineLink>
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric) => (
          <MetricCard key={metric.label} metric={metric} />
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <Panel title="纪律与策略" description="止盈 / 止损 / 财报前限制等动作只生成草稿或规则请求，不自动下单。">
          <div className="space-y-4">
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium text-[#171417]">纪律状态</p>
                <DisciplinePill state={holding.discipline} />
              </div>
              <p className="mt-2 text-sm text-[#6f686b]">
                当前页面保留规则命中、策略建议与确认入口，不直接提交交易事实。
              </p>
            </div>
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4 text-sm text-[#4f494c]">
              <p className="font-medium text-[#171417]">后续分析入口</p>
              <ul className="mt-3 space-y-2">
                <li>价格与收益路径图：接入历史行情后展示。</li>
                <li>交易时间线：同步交易记录后展示。</li>
                <li>页面内 AI 建议：只展示结构，不提供独立全局聊天入口。</li>
              </ul>
            </div>
          </div>
        </Panel>

        <Panel title="来源 / 更新 / 微信处理" description="影响持仓事实的数据修正以微信渠道和后台处理记录为准，WebApp 只展示当前结果和来源。">
          <div className="space-y-3">
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <p className="text-xs uppercase tracking-[0.22em] text-[#8a817d]">数据来源</p>
              <p className="mt-2 font-medium text-[#171417]">{holding.source}</p>
            </div>
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <p className="text-xs uppercase tracking-[0.22em] text-[#8a817d]">更新时间</p>
              <p className="mt-2 font-medium text-[#171417]">{holding.freshness}</p>
            </div>
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <p className="text-xs uppercase tracking-[0.22em] text-[#8a817d]">建议下一步</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <StatusPill tone="muted">发起深研</StatusPill>
                <StatusPill tone="warning">生成止盈 / 止损草稿</StatusPill>
                <StatusPill tone="danger">录入交易需确认</StatusPill>
              </div>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
