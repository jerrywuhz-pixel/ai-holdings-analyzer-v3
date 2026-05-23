import { createClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { createHmac, timingSafeEqual } from 'crypto';
import {
  ACCESS_TOKEN_COOKIE,
  LOCAL_SESSION_COOKIE,
  REFRESH_TOKEN_COOKIE,
} from '@/lib/auth-cookies';
import { validateLocalDbCredentials } from '@/lib/local-auth-store';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY;
const supabaseServiceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

export { ACCESS_TOKEN_COOKIE, LOCAL_SESSION_COOKIE, REFRESH_TOKEN_COOKIE };

export type AuthProvider = 'supabase' | 'local';

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
  supabase: any;
}

interface LocalSessionPayload {
  sub: string;
  email: string;
  name: string;
  role: 'user' | 'admin';
  provider: 'local';
  iat: number;
  exp: number;
}

function requireSupabaseEnv() {
  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('Missing Supabase environment variables');
  }

  return { supabaseUrl, supabaseAnonKey };
}

export function hasSupabaseAuthConfig() {
  return Boolean(supabaseUrl && supabaseAnonKey);
}

export function isLocalAuthEnabled() {
  const mode = process.env.AUTH_MODE || 'auto';
  if (mode === 'local') {
    return true;
  }
  if (mode === 'supabase') {
    return false;
  }
  return process.env.LOCAL_AUTH_ENABLED !== 'false';
}

export function getAuthModeLabel() {
  if (hasSupabaseAuthConfig()) {
    return isLocalAuthEnabled() ? 'Supabase / 本地备用登录' : 'Supabase 登录';
  }
  return '本地登录';
}

function base64UrlEncode(input: string) {
  return Buffer.from(input, 'utf8').toString('base64url');
}

function base64UrlDecode(input: string) {
  return Buffer.from(input, 'base64url').toString('utf8');
}

function getLocalAuthSecret() {
  return (
    process.env.AUTH_SESSION_SECRET ||
    process.env.LOCAL_AUTH_PASSWORD ||
    'ai-holdings-local-auth-development-secret'
  );
}

function signPayload(payload: string) {
  return createHmac('sha256', getLocalAuthSecret()).update(payload).digest('base64url');
}

function safeEqual(left: string, right: string) {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  if (leftBuffer.length !== rightBuffer.length) {
    return false;
  }
  return timingSafeEqual(leftBuffer, rightBuffer);
}

export function createLocalSessionToken(user: Omit<AppUser, 'provider'>, maxAgeSeconds = 60 * 60 * 24 * 7) {
  const now = Math.floor(Date.now() / 1000);
  const payload: LocalSessionPayload = {
    sub: user.id,
    email: user.email,
    name: user.name,
    role: user.role,
    provider: 'local',
    iat: now,
    exp: now + maxAgeSeconds,
  };
  const encodedPayload = base64UrlEncode(JSON.stringify(payload));
  return `${encodedPayload}.${signPayload(encodedPayload)}`;
}

export function verifyLocalSessionToken(token: string): AppUser | null {
  const [encodedPayload, signature] = token.split('.');
  if (!encodedPayload || !signature) {
    return null;
  }
  if (!safeEqual(signature, signPayload(encodedPayload))) {
    return null;
  }

  try {
    const payload = JSON.parse(base64UrlDecode(encodedPayload)) as LocalSessionPayload;
    if (payload.provider !== 'local' || payload.exp < Math.floor(Date.now() / 1000)) {
      return null;
    }
    return {
      id: payload.sub,
      email: payload.email,
      name: payload.name,
      role: payload.role,
      provider: 'local',
    };
  } catch {
    return null;
  }
}

