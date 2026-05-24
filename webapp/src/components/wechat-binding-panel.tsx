'use client';

import { useEffect, useMemo, useState } from 'react';
import { StatusPill } from '@/components/p0-ui';

type WechatAuth = {
  id: string;
  qrcode_url?: string | null;
  status: string;
  bind_code?: string | null;
  expires_at?: string | null;
  confirmed_at?: string | null;
  conversation_verified_at?: string | null;
  last_checked_at?: string | null;
  error_message?: string | null;
};

type WechatBinding = {
  id: string;
  openclaw_account_id: string;
  channel_user_ref?: string | null;
  bound_at?: string | null;
};

const statusLabel: Record<string, string> = {
  qr_pending: '等待扫码',
  authorized: '已授权',
  conversation_pending: '等待绑定码',
  conversation_verified: '已绑定',
  expired: '已过期',
  failed: '失败',
  revoked: '已撤销',
};

function StepPill({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return <StatusPill tone={ok ? 'positive' : 'muted'}>{children}</StatusPill>;
}

function WechatMark() {
  return (
    <div className="flex h-11 w-11 items-center justify-center rounded-full border border-black/10 bg-white shadow-lg">
      <span className="text-xl" aria-hidden="true">微信</span>
    </div>
  );
}

async function postBinding(action: 'start' | 'refresh' | 'verify', authSessionId?: string, verifyCode?: string) {
  const response = await fetch('/api/onboarding/wechat/binding', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, authSessionId, verifyCode }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || '微信 Claw 绑定操作失败');
  }
  return payload as { auth?: WechatAuth | null; binding?: WechatBinding | null; status?: string };
}

