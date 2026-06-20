import Link from 'next/link';
import { createWebappLoginForWechat } from '@/app/admin/actions';
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

export default async function NewWebappAccountPage({ searchParams }: { searchParams?: PageSearchParams }) {
  await requireAdmin();
  const params = (await searchParams) ?? {};
  const errorMessage = firstParam(params.error);
  const databaseConfigured = localAuthDatabaseConfigured();
  let accountLoadError = '';
  const accounts = databaseConfigured
    ? await listWechatBoundAccountsForAdmin().catch((error) => {
        accountLoadError = error instanceof Error ? error.message : '账号库连接失败';
        return [];
      })
    : [];
  const defaultTenantId = accounts.find((account) => !account.loginName)?.tenantId || accounts[0]?.tenantId || '';

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-gray-500">管理员账号管理</p>
          <h1 className="mt-1 text-2xl font-bold text-gray-900">创建 WebApp 登录账号</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500">
            为已经完成微信绑定的 tenant 分配 WebApp 登录名、初始密码和角色。账号创建后会直接映射到所选微信账号对应的 tenant。
          </p>
        </div>
        <Link href="/admin" className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50">
          返回账号列表
        </Link>
      </div>

      {errorMessage ? (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-700">
          {errorMessage}
        </div>
      ) : null}

      <div className="rounded-lg bg-white p-6 shadow">
        {!databaseConfigured ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">
            当前 WebApp 未配置 DATABASE_URL 或 WEBAPP_DATABASE_URL，无法读取已绑定微信账号。请先连接账号库后再创建 WebApp 登录账号。
          </div>
        ) : accountLoadError ? (
          <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-700">
            账号库连接失败：{accountLoadError}
          </div>
        ) : accounts.length === 0 ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800">
            目前没有可绑定的 active 微信账号。请先完成微信侧绑定，再回来创建 WebApp 登录账号。
          </div>
        ) : (
          <form action={createWebappLoginForWechat} className="space-y-6">
            <label className="block">
              <span className="text-sm font-medium text-gray-700">选择已绑定微信账号</span>
              <select
                name="tenantId"
                required
                defaultValue={defaultTenantId}
                className="mt-2 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {accounts.map((account) => {
                  const accountName = account.humanName || account.accountLabel || account.displayName || '微信账号';
                  const accountId = maskAccount(account.channelAccountId || account.openclawAccountId);
                  const loginState = account.loginName ? `已分配: ${account.loginName}` : '未分配登录';
                  return (
                    <option key={account.tenantId} value={account.tenantId}>
                      {accountName} / {accountId} / {loginState}
                    </option>
                  );
                })}
              </select>
              <p className="mt-2 text-xs text-gray-500">
                已分配过登录名的微信账号也可以在这里重置账号、密码和角色。
              </p>
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="text-sm font-medium text-gray-700">登录名</span>
                <input
                  name="loginName"
                  type="text"
                  required
                  autoComplete="username"
                  placeholder="例如 jerrywu"
                  className="mt-2 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700">初始密码</span>
                <input
                  name="password"
                  type="password"
                  required
                  minLength={6}
                  autoComplete="new-password"
                  placeholder="至少 6 位"
                  className="mt-2 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="text-sm font-medium text-gray-700">显示名称</span>
                <input
                  name="displayName"
                  type="text"
                  placeholder="用于控制台顶部和账号页展示"
                  className="mt-2 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-gray-700">角色</span>
                <select
                  name="role"
                  defaultValue="user"
                  className="mt-2 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="user">试用用户</option>
                  <option value="admin">管理员</option>
                </select>
              </label>
            </div>

            <div className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm leading-6 text-gray-600">
              绑定关系会写入本地认证表，登录账号的用户 id 与所选微信 tenant 保持一致。这样用户登录 WebApp 后读取的持仓、关注清单和微信对话上下文都归属同一 tenant。
            </div>

            <div className="flex flex-wrap justify-end gap-3">
              <Link href="/admin" className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50">
                取消
              </Link>
              <button type="submit" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition hover:bg-primary-600">
                创建并绑定微信账号
              </button>
            </div>
          </form>
        )}
      </div>

      {accounts.length > 0 ? (
        <div className="mt-6 rounded-lg bg-white p-6 shadow">
          <h2 className="text-base font-semibold text-gray-900">可绑定微信账号</h2>
          <div className="mt-4 divide-y divide-gray-100">
            {accounts.slice(0, 8).map((account) => (
              <div key={`preview-${account.tenantId}`} className="grid gap-2 py-3 text-sm md:grid-cols-[1.2fr_1.4fr_1fr]">
                <div>
                  <p className="font-medium text-gray-900">{account.humanName || account.accountLabel || account.displayName || '微信账号'}</p>
                  <p className="font-mono text-xs text-gray-500">{maskAccount(account.channelAccountId || account.openclawAccountId)}</p>
                </div>
                <div className="font-mono text-xs text-gray-600">{account.tenantId}</div>
                <div className="text-xs text-gray-500">
                  {account.loginName ? `已分配 ${account.loginName}` : '未分配'} / 绑定 {formatDateTime(account.boundAt)}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
