import { NextRequest, NextResponse } from 'next/server';
import { pollWechatClawbotMessages } from '@/lib/wechat-clawbot-bridge';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function authorized(request: NextRequest) {
  const secret = process.env.HERMES_CRON_SECRET || process.env.OPENCLAW_CRON_SECRET || process.env.WECHAT_CLAWBOT_BRIDGE_SECRET || '';
  if (!secret) return false;
  return request.headers.get('authorization') === `Bearer ${secret}`;
}

export async function POST(request: NextRequest) {
  if (!authorized(request)) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  try {
    const result = await pollWechatClawbotMessages();
    return NextResponse.json({ ok: true, runtime: 'hermes', legacy_alias: '/api/openclaw/wechat/poll', ...result });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : '微信消息轮询失败' },
      { status: 500 }
    );
  }
}
