import { createHmac, timingSafeEqual } from 'crypto';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { LOCAL_SESSION_COOKIE } from '@/lib/auth-cookies';
import { getLocalUserById } from '@/lib/local-auth-store';

export { ACCESS_TOKEN_COOKIE, LOCAL_SESSION_COOKIE, REFRESH_TOKEN_COOKIE } from '@/lib/auth-cookies';

export type AuthProvider = 'local';

export interface AppUser {
  id: string;
  email: string;
  name: string;
  role: 'user' | 'admin';
  provider: AuthProvider;
}

export interface AppSession {
  provider: AuthProvider;
  accessToken: string;
  user: AppUser;
}

interface LocalSessionPayload {
  sub: string;
  email: string;
  name: string;
  role: 'user' | 'admin';
  iat: number;
  exp: number;
}

function sessionSecret() {
  return (
    process.env.AUTH_SESSION_SECRET ||
    process.env.LOCAL_AUTH_PASSWORD ||
    'ai-holdings-local-auth-development-secret'
  );
}

function base64UrlEncode(value: string) {
  return Buffer.from(value, 'utf8').toString('base64url');
}

function base64UrlDecode(value: string) {
  return Buffer.from(value, 'base64url').toString('utf8');
}

function signPayload(payload: string) {
  return createHmac('sha256', sessionSecret()).update(payload).digest('base64url');
}

function signatureMatches(left: string, right: string) {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer);
}

export function createLocalSessionToken(user: Omit<AppUser, 'provider'>, maxAgeSeconds = 60 * 60 * 24 * 14) {
  const now = Math.floor(Date.now() / 1000);
  const payload: LocalSessionPayload = {
    sub: user.id,
    email: user.email,
    name: user.name,
    role: user.role,
    iat: now,
    exp: now + maxAgeSeconds,
  };
  const encodedPayload = base64UrlEncode(JSON.stringify(payload));
  return `${encodedPayload}.${signPayload(encodedPayload)}`;
}

function parseLocalSessionToken(token: string): LocalSessionPayload | null {
  const [encodedPayload, signature] = token.split('.');
  if (!encodedPayload || !signature) return null;
  if (!signatureMatches(signature, signPayload(encodedPayload))) return null;

  try {
    const payload = JSON.parse(base64UrlDecode(encodedPayload)) as LocalSessionPayload;
    if (!payload.sub || !payload.email || !payload.exp || payload.exp < Math.floor(Date.now() / 1000)) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}

export function getAuthModeLabel() {
  return '管理员分配账号登录';
}

export async function getCurrentSession(): Promise<AppSession | null> {
  const cookieStore = await cookies();
  const token = cookieStore.get(LOCAL_SESSION_COOKIE)?.value;
  if (!token) {
    return null;
  }

  const payload = parseLocalSessionToken(token);
  if (!payload) {
    return null;
  }

  const dbUser = await getLocalUserById(payload.sub).catch(() => null);
  const user = dbUser ?? {
    id: payload.sub,
    email: payload.email,
    name: payload.name,
    role: payload.role,
  };

  return {
    provider: 'local',
    accessToken: token,
    user: {
      ...user,
      provider: 'local',
    },
  };
}

export async function requireUser() {
  const session = await getCurrentSession();
  if (!session) {
    redirect('/login');
  }
  return session;
}

export async function requireAdmin() {
  const session = await requireUser();
  if (session.user.role !== 'admin') {
    redirect('/dashboard');
  }
  return { session };
}
