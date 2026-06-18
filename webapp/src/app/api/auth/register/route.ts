import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { ensureUserAccount } from '@/lib/account-store';
import { ACCESS_TOKEN_COOKIE, LOCAL_SESSION_COOKIE, REFRESH_TOKEN_COOKIE, hasSupabaseAuthConfig } from '@/lib/supabase';
import { authAudit } from '@/lib/auth-audit';

export const runtime = 'nodejs';

const MONTH_SECONDS = 60 * 60 * 24 * 30;

function secureCookie(request: NextRequest) {
  return request.nextUrl.protocol === 'https:' || process.env.AUTH_COOKIE_SECURE === 'true';
}

function setSessionCookie(response: NextResponse, request: NextRequest, name: string, value: string, maxAge: number) {
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
    authAudit('register_rejected', { email, request, level: 'warn', reason: 'missing_email_or_password' });
    return NextResponse.json({ error: '请输入邮箱和密码' }, { status: 400 });
  }
  if (password.length < 8) {
    authAudit('register_rejected', { email, request, level: 'warn', reason: 'weak_password' });
    return NextResponse.json({ error: '密码至少需要 8 位' }, { status: 400 });
  }
  if (confirmPassword && confirmPassword !== password) {
    authAudit('register_rejected', { email, request, level: 'warn', reason: 'password_mismatch' });
    return NextResponse.json({ error: '两次输入的密码不一致' }, { status: 400 });
  }

  if (!hasSupabaseAuthConfig()) {
    return NextResponse.json({ error: '未配置 Supabase 登录环境，请先补齐登录环境变量' }, { status: 500 });
  }

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
    authAudit('register_failed', {
      email,
      request,
      level: 'warn',
      provider: 'supabase',
      reason: error.message || 'supabase_signup_error',
    });
    return NextResponse.json({ error: error.message || '注册失败' }, { status: 400 });
  }

  if (data.session && data.user) {
    const user = {
      id: data.user.id,
      email: data.user.email || email,
      name: data.user.user_metadata?.name || data.user.email || email,
      role: data.user.user_metadata?.role === 'admin' ? ('admin' as const) : ('user' as const),
      provider: 'supabase' as const,
    };
    await ensureUserAccount(user);
    authAudit('register_succeeded', { email, request, provider: 'supabase', mode: 'signed_in' });
    const response = NextResponse.json({
      status: 'signed_in',
      message: '注册成功，已登录。',
      user,
    });
    setSessionCookie(response, request, ACCESS_TOKEN_COOKIE, data.session.access_token, data.session.expires_in);
    setSessionCookie(response, request, REFRESH_TOKEN_COOKIE, data.session.refresh_token, MONTH_SECONDS);
    clearCookie(response, LOCAL_SESSION_COOKIE);
    return response;
  }

  authAudit('register_verification_required', {
    email,
    request,
    provider: 'supabase',
    delivery: 'email_sent',
  });
  return NextResponse.json({
    status: 'verification_required',
    provider: 'supabase',
    email,
    delivery: 'email_sent',
    message: '确认邮件已发送，请打开邮箱完成验证后再登录。',
  });
}
