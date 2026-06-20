'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const sidebarLinks = [
  { href: '/dashboard', label: '总览' },
  { href: '/holdings', label: '持仓' },
  { href: '/sell-put', label: 'Sell Put' },
  { href: '/data', label: '数据与账户' },
  { href: '/rules', label: '交易纪律' },
  { href: '/ops', label: '运行状态' },
  { href: '/settings', label: '设置' },
  { href: '/admin', label: '试用账号管理' },
  { href: '/admin/social-watchlist', label: '社媒关注清单' },
  { href: '/admin/accounts/new', label: '创建登录账号' },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-64 flex-shrink-0 border-r border-gray-200 bg-white md:flex md:flex-col">
      <div className="flex flex-1 flex-col overflow-y-auto py-4">
        <nav className="space-y-1 px-2">
          {sidebarLinks.map((link) => {
            const isActive = pathname === link.href || (link.href !== '/admin' && pathname.startsWith(`${link.href}/`));
            return (
              <Link
                key={link.href}
                href={link.href}
                className={[
                  'block rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  isActive ? 'bg-primary text-white' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
                ].join(' ')}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}
