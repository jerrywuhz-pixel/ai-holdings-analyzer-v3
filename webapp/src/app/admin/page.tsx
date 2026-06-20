import Link from 'next/link';
import { assignWechatLogin } from '@/app/admin/actions';
import { listWechatBoundAccountsForAdmin, localAuthDatabaseConfigured } from '@/lib/local-auth-store';
import { requireAdmin } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

type PageSearchParams = Promise<Record<string, string | string[] | undefined>>;

function formatDateTime(iso: string | null) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function maskAccount(value: string | null) {
  if (!value) return '-';
  if (value.length <= 12) return value;
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}

function firstParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

export default async function AdminPage({ searchParams }: { searchParams?: PageSearchParams }) {
  await requireAdmin();
  const params = (await searchParams) ?? {};
  const errorMessage = firstParam(params.error);
  const successMessage = firstParam(params.success);
  const databaseConfigured = localAuthDatabaseConfigured();
  let accountLoadError = '';
  const accounts = databaseConfigured
    ? await listWechatBoundAccountsForAdmin().catch((error) => {
        accountLoadError = error instanceof Error ? error.message : '账号库连接失败';
        return [];
      })
    : [];
  const assignedCount = accounts.filter((account) => account.loginName).length;

  return (
    <div className="mx-auto max-w-7xl">
      <div className="mb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">试用账号管理</h1>
            <p className="mt-1 text-sm text-gray-500">
              当前版本以微信绑定为主账号来源。管理员在这里查看已绑定微信账号，并为对应 tenant 分配或重置 WebApp 登录名和密码。
            </p>
          </div>
          <Link
            href="/admin/accounts/new"
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition hover:bg-primary-600"
          >
            创建登录账号
          </Link>
          <Link
            href="/admin/social-watchlist"
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
          >
            社媒关注清单
          </Link>
        </div>
      </div>

      {errorMessage ? (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-700">
          {errorMessage}
        </div>
      ) : null}
      {successMessage ? (
        <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm leading-6 text-emerald-700">
          {successMessage}
        </div>
      ) : null}

      <div className="mb-6 grid grid-cols-1 gap-5 sm:grid-cols-3">
        <SummaryCard title="已绑定微信账号" value={databaseConfigured ? String(accounts.length) : '-'} subtitle="active channel binding" />
        <SummaryCard title="已分配登录" value={databaseConfigured ? String(assignedCount) : '-'} subtitle="local_auth_users" />
        <SummaryCard title="待分配登录" value={databaseConfigured ? String(accounts.length - assignedCount) : '-'} subtitle="需要管理员处理" />
      </div>

      <div className="rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-medium text-gray-900">微信绑定账号</h2>
        {!databaseConfigured ? (
          <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">
            当前 WebApp 未配置 DATABASE_URL 或 WEBAPP_DATABASE_URL，无法读取已绑定微信账号。请先连接账号库后再管理登录账号。
          </div>
        ) : accountLoadError ? (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-700">
            账号库连接失败：{accountLoadError}
          </div>
        ) : accounts.length === 0 ? (
          <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            暂无有效微信绑定。用户完成微信绑定后会出现在这里。
          </div>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs uppercase tracking-wider text-gray-500">
                <tr>
                  <th className="px-4 py-3 font-medium">微信账号</th>
                  <th className="px-4 py-3 font-medium">Tenant</th>
                  <th className="px-4 py-3 font-medium">绑定时间</th>
                  <th className="px-4 py-3 font-medium">当前登录账号</th>
                  <th className="px-4 py-3 font-medium">分配 / 重置登录</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {accounts.map((account) => {
                  const defaultName =
                    account.loginDisplayName ||
                    account.humanName ||
                    account.displayName ||
                    account.accountLabel ||
                    'Hermes 试用用户';
                  return (
                    <tr key={`${account.tenantId}-${account.channelAccountId || account.openclawAccountId}`} className="align-top">
                      <td className="px-4 py-4">
                        <div className="font-medium text-gray-900">{account.humanName || account.accountLabel || '微信账号'}</div>
                        <div className="mt-1 font-mono text-xs text-gray-500">
                          {maskAccount(account.channelAccountId || account.openclawAccountId)}
                        </div>
                        <div className="mt-1 text-xs text-gray-500">最近活跃 {formatDateTime(account.lastSeenAt)}</div>
                      </td>
                      <td className="px-4 py-4">
                        <div className="font-mono text-xs text-gray-700">{account.tenantId}</div>
                        <div className="mt-1 text-xs text-gray-500">{account.displayName || account.accountStatus || '-'}</div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-4 text-gray-600">{formatDateTime(account.boundAt)}</td>
                      <td className="px-4 py-4">
                        {account.loginName ? (
                          <div>
                            <div className="font-medium text-gray-900">{account.loginName}</div>
                            <div className="mt-1 text-xs text-gray-500">
                              {account.loginRole === 'admin' ? '管理员' : '试用用户'} · 更新 {formatDateTime(account.loginUpdatedAt)}
                            </div>
                          </div>
                        ) : (
                          <span className="inline-flex rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">
                            未分配
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-4">
                        <form action={assignWechatLogin} className="grid min-w-[320px] gap-2">
                          <input type="hidden" name="tenantId" value={account.tenantId} />
                          <input
                            name="loginName"
                            type="text"
                            required
                            defaultValue={account.loginName || ''}
                            placeholder="登录名"
                            className="rounded-md border border-gray-300 px-3 py-2"
                          />
                          <div className="grid grid-cols-[1fr_120px] gap-2">
                            <input
                              name="password"
                              type="password"
                              required
                              minLength={6}
                              placeholder="新密码，至少 6 位"
                              className="rounded-md border border-gray-300 px-3 py-2"
                            />
                            <select name="role" defaultValue={account.loginRole || 'user'} className="rounded-md border border-gray-300 px-3 py-2">
                              <option value="user">试用用户</option>
                              <option value="admin">管理员</option>
                            </select>
                          </div>
                          <input
                            name="displayName"
                            defaultValue={defaultName}
                            placeholder="显示名称"
                            className="rounded-md border border-gray-300 px-3 py-2"
                          />
                          <button
                            type="submit"
                            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition hover:bg-primary-600"
                          >
                            {account.loginName ? '重置账号密码' : '分配登录账号'}
                          </button>
                        </form>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function SummaryCard({ title, value, subtitle }: { title: string; value: string; subtitle: string }) {
  return (
    <div className="overflow-hidden rounded-lg border-l-4 border-l-red-500 bg-white shadow">
      <div className="p-5">
        <p className="truncate text-sm font-medium text-gray-500">{title}</p>
        <p className="mt-1 text-2xl font-semibold text-gray-900">{value}</p>
      </div>
      <div className="bg-gray-50 px-5 py-3">
        <p className="text-sm text-gray-500">{subtitle}</p>
      </div>
    </div>
  );
}
