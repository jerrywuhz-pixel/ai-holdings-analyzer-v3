import { createClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
const supabaseServiceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

export const ACCESS_TOKEN_COOKIE = 'ai_holdings_access_token';
export const REFRESH_TOKEN_COOKIE = 'ai_holdings_refresh_token';

function requireSupabaseEnv() {
  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('Missing Supabase environment variables');
  }

  return { supabaseUrl, supabaseAnonKey };
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

export async function getCurrentSession() {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) {
    return null;
  }

  const supabase = createTenantClient(accessToken);
  const { data, error } = await supabase.auth.getUser(accessToken);
  if (error || !data.user) {
    return null;
  }

  return { accessToken, user: data.user, supabase };
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
    redirect('/');
  }

  return { session, supabaseAdmin: createAdminClient() };
}
