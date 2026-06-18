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

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const email = String(body?.email || '').trim();
  const code = String(body?.code || '').trim();

  if (!email || !code) {
    authAudit('verify_rejected', { email, request, level: 'warn', reason: 'missing_email_or_code' });
    return NextResponse.json({ error: '请输入邮箱和验证码' }, { status: 400 });
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
  const { data, error } = await supabase.auth.verifyOtp({
    email,
    token: code,
    type: 'signup',
  });

  if (error || !data.session || !data.user) {
    authAudit('verify_failed', {
      email,
      request,
      level: 'warn',
      provider: 'supabase',
      reason: error?.message || 'invalid_or_expired_code',
    });
    return NextResponse.json({ error: error?.message || '邮箱验证码不正确或已过期' }, { status: 400 });
  }

  const user = {
    id: data.user.id,
    email: data.user.email || email,
    name: data.user.user_metadata?.name || data.user.email || email,
    role: data.user.user_metadata?.role === 'admin' ? ('admin' as const) : ('user' as const),
    provider: 'supabase' as const,
  };
  await ensureUserAccount(user);
  authAudit('verify_succeeded', { email, request, provider: 'supabase' });
  const response = NextResponse.json({
    status: 'signed_in',
    user,
  });
  setSessionCookie(response, request, ACCESS_TOKEN_COOKIE, data.session.access_token, data.session.expires_in);
  setSessionCookie(response, request, REFRESH_TOKEN_COOKIE, data.session.refresh_token, MONTH_SECONDS);
  clearCookie(response, LOCAL_SESSION_COOKIE);
  return response;
}
