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

function appUrl(path: string, request: NextRequest) {
  const configuredBaseUrl = process.env.WEBAPP_BASE_URL;
  const forwardedHost = request.headers.get('x-forwarded-host') || request.headers.get('host');
  if (configuredBaseUrl) {
    return new URL(path, configuredBaseUrl);
  }
  if (forwardedHost) {
    const forwardedProto =
      request.headers.get('x-forwarded-proto') || request.nextUrl.protocol.replace(':', '') || 'http';
    return new URL(path, `${forwardedProto}://${forwardedHost}`);
  }
  return new URL(path, request.url);
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const sessionExists = hasSession(request);

  if (pathname === '/login' && sessionExists) {
    return NextResponse.redirect(appUrl('/', request));
  }

  if (!isPublicPath(pathname) && !sessionExists) {
    const loginUrl = appUrl('/login', request);
    loginUrl.searchParams.set('next', `${pathname}${search}`);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!.*\\..*).*)'],
};
