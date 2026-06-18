import {
  DataStateView,
  InlineLink,
  MetricCard,
  PageHeader,
  Panel,
  StatusPill,
} from '@/components/p0-ui';
import { getWorkspaceSnapshot, resolveDemoState } from '@/lib/p0';

export const dynamic = 'force-dynamic';

const typeLabel = {
  trade_input: '交易录入',
  ocr_fix: '截图识别修正',
  asr_fix: '语音识别修正',
  rule_change: '规则变更',
  sell_put_trade_draft: 'Sell Put 草稿',
  broker_conflict: '历史来源差异',
  source_conflict: '来源差异',
  portfolio_view_change: '资产视图变更',
} as const;

const riskLabel = {
  high: '高风险',
  medium: '中风险',
  low: '低风险',
} as const;

const statusLabel = {
  pending: '待确认',
  needs_input: '需补充',
  blocked: '已阻断',
} as const;

export default async function ConfirmationsPage({
  searchParams,
}: {
  searchParams?: Promise<{ state?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const state = resolveDemoState(params.state);
  const snapshot = await getWorkspaceSnapshot({ state });

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="确认中心"
        title="微信和页面里的待确认事项在这里统一查看"
        description="交易录入、截图 / 语音修正、规则变更、Sell Put 草稿和来源差异都会先进入确认中心。你可以通过微信口令完成二次确认，也可以在这里核对同一事项的状态和证据。确认只会记录结果或生成草稿，不会自动下单。"
        actions={<InlineLink href="/data">查看数据来源与证据</InlineLink>}
      />

      <DataStateView
        state={snapshot.state}
        errorMessage={snapshot.errorMessage}
        emptyTitle="当前没有待处理确认"
        emptyDetail="交易录入、截图 / 语音修正、规则变更或来源差异产生后会在这里聚合。"
      />

      {snapshot.data ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {snapshot.data.confirmations.summary.map((metric) => (
              <MetricCard key={metric.label} metric={metric} />
            ))}
          </div>

          <Panel
            title="待处理队列"
            description="按对象类型与风险等级组织，证据链与下一步动作并排可读。"
            aside={<StatusPill tone="danger">{snapshot.data.confirmations.items.length} 项待处理</StatusPill>}
          >
            <div className="space-y-3">
              {snapshot.data.confirmations.items.map((item) => (
                <div key={item.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-white">{item.title}</p>
                        <StatusPill tone="muted">{typeLabel[item.type]}</StatusPill>
                        <StatusPill tone={item.risk === 'high' ? 'danger' : item.risk === 'medium' ? 'warning' : 'muted'}>
                          {riskLabel[item.risk]}
                        </StatusPill>
                      </div>
                      <p className="text-sm text-slate-400">{item.summary}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusPill tone={item.status === 'blocked' ? 'danger' : item.status === 'needs_input' ? 'warning' : 'positive'}>
                        {statusLabel[item.status]}
                      </StatusPill>
                      <StatusPill tone="muted">更新 {item.freshness}</StatusPill>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_0.85fr]">
                    <div>
                      <p className="text-xs uppercase tracking-[0.22em] text-slate-500">证据与记录</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {item.evidence.map((evidence) => (
                          <StatusPill key={evidence} tone="muted">
                            {evidence}
                          </StatusPill>
                        ))}
                      </div>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.22em] text-slate-500">下一步</p>
                      <p className="mt-2 text-sm text-slate-300">{item.nextStep}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </>
      ) : null}
    </div>
  );
}
