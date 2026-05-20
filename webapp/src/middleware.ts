import { NextRequest, NextResponse } from 'next/server';
import { ACCESS_TOKEN_COOKIE, LOCAL_SESSION_COOKIE } from '@/lib/auth-cookies';

const PUBLIC_PREFIXES = [
  '/api/auth',
  '/_next',
  '/favicon.svg',
  '/favicon.ico',
  '/robots.txt',
  '/sitemap.xml',
];

function hasSession(request: NextRequest) {
  return (
    request.cookies.has(LOCAL_SESSION_COOKIE) ||
    request.cookies.has(ACCESS_TOKEN_COOKIE)
  );
}

function isPublicPath(pathname: string) {
  return pathname === '/login' || PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const sessionExists = hasSession(request);

  if (pathname === '/login' && sessionExists) {
    return NextResponse.redirect(new URL('/', request.url));
  }

  if (!isPublicPath(pathname) && !sessionExists) {
    const loginUrl = new URL('/login', request.url);
    loginUrl.searchParams.set('next', `${pathname}${search}`);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!.*\\..*).*)'],
};
