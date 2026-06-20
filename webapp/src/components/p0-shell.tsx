'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { FreshnessPill } from '@/components/p0-ui';
import { ChromeSnapshot } from '@/lib/p0';
import type { AppUser } from '@/lib/supabase';

const desktopNav = [
  { href: '/dashboard', label: '总览' },
  { href: '/holdings', label: '持仓' },
  { href: '/sell-put', label: 'Sell Put' },
  { href: '/data', label: '数据与账户' },
  { href: '/rules', label: '交易纪律' },
  { href: '/ops', label: '运行状态' },
  { href: '/settings', label: '设置' },
];

const mobileTabs = [
  { href: '/dashboard', label: '总览' },
  { href: '/holdings', label: '持仓' },
  { href: '/sell-put', label: 'Sell Put' },
  { href: '/data', label: '数据' },
  { href: '/rules', label: '纪律' },
];

function isActive(pathname: string, href: string) {
  return href === '/' ? pathname === href : pathname.startsWith(href);
}

const standalonePaths = new Set(['/', '/features', '/intro', '/wechat-clawbot', '/onboarding/welcome']);

export default function AppShell({
  chrome,
  user,
  children,
}: {
  chrome: ChromeSnapshot;
  user: AppUser | null;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  if (pathname.startsWith('/login') || standalonePaths.has(pathname)) {
    return <main>{children}</main>;
  }

  const activeView = chrome.views.find((view) => view.id === chrome.activeViewId) ?? chrome.views[0];
  const userLabel = user?.name || user?.email || '已登录';

  async function handleLogout() {
    await fetch('/api/auth/logout', { method: 'POST' });
    router.push('/login');
    router.refresh();
  }

  return (
    <div className="min-h-screen bg-[#fafafa] text-[#171417]">
      <div className="mx-auto flex min-h-screen max-w-[1680px] flex-col px-2 pb-16 pt-2 md:px-4 md:pb-4 md:pt-4">
        <header className="sticky top-2 z-20 rounded-lg border border-[#e5ddd9] bg-[#fafafa]/95 shadow-[0_12px_36px_rgba(61,38,32,0.08)] backdrop-blur">
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 md:px-4">
            <div className="flex min-w-0 items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#d71920] text-sm font-semibold text-white shadow-sm">
                AI
              </div>
              <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-[0.18em] text-[#d71920]">AI 资产与风险助手</p>
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                  <span className="truncate text-sm font-semibold text-[#171417] md:text-base">投资控制台</span>
                  <span className="rounded-full border border-[#f0c8c5] bg-[#fff4f1] px-2 py-0.5 text-[11px] font-medium text-[#a8181e]">
                    实盘账户视图
                  </span>
                </div>
              </div>
            </div>
            <nav className="order-3 -mx-1 flex w-[calc(100%+0.5rem)] items-center gap-1 overflow-x-auto border-t border-[#eee7e3] px-1 pt-2 md:order-none md:mx-0 md:w-auto md:border-t-0 md:px-0 md:pt-0">
              {desktopNav.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={[
                    'whitespace-nowrap rounded-lg px-3 py-1.5 text-sm transition',
                    isActive(pathname, item.href)
                      ? 'bg-[#d71920] text-white shadow-sm'
                      : 'text-[#4f494c] hover:bg-[#f2ece8] hover:text-[#171417]',
                  ].join(' ')}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="flex items-center gap-2">
              {user ? (
                <details className="group relative">
                  <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-lg border border-[#e5ddd9] bg-white px-2.5 py-1.5 text-xs text-[#4f494c] transition hover:border-[#d8ccc7] hover:bg-[#fffaf8] [&::-webkit-details-marker]:hidden">
                    <span className="max-w-[84px] truncate sm:max-w-[180px]">{userLabel}</span>
                    <span className="hidden rounded-full bg-[#f2ece8] px-2 py-0.5 text-[11px] text-[#6f686b] sm:inline-flex">
                      本地账号
                    </span>
                    <span className="text-[#8a817d] transition group-open:rotate-180">⌄</span>
                  </summary>
                  <div
                    role="menu"
                    className="absolute right-0 top-[calc(100%+8px)] z-30 w-48 overflow-hidden rounded-lg border border-[#e5ddd9] bg-white p-1 text-sm shadow-[0_18px_60px_rgba(61,38,32,0.14)]"
                  >
                    <Link
                      href="/account/password"
                      role="menuitem"
                      className="block rounded-md px-3 py-2 text-[#171417] transition hover:bg-[#fff4f1] hover:text-[#d71920]"
                    >
                      修改密码
                    </Link>
                    <Link
                      href="/settings"
                      role="menuitem"
                      className="block rounded-md px-3 py-2 text-[#6f686b] transition hover:bg-[#f8f3ef] hover:text-[#171417]"
                    >
                      账户设置
                    </Link>
                  </div>
                </details>
              ) : null}
              <button
                type="button"
                onClick={handleLogout}
                className="rounded-lg border border-[#e5ddd9] bg-white px-2.5 py-1.5 text-xs text-[#4f494c] transition hover:border-[#d8ccc7] hover:bg-[#fffaf8] sm:px-3 sm:text-sm"
              >
                退出
              </button>
            </div>
          </div>
        </header>

        <main className="mt-2 min-w-0 flex-1 rounded-lg border border-[#e5ddd9] bg-white p-3 shadow-[0_18px_60px_rgba(61,38,32,0.08)] md:mt-3 md:p-5">
          {children}
        </main>

        <footer className="mt-3 hidden rounded-lg border border-[#e5ddd9] bg-white px-4 py-2 text-xs text-[#6f686b] shadow-sm md:block md:px-5">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="text-[#171417]">账户视图 {activeView.name} / {activeView.baseCurrency}</span>
            {chrome.marketStates.map((item) => (
              <span key={item.market}>{item.market} {item.status}</span>
            ))}
            <span className={chrome.syncIssues ? 'text-amber-700' : 'text-emerald-700'}>
              数据提醒 {chrome.syncIssues}
            </span>
            <span>处理中 {chrome.runningJobs}</span>
            {chrome.sources.map((source) => (
              <FreshnessPill key={source.key} source={source} />
            ))}
          </div>
        </footer>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-[#e5ddd9] bg-white/95 px-2 py-1.5 shadow-[0_-10px_30px_rgba(61,38,32,0.1)] backdrop-blur md:hidden">
        <div className="mx-auto grid max-w-xl grid-cols-5 gap-1">
          {mobileTabs.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={[
                'rounded-lg px-2 py-2 text-center text-xs',
                isActive(pathname, item.href) ? 'bg-[#d71920] text-white' : 'text-[#6f686b]',
              ].join(' ')}
            >
              {item.label}
            </Link>
          ))}
        </div>
      </nav>
    </div>
  );
}
