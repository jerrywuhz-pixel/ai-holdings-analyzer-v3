import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import {
  hasSupabaseAuthConfig,
  isLocalAuthEnabled,
} from '@/lib/supabase';
import { resendLocalRegistrationCode } from '@/lib/local-auth-store';
import { sendVerificationEmail } from '@/lib/email';

export const runtime = 'nodejs';

function getBaseUrl(request: NextRequest) {
  return process.env.WEBAPP_BASE_URL || request.nextUrl.origin;
}

function verificationResponse({
  provider,
  email,
  delivery,
  expiresAt,
  message,
  debugCode,
}: {
  provider: 'supabase' | 'local';
  email: string;
  delivery: 'email_sent' | 'server_log';
  expiresAt?: string;
  message: string;
  debugCode?: string;
}) {
  return NextResponse.json({
    status: 'verification_required',
    provider,
    email,
    delivery,
    expiresAt,
    message,
    debugCode,
  });
}

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const email = String(body?.email || '').trim();

  if (!email) {
    return NextResponse.json({ error: '请输入邮箱' }, { status: 400 });
  }

  const authMode = process.env.AUTH_MODE || 'auto';
  const canUseSupabase = authMode !== 'local' && hasSupabaseAuthConfig();

  if (canUseSupabase) {
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

    if (!error) {
      return verificationResponse({
        provider: 'supabase',
        email,
        delivery: 'email_sent',
        message: '确认邮件已重新发送，请打开邮箱完成验证后再登录。',
      });
    }

    if (!isLocalAuthEnabled()) {
      return NextResponse.json({ error: error.message || '重新发送失败' }, { status: 400 });
    }
  }

  try {
    const pending = await resendLocalRegistrationCode(email);
    const delivery = await sendVerificationEmail({ to: pending.email, code: pending.code });
    return verificationResponse({
      provider: 'local',
      email: pending.email,
      delivery: delivery.mode === 'smtp' ? 'email_sent' : 'server_log',
      expiresAt: pending.expiresAt,
      message:
        delivery.mode === 'smtp'
          ? '验证码已重新发送到邮箱，请输入验证码完成注册。'
          : '邮件服务暂未配置，验证码已写入服务器日志。测试阶段可从 WebApp 容器日志查看。',
      debugCode: process.env.AUTH_EXPOSE_LOCAL_CODE === 'true' ? pending.code : undefined,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : '重新发送失败' },
      { status: 400 }
    );
  }
}
