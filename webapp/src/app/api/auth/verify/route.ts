import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { ensureUserAccount } from '@/lib/account-store';
import {
  ACCESS_TOKEN_COOKIE,
  LOCAL_SESSION_COOKIE,
  REFRESH_TOKEN_COOKIE,
  createLocalSessionToken,
  hasSupabaseAuthConfig,
} from '@/lib/supabase';
import { verifyLocalRegistration } from '@/lib/local-auth-store';

export const runtime = 'nodejs';

const WEEK_SECONDS = 60 * 60 * 24 * 7;
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

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const email = String(body?.email || '').trim();
  const code = String(body?.code || '').trim();

  if (!email || !code) {
    return NextResponse.json({ error: '请输入邮箱和验证码' }, { status: 400 });
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
    const { data, error } = await supabase.auth.verifyOtp({
      email,
      token: code,
      type: 'signup',
    });
    if (!error && data.session && data.user) {
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
        user,
      });
      setSessionCookie(response, request, ACCESS_TOKEN_COOKIE, data.session.access_token, data.session.expires_in);
      setSessionCookie(response, request, REFRESH_TOKEN_COOKIE, data.session.refresh_token, MONTH_SECONDS);
      clearCookie(response, LOCAL_SESSION_COOKIE);
      return response;
    }
    return NextResponse.json(
      { error: error?.message || '邮箱验证码不正确或已过期' },
      { status: 400 }
    );
  }

  try {
    const user = await verifyLocalRegistration({ email, code });
    await ensureUserAccount({ ...user, provider: 'local' });
    const response = NextResponse.json({
      status: 'signed_in',
      user: {
        ...user,
        provider: 'local',
      },
    });
    setSessionCookie(response, request, LOCAL_SESSION_COOKIE, createLocalSessionToken(user, WEEK_SECONDS), WEEK_SECONDS);
    clearCookie(response, ACCESS_TOKEN_COOKIE);
    clearCookie(response, REFRESH_TOKEN_COOKIE);
    return response;
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : '邮箱验证码不正确或已过期' },
      { status: 400 }
    );
  }
}
