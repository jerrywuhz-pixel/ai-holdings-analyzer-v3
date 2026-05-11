import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

function requireSupabaseEnv() {
  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('Missing Supabase environment variables');
  }

  return { supabaseUrl, supabaseAnonKey };
}

export const ACCESS_TOKEN_COOKIE = 'ai_holdings_access_token';
export const REFRESH_TOKEN_COOKIE = 'ai_holdings_refresh_token';

export function createBrowserClient() {
  const env = requireSupabaseEnv();
  return createClient(env.supabaseUrl, env.supabaseAnonKey);
}
