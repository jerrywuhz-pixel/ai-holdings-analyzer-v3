'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

type AuthMode = 'login' | 'register' | 'verify';

export default function LoginForm({ authModeLabel }: { authModeLabel: string }) {
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>('login');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);
  const [resendLoading, setResendLoading] = useState(false);
  const [showInsecureWarning, setShowInsecureWarning] = useState(false);

  useEffect(() => {
    const isLocalhost = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
    setShowInsecureWarning(window.location.protocol !== 'https:' && !isLocalhost);

    const modeParam = new URLSearchParams(window.location.search).get('mode');
    if (modeParam === 'register') {
      setMode('register');
    }
  }, []);

  function goToOnboarding() {
    router.push('/onboarding/welcome');
  }

  function getSafeNextPath() {
    const nextPath = new URLSearchParams(window.location.search).get('next');
    if (!nextPath || !nextPath.startsWith('/') || nextPath.startsWith('//') || nextPath === '/login') {
      return null;
    }
    return nextPath === '/' ? '/dashboard' : nextPath;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setNotice('');

    if (mode === 'register' && password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }

    setLoading(true);

    const endpoint =
      mode === 'login'
        ? '/api/auth/login'
        : mode === 'register'
          ? '/api/auth/register'
          : '/api/auth/verify';
    const payload =
      mode === 'verify'
        ? { email, code: verificationCode }
        : mode === 'register'
          ? { email, password, confirmPassword, displayName }
          : { email, password };

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));

    setLoading(false);

    if (!response.ok) {
      setError(result.error || '登录失败，请检查账号信息');
      return;
    }

    if (result.status === 'verification_required') {
      setMode('verify');
      setNotice(
        [result.message, result.debugCode ? `测试验证码：${result.debugCode}` : null]
          .filter(Boolean)
          .join(' ') ||
          (result.delivery === 'email_sent'
            ? '验证码已发送到邮箱，请输入验证码完成注册。'
            : '验证码已生成，请按页面提示完成确认。')
      );
      return;
    }

    const nextPath = getSafeNextPath();
    if (mode === 'login') {
      router.push(nextPath ?? '/dashboard');
    } else {
      goToOnboarding();
    }
    router.refresh();
  }

  async function handleResendVerification() {
    setError('');
    setNotice('');
    if (!email) {
      setError('请输入邮箱');
      return;
    }

    setResendLoading(true);
    const response = await fetch('/api/auth/resend-verification', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const result = await response.json().catch(() => ({}));
    setResendLoading(false);

    if (!response.ok) {
      setError(result.error || '重新发送失败，请稍后再试');
      return;
    }

    setNotice(
      [result.message, result.debugCode ? `测试验证码：${result.debugCode}` : null]
        .filter(Boolean)
        .join(' ') ||
        (result.delivery === 'email_sent'
          ? '验证码已重新发送到邮箱。'
          : '验证码已重新生成，请按页面提示完成确认。')
    );
  }

  function switchMode(nextMode: AuthMode) {
    setMode(nextMode);
    setError('');
    setNotice('');
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto mt-16 w-full max-w-sm rounded-lg bg-white p-6 shadow">
      <p className="text-xs font-medium uppercase tracking-[0.2em] text-red-500">AI 持仓分析系统</p>
      <h1 className="mt-2 text-xl font-semibold text-gray-900">
        {mode === 'login' ? '登录投资控制台' : mode === 'register' ? '创建账号' : '确认邮箱验证码'}
      </h1>
      <p className="mt-2 text-sm text-gray-500">{authModeLabel}</p>

      <div className="mt-6 grid grid-cols-2 rounded-lg bg-gray-100 p-1 text-sm">
        <button
          type="button"
          onClick={() => switchMode('login')}
          className={[
            'rounded-md px-3 py-2 font-medium transition',
            mode === 'login' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800',
          ].join(' ')}
        >
          登录
        </button>
        <button
          type="button"
          onClick={() => switchMode('register')}
          className={[
            'rounded-md px-3 py-2 font-medium transition',
            mode === 'register' || mode === 'verify'
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-500 hover:text-gray-800',
          ].join(' ')}
        >
          注册
        </button>
      </div>

      <div className="mt-6 space-y-4">
        {mode === 'register' ? (
          <label className="block">
            <span className="text-sm font-medium text-gray-700">昵称</span>
            <input
              type="text"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="例如：Jerry"
            />
          </label>
        ) : null}

        <label className="block">
          <span className="text-sm font-medium text-gray-700">邮箱</span>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            disabled={mode === 'verify'}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </label>

        {mode === 'verify' ? (
          <label className="block">
            <span className="text-sm font-medium text-gray-700">邮箱验证码</span>
            <input
              type="text"
              inputMode="numeric"
              value={verificationCode}
              onChange={(event) => setVerificationCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
              required
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm tracking-[0.4em] focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="000000"
            />
          </label>
        ) : (
          <label className="block">
            <span className="text-sm font-medium text-gray-700">密码</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={mode === 'register' ? 8 : undefined}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </label>
        )}

        {mode === 'register' ? (
          <label className="block">
            <span className="text-sm font-medium text-gray-700">确认密码</span>
            <input
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
              minLength={8}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </label>
        ) : null}
      </div>
      {notice && <p className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{notice}</p>}
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      <button
        type="submit"
        disabled={loading}
        className="mt-6 w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {loading
          ? mode === 'login'
            ? '登录中...'
            : mode === 'register'
              ? '发送中...'
              : '确认中...'
          : mode === 'login'
            ? '登录'
            : mode === 'register'
              ? '发送验证码'
              : '确认并登录'}
      </button>
      {mode === 'verify' ? (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={handleResendVerification}
            disabled={resendLoading}
            className="rounded-md border border-gray-200 px-3 py-2 text-sm text-gray-600 transition hover:border-gray-300 hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {resendLoading ? '发送中...' : '重新发送验证码'}
          </button>
          <button
            type="button"
            onClick={() => switchMode('register')}
            className="rounded-md border border-gray-200 px-3 py-2 text-sm text-gray-600 transition hover:border-gray-300 hover:text-gray-900"
          >
            修改邮箱
          </button>
        </div>
      ) : null}
      {showInsecureWarning ? (
        <p className="mt-4 text-xs leading-5 text-gray-500">
          当前入口未启用 HTTPS，登录信息请仅用于测试部署；绑定域名和证书后再作为长期入口使用。
        </p>
      ) : null}
    </form>
  );
}
