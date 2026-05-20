import { PageHeader, Panel, StatusPill } from '@/components/p0-ui';
import { ensureUserAccount, getEmailDeliveryMode } from '@/lib/account-store';
import { requireUser } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

function sourceLabel(sourceType: string) {
  if (sourceType === 'manual') return '手工录入';
  if (sourceType === 'message_trade_input') return '买卖消息';
  if (sourceType === 'ocr') return '截图识别';
  if (sourceType === 'voice_asr') return '语音识别';
  if (sourceType === 'broker_api') return '券商只读连接';
  return sourceType;
}

export default async function SettingsPage() {
  const session = await requireUser();
  const account = await ensureUserAccount(session.user);
  const emailDelivery = getEmailDeliveryMode();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="设置"
        title="账号、资产空间和消息能力"
        description="这里展示当前登录账号对应的系统账号、数据隔离空间、默认资产视图、关注清单、清仓回溯与验证码邮件发送状态。"
      />

      <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <Panel title="登录账号" description="登录身份和持仓系统账号分开管理，但会在这里完成绑定。">
          <div className="space-y-3 text-sm text-slate-300">
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">邮箱</p>
              <p className="mt-2 text-white">{account.email}</p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                <p className="text-xs text-slate-500">登录方式</p>
                <p className="mt-1 text-white">{session.provider === 'local' ? '本地登录' : 'Supabase'}</p>
              </div>
              <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                <p className="text-xs text-slate-500">账号状态</p>
                <p className="mt-1 text-white">{account.status === 'active' ? '正常' : account.status}</p>
              </div>
            </div>
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">account_id</p>
              <p className="mt-2 break-all font-mono text-white">{account.accountId}</p>
            </div>
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">tenant_id</p>
              <p className="mt-2 break-all font-mono text-white">{account.tenantId}</p>
            </div>
          </div>
        </Panel>

        <Panel title="验证码邮件" description="注册验证码支持真实 SMTP 邮件；测试阶段未配置 SMTP 时会写入服务器日志。">
          <div className="space-y-3 text-sm text-slate-300">
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-medium text-white">邮件发送状态</p>
                  <p className="mt-1 text-slate-400">
                    {emailDelivery.configured
                      ? '已配置 SMTP，注册验证码会发送到用户邮箱。'
                      : '暂未配置 SMTP，验证码会写入 WebApp 容器日志，仅适合测试。'}
                  </p>
                </div>
                <StatusPill tone={emailDelivery.configured ? 'positive' : 'warning'}>
                  {emailDelivery.configured ? '可发邮件' : '日志模式'}
                </StatusPill>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                <p className="text-xs text-slate-500">SMTP 主机</p>
                <p className="mt-1 break-all text-white">{emailDelivery.host || '未配置'}</p>
              </div>
              <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                <p className="text-xs text-slate-500">发件人</p>
                <p className="mt-1 break-all text-white">{emailDelivery.from || '未配置'}</p>
              </div>
            </div>
            <p className="rounded-xl border border-amber-400/20 bg-amber-500/10 p-3 text-sm text-amber-100">
              当前公网入口还没有启用 HTTPS，真实用户测试前请先绑定域名和证书，再启用真实 SMTP。
            </p>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="资产视图" description="首期支持多个资产视图，后续券商账户、手工录入、消息和 OCR 来源都通过视图聚合。">
          <div className="space-y-3">
            {account.portfolioViews.map((view) => (
              <div key={view.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-white">{view.name}</p>
                    <p className="mt-1 text-sm text-slate-400">
                      {view.baseCurrency} · {view.sourceCount} 个数据来源
                    </p>
                  </div>
                  {view.isDefault ? <StatusPill tone="danger">默认</StatusPill> : <StatusPill tone="muted">{view.viewType}</StatusPill>}
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="账户资产清单" description="关注清单用于持仓前机会管理；清仓回溯用于持仓后复盘和二次买入策略。">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">follow_view</p>
              <p className="mt-2 font-medium text-white">{account.followView?.name || '关注清单'}</p>
              <p className="mt-1 text-sm text-slate-400">{account.followView?.itemCount ?? 0} 个关注标的</p>
            </div>
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">list_view</p>
              <p className="mt-2 font-medium text-white">{account.listView?.name || '清仓回溯'}</p>
              <p className="mt-1 text-sm text-slate-400">{account.listView?.itemCount ?? 0} 个历史标的</p>
            </div>
          </div>
        </Panel>
      </div>

      <Panel title="资产数据来源" description="所有来源都写在当前 tenant 下，后续微信、富途 OpenD、OCR 和语音写入时会记录 lineage。">
        <div className="hidden overflow-x-auto md:block">
          <table className="min-w-full divide-y divide-white/8 text-sm">
            <thead className="text-left text-slate-400">
              <tr>
                <th className="px-3 py-3 font-medium">来源</th>
                <th className="px-3 py-3 font-medium">类型</th>
                <th className="px-3 py-3 font-medium">提供方</th>
                <th className="px-3 py-3 font-medium">质量</th>
                <th className="px-3 py-3 font-medium">状态</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/8">
              {account.assetSources.map((source) => (
                <tr key={source.id}>
                  <td className="px-3 py-3 font-medium text-white">{source.sourceName}</td>
                  <td className="px-3 py-3 text-slate-300">{sourceLabel(source.sourceType)}</td>
                  <td className="px-3 py-3 text-slate-300">{source.provider}</td>
                  <td className="px-3 py-3 text-slate-300">{source.sourceQuality}</td>
                  <td className="px-3 py-3">
                    <StatusPill tone={source.isActive ? 'positive' : 'muted'}>
                      {source.isActive ? '启用' : '待连接'}
                    </StatusPill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="space-y-3 md:hidden">
          {account.assetSources.map((source) => (
            <div key={source.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-medium text-white">{source.sourceName}</p>
                  <p className="mt-1 text-sm text-slate-400">{sourceLabel(source.sourceType)} · {source.provider}</p>
                </div>
                <StatusPill tone={source.isActive ? 'positive' : 'muted'}>{source.isActive ? '启用' : '待连接'}</StatusPill>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
