import { NextRequest, NextResponse } from 'next/server';
import { AUTH_COOKIE_NAMES, LOCAL_SESSION_COOKIE } from '@/lib/auth-cookies';
import { validateLocalDbCredentials } from '@/lib/local-auth-store';
import { createLocalSessionToken } from '@/lib/supabase';

export const runtime = 'nodejs';

const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14;

function secureCookie(request: NextRequest) {
  return request.nextUrl.protocol === 'https:' || process.env.AUTH_COOKIE_SECURE === 'true';
}

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const loginName = String(body?.loginName || body?.email || '').trim();
  const password = String(body?.password || '');

  if (!loginName || !password) {
    return NextResponse.json({ error: '请输入管理员分配的登录名和密码' }, { status: 400 });
  }

  const user = await validateLocalDbCredentials(loginName, password);
  if (!user) {
    return NextResponse.json({ error: '账号不存在或密码错误，请联系管理员分配试用账号' }, { status: 401 });
  }

  const response = NextResponse.json({
    user: { ...user, provider: 'local' },
  });
  for (const name of AUTH_COOKIE_NAMES) {
    response.cookies.set(name, '', {
      httpOnly: true,
      sameSite: 'lax',
      secure: false,
      path: '/',
      maxAge: 0,
    });
  }
  response.cookies.set(LOCAL_SESSION_COOKIE, createLocalSessionToken(user, SESSION_MAX_AGE_SECONDS), {
    httpOnly: true,
    sameSite: 'lax',
    secure: secureCookie(request),
    path: '/',
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  return response;
}
