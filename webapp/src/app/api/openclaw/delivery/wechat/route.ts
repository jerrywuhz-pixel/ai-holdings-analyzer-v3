import crypto from 'crypto';
import { NextRequest, NextResponse } from 'next/server';
import { deliverWechatOutboxMessage, type DeliveryPayload } from '@/lib/wechat-clawbot-bridge';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const BLOCKED_WECHAT_DELIVERY_CONTENT_TYPES = new Set([
  'confirmation_card',
  'task_update',
  'system',
  'system_message',
]);

async function readBody(request: NextRequest) {
  const text = await request.text();
  const payload = text ? JSON.parse(text) : {};
  return { text, payload };
}

function signatureMatches(secret: string, timestamp: string, body: string, signature: string) {
  const expected = crypto
    .createHmac('sha256', secret)
    .update(`${timestamp}.${body}`)
    .digest('hex');
  const actual = signature.replace(/^v1=/, '');
  return crypto.timingSafeEqual(Buffer.from(actual), Buffer.from(expected));
}

function authorized(request: NextRequest, body: string) {
  const secret = process.env.HERMES_DELIVERY_WEBHOOK_SECRET || process.env.OPENCLAW_DELIVERY_WEBHOOK_SECRET || '';
  if (!secret) return false;

  const legacySecret = request.headers.get('x-openclaw-delivery-secret');
  if (legacySecret && legacySecret === secret) return true;

  const hermesSecret = request.headers.get('x-hermes-delivery-secret');
  if (hermesSecret && hermesSecret === secret) return true;

  const timestamp =
    request.headers.get('x-hermes-delivery-timestamp') ||
    request.headers.get('x-openclaw-delivery-timestamp') ||
    '';
  const signature =
    request.headers.get('x-hermes-delivery-signature') ||
    request.headers.get('x-openclaw-delivery-signature') ||
    '';
  if (!timestamp || !signature) return false;

  try {
    return signatureMatches(secret, timestamp, body, signature);
  } catch {
    return false;
  }
}

export async function POST(request: NextRequest) {
  let parsed: { text: string; payload: DeliveryPayload };
  try {
    parsed = await readBody(request);
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  if (!authorized(request, parsed.text)) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  try {
    const contentType = String(parsed.payload?.message?.content_type || '').trim().toLowerCase();
    if (contentType && BLOCKED_WECHAT_DELIVERY_CONTENT_TYPES.has(contentType)) {
      return NextResponse.json({
        ok: false,
        dropped: true,
        reason: `已过滤微信不下发消息类型：${contentType}`,
      });
    }

    const result = await deliverWechatOutboxMessage(parsed.payload);
    return NextResponse.json({ runtime: 'hermes', legacy_alias: '/api/openclaw/delivery/wechat', ...result });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : '微信投递失败' },
      { status: 500 }
    );
  }
}
