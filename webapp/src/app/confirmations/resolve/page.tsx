import {
  InlineLink,
  PageHeader,
  Panel,
  StatusPill,
} from '@/components/p0-ui';
import { findConfirmationById, getWorkspaceSnapshot } from '@/lib/p0';

export const dynamic = 'force-dynamic';

const riskTone = {
  high: 'danger',
  medium: 'warning',
  low: 'muted',
} as const;

const riskLabel = {
  high: '高风险',
  medium: '中风险',
  low: '低风险',
} as const;

function displayValue(value?: string) {
  return value && value.trim() ? value : '未提供';
}

function maskToken(value?: string) {
  if (!value) return '未提供';
  if (value.length <= 6) return value;
  return `${value.slice(0, 3)}...${value.slice(-3)}`;
}

export default async function ConfirmationResolvePage({
  searchParams,
}: {
  searchParams?: Promise<{
    tenant_id?: string;
    session_id?: string;
    session_token?: string;
    pending_action_id?: string;
    channel?: string;
  }>;
}) {
  const params = (await searchParams) ?? {};
  const snapshot = await getWorkspaceSnapshot();
  const item = snapshot.data ? findConfirmationById(snapshot.data, params.pending_action_id) : undefined;
  const hasRequiredParams = Boolean(params.session_id && params.session_token);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="确认请求"
        title="确认链接已打开"
        description="这里用于核对微信消息里的待确认事项。确认只表示记录、修正或生成草稿，不会自动下单。"
        actions={<InlineLink href="/confirmations">返回确认中心</InlineLink>}
      />

      <Panel
        title={hasRequiredParams ? '确认请求已识别' : '确认链接信息不完整'}
        description={
          hasRequiredParams
            ? '请核对下方内容，再回到微信使用口令完成确认，或在确认中心查看同一事项。'
            : '这个链接缺少确认编号或安全口令。请从最新的微信确认消息重新打开。'
        }
        aside={<StatusPill tone={hasRequiredParams ? 'positive' : 'warning'}>{hasRequiredParams ? '可复核' : '需重新打开'}</StatusPill>}
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-500">确认口令</p>
            <p className="mt-2 font-mono text-lg font-semibold text-white">{maskToken(params.session_token)}</p>
          </div>
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-500">来源渠道</p>
            <p className="mt-2 text-sm font-medium text-white">{displayValue(params.channel === 'wechat' ? '微信' : params.channel)}</p>
          </div>
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-500">确认对象</p>
            <p className="mt-2 text-sm font-medium text-white">{displayValue(item?.title ?? params.pending_action_id)}</p>
          </div>
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-500">状态</p>
            <p className="mt-2 text-sm font-medium text-white">{hasRequiredParams ? '等待你确认' : '无法识别'}</p>
          </div>
        </div>
      </Panel>

      <Panel
        title={item ? item.title : '待确认事项'}
        description={item ? item.summary : '当前本地快照没有匹配到具体事项。请以微信消息中的确认内容为准。'}
        aside={item ? <StatusPill tone={riskTone[item.risk]}>{riskLabel[item.risk]}</StatusPill> : <StatusPill tone="muted">等待匹配</StatusPill>}
      >
        {item ? (
          <div className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">证据与记录</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {item.evidence.map((evidence) => (
                  <StatusPill key={evidence} tone="muted">
                    {evidence}
                  </StatusPill>
                ))}
              </div>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">下一步</p>
              <p className="mt-3 text-sm leading-6 text-slate-300">{item.nextStep}</p>
            </div>
          </div>
        ) : (
          <p className="text-sm leading-6 text-slate-300">
            如果确认内容涉及交易记录、截图识别、语音识别、规则变更或 Sell Put 草稿，请不要只凭截图操作，先回到微信消息核对完整内容。
          </p>
        )}
      </Panel>

      <Panel
        title="完成确认"
        description="当前优先保证微信口令和确认中心的状态一致。网页端先提供安全核对页，后续再接入直接提交能力。"
      >
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-xl border border-red-400/20 bg-red-500/10 p-4">
            <p className="text-sm font-medium text-red-100">微信口令</p>
            <p className="mt-2 text-sm leading-6 text-red-50/85">
              回到微信回复：
              <span className="mx-1 rounded-lg bg-black/30 px-2 py-1 font-mono text-white">
                确认 {displayValue(params.session_token)}
              </span>
              。如需取消，请回复：
              <span className="mx-1 rounded-lg bg-black/30 px-2 py-1 font-mono text-white">
                取消 {displayValue(params.session_token)}
              </span>
              。
            </p>
          </div>
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
            <p className="text-sm font-medium text-white">安全边界</p>
            <p className="mt-2 text-sm leading-6 text-slate-300">
              确认后系统只会记录事实、保存规则或生成草稿；涉及实际交易的内容仍需你在交易端独立确认。
            </p>
          </div>
        </div>
      </Panel>
    </div>
  );
}
