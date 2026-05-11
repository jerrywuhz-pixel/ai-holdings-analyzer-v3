'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  createBrowserClient,
} from '@/lib/supabase-browser';

function setSessionCookie(name: string, value: string, maxAge: number) {
  const secure = window.location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAge}; SameSite=Lax${secure}`;
}

export default function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setLoading(true);

    const supabase = createBrowserClient();
    const { data, error: authError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    setLoading(false);

    if (authError || !data.session) {
      setError(authError?.message || '登录失败，请检查账号信息');
      return;
    }

    setSessionCookie(ACCESS_TOKEN_COOKIE, data.session.access_token, data.session.expires_in);
    setSessionCookie(REFRESH_TOKEN_COOKIE, data.session.refresh_token, 60 * 60 * 24 * 30);
    router.push('/');
    router.refresh();
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto mt-16 w-full max-w-sm rounded-lg bg-white p-6 shadow">
      <h1 className="text-xl font-semibold text-gray-900">登录</h1>
      <div className="mt-6 space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-gray-700">邮箱</span>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-gray-700">密码</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </label>
      </div>
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      <button
        type="submit"
        disabled={loading}
        className="mt-6 w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {loading ? '登录中...' : '登录'}
      </button>
    </form>
  );
}
