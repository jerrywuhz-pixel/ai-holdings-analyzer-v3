import Link from 'next/link';
import { PageHeader, Panel, StatusPill } from '@/components/p0-ui';
import { finishOnboarding } from '@/app/onboarding/actions';
import { getOnboardingState } from '@/lib/onboarding';

export const dynamic = 'force-dynamic';

function CheckRow({
  ok,
  title,
  detail,
  href,
}: {
  ok: boolean;
  title: string;
  detail: string;
  href: string;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-4 md:flex-row md:items-center md:justify-between">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium text-white">{title}</p>
          <StatusPill tone={ok ? 'positive' : 'warning'}>{ok ? '已就绪' : '待处理'}</StatusPill>
        </div>
        <p className="mt-2 text-sm text-slate-400">{detail}</p>
      </div>
      <Link
        href={href}
        className="inline-flex w-fit rounded-xl border border-white/10 bg-white/[0.06] px-3 py-2 text-sm font-medium text-white transition hover:bg-white/[0.1]"
      >
        查看
      </Link>
    </div>
  );
}

export default async function OnboardingReviewPage() {
  const state = await getOnboardingState();
  const ready = state.checks.profile;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="注册初始化"
        title="完成前检查"
        description="试用阶段登录账号由管理员基于已绑定微信账号分配。用户侧只需要确认账户口径，系统行情源由管理员统一维护。"
        actions={<StatusPill tone="muted">2 / 2</StatusPill>}
      />

      <Panel
        title="切换检查"
        description="全部就绪后，账号会进入 3.0 持仓系统。"
        aside={<StatusPill tone={ready ? 'positive' : 'warning'}>{ready ? '可以进入' : '仍有阻塞'}</StatusPill>}
      >
        <div className="space-y-3">
          <CheckRow
            ok={state.checks.profile}
            title="资产画像与分析口径"
            detail={state.settings ? `${state.settings.base_currency} / ${state.settings.timezone}` : '尚未保存账户基础口径'}
            href="/onboarding/profile"
          />
          <CheckRow
            ok={Boolean(state.wechatBinding)}
            title="微信账号映射"
            detail={state.wechatBinding ? (state.wechatBinding.channel_account_id || state.wechatBinding.openclaw_account_id) : '当前登录账号由管理员分配；如未看到微信映射，请联系管理员检查绑定。'}
            href="/settings"
          />
        </div>

        <form action={finishOnboarding} className="mt-5">
          <button
            type="submit"
            disabled={!ready}
            className="rounded-xl bg-red-500 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            完成初始化并进入系统
          </button>
        </form>
      </Panel>
    </div>
  );
}
