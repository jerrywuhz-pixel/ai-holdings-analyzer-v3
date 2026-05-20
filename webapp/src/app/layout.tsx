import type { Metadata } from 'next';
import './globals.css';
import AppShell from '@/components/p0-shell';
import { getChromeSnapshot } from '@/lib/p0';
import { getCurrentSession } from '@/lib/supabase';

export const metadata: Metadata = {
  title: 'AI 持仓分析系统 3.0',
  description: 'AI 持仓投资分析系统 3.0',
  icons: {
    icon: '/favicon.svg',
  },
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [chrome, session] = await Promise.all([getChromeSnapshot(), getCurrentSession()]);

  return (
    <html lang="zh-CN">
      <body className="font-sans antialiased">
        <AppShell chrome={chrome} user={session?.user ?? null}>{children}</AppShell>
      </body>
    </html>
  );
}