export function getConfiguredLocalUser(): Omit<AppUser, 'provider'> | null {
  const email = process.env.LOCAL_AUTH_EMAIL || 'admin@ai-holdings.local';
  const password = process.env.LOCAL_AUTH_PASSWORD;
  if (!isLocalAuthEnabled() || !password) {
    return null;
  }

  return {
    id: process.env.LOCAL_AUTH_USER_ID || '00000000-0000-0000-0000-000000000000',
    email,
    name: process.env.LOCAL_AUTH_DISPLAY_NAME || '本地管理员',
    role: process.env.LOCAL_AUTH_ROLE === 'user' ? 'user' : 'admin',
  };
}

export async function validateLocalCredentials(email: string, password: string) {
  const localUser = getConfiguredLocalUser();
  const expectedPassword = process.env.LOCAL_AUTH_PASSWORD || '';
  if (localUser && email.trim().toLowerCase() === localUser.email.toLowerCase()) {
    if (safeEqual(password, expectedPassword)) {
      return localUser;
    }
    return null;
  }

  return validateLocalDbCredentials(email, password);
}

function createEmptyQueryResult(single = false) {
  return { data: single ? null : [], error: null };
}

function createLocalQueryBuilder(): any {
  const builder: Record<string, unknown> = {
    select: () => builder,
    eq: () => builder,
    neq: () => builder,
    gt: () => builder,
    gte: () => builder,
    lt: () => builder,
    lte: () => builder,
    order: () => builder,
    limit: () => builder,
    range: () => builder,
    in: () => builder,
    is: () => builder,
    maybeSingle: async () => createEmptyQueryResult(true),
    single: async () => createEmptyQueryResult(true),
    insert: async () => createEmptyQueryResult(),
    update: () => builder,
    delete: () => builder,
    upsert: async () => createEmptyQueryResult(),
    then: (onFulfilled?: any, onRejected?: any) =>
      Promise.resolve(createEmptyQueryResult()).then(onFulfilled, onRejected),
  };
  return builder;
}

function createLocalDataClient(): any {
  return {
    from: () => createLocalQueryBuilder(),
  };
}

export function createTenantClient(accessToken: string) {
  const env = requireSupabaseEnv();
  return createClient(env.supabaseUrl, env.supabaseAnonKey, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
    },
    global: {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    },
  });
}

export function createAdminClient() {
  const env = requireSupabaseEnv();
  if (!supabaseServiceRoleKey) {
    throw new Error('Missing SUPABASE_SERVICE_ROLE_KEY');
  }

  return createClient(env.supabaseUrl, supabaseServiceRoleKey, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
    },
  });
}

export async function getCurrentSession(): Promise<AppSession | null> {
  const cookieStore = await cookies();
  const localToken = cookieStore.get(LOCAL_SESSION_COOKIE)?.value;
  if (localToken) {
    const user = verifyLocalSessionToken(localToken);
    if (user) {
      return {
        provider: 'local' as const,
        accessToken: localToken,
        user,
        supabase: createLocalDataClient(),
      };
    }
  }

  const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken || !hasSupabaseAuthConfig()) {
    return null;
  }

  const supabase = createTenantClient(accessToken);
  const { data, error } = await supabase.auth.getUser(accessToken);
  if (error || !data.user) {
    return null;
  }

  const appUser: AppUser = {
    id: data.user.id,
    email: data.user.email || '',
    name:
      String(data.user.user_metadata?.name || data.user.user_metadata?.full_name || '') ||
      data.user.email ||
      '已登录用户',
    role: data.user.user_metadata?.role === 'admin' ? 'admin' : 'user',
    provider: 'supabase',
  };

  return { provider: 'supabase' as const, accessToken, user: appUser, supabase };
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
  if (session.provider === 'local') {
    if (session.user.role !== 'admin') {
      redirect('/dashboard');
    }
    return { session, supabaseAdmin: createLocalDataClient() };
  }

  const { data, error } = await session.supabase
    .from('users')
    .select('role')
    .eq('id', session.user.id)
    .maybeSingle();

  if (error || data?.role !== 'admin') {
    redirect('/dashboard');
  }

  return { session, supabaseAdmin: createAdminClient() };
}