export function WechatBindingPanel({
  initialAuth,
  initialBinding,
}: {
  initialAuth: WechatAuth | null;
  initialBinding: WechatBinding | null;
}) {
  const [auth, setAuth] = useState<WechatAuth | null>(initialAuth);
  const [binding, setBinding] = useState<WechatBinding | null>(initialBinding);
  const [modalOpen, setModalOpen] = useState(Boolean(initialAuth && !initialBinding));
  const [busy, setBusy] = useState(false);
  const [pairCode, setPairCode] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const isAuthorized = auth?.status === 'authorized' || auth?.status === 'conversation_pending' || auth?.status === 'conversation_verified';
  const isBound = Boolean(binding);
  const authId = auth?.id;
  const needsPairCode = Boolean(auth?.error_message?.includes('验证码'));
  const modalTitle = isBound ? '微信已连接' : '扫码登录';
  const modalHint = isBound
    ? '微信 ClawBot 已完成绑定，可以继续下一步。'
    : needsPairCode
      ? '请输入手机微信显示的数字验证码'
      : '请使用微信扫描下方二维码完成连接';
  const statusText = useMemo(() => {
    if (binding) return '已绑定';
    if (!auth) return '未开始';
    return statusLabel[auth.status] || auth.status;
  }, [auth, binding]);

  async function run(action: 'start' | 'refresh' | 'verify') {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const payload = await postBinding(action, auth?.id, action === 'refresh' ? pairCode : undefined);
      if (payload.auth !== undefined) setAuth(payload.auth || null);
      if (payload.binding) {
        setBinding(payload.binding);
        setMessage('微信 ClawBot 已完成绑定');
        setPairCode('');
      } else if (action === 'verify') {
        setMessage('还没有收到绑定码消息，请稍后再试');
      }
      setModalOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : '微信 Claw 绑定操作失败');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!modalOpen || !authId || binding || needsPairCode) return;
    let cancelled = false;
    let timer: number | undefined;

    async function poll() {
      try {
        const payload = await postBinding('refresh', authId);
        if (!cancelled) {
          if (payload.auth !== undefined) setAuth(payload.auth || null);
          if (payload.binding) {
            setBinding(payload.binding);
            setMessage('微信 ClawBot 已完成绑定');
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '刷新微信扫码状态失败');
        }
      } finally {
        if (!cancelled) {
          timer = window.setTimeout(poll, 5000);
        }
      }
    }

    timer = window.setTimeout(poll, 500);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [authId, binding, modalOpen, needsPairCode]);

  return (
    <>
      <div className="space-y-5">
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-emerald-400/10 text-emerald-200">
                微信
              </div>
              <div>
                <p className="text-base font-semibold text-white">微信 ClawBot</p>
                <p className="mt-1 text-sm text-slate-400">通过微信机器人接收并回复用户消息</p>
                {binding ? (
                  <p className="mt-2 break-all font-mono text-xs text-emerald-200">{binding.openclaw_account_id}</p>
                ) : null}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <StatusPill tone={isBound ? 'positive' : auth ? 'warning' : 'muted'}>{statusText}</StatusPill>
              <button
                type="button"
                onClick={() => (auth ? setModalOpen(true) : run('start'))}
                disabled={busy}
                className="rounded-xl bg-white px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {auth ? '配置' : '开始绑定'}
              </button>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <StepPill ok={Boolean(auth)}>生成二维码</StepPill>
          <StepPill ok={Boolean(isAuthorized || binding)}>扫码确认</StepPill>
          <StepPill ok={Boolean(binding)}>写入 channel binding</StepPill>
        </div>

        {message ? <div className="rounded-xl border border-emerald-400/20 bg-emerald-500/10 p-3 text-sm text-emerald-100">{message}</div> : null}
        {error ? <div className="rounded-xl border border-red-400/20 bg-red-500/10 p-3 text-sm text-red-100">{error}</div> : null}
      </div>

      {modalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 px-4 py-8 backdrop-blur-sm">
          <div className="relative w-full max-w-[520px] rounded-[28px] border border-black/10 bg-white text-slate-950 shadow-2xl">
            <div className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2">
              <WechatMark />
            </div>
            <button
              type="button"
              onClick={() => setModalOpen(false)}
              aria-label="关闭微信绑定弹窗"
              className="absolute right-6 top-6 flex h-9 w-9 items-center justify-center rounded-full text-2xl leading-none text-slate-900 transition hover:bg-slate-100"
            >
              ×
            </button>

            <div className="px-8 pb-8 pt-20 text-center">
              <h2 className="text-3xl font-semibold tracking-normal">{modalTitle}</h2>
              <p className="mt-4 text-base font-medium text-slate-400">{modalHint}</p>

              <div className="mx-auto mt-8 flex h-[268px] w-[268px] items-center justify-center rounded-xl border border-slate-200 bg-white p-3">
                {auth?.qrcode_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={auth.qrcode_url} alt="微信 ClawBot 授权二维码" className="h-full w-full object-contain" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center rounded-lg bg-slate-100 px-5 text-sm text-slate-500">
                    {busy ? '正在生成二维码' : '当前接口未返回二维码图片'}
                  </div>
                )}
              </div>

              {!binding && auth?.bind_code ? (
                <div className="mx-auto mt-5 max-w-sm rounded-xl bg-slate-50 p-4 text-left">
                  <p className="text-xs font-medium text-slate-500">备用验证</p>
                  <p className="mt-2 text-sm text-slate-600">扫码后如果没有自动完成绑定，请向 ClawBot 发送：</p>
                  <p className="mt-2 break-all font-mono text-xl font-semibold text-slate-950">{auth.bind_code}</p>
                </div>
              ) : null}

              {!binding && needsPairCode ? (
                <div className="mx-auto mt-4 max-w-sm text-left">
                  <label htmlFor="wechat-pair-code" className="text-xs font-medium text-slate-500">
                    请输入手机微信显示的数字验证码
                  </label>
                  <input
                    id="wechat-pair-code"
                    value={pairCode}
                    onChange={(event) => setPairCode(event.target.value)}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    className="mt-2 h-12 w-full rounded-xl border border-slate-200 px-4 text-center font-mono text-lg font-semibold outline-none transition focus:border-slate-900"
                  />
                </div>
              ) : null}
            </div>

            <div className="border-t border-slate-200 px-8 py-6">
              <div className="flex flex-col gap-3 sm:flex-row">
                <button
                  type="button"
                  onClick={() => run('start')}
                  disabled={busy}
                  className="min-h-[48px] flex-1 rounded-full bg-black px-5 py-3 text-base font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  重新生成
                </button>
                {!binding && auth ? (
                  <button
                    type="button"
                    onClick={() => run(isAuthorized ? 'verify' : 'refresh')}
                    disabled={busy}
                    className="min-h-[48px] flex-1 rounded-full border border-slate-200 px-5 py-3 text-base font-semibold text-slate-950 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isAuthorized ? '验证绑定' : '刷新状态'}
                  </button>
                ) : null}
              </div>
              {error ? <p className="mt-4 text-center text-sm text-red-600">{error}</p> : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
