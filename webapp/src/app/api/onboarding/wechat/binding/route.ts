import { NextRequest, NextResponse } from 'next/server';
import {
  refreshWechatBindingStatus,
  startWechatBindingSession,
  verifyWechatBindingConversation,
} from '@/lib/wechat-binding';
import { requireUser } from '@/lib/supabase';

export const runtime = 'nodejs';

function jsonError(error: unknown, status = 400) {
  const message = error instanceof Error ? error.message : '微信 Claw 绑定操作失败';
  if (message.includes('已绑定到其他账号')) {
    status = 409;
  }
  return NextResponse.json(
    { error: message },
    { status }
  );
}

export async function POST(request: NextRequest) {
  const { user } = await requireUser();
  const body = await request.json().catch(() => ({}));
  const action = String(body?.action || 'start');
  const authSessionId = String(body?.authSessionId || '').trim();
  const verifyCode = String(body?.verifyCode || '').trim();

  try {
    if (action === 'start') {
      const result = await startWechatBindingSession(user);
      return NextResponse.json({ status: 'qr_pending', ...result });
    }

    if (!authSessionId) {
      return jsonError(new Error('缺少微信绑定会话 ID'));
    }

    if (action === 'refresh') {
      const result = await refreshWechatBindingStatus(user, authSessionId, { verifyCode });
      return NextResponse.json({ status: result.binding ? 'bound' : 'pending', ...result });
    }

    if (action === 'verify') {
      const result = await verifyWechatBindingConversation(user, authSessionId);
      return NextResponse.json({ status: result.binding ? 'bound' : 'pending', ...result });
    }

    return jsonError(new Error(`不支持的微信绑定操作: ${action}`));
  } catch (error) {
    return jsonError(error);
  }
}
