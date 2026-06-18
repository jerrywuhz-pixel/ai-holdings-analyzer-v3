import { NextRequest, NextResponse } from 'next/server';
import { routeWechatClawbotMessageFromAdapter } from '@/lib/wechat-clawbot-bridge';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function authorized(request: NextRequest) {
  const secret =
    process.env.HERMES_WECHAT_ROUTE_ADAPTER_SECRET ||
    process.env.HERMES_CRON_SECRET ||
    process.env.WECHAT_CLAWBOT_BRIDGE_SECRET ||
    process.env.OPENCLAW_WEIXIN_ROUTE_ADAPTER_SECRET ||
    process.env.OPENCLAW_CRON_SECRET ||
    '';
  if (!secret) return false;
  return request.headers.get('authorization') === `Bearer ${secret}`;
}

export async function POST(request: NextRequest) {
  if (!authorized(request)) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  try {
    const result = await routeWechatClawbotMessageFromAdapter(payload as any);
    return NextResponse.json({ ok: true, runtime: 'hermes', ...result });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : '微信路由适配失败' },
      { status: 500 }
    );
  }
}
