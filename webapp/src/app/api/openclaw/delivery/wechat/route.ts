import crypto from 'crypto';
import { NextRequest, NextResponse } from 'next/server';
import postgres from 'postgres';
import { decryptCredential, sendClawbotTextMessage } from '@/lib/clawbot';

export const runtime = 'nodejs';

declare global {
  // eslint-disable-next-line no-var
  var __aiHoldingsOpenClawDeliverySql: ReturnType<typeof postgres> | undefined;
}

interface DeliveryPayload {
  delivery_id?: string;
  tenant_id?: string;
  recipient?: {
    channel_binding_id?: string | null;
    openclaw_account_id?: string | null;
    target_conversation?: string | null;
    context_token?: string | null;
  };
  message?: {
    content_type?: string | null;
    content?: unknown;
  };
}

function databaseUrl() {
  return process.env.WEBAPP_DATABASE_URL || process.env.DATABASE_URL || '';
}

function sqlClient() {
  const url = databaseUrl();
  if (!url) {
    throw new Error('OpenClaw 微信发送需要配置 DATABASE_URL 或 WEBAPP_DATABASE_URL');
  }

  if (!globalThis.__aiHoldingsOpenClawDeliverySql) {
    globalThis.__aiHoldingsOpenClawDeliverySql = postgres(url, {
      max: 4,
      idle_timeout: 20,
      connect_timeout: 10,
      prepare: false,
    });
  }

  return globalThis.__aiHoldingsOpenClawDeliverySql;
}

function jsonError(message: string, status = 400) {
  return NextResponse.json({ ok: false, error: message }, { status });
}

function safeEqual(left: string, right: string) {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  if (leftBuffer.length !== rightBuffer.length) {
    return false;
  }
  return crypto.timingSafeEqual(leftBuffer, rightBuffer);
}

function verifyDeliverySignature(request: NextRequest, rawBody: string) {
  const secret = process.env.OPENCLAW_DELIVERY_WEBHOOK_SECRET || '';
  if (!secret) {
    throw new Error('OPENCLAW_DELIVERY_WEBHOOK_SECRET is required');
  }

  const timestamp = request.headers.get('x-openclaw-delivery-timestamp') || '';
  const signature = request.headers.get('x-openclaw-delivery-signature') || '';
  if (!timestamp || !signature.startsWith('v1=')) {
    return false;
  }

  const timestampMs = Number(timestamp) * 1000;
  if (!Number.isFinite(timestampMs) || Math.abs(Date.now() - timestampMs) > 5 * 60 * 1000) {
    return false;
  }

  const expected = `v1=${crypto
    .createHmac('sha256', secret)
    .update(`${timestamp}.${rawBody}`)
    .digest('hex')}`;
  return safeEqual(signature, expected);
}

function contentText(payload: DeliveryPayload) {
  const content = payload.message?.content;
  if (typeof content === 'string') {
    return content.trim();
  }
  if (!content || typeof content !== 'object' || Array.isArray(content)) {
    return '';
  }

  const record = content as Record<string, unknown>;
  if (typeof record.text === 'string' && record.text.trim()) {
    return record.text.trim();
  }

  if (payload.message?.content_type === 'confirmation_card') {
    return [
      typeof record.title === 'string' ? record.title : '',
      typeof record.body === 'string' ? record.body : '',
      typeof record.risk_note === 'string' ? record.risk_note : '',
      typeof record.command_hint === 'string' ? `确认：${record.command_hint}` : '',
      typeof record.reject_hint === 'string' ? `取消：${record.reject_hint}` : '',
      typeof record.deep_link === 'string' ? `确认页面：${record.deep_link}` : '',
      typeof record.expires_at === 'string' ? `有效期至：${record.expires_at}` : '',
    ]
      .filter(Boolean)
      .join('\n');
  }

  return JSON.stringify(record);
}

async function loadWechatRoute(payload: DeliveryPayload) {
  const tenantId = String(payload.tenant_id || '').trim();
  const channelBindingId = String(payload.recipient?.channel_binding_id || '').trim();
  const openclawAccountId = String(payload.recipient?.openclaw_account_id || '').trim();
  if (!tenantId) {
    throw new Error('缺少 tenant_id');
  }

  const sql = sqlClient();
  const rows = await sql<Record<string, any>[]>`
    SELECT
      cb.id AS channel_binding_id,
      cb.openclaw_account_id,
      cb.channel_user_ref,
      cb.binding_metadata,
      wc.bot_token_ciphertext,
      wc.base_url
    FROM public.channel_bindings cb
    JOIN public.wechat_bot_credentials wc
      ON wc.tenant_id = cb.tenant_id
     AND wc.credential_status = 'active'
    WHERE cb.tenant_id::text = ${tenantId}
      AND cb.channel = 'openclaw_wechat'
      AND cb.binding_status = 'active'
      AND (
        ${channelBindingId} = ''
        OR cb.id::text = ${channelBindingId}
      )
      AND (
        ${openclawAccountId} = ''
        OR cb.openclaw_account_id = ${openclawAccountId}
      )
    ORDER BY cb.is_primary DESC, cb.updated_at DESC
    LIMIT 1
  `;

  if (!rows[0]) {
    throw new Error('未找到可用的微信 ClawBot 绑定或 bot token');
  }
  return rows[0];
}

export async function POST(request: NextRequest) {
  const rawBody = await request.text();
  let payload: DeliveryPayload;
  try {
    if (!verifyDeliverySignature(request, rawBody)) {
      return jsonError('invalid delivery signature', 401);
    }
    payload = JSON.parse(rawBody) as DeliveryPayload;
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : 'invalid delivery payload', 400);
  }

  try {
    const route = await loadWechatRoute(payload);
    const botToken = decryptCredential(route.bot_token_ciphertext);
    const bindingMetadata =
      route.binding_metadata && typeof route.binding_metadata === 'object' ? route.binding_metadata : {};
    const toUserId =
      String(route.channel_user_ref || '').trim() ||
      String(payload.recipient?.target_conversation || '').trim();
    const contextToken =
      String(payload.recipient?.context_token || '').trim() ||
      String(bindingMetadata.context_token || '').trim();
    const text = contentText(payload);

    if (!toUserId) {
      return jsonError('missing WeChat recipient user id', 422);
    }
    if (!contextToken) {
      return jsonError('missing WeChat context token', 422);
    }
    if (!text) {
      return jsonError('missing delivery message text', 422);
    }

    const result = await sendClawbotTextMessage({
      baseUrl: route.base_url,
      botToken,
      toUserId,
      contextToken,
      text,
    });

    return NextResponse.json({
      ok: true,
      delivery_id: payload.delivery_id,
      channel_binding_id: route.channel_binding_id,
      provider_message_id: result.providerMessageId || null,
    });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : '微信消息发送失败', 502);
  }
}
