import { NextRequest, NextResponse } from 'next/server';
import { ACCESS_TOKEN_COOKIE } from '@/lib/auth-cookies';

const PUBLIC_PREFIXES = [
  '/api/auth',
  '/api/hermes',
  '/api/openclaw',
  '/_next',
  '/favicon.svg',
  '/favicon.ico',
  '/robots.txt',
  '/sitemap.xml',
];

const PUBLIC_PATHS = new Set(['/', '/features', '/pricing', '/intro', '/wechat-clawbot', '/login']);

function hasSession(request: NextRequest) {
  return request.cookies.has(ACCESS_TOKEN_COOKIE);
}

function isPublicPath(pathname: string) {
  return PUBLIC_PATHS.has(pathname) || PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

function firstHeaderValue(value: string | null) {
  return value?.split(',')[0]?.trim() || '';
}

function hostnameFromHost(host: string) {
  try {
    return new URL(`http://${host}`).hostname.toLowerCase();
  } catch {
    return host.split(':')[0]?.toLowerCase() || '';
  }
}

function isLoopbackHost(host: string) {
  const hostname = hostnameFromHost(host);
  return ['localhost', '127.0.0.1', '0.0.0.0', '::1'].includes(hostname);
}

function configuredBaseOrigin() {
  const baseUrl = process.env.WEBAPP_BASE_URL;
  if (!baseUrl) return null;

  try {
    return new URL(baseUrl).origin;
  } catch {
    return null;
  }
}

function publicOrigin(request: NextRequest) {
  const forwardedHost = firstHeaderValue(request.headers.get('x-forwarded-host'));
  const host = forwardedHost || request.headers.get('host') || request.nextUrl.host;
  const forwardedProto = firstHeaderValue(request.headers.get('x-forwarded-proto'));
  const proto =
    forwardedProto ||
    (request.headers.get('x-forwarded-ssl') === 'on' ? 'https' : request.nextUrl.protocol.replace(':', ''));

  if (host && !isLoopbackHost(host)) {
    return `${proto || 'https'}://${host}`;
  }

  return configuredBaseOrigin() || request.nextUrl.origin;
}

function publicUrl(request: NextRequest, pathname: string) {
  return new URL(pathname, publicOrigin(request));
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const sessionExists = hasSession(request);
  const isMarketingAuthEntry =
    request.nextUrl.searchParams.get('entry') === 'marketing' ||
    request.nextUrl.searchParams.get('mode') === 'register';

  if (pathname === '/login' && sessionExists && !isMarketingAuthEntry) {
    return NextResponse.redirect(publicUrl(request, '/dashboard'));
  }

  if (!isPublicPath(pathname) && !sessionExists) {
    const loginUrl = publicUrl(request, '/login');
    loginUrl.searchParams.set('next', `${pathname}${search}`);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!.*\\..*).*)'],
};
