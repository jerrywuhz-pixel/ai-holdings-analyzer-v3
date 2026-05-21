import Link from 'next/link';
import { PageHeader, Panel, StatusPill } from '@/components/p0-ui';
import { WechatBindingPanel } from '@/components/wechat-binding-panel';
import { getOnboardingState, safeWechatAuth, safeWechatBinding } from '@/lib/onboarding';

export const dynamic = 'force-dynamic';

export default async function OnboardingWechatPage() {
  const state = await getOnboardingState();
  const auth = safeWechatAuth(state.latestWechatAuth);
  const binding = safeWechatBinding(state.wechatBinding);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="注册初始化"
        title="绑定微信 ClawBot"
        description="系统会通过 Tencent OpenClaw Weixin 的二维码连接流程授权微信，并把确认后的账号写入当前 tenant 的 channel binding。"
        actions={<StatusPill tone="muted">2 / 4</StatusPill>}
      />

      <div className="grid gap-5 xl:grid-cols-[0.86fr_1.14fr]">
        <Panel
          title="连接状态"
          description="扫码后系统会轮询确认结果；确认成功后会自动创建当前账号的微信消息路由。"
          aside={binding ? <StatusPill tone="positive">已绑定</StatusPill> : <StatusPill tone="warning">待配置</StatusPill>}
        >
          <WechatBindingPanel initialAuth={auth} initialBinding={binding} />
        </Panel>

        <Panel title="绑定后的路由" description="微信消息会进入 OpenClaw 网关，再按 tenant/channel binding 回到持仓系统。">
          <div className="space-y-4 text-sm leading-6 text-slate-300">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <p className="font-medium text-white">消息归属</p>
              <p className="mt-2">绑定成功后，`openclaw_account_id` 会作为当前 tenant 的微信账号标识，OpenClaw 网关用它解析用户消息和确认指令。</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <p className="font-medium text-white">下一步</p>
              <p className="mt-2">微信绑定完成后继续连接 Futu 本地只读 connector，用于同步股票、期权、现金和保证金快照。</p>
              {binding ? (
                <Link
                  href="/onboarding/broker"
                  className="mt-4 inline-flex rounded-xl bg-emerald-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-400"
                >
                  继续连接 Futu
                </Link>
              ) : null}
            </div>
            {auth?.error_message ? (
              <div className="rounded-xl border border-amber-400/20 bg-amber-400/10 p-4 text-amber-100">
                {auth.error_message}
              </div>
            ) : null}
          </div>
        </Panel>
      </div>
    </div>
  );
}
