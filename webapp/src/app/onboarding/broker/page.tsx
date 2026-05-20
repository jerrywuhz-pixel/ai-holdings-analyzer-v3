import Link from 'next/link';
import { PageHeader, Panel, StatusPill } from '@/components/p0-ui';
import { startFutuPairing } from '@/app/onboarding/actions';
import { getOnboardingState } from '@/lib/onboarding';
import { getDataServiceBaseUrl } from '@/lib/p0-api';

export const dynamic = 'force-dynamic';

const inputClass =
  'mt-2 block w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-300/50';

export default async function OnboardingBrokerPage() {
  const state = await getOnboardingState();
  const connector = state.brokerConnector;
  const baseUrl = getDataServiceBaseUrl();
  const tokenConfigured = Boolean(process.env.FUTU_CONNECTOR_PAIRING_TOKEN);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="注册初始化"
        title="连接 Futu 本地数据源"
        description="云端只接收只读快照，本机 Futu OpenD 与本地 connector 负责读取持仓、现金和期权数据。"
        actions={<StatusPill tone="muted">3 / 4</StatusPill>}
      />

      <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel
          title="Connector 配对"
          description="创建后会生成租户级 connector_instance_id，用于本地轮询和上传。"
          aside={<StatusPill tone={connector ? 'positive' : 'muted'}>{connector ? '已创建' : '未创建'}</StatusPill>}
        >
          {connector ? (
            <div className="space-y-4">
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-sm text-slate-400">Connector ID</p>
                <p className="mt-2 break-all font-mono text-sm text-white">{connector.id}</p>
              </div>
              <div className="grid gap-3 text-sm text-slate-300 sm:grid-cols-2">
                <p>状态 {connector.pairing_status}</p>
                <p>心跳 {connector.heartbeat_status}</p>
                <p>权限 {connector.permission_scope}</p>
                <p>运行模式 {connector.runtime_mode}</p>
              </div>
              <Link
                href="/onboarding/review"
                className="inline-flex rounded-xl bg-red-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-400"
              >
                继续最终检查
              </Link>
            </div>
          ) : (
            <form action={startFutuPairing} className="space-y-4">
              <label className="block">
                <span className="text-sm font-medium text-slate-200">设备名称</span>
                <input name="device_label" defaultValue="本机 Futu OpenD" className={inputClass} />
              </label>
              <button
                type="submit"
                className="rounded-xl bg-red-500 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-red-400"
              >
                创建 Futu 配对
              </button>
            </form>
          )}
        </Panel>

        <Panel
          title="云端接入参数"
          description="这些值会用于本地 connector 轮询任务和上传账户快照。"
          aside={<StatusPill tone={tokenConfigured ? 'positive' : 'warning'}>{tokenConfigured ? 'Token 已配置' : 'Token 待配置'}</StatusPill>}
        >
          <div className="space-y-3 text-sm">
            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <p className="text-slate-400">Tenant ID</p>
              <p className="mt-2 break-all font-mono text-white">{state.tenantId}</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <p className="text-slate-400">Poll Endpoint</p>
              <p className="mt-2 break-all font-mono text-white">{baseUrl}/api/v3/connectors/poll</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <p className="text-slate-400">Upload Endpoint</p>
              <p className="mt-2 break-all font-mono text-white">{baseUrl}/api/v3/connectors/upload</p>
            </div>
            {!tokenConfigured ? (
              <div className="rounded-xl border border-amber-400/20 bg-amber-400/10 p-4 text-amber-100">
                云端还缺少 FUTU_CONNECTOR_PAIRING_TOKEN，connector 轮询会被 Data Service 拦截。
              </div>
            ) : null}
          </div>
        </Panel>
      </div>
    </div>
  );
}
