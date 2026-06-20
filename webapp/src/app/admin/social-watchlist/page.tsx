import Link from 'next/link';
import {
  deleteSocialWatchAccountAction,
  importSocialWatchAccountsAction,
  saveSocialWatchAccountAction,
} from '@/app/admin/actions';
import {
  listSocialWatchAccountsForAdmin,
  maskSecret,
  socialWatchlistDatabaseConfigured,
  type SocialPlatform,
  type SocialWatchAccount,
} from '@/lib/social-watchlist';
import { requireAdmin } from '@/lib/supabase';
import { NewAccountDialog } from './new-account-dialog';

export const dynamic = 'force-dynamic';

type PageSearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function platformLabel(platform: SocialPlatform) {
  if (platform === 'twitter') return 'X';
  if (platform === 'xhs') return '小红书';
  return 'YouTube';
}

function formatSymbols(symbols: string[]) {
  return symbols.length ? symbols.join(', ') : '*';
}

function formatDateTime(iso: string) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default async function SocialWatchlistAdminPage({ searchParams }: { searchParams?: PageSearchParams }) {
  await requireAdmin();
  const params = (await searchParams) ?? {};
  const errorMessage = firstParam(params.error);
  const successMessage = firstParam(params.success);
  const databaseConfigured = socialWatchlistDatabaseConfigured();
  let accountLoadError = '';
  const accounts = databaseConfigured
    ? await listSocialWatchAccountsForAdmin().catch((error) => {
        accountLoadError = error instanceof Error ? error.message : '社媒关注清单读取失败';
        return [];
      })
    : [];
  const activeCount = accounts.filter((account) => account.isActive).length;
  const byPlatform = {
    twitter: accounts.filter((account) => account.platform === 'twitter').length,
    xhs: accounts.filter((account) => account.platform === 'xhs').length,
    youtube: accounts.filter((account) => account.platform === 'youtube').length,
  };

  return (
    <div className="mx-auto max-w-7xl text-slate-100">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">社媒关注清单</h1>
          <p className="mt-1 text-sm text-slate-300">管理员维护 X、小红书、YouTube 的有限账号来源。</p>
        </div>
        <Link href="/admin" className="rounded-md border border-white/15 bg-white/[0.04] px-4 py-2 text-sm font-medium text-slate-200 transition hover:bg-white/[0.08]">
          返回账号管理
        </Link>
      </div>

      {errorMessage ? (
        <div className="mb-4 rounded-md border border-red-400/30 bg-red-500/10 p-4 text-sm leading-6 text-red-100">
          {errorMessage}
        </div>
      ) : null}
      {successMessage ? (
        <div className="mb-4 rounded-md border border-emerald-400/30 bg-emerald-500/10 p-4 text-sm leading-6 text-emerald-100">
          {successMessage}
        </div>
      ) : null}

      <div className="mb-6 grid grid-cols-1 gap-5 sm:grid-cols-4">
        <SummaryCard title="启用账号" value={databaseConfigured ? String(activeCount) : '-'} subtitle={`${accounts.length} total`} />
        <SummaryCard title="X" value={databaseConfigured ? String(byPlatform.twitter) : '-'} subtitle="twitter-cli" />
        <SummaryCard title="小红书" value={databaseConfigured ? String(byPlatform.xhs) : '-'} subtitle="xiaohongshu-mcp" />
        <SummaryCard title="YouTube" value={databaseConfigured ? String(byPlatform.youtube) : '-'} subtitle="yt-dlp" />
      </div>

      {!databaseConfigured ? (
        <div className="rounded-lg border border-amber-400/30 bg-amber-500/10 p-4 text-sm leading-6 text-amber-100">
          当前 WebApp 未配置 DATABASE_URL 或 WEBAPP_DATABASE_URL，无法保存社媒关注清单。
        </div>
      ) : accountLoadError ? (
        <div className="rounded-lg border border-red-400/30 bg-red-500/10 p-4 text-sm leading-6 text-red-100">
          {accountLoadError}
        </div>
      ) : (
        <div className="space-y-6">
          <div className={panelClass}>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-medium text-white">当前账号</h2>
                <span className="mt-1 block text-sm text-slate-400">{accounts.length} 个来源</span>
              </div>
              <NewAccountDialog>
                <AccountForm variant="modal" />
              </NewAccountDialog>
            </div>
            {accounts.length === 0 ? (
              <div className="mt-4 rounded-md border border-white/10 bg-white/[0.04] p-4 text-sm text-slate-300">暂无社媒关注账号。</div>
            ) : (
              <div className="mt-4 overflow-x-auto">
                <table className="min-w-full divide-y divide-white/10 text-sm">
                  <thead className="bg-white/[0.04] text-left text-xs uppercase tracking-wider text-slate-400">
                    <tr>
                      <th className="px-4 py-3 font-medium">账号</th>
                      <th className="px-4 py-3 font-medium">范围</th>
                      <th className="px-4 py-3 font-medium">平台字段</th>
                      <th className="px-4 py-3 font-medium">状态</th>
                      <th className="px-4 py-3 font-medium">编辑</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/10">
                    {accounts.map((account) => (
                      <AccountRow key={account.id} account={account} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <ImportPanel />
        </div>
      )}
    </div>
  );
}

function SummaryCard({ title, value, subtitle }: { title: string; value: string; subtitle: string }) {
  return (
    <div className="overflow-hidden rounded-lg border border-white/10 border-l-4 border-l-red-400 bg-[#111419]/95 shadow-[0_18px_45px_rgba(0,0,0,0.28)]">
      <div className="p-5">
        <p className="truncate text-sm font-medium text-slate-300">{title}</p>
        <p className="mt-1 text-2xl font-semibold text-white">{value}</p>
      </div>
      <div className="border-t border-white/10 bg-white/[0.03] px-5 py-3">
        <p className="text-sm text-slate-400">{subtitle}</p>
      </div>
    </div>
  );
}

function AccountForm({ account, variant = 'panel' }: { account?: SocialWatchAccount; variant?: 'panel' | 'modal' }) {
  return (
    <form action={saveSocialWatchAccountAction} className={variant === 'modal' ? 'p-6' : panelClass}>
      <input type="hidden" name="id" value={account?.id ?? ''} />
      {variant === 'panel' ? <h2 className="text-lg font-medium text-white">{account ? '编辑账号' : '新增账号'}</h2> : null}
      <div className={variant === 'modal' ? 'grid gap-3' : 'mt-4 grid gap-3'}>
        <div className="grid grid-cols-[130px_1fr] gap-3">
          <label className={labelClass} htmlFor={account ? `platform-${account.id}` : 'platform-new'}>平台</label>
          <select id={account ? `platform-${account.id}` : 'platform-new'} name="platform" defaultValue={account?.platform ?? 'twitter'} className={inputClass}>
            <option value="twitter">X</option>
            <option value="xhs">小红书</option>
            <option value="youtube">YouTube</option>
          </select>
        </div>
        <Field name="handle" label="Handle" required defaultValue={account?.handle ?? ''} />
        <Field name="displayName" label="显示名" defaultValue={account?.displayName ?? ''} />
        <Field name="symbols" label="标的" defaultValue={account ? formatSymbols(account.symbols) : '*'} />
        <Field name="priority" label="优先级" type="number" defaultValue={String(account?.priority ?? 100)} />
        <Field name="tenantId" label="Tenant" defaultValue={account?.tenantId ?? ''} />
        <Field name="url" label="主页 URL" defaultValue={account?.url ?? ''} />
        <Field name="channelUrl" label="频道 URL" defaultValue={account?.channelUrl ?? ''} />
        <Field name="userId" label="XHS 用户ID" defaultValue={account?.userId ?? ''} />
        <Field name="xsecToken" label="xsec_token" type="password" placeholder={account?.xsecToken ? '留空保留原值' : ''} />
        <div className="grid grid-cols-[130px_1fr] gap-3">
          <span className={labelClass}>启用</span>
          <label className="inline-flex items-center gap-2 text-sm text-slate-300">
            <input name="isActive" type="checkbox" defaultChecked={account?.isActive ?? true} className="h-4 w-4 rounded border-white/20 bg-[#0b0e13] text-red-500" />
            active
          </label>
        </div>
        <div className="grid grid-cols-[130px_1fr] gap-3">
          <label className={labelClass} htmlFor={account ? `notes-${account.id}` : 'notes-new'}>备注</label>
          <textarea id={account ? `notes-${account.id}` : 'notes-new'} name="notes" defaultValue={account?.notes ?? ''} rows={2} className={inputClass} />
        </div>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2">
        <button type="submit" className="rounded-md bg-red-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-400">
          {account ? '保存修改' : '添加账号'}
        </button>
      </div>
    </form>
  );
}

function AccountRow({ account }: { account: SocialWatchAccount }) {
  return (
    <tr className="align-top">
      <td className="px-4 py-4">
        <div className="font-medium text-white">{account.displayName || account.handle}</div>
        <div className="mt-1 text-xs text-slate-400">{platformLabel(account.platform)} · {account.handle}</div>
        <div className="mt-1 text-xs text-slate-400">更新 {formatDateTime(account.updatedAt)}</div>
      </td>
      <td className="px-4 py-4">
        <div className="font-mono text-xs text-slate-200">{formatSymbols(account.symbols)}</div>
        <div className="mt-1 text-xs text-slate-400">{account.tenantId || 'global'}</div>
        <div className="mt-1 text-xs text-slate-400">priority {account.priority}</div>
      </td>
      <td className="px-4 py-4">
        <div className="space-y-1 text-xs text-slate-300">
          {account.channelUrl ? <div className="max-w-[260px] truncate">channel_url: {account.channelUrl}</div> : null}
          {account.userId ? <div className="max-w-[260px] truncate">user_id: {account.userId}</div> : null}
          {account.xsecToken ? <div>xsec_token: {maskSecret(account.xsecToken)}</div> : null}
          {account.url ? <div className="max-w-[260px] truncate">url: {account.url}</div> : null}
        </div>
      </td>
      <td className="px-4 py-4">
        <span className={account.isActive ? activeBadgeClass : inactiveBadgeClass}>{account.isActive ? '启用' : '停用'}</span>
      </td>
      <td className="px-4 py-4">
        <details className="min-w-[360px]">
          <summary className="cursor-pointer text-sm font-medium text-red-300">编辑</summary>
          <div className="mt-3">
            <AccountForm account={account} />
            <form action={deleteSocialWatchAccountAction} className="mt-2 text-right">
              <input type="hidden" name="id" value={account.id} />
              <button type="submit" className="rounded-md border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm font-medium text-red-100 transition hover:bg-red-500/20">
                删除
              </button>
            </form>
          </div>
        </details>
      </td>
    </tr>
  );
}

function ImportPanel() {
  const sample = JSON.stringify(
    {
      accounts: [
        { platform: 'twitter', handle: 'account_handle', symbols: ['*'], priority: 10 },
        { platform: 'xhs', handle: 'account_handle', user_id: 'user_id', xsec_token: 'xsec_token', symbols: ['*'], priority: 20 },
        { platform: 'youtube', handle: 'channel_handle', channel_url: 'https://www.youtube.com/@channel/videos', symbols: ['*'], priority: 30 },
      ],
    },
    null,
    2
  );
  return (
    <form action={importSocialWatchAccountsAction} className={panelClass}>
      <h2 className="text-lg font-medium text-white">JSON 导入</h2>
      <textarea name="watchlistJson" rows={12} defaultValue={sample} className={`${inputClass} mt-4 font-mono text-xs`} />
      <div className="mt-5 flex justify-end">
        <button type="submit" className="rounded-md bg-red-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-400">
          导入清单
        </button>
      </div>
    </form>
  );
}

function Field({
  name,
  label,
  type = 'text',
  required = false,
  defaultValue = '',
  placeholder = '',
}: {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  defaultValue?: string;
  placeholder?: string;
}) {
  return (
    <div className="grid grid-cols-[130px_1fr] gap-3">
      <label className={labelClass} htmlFor={name}>{label}</label>
      <input id={name} name={name} type={type} required={required} defaultValue={defaultValue} placeholder={placeholder} className={inputClass} />
    </div>
  );
}

const panelClass = 'rounded-lg border border-white/10 bg-[#111419]/95 p-6 shadow-[0_18px_45px_rgba(0,0,0,0.28)]';
const labelClass = 'text-sm font-medium text-slate-300';
const inputClass = 'w-full rounded-md border border-white/10 bg-[#0b0e13] px-3 py-2 text-sm text-slate-100 shadow-sm placeholder:text-slate-500 focus:border-red-400 focus:outline-none focus:ring-1 focus:ring-red-400';
const activeBadgeClass = 'inline-flex rounded-full border border-emerald-400/20 bg-emerald-500/15 px-2.5 py-0.5 text-xs font-medium text-emerald-100';
const inactiveBadgeClass = 'inline-flex rounded-full border border-white/10 bg-white/[0.06] px-2.5 py-0.5 text-xs font-medium text-slate-300';
