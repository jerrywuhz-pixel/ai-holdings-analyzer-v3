import Link from 'next/link';
import { PageHeader, Panel, StatusPill } from '@/components/p0-ui';
import { getOnboardingState } from '@/lib/onboarding';

export const dynamic = 'force-dynamic';

export default async function OnboardingDonePage() {
  const state = await getOnboardingState();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="注册初始化"
        title="初始化完成"
        description="账号已经切换到 3.0 持仓系统，后续页面会按当前租户、微信绑定和系统行情源读取数据。"
        actions={<StatusPill tone="positive">已完成</StatusPill>}
      />

      <Panel title="当前账号" description="这是本次注册初始化落地的租户信息。">
        <div className="grid gap-3 text-sm text-slate-300 md:grid-cols-2">
          <p>Tenant ID: <span className="font-mono text-white">{state.tenantId}</span></p>
          <p>账号: <span className="text-white">{state.userEmail || '-'}</span></p>
          <p>微信: <span className="break-all font-mono text-white">{state.wechatBinding?.channel_account_id || state.wechatBinding?.openclaw_account_id || '-'}</span></p>
          <p>行情源: <span className="text-white">管理员统一维护</span></p>
        </div>
        <Link
          href="/dashboard"
          className="mt-5 inline-flex rounded-xl bg-red-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-400"
        >
          进入总览
        </Link>
      </Panel>
    </div>
  );
}
