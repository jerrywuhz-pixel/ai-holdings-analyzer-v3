'use client';

import { FormEvent, useEffect, useState } from 'react';

export default function LoginForm({ authModeLabel }: { authModeLabel: string }) {
  const [loginName, setLoginName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showInsecureWarning, setShowInsecureWarning] = useState(false);

  useEffect(() => {
    const isLocalhost = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
    setShowInsecureWarning(window.location.protocol !== 'https:' && !isLocalhost);
  }, []);

  function getSafeNextPath() {
    const nextPath = new URLSearchParams(window.location.search).get('next');
    if (!nextPath || !nextPath.startsWith('/') || nextPath.startsWith('//') || nextPath === '/login') {
      return null;
    }
    return nextPath === '/' ? '/dashboard' : nextPath;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const submittedLoginName = String(formData.get('loginName') || '').trim();
    const submittedPassword = String(formData.get('password') || '');
    setError('');
    setLoading(true);

    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ loginName: submittedLoginName, password: submittedPassword }),
    });
    const result = await response.json().catch(() => ({}));
    setLoading(false);

    if (!response.ok) {
      setError(result.error || '登录失败，请检查管理员分配的账号信息');
      return;
    }

    window.location.assign(getSafeNextPath() ?? '/dashboard');
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto mt-16 w-full max-w-sm rounded-lg bg-white p-6 shadow">
      <p className="text-xs font-medium uppercase tracking-[0.2em] text-red-500">AI 持仓分析系统</p>
      <h1 className="mt-2 text-xl font-semibold text-gray-900">登录投资控制台</h1>
      <p className="mt-2 text-sm text-gray-500">{authModeLabel}</p>
      <p className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-3 text-sm leading-6 text-gray-600">
        试用阶段不开放自助注册。请使用管理员为已绑定微信账号分配的登录名和密码。
      </p>

      <div className="mt-6 space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-gray-700">登录名</span>
          <input
            name="loginName"
            type="text"
            value={loginName}
            onChange={(event) => setLoginName(event.target.value)}
            required
            autoComplete="username"
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">密码</span>
          <input
            name="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            autoComplete="current-password"
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </label>
      </div>

      {showInsecureWarning ? (
        <p className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          当前页面不是 HTTPS，仅适合内部试用环境。
        </p>
      ) : null}
      {error ? <p className="mt-4 text-sm text-red-600">{error}</p> : null}

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
