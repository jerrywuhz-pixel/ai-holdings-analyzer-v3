import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { hasSupabaseAuthConfig } from '@/lib/supabase';
import { authAudit } from '@/lib/auth-audit';

export const runtime = 'nodejs';

function getBaseUrl(request: NextRequest) {
  return process.env.WEBAPP_BASE_URL || request.nextUrl.origin;
}

function verificationResponse({
  provider,
  email,
  delivery,
  message,
}: {
  provider: 'supabase';
  email: string;
  delivery: 'email_sent' | 'server_log';
  message: string;
}) {
  return NextResponse.json({
    status: 'verification_required',
    provider,
    email,
    delivery,
    message,
  });
}

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const email = String(body?.email || '').trim();

  if (!email) {
    authAudit('resend_verification_rejected', { request, level: 'warn', reason: 'missing_email' });
    return NextResponse.json({ error: '请输入邮箱' }, { status: 400 });
  }

  if (!hasSupabaseAuthConfig()) {
    return NextResponse.json({ error: '未配置 Supabase 登录环境，请先补齐登录环境变量' }, { status: 500 });
  }

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL || '',
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY || '',
    {
      auth: {
        autoRefreshToken: false,
        persistSession: false,
      },
    }
  );

  const { error } = await supabase.auth.resend({
    type: 'signup',
    email,
    options: {
      emailRedirectTo: `${getBaseUrl(request)}/login?verified=1`,
    },
  });

  if (error) {
    authAudit('resend_verification_failed', {
      email,
      request,
      level: 'warn',
      provider: 'supabase',
      reason: error.message || 'resend_error',
    });
    return NextResponse.json({ error: error.message || '重新发送失败' }, { status: 400 });
  }

  authAudit('resend_verification_succeeded', {
    email,
    request,
    provider: 'supabase',
    delivery: 'email_sent',
  });
  return verificationResponse({
    provider: 'supabase',
    email,
    delivery: 'email_sent',
    message: '确认邮件已重新发送，请打开邮箱完成验证后再登录。',
  });
}
