import { createClient } from '@supabase/supabase-js';
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE } from '@/lib/auth-cookies';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

function requireSupabaseEnv() {
  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('Missing Supabase environment variables');
  }

  return { supabaseUrl, supabaseAnonKey };
}

export function createBrowserClient() {
  const env = requireSupabaseEnv();
  return createClient(env.supabaseUrl, env.supabaseAnonKey);
}

export { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE };
