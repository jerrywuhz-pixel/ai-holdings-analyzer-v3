import { PageHeader, Panel, StatusPill } from '@/components/p0-ui';
import { ensureUserAccount } from '@/lib/account-store';
import { requireUser } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

function sourceLabel(sourceType: string) {
  if (sourceType === 'manual') return '手工录入';
  if (sourceType === 'message_trade_input') return '买卖消息';
  if (sourceType === 'ocr') return '截图识别';
  if (sourceType === 'voice_asr') return '语音识别';
  if (sourceType === 'broker_api') return '系统行情源';
  return sourceType;
}

function sourceNameLabel(sourceName: string, sourceType: string) {
  if (sourceType === 'broker_api' || sourceName.includes('富途') || sourceName.includes('券商')) {
    return '系统 Futu 行情源';
  }
  return sourceName;
}

function providerLabel(provider: string) {
  return provider.toLowerCase().includes('futu') ? 'system_market_data' : provider;
}

export default async function SettingsPage() {
  const session = await requireUser();
  const account = await ensureUserAccount(session.user);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="设置"
        title="账号、资产空间和消息能力"
        description="这里展示当前登录账号对应的系统账号、数据隔离空间、默认资产视图、关注清单和清仓回溯。试用阶段登录账号由管理员基于微信绑定分配。"
      />

      <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <Panel title="登录账号" description="登录身份由管理员分配，并映射到已绑定微信账号对应的 tenant。">
          <div className="space-y-3 text-sm text-[#4f494c]">
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#8a817d]">邮箱</p>
              <p className="mt-2 text-[#171417]">{account.email}</p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                <p className="text-xs text-[#8a817d]">登录方式</p>
                <p className="mt-1 text-[#171417]">管理员分配账号</p>
              </div>
              <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                <p className="text-xs text-[#8a817d]">账号状态</p>
                <p className="mt-1 text-[#171417]">{account.status === 'active' ? '正常' : account.status}</p>
              </div>
            </div>
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#8a817d]">account_id</p>
              <p className="mt-2 break-all font-mono text-[#171417]">{account.accountId}</p>
            </div>
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#8a817d]">tenant_id</p>
              <p className="mt-2 break-all font-mono text-[#171417]">{account.tenantId}</p>
            </div>
          </div>
        </Panel>

        <Panel title="登录管理" description="试用阶段不开放用户自助注册、验证码注册和登录后二维码绑定。">
          <div className="space-y-3 text-sm text-[#4f494c]">
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-medium text-[#171417]">账号分配状态</p>
                  <p className="mt-1 text-[#6f686b]">如需修改登录名或重置密码，请由管理员在试用账号管理页操作。</p>
                </div>
                <StatusPill tone="positive">本地账号</StatusPill>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                <p className="text-xs text-[#8a817d]">自助注册</p>
                <p className="mt-1 break-all text-[#171417]">已关闭</p>
              </div>
              <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                <p className="text-xs text-[#8a817d]">登录后微信绑定</p>
                <p className="mt-1 break-all text-[#171417]">已移除</p>
              </div>
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="资产视图" description="首期支持多个资产视图，后续系统行情、手工录入、消息和 OCR 来源都通过视图聚合。">
          <div className="space-y-3">
            {account.portfolioViews.map((view) => (
              <div key={view.id} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-[#171417]">{view.name}</p>
                    <p className="mt-1 text-sm text-[#6f686b]">
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
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#8a817d]">follow_view</p>
              <p className="mt-2 font-medium text-[#171417]">{account.followView?.name || '关注清单'}</p>
              <p className="mt-1 text-sm text-[#6f686b]">{account.followView?.itemCount ?? 0} 个关注标的</p>
            </div>
            <div className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#8a817d]">list_view</p>
              <p className="mt-2 font-medium text-[#171417]">{account.listView?.name || '清仓回溯'}</p>
              <p className="mt-1 text-sm text-[#6f686b]">{account.listView?.itemCount ?? 0} 个历史标的</p>
            </div>
          </div>
        </Panel>
      </div>

      <Panel title="资产数据来源" description="所有来源都写在当前 tenant 下，后续微信、系统行情、OCR 和语音写入时会记录 lineage。">
        <div className="hidden overflow-x-auto md:block">
          <table className="min-w-full divide-y divide-[#e5ddd9] text-sm">
            <thead className="text-left text-[#6f686b]">
              <tr>
                <th className="px-3 py-3 font-medium">来源</th>
                <th className="px-3 py-3 font-medium">类型</th>
                <th className="px-3 py-3 font-medium">提供方</th>
                <th className="px-3 py-3 font-medium">质量</th>
                <th className="px-3 py-3 font-medium">状态</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e5ddd9]">
              {account.assetSources.map((source) => (
                <tr key={source.id}>
                  <td className="px-3 py-3 font-medium text-[#171417]">{sourceNameLabel(source.sourceName, source.sourceType)}</td>
                  <td className="px-3 py-3 text-[#4f494c]">{sourceLabel(source.sourceType)}</td>
                  <td className="px-3 py-3 text-[#4f494c]">{providerLabel(source.provider)}</td>
                  <td className="px-3 py-3 text-[#4f494c]">{source.sourceQuality}</td>
                  <td className="px-3 py-3">
                    <StatusPill tone={source.isActive ? 'positive' : 'muted'}>
                      {source.isActive ? '启用' : '待启用'}
                    </StatusPill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="space-y-3 md:hidden">
          {account.assetSources.map((source) => (
            <div key={source.id} className="rounded-lg border border-[#e5ddd9] bg-white p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-medium text-[#171417]">{sourceNameLabel(source.sourceName, source.sourceType)}</p>
                  <p className="mt-1 text-sm text-[#6f686b]">{sourceLabel(source.sourceType)} · {providerLabel(source.provider)}</p>
                </div>
                <StatusPill tone={source.isActive ? 'positive' : 'muted'}>{source.isActive ? '启用' : '待启用'}</StatusPill>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
