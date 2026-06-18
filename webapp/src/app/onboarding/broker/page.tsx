import Link from 'next/link';
import { PageHeader, Panel, StatusPill } from '@/components/p0-ui';
import { getOnboardingState } from '@/lib/onboarding';

export const dynamic = 'force-dynamic';

export default async function OnboardingBrokerPage() {
  const state = await getOnboardingState();
  const hasWechat = state.checks.wechat;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="注册初始化"
        title="系统行情源说明"
        description="Futu OpenD 已调整为管理员侧系统行情源。普通用户不再创建本地 connector，也不会通过自己的富途账号做数据同步。"
        actions={<StatusPill tone="muted">不需要配置</StatusPill>}
      />

      <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel
          title="普通用户数据入口"
          description="用户持仓来自手工录入、微信消息、截图 OCR 和后续确认写入；行情、期权链等市场数据由系统源补充。"
          aside={<StatusPill tone="positive">已简化</StatusPill>}
        >
          <div className="space-y-4 text-sm leading-6 text-slate-300">
            <p>这个页面保留为历史入口说明，不再提供用户级 Futu 配对操作。</p>
            <p>如果需要初始化持仓，请在进入系统后使用“数据与账户”里的手工录入，或通过微信发送持仓截图进行识别和确认。</p>
            <Link
              href={hasWechat ? '/onboarding/review' : '/onboarding/wechat'}
              className="inline-flex rounded-xl bg-red-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-400"
            >
              {hasWechat ? '继续最终检查' : '返回微信绑定'}
            </Link>
          </div>
        </Panel>

        <Panel
          title="系统源边界"
          description="管理员维护的 Futu OpenD 只提供市场行情和期权链等参考数据，不代表任何普通用户的个人券商账户。"
          aside={<StatusPill tone="muted">管理员侧</StatusPill>}
        >
          <div className="space-y-3 text-sm text-slate-300">
            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <p className="text-slate-400">Tenant ID</p>
              <p className="mt-2 break-all font-mono text-white">{state.tenantId}</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <p className="font-medium text-white">不会同步个人富途账户</p>
              <p className="mt-2">普通用户的持仓、现金和成本必须来自用户确认过的输入；系统行情只用于估值、策略分析和实时性校验。</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <p className="font-medium text-white">管理员 OpenD</p>
              <p className="mt-2">部署与心跳监控属于运维范围，不进入用户注册流程。</p>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
