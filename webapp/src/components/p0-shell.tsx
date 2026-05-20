'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useState } from 'react';
import { FreshnessPill, StatusPill } from '@/components/p0-ui';
import { ChromeSnapshot } from '@/lib/p0';
import type { AppUser } from '@/lib/supabase';

const desktopNav = [
  { href: '/', label: '总览' },
  { href: '/holdings', label: '持仓' },
  { href: '/sell-put', label: 'Sell Put' },
  { href: '/confirmations', label: '确认中心' },
  { href: '/data', label: '数据与账户' },
  { href: '/rules', label: '交易纪律' },
  { href: '/ops', label: '运行状态' },
  { href: '/settings', label: '设置' },
];

const mobileTabs = [
  { href: '/', label: '总览' },
  { href: '/holdings', label: '持仓' },
  { href: '/sell-put', label: 'Sell Put' },
  { href: '/confirmations', label: '确认' },
  { href: '/data', label: '数据' },
  { href: '/rules', label: '纪律' },
];

function isActive(pathname: string, href: string) {
  return href === '/' ? pathname === href : pathname.startsWith(href);
}

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
  const [open, setOpen] = useState(false);

  if (pathname.startsWith('/login')) {
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
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,#381116_0%,#0b0d10_38%,#060708_100%)] text-white">
      <div className="mx-auto flex min-h-screen max-w-[1680px] flex-col px-3 pb-24 pt-3 md:px-5 md:pb-6">
        <header className="rounded-[28px] border border-white/10 bg-black/35 backdrop-blur">
          <div className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3 md:px-6">
            <div className="flex items-center gap-3">
              <button
                type="button"
                className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-slate-200 md:hidden"
                onClick={() => setOpen((value) => !value)}
                aria-label="切换导航"
              >
                {open ? '×' : '≡'}
              </button>
              <div>
                <p className="text-xs uppercase tracking-[0.24em] text-red-300/80">AI 资产与风险助手</p>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-white md:text-base">投资控制台</span>
                  <StatusPill tone="danger">实盘账户视图</StatusPill>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {user ? (
                <div className="hidden items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-200 lg:flex">
                  <span className="max-w-[180px] truncate">{userLabel}</span>
                  <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-slate-300">
                    {user.provider === 'local' ? '本地' : 'Supabase'}
                  </span>
                </div>
              ) : null}
              <Link
                href="/confirmations"
                className="inline-flex items-center gap-2 rounded-xl border border-red-400/20 bg-red-500/10 px-2.5 py-2 text-xs text-red-100 transition hover:bg-red-500/15 sm:px-3 sm:text-sm"
              >
                <span className="sm:hidden">待确认</span>
                <span className="hidden sm:inline">确认中心</span>
                <span className="rounded-full bg-red-500 px-2 py-0.5 text-xs font-medium text-white">
                  {chrome.pendingConfirmations}
                </span>
              </Link>
              <button
                type="button"
                onClick={handleLogout}
                className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-200 transition hover:bg-white/[0.08] sm:text-sm"
              >
                退出
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-4 px-4 py-4 md:px-6">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill tone="muted">
                  账户视图 {activeView.name} / {activeView.baseCurrency}
                </StatusPill>
                {chrome.marketStates.map((item) => (
                  <StatusPill key={item.market} tone="muted">
                    {item.market} {item.status}
                  </StatusPill>
                ))}
                <StatusPill tone={chrome.syncIssues ? 'warning' : 'positive'}>
                  数据提醒 {chrome.syncIssues}
                </StatusPill>
                <StatusPill tone="muted">处理中 {chrome.runningJobs}</StatusPill>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {chrome.sources.map((source) => (
                  <FreshnessPill key={source.key} source={source} />
                ))}
              </div>
            </div>

            <div className="hidden items-center gap-2 md:flex">
              {desktopNav.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={[
                    'rounded-xl px-3 py-2 text-sm transition',
                    isActive(pathname, item.href)
                      ? 'bg-red-500 text-white shadow-[0_0_0_1px_rgba(255,255,255,0.06)]'
                      : 'text-slate-300 hover:bg-white/6 hover:text-white',
                  ].join(' ')}
                >
                  {item.label}
                </Link>
              ))}
            </div>

            {open ? (
              <div className="grid gap-2 md:hidden">
                {desktopNav.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setOpen(false)}
                    className={[
                      'rounded-xl border px-3 py-2 text-sm',
                      isActive(pathname, item.href)
                        ? 'border-red-400/30 bg-red-500/10 text-white'
                        : 'border-white/10 bg-white/[0.03] text-slate-200',
                    ].join(' ')}
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            ) : null}
          </div>
        </header>

        <div className="mt-4 flex min-h-0 flex-1 gap-4">
          <aside className="hidden w-[280px] shrink-0 rounded-[28px] border border-white/10 bg-black/30 p-5 xl:block">
            <p className="text-xs uppercase tracking-[0.28em] text-slate-400">资产视图</p>
            <div className="mt-4 space-y-3">
              {chrome.views.map((view) => (
                <div key={view.id} className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-medium text-white">{view.name}</p>
                    {view.id === chrome.activeViewId ? <StatusPill tone="danger">当前</StatusPill> : null}
                  </div>
                  <p className="mt-2 text-sm text-slate-400">
                    {view.baseCurrency} · {view.scope}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">{view.sourceCount} 个数据来源</p>
                  {view.highImpactChangePending ? (
                    <p className="mt-3 text-xs text-amber-300">数据来源变更待确认</p>
                  ) : null}
                </div>
              ))}
            </div>
            <div className="mt-6 rounded-2xl border border-white/8 bg-white/[0.03] p-4">
              <p className="text-sm font-medium text-white">快捷入口</p>
              <div className="mt-3 grid gap-2 text-sm">
                <Link href="/confirmations" className="rounded-xl bg-white/[0.04] px-3 py-2 text-slate-200 transition hover:bg-white/[0.08]">
                  交易录入 / 识别修正
                </Link>
                <Link href="/data" className="rounded-xl bg-white/[0.04] px-3 py-2 text-slate-200 transition hover:bg-white/[0.08]">
                  账户连接 / 数据更新
                </Link>
                <Link href="/ops" className="rounded-xl bg-white/[0.04] px-3 py-2 text-slate-200 transition hover:bg-white/[0.08]">
                  处理进度 / 消息状态
                </Link>
              </div>
            </div>
          </aside>

          <main className="min-w-0 flex-1 rounded-[28px] border border-white/10 bg-black/25 p-4 shadow-[0_24px_80px_rgba(0,0,0,0.32)] md:p-6">
            {children}
          </main>
        </div>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-white/10 bg-[#0a0c0f]/95 px-2 py-2 backdrop-blur md:hidden">
        <div className="mx-auto grid max-w-xl grid-cols-6 gap-1">
          {mobileTabs.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={[
                'rounded-2xl px-2 py-2 text-center text-xs',
                isActive(pathname, item.href) ? 'bg-red-500 text-white' : 'text-slate-400',
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
