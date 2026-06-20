'use client';

import { FormEvent, useState } from 'react';

export default function ChangePasswordForm() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setSuccess('');

    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致');
      return;
    }

    setLoading(true);
    const response = await fetch('/api/auth/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ currentPassword, newPassword, confirmPassword }),
    });
    const result = await response.json().catch(() => ({}));
    setLoading(false);

    if (!response.ok) {
      setError(result.error || '密码修改失败，请稍后重试');
      return;
    }

    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setSuccess('密码已更新。下次登录请使用新密码。');
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-4">
      <label className="block">
        <span className="text-sm font-medium text-[#4f494c]">当前密码</span>
        <input
          name="currentPassword"
          type="password"
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.target.value)}
          required
          autoComplete="current-password"
          className="mt-2 block w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition placeholder:text-[#8a817d] focus:border-[#d71920]"
        />
      </label>

      <div className="grid gap-4 md:grid-cols-2">
        <label className="block">
          <span className="text-sm font-medium text-[#4f494c]">新密码</span>
          <input
            name="newPassword"
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            required
            minLength={6}
            autoComplete="new-password"
            className="mt-2 block w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition placeholder:text-[#8a817d] focus:border-[#d71920]"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-[#4f494c]">确认新密码</span>
          <input
            name="confirmPassword"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            required
            minLength={6}
            autoComplete="new-password"
            className="mt-2 block w-full rounded-lg border border-[#e5ddd9] bg-white px-3 py-2 text-sm text-[#171417] outline-none transition placeholder:text-[#8a817d] focus:border-[#d71920]"
          />
        </label>
      </div>

      <p className="rounded-lg border border-[#e5ddd9] bg-[#fffaf8] p-4 text-sm leading-6 text-[#6f686b]">
        修改密码只影响 WebApp 本地登录账号，不会改变已经绑定的微信账号或 tenant 数据归属。
      </p>

      {error ? (
        <p className="rounded-lg border border-[#f0c8c5] bg-[#fff0ef] p-3 text-sm text-[#d71920]">{error}</p>
      ) : null}
      {success ? (
        <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{success}</p>
      ) : null}

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-[#d71920] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#bd151b] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? '保存中...' : '保存新密码'}
        </button>
      </div>
    </form>
  );
}
