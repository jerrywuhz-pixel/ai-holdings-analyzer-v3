import Link from 'next/link';
import { PageHeader, Panel, StatusPill } from '@/components/p0-ui';
import {
  refreshWechatStatus,
  startWechatBinding,
  verifyWechatConversation,
} from '@/app/onboarding/actions';
import { getOnboardingState } from '@/lib/onboarding';

export const dynamic = 'force-dynamic';

const statusLabel: Record<string, string> = {
  qr_pending: '等待扫码',
  authorized: '已授权',
  conversation_pending: '等待绑定码',
  conversation_verified: '已验证',
  expired: '已过期',
  failed: '失败',
  revoked: '已撤销',
};

function StepPill({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return <StatusPill tone={ok ? 'positive' : 'muted'}>{children}</StatusPill>;
}

export default async function OnboardingWechatPage() {
  const state = await getOnboardingState();
  const auth = state.latestWechatAuth;
  const binding = state.wechatBinding;
  const isAuthorized = auth?.status === 'authorized' || auth?.status === 'conversation_pending' || auth?.status === 'conversation_verified';
  const isVerified = Boolean(binding);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="注册初始化"
        title="绑定微信 ClawBot"
        description="系统会通过官方 ClawBot 二维码授权微信，再用一次性绑定码确认当前账号归属。"
        actions={<StatusPill tone="muted">2 / 4</StatusPill>}
      />

      <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel
          title="授权状态"
          description="完成扫码后，继续发送绑定码来确认会话。"
          aside={auth ? <StatusPill tone={isVerified ? 'positive' : isAuthorized ? 'warning' : 'muted'}>{statusLabel[auth.status] ?? auth.status}</StatusPill> : null}
        >
          <div className="flex flex-wrap gap-2">
            <StepPill ok={Boolean(auth)}>二维码</StepPill>
            <StepPill ok={isAuthorized}>授权</StepPill>
            <StepPill ok={isVerified}>会话验证</StepPill>
          </div>

          {binding ? (
            <div className="mt-5 rounded-xl border border-emerald-400/20 bg-emerald-400/10 p-4 text-sm text-emerald-100">
              <p className="font-medium">微信已绑定</p>
              <p className="mt-2 break-all font-mono text-xs opacity-85">{binding.openclaw_account_id}</p>
              <Link
                href="/onboarding/broker"
                className="mt-4 inline-flex rounded-xl bg-emerald-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-400"
              >
                继续连接 Futu
              </Link>
            </div>
          ) : (
            <form action={startWechatBinding} className="mt-5">
              <button
                type="submit"
                className="rounded-xl bg-red-500 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-red-400"
              >
                获取微信授权二维码
              </button>
            </form>
          )}
        </Panel>

        <Panel title="二维码与绑定码" description="扫码授权后，在微信里向 ClawBot 发送绑定码。">
          {!auth ? (
            <div className="rounded-xl border border-dashed border-white/15 bg-white/[0.03] px-5 py-10 text-center text-sm text-slate-400">
              等待生成二维码
            </div>
          ) : (
            <div className="grid gap-5 md:grid-cols-[220px_1fr]">
              <div className="rounded-2xl border border-white/10 bg-white p-3">
                {auth.qrcode_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={auth.qrcode_url} alt="微信 ClawBot 授权二维码" className="aspect-square w-full rounded-xl object-contain" />
                ) : (
                  <div className="flex aspect-square items-center justify-center rounded-xl bg-slate-100 text-center text-sm text-slate-500">
                    当前接口未返回二维码图片
                  </div>
                )}
              </div>

              <div className="space-y-4">
                <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                  <p className="text-sm text-slate-400">绑定码</p>
                  <p className="mt-2 break-all font-mono text-2xl font-semibold text-white">{auth.bind_code}</p>
                </div>

                {auth.error_message ? (
                  <div className="rounded-xl border border-amber-400/20 bg-amber-400/10 p-4 text-sm text-amber-100">
                    {auth.error_message}
                  </div>
                ) : null}

                <div className="flex flex-wrap gap-3">
                  <form action={refreshWechatStatus}>
                    <input type="hidden" name="auth_session_id" value={auth.id} />
                    <button
                      type="submit"
                      className="rounded-xl border border-white/10 bg-white/[0.06] px-4 py-2 text-sm font-medium text-white transition hover:bg-white/[0.1]"
                    >
                      刷新授权状态
                    </button>
                  </form>

                  <form action={verifyWechatConversation}>
                    <input type="hidden" name="auth_session_id" value={auth.id} />
                    <button
                      type="submit"
                      disabled={!isAuthorized}
                      className="rounded-xl bg-red-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      验证微信绑定码
                    </button>
                  </form>
                </div>
              </div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
