import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { ensureUserAccount } from '@/lib/account-store';
import {
  ACCESS_TOKEN_COOKIE,
  LOCAL_SESSION_COOKIE,
  REFRESH_TOKEN_COOKIE,
  createLocalSessionToken,
  hasSupabaseAuthConfig,
  isLocalAuthEnabled,
} from '@/lib/supabase';
import { createLocalRegistration } from '@/lib/local-auth-store';
import { sendVerificationEmail } from '@/lib/email';

export const runtime = 'nodejs';

const MONTH_SECONDS = 60 * 60 * 24 * 30;

function secureCookie(request: NextRequest) {
  return request.nextUrl.protocol === 'https:' || process.env.AUTH_COOKIE_SECURE === 'true';
}

function setSessionCookie(
  response: NextResponse,
  request: NextRequest,
  name: string,
  value: string,
  maxAge: number
) {
  response.cookies.set(name, value, {
    httpOnly: true,
    sameSite: 'lax',
    secure: secureCookie(request),
    path: '/',
    maxAge,
  });
}

function clearCookie(response: NextResponse, name: string) {
  response.cookies.set(name, '', {
    httpOnly: true,
    sameSite: 'lax',
    secure: false,
    path: '/',
    maxAge: 0,
  });
}

function getBaseUrl(request: NextRequest) {
  return process.env.WEBAPP_BASE_URL || request.nextUrl.origin;
}

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const email = String(body?.email || '').trim();
  const password = String(body?.password || '');
  const confirmPassword = body?.confirmPassword ? String(body.confirmPassword) : '';
  const displayName = String(body?.displayName || body?.name || '').trim();

  if (!email || !password) {
    return NextResponse.json({ error: '请输入邮箱和密码' }, { status: 400 });
  }
  if (password.length < 8) {
    return NextResponse.json({ error: '密码至少需要 8 位' }, { status: 400 });
  }
  if (confirmPassword && confirmPassword !== password) {
    return NextResponse.json({ error: '两次输入的密码不一致' }, { status: 400 });
  }

  const authMode = process.env.AUTH_MODE || 'auto';
  const canUseSupabase = authMode !== 'local' && hasSupabaseAuthConfig();

  if (canUseSupabase) {
    const supabase = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL || '',
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY || '',
      {
        auth: {
          autoRefreshToken: false,
          persistSession: false,
        },
      }
    );
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: `${getBaseUrl(request)}/login?verified=1`,
        data: {
          name: displayName || email.split('@')[0],
        },
      },
    });

    if (error) {
      if (!isLocalAuthEnabled()) {
        return NextResponse.json({ error: error.message || '注册失败' }, { status: 400 });
      }
    } else if (data.session && data.user) {
      const user = {
        id: data.user.id,
        email: data.user.email || email,
        name: data.user.user_metadata?.name || data.user.email || email,
        role: data.user.user_metadata?.role === 'admin' ? ('admin' as const) : ('user' as const),
        provider: 'supabase' as const,
      };
      await ensureUserAccount(user);
      const response = NextResponse.json({
        status: 'signed_in',
        message: '注册成功，已登录。',
        user,
      });
      setSessionCookie(response, request, ACCESS_TOKEN_COOKIE, data.session.access_token, data.session.expires_in);
      setSessionCookie(response, request, REFRESH_TOKEN_COOKIE, data.session.refresh_token, MONTH_SECONDS);
      clearCookie(response, LOCAL_SESSION_COOKIE);
      return response;
    } else {
      return NextResponse.json({
        status: 'verification_required',
        provider: 'supabase',
        email,
        delivery: 'email_sent',
        message: '确认邮件已发送，请打开邮箱完成验证后再登录。',
      });
    }
  }

  try {
    const pending = await createLocalRegistration({ email, password, displayName });
    const delivery = await sendVerificationEmail({ to: pending.email, code: pending.code });
    return NextResponse.json({
      status: 'verification_required',
      provider: 'local',
      email: pending.email,
      delivery: delivery.mode === 'smtp' ? 'email_sent' : 'server_log',
      expiresAt: pending.expiresAt,
      message:
        delivery.mode === 'smtp'
          ? '验证码已发送到邮箱，请输入验证码完成注册。'
          : '邮件服务暂未配置，验证码已写入服务器日志。测试阶段可从 WebApp 容器日志查看。',
      debugCode: process.env.AUTH_EXPOSE_LOCAL_CODE === 'true' ? pending.code : undefined,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : '注册失败' },
      { status: 400 }
    );
  }
}
