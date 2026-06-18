import { createClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import {
  ACCESS_TOKEN_COOKIE,
  LOCAL_SESSION_COOKIE,
  REFRESH_TOKEN_COOKIE,
} from '@/lib/auth-cookies';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY;
const supabaseServiceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

export { ACCESS_TOKEN_COOKIE, LOCAL_SESSION_COOKIE, REFRESH_TOKEN_COOKIE };

export type AuthProvider = 'supabase';

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

function requireSupabaseEnv() {
  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('Missing Supabase environment variables');
  }

  return { supabaseUrl, supabaseAnonKey };
}

export function hasSupabaseAuthConfig() {
  return Boolean(supabaseUrl && supabaseAnonKey);
}

export function getAuthModeLabel() {
  return hasSupabaseAuthConfig() ? 'Supabase 登录' : '未配置登录';
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
