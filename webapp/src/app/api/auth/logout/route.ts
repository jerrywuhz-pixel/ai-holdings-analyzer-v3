import { NextResponse } from 'next/server';
import {
  ACCESS_TOKEN_COOKIE,
  LOCAL_SESSION_COOKIE,
  REFRESH_TOKEN_COOKIE,
} from '@/lib/auth-cookies';

export const runtime = 'nodejs';

export async function POST() {
  const response = NextResponse.json({ ok: true });
  for (const name of [ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, LOCAL_SESSION_COOKIE]) {
    response.cookies.set(name, '', {
      httpOnly: true,
      sameSite: 'lax',
      secure: false,
      path: '/',
      maxAge: 0,
    });
  }
  return response;
}
