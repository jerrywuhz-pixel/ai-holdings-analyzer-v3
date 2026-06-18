import crypto from 'crypto';
import postgres from 'postgres';
import {
  decryptCredential,
  downloadClawbotCdnMedia,
  requestClawbotSendTyping,
  requestClawbotSendTextMessage,
  requestClawbotUpdates,
} from '@/lib/clawbot';
import { extractClawbotImagePayload } from '@/lib/clawbot-message-media';
import type { ClawbotCdnMediaPayload } from '@/lib/clawbot-message-media';
import { extractClawbotUserText } from '@/lib/clawbot-message-text';
import { ensureOnboardingSchema } from '@/lib/onboarding';
import {
  buildWechatBindingInitializationMessage,
  parseWechatSelfIntroduction,
  shouldCaptureWechatSelfIntroduction,
  shouldDeliverWechatOnboardingInitialization,
  wechatOnboardingInitializationMetadata,
  wechatSelfIntroductionMetadata,
} from '@/lib/wechat-onboarding-init';

declare global {
  // eslint-disable-next-line no-var
  var __aiHoldingsWechatBridgeSql: ReturnType<typeof postgres> | undefined;
}

type BridgeCredentialRow = {
  credential_id: string;
  tenant_id: string;
  bot_token_ciphertext: string;
  base_url: string;
  get_updates_buf: string | null;
  channel_binding_id: string;
  channel_account_id: string | null;
  openclaw_account_id: string;
  channel_user_ref: string | null;
  session_space: string | null;
  binding_metadata: Record<string, unknown> | null;
};

type ClawbotBridgeMessage = {
  id: string;
  fromUserId: string;
  toUserId: string | null;
  contextToken: string;
  type: 'text' | 'image' | 'voice';
  text?: string | null;
  transcript?: string | null;
  transcriptConfidence?: number | null;
  mediaId?: string | null;
  mediaUrl?: string | null;
  cdnMedia?: ClawbotCdnMediaPayload | null;
  ocrText?: string | null;
  imageText?: string | null;
  mimeType?: string | null;
  raw: unknown;
};

type BridgeSummary = {
  credentials: number;
  rawMessagesReceived: number;
  messagesSeen: number;
  messagesSkipped: number;
  imageMessagesSeen: number;
  voiceMessagesSeen: number;
  typingStarted: number;
  typingKeepalives: number;
  typingFailed: number;
  messagesForwarded: number;
  repliesSent: number;
  errors: string[];
};

type RouteAdapterPayload = {
  accountId?: string | null;
  rawAccountId?: string | null;
  getUpdatesBuf?: string | null;
  message?: unknown;
};

type DeliveryRecipient = {
  openclaw_account_id?: string | null;
  target_conversation?: string | null;
  context_token?: string | null;
  channel_binding_id?: string | null;
};

export type DeliveryPayload = {
  delivery_id?: string | null;
  tenant_id?: string | null;
  channel?: string | null;
  recipient?: DeliveryRecipient | null;
  message?: {
    content_type?: string | null;
    content?: unknown;
  } | null;
};

const BLOCKED_WECHAT_DELIVERY_CONTENT_TYPES = new Set([
  'confirmation_card',
  'task_update',
  'system_message',
  'system',
]);

function databaseUrl() {
  return process.env.WEBAPP_DATABASE_URL || process.env.DATABASE_URL || '';
}

function sqlClient() {
  const url = databaseUrl();
  if (!url) {
    throw new Error('微信 ClawBot 桥接需要配置 DATABASE_URL 或 WEBAPP_DATABASE_URL');
  }

  if (!globalThis.__aiHoldingsWechatBridgeSql) {
    globalThis.__aiHoldingsWechatBridgeSql = postgres(url, {
      max: 3,
      idle_timeout: 20,
      connect_timeout: 10,
      prepare: false,
    });
  }

  return globalThis.__aiHoldingsWechatBridgeSql;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function pickString(value: unknown, keys: string[]): string | undefined {
  const record = asRecord(value);
  if (!record) return undefined;

  for (const key of keys) {
    const item = record[key];
    if (typeof item === 'string' && item.trim()) return item.trim();
    if (typeof item === 'number' && Number.isFinite(item)) return String(item);
  }

  for (const nested of Object.values(record)) {
    const result = pickString(nested, keys);
    if (result) return result;
  }

  return undefined;
}

function pickNumber(value: unknown, keys: string[]): number | undefined {
  const raw = pickString(value, keys);
  if (!raw) return undefined;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function isLikelyBotMessage(message: unknown, accountId: string) {
  const fromUserId = pickString(message, ['from_user_id', 'fromUserId']);
  if (fromUserId && fromUserId === accountId) return true;
  const messageType = pickString(message, ['message_type', 'messageType', 'sender_type', 'senderType']);
  return messageType === '2' || messageType?.toLowerCase() === 'bot';
}

function isLikelyVoiceMessage(message: unknown) {
  const messageType = pickString(message, [
    'message_type',
    'messageType',
    'msg_type',
    'msgType',
    'type',
    'content_type',
    'contentType',
    'media_type',
    'mediaType',
  ])?.toLowerCase();
  if (!messageType) return false;
  return ['voice', 'audio', 'speech', 'asr', '34'].some((signal) => messageType.includes(signal));
}

function extractVoiceTranscript(message: unknown) {
  return pickString(message, [
    'transcript',
    'transcript_text',
    'transcriptText',
    'voice_text',
    'voiceText',
    'speech_text',
    'speechText',
    'asr_text',
    'asrText',
    'recognized_text',
    'recognizedText',
    'recognition',
  ]);
}

function extractBridgeMessages(messages: unknown[], accountId: string): ClawbotBridgeMessage[] {
  return messages.flatMap<ClawbotBridgeMessage>((message) => {
    if (isLikelyBotMessage(message, accountId)) return [];

    const fromUserId = pickString(message, ['from_user_id', 'fromUserId']);
    const contextToken = pickString(message, ['context_token', 'contextToken']);
    const messageId = pickString(message, ['msg_id', 'msgId', 'message_id', 'messageId', 'id']);
    const toUserId = pickString(message, ['to_user_id', 'toUserId']) || null;
    const context = {
      contextToken,
      fromUserId,
      toUserId,
      messageId,
    };
    const imagePayload = extractClawbotImagePayload(message, context);
    const text = extractClawbotUserText(message, context);
    const voiceTranscript = extractVoiceTranscript(message);
    const isVoiceMessage = isLikelyVoiceMessage(message);
    if (!fromUserId || !contextToken) return [];

    if (imagePayload) {
      return [
        {
          id: messageId || `${fromUserId}:${contextToken}:${imagePayload.mediaId || imagePayload.mediaUrl || 'image'}`,
          fromUserId,
          toUserId,
          contextToken,
          type: 'image',
          mediaId: imagePayload.mediaId,
          mediaUrl: imagePayload.mediaUrl,
          cdnMedia: imagePayload.cdnMedia,
          ocrText: imagePayload.ocrText,
          imageText: imagePayload.imageText,
          mimeType: imagePayload.mimeType,
          raw: message,
        },
      ];
    }

    if (isVoiceMessage && (voiceTranscript || text)) {
      const transcript = voiceTranscript || text || '';
      return [
        {
          id: messageId || `${fromUserId}:${contextToken}:${transcript.slice(0, 80)}`,
          fromUserId,
          toUserId,
          contextToken,
          type: 'voice',
          transcript,
          transcriptConfidence:
            pickNumber(message, [
              'transcript_confidence',
              'transcriptConfidence',
              'voice_confidence',
              'voiceConfidence',
              'asr_confidence',
              'asrConfidence',
              'confidence',
            ]) ?? null,
          raw: message,
        },
      ];
    }

    if (!text) return [];

    return [
      {
        id: messageId || `${fromUserId}:${contextToken}:${text.slice(0, 80)}`,
        fromUserId,
        toUserId,
        contextToken,
        type: 'text',
        text,
        raw: message,
      },
    ];
  });
}

function normalizeOpenClawAccountId(value: string) {
  return value
    .trim()
    .replace(/@/g, '-')
    .replace(/\./g, '-')
    .replace(/[^A-Za-z0-9_-]/g, '-');
}

async function activeWechatCredentials(primaryOnly = true): Promise<BridgeCredentialRow[]> {
  await ensureWechatBridgeSchema();
  const sql = sqlClient();
  return sql<BridgeCredentialRow[]>`
    SELECT
      c.id AS credential_id,
      c.tenant_id,
      c.bot_token_ciphertext,
      c.base_url,
      c.get_updates_buf,
      b.id AS channel_binding_id,
      b.channel_account_id,
      b.openclaw_account_id,
      b.channel_user_ref,
      b.session_space,
      b.binding_metadata
    FROM public.wechat_bot_credentials c
    JOIN public.channel_bindings b
      ON b.tenant_id = c.tenant_id
      AND b.channel IN ('hermes_wechat', 'openclaw_wechat')
      AND b.binding_status = 'active'
      AND (${primaryOnly} = false OR b.is_primary = true)
    WHERE c.credential_status = 'active'
    ORDER BY c.updated_at DESC
  `;
}

async function activeWechatCredentialForOpenClawAccount(accountId: string) {
  const normalized = normalizeOpenClawAccountId(accountId);
  const rows = await activeWechatCredentials(false);
  return (
    rows.find((row) => normalizeOpenClawAccountId(row.channel_account_id || row.openclaw_account_id) === normalized) ||
    rows.find((row) => row.openclaw_account_id === accountId) ||
    null
  );
}

async function ensureWechatBridgeSchema() {
  await ensureOnboardingSchema();
  const sql = sqlClient();
  await sql`
    CREATE TABLE IF NOT EXISTS public.wechat_clawbot_message_receipts (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      credential_id UUID NOT NULL REFERENCES public.wechat_bot_credentials(id) ON DELETE CASCADE,
      message_key TEXT NOT NULL,
      processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (credential_id, message_key)
    )
  `;
  await sql`
    CREATE INDEX IF NOT EXISTS idx_wechat_clawbot_message_receipts_processed_at
      ON public.wechat_clawbot_message_receipts (processed_at DESC)
  `;
}

async function updateCredentialCursor(credentialId: string, getUpdatesBuf?: string | null) {
  const sql = sqlClient();
  await sql`
    UPDATE public.wechat_bot_credentials
    SET get_updates_buf = ${getUpdatesBuf || null}, updated_at = now()
    WHERE id = ${credentialId}
  `;
}

function messageKey(message: ClawbotBridgeMessage) {
  return crypto
    .createHash('sha256')
    .update([
      message.id,
      message.fromUserId,
      message.contextToken,
      message.type,
      message.text ||
        message.transcript ||
        message.ocrText ||
        message.imageText ||
        message.mediaId ||
        message.mediaUrl ||
        '',
    ].join('\u001f'))
    .digest('hex');
}

async function claimMessage(credentialId: string, message: ClawbotBridgeMessage) {
  const sql = sqlClient();
  const rows = await sql<{ id: string }[]>`
    INSERT INTO public.wechat_clawbot_message_receipts (credential_id, message_key)
    VALUES (${credentialId}, ${messageKey(message)})
    ON CONFLICT (credential_id, message_key) DO NOTHING
    RETURNING id
  `;
  return rows.length > 0;
}

async function releaseMessageClaim(credentialId: string, message: ClawbotBridgeMessage) {
  const sql = sqlClient();
  await sql`
    DELETE FROM public.wechat_clawbot_message_receipts
    WHERE credential_id = ${credentialId}
      AND message_key = ${messageKey(message)}
  `;
}

async function rememberMessageRoute(row: BridgeCredentialRow, message: ClawbotBridgeMessage) {
  const sql = sqlClient();
  await sql`
    UPDATE public.channel_bindings
    SET
      channel_user_ref = ${message.fromUserId},
      last_seen_at = now(),
      binding_metadata = jsonb_set(
        jsonb_set(
          jsonb_set(
            coalesce(binding_metadata, '{}'::jsonb),
            '{context_token}',
            to_jsonb(${message.contextToken}::text),
            true
          ),
          '{last_inbound_message_id}',
          to_jsonb(${message.id}::text),
          true
        ),
        '{last_inbound_at}',
        to_jsonb(now()::text),
        true
      ),
      updated_at = now()
    WHERE id = ${row.channel_binding_id}
  `;
}

async function markWechatInitializationDelivery(
  bindingId: string,
  status: 'sent' | 'failed',
  error?: string
) {
  const sql = sqlClient();
  await sql`
    UPDATE public.channel_bindings
    SET
      binding_metadata = jsonb_set(
        coalesce(binding_metadata, '{}'::jsonb),
        '{onboarding}',
        coalesce(binding_metadata->'onboarding', '{}'::jsonb) || ${sql.json(
          wechatOnboardingInitializationMetadata(status, error).onboarding as any
        )}::jsonb,
        true
      ),
      updated_at = now()
    WHERE id = ${bindingId}
  `;
}

async function maybeSendWechatInitialization(
  row: BridgeCredentialRow,
  botToken: string,
  message: ClawbotBridgeMessage
) {
  if (!shouldDeliverWechatOnboardingInitialization(row.binding_metadata)) {
    return { sent: false, skipped: true };
  }

  try {
    await sendText(
      row,
      botToken,
      message.fromUserId,
      message.contextToken,
      buildWechatBindingInitializationMessage()
    );
    await markWechatInitializationDelivery(row.channel_binding_id, 'sent');
    row.binding_metadata = {
      ...(row.binding_metadata || {}),
      ...wechatOnboardingInitializationMetadata('sent'),
    };
    return { sent: true, skipped: false };
  } catch (error) {
    const messageText = error instanceof Error ? error.message : String(error);
    await markWechatInitializationDelivery(row.channel_binding_id, 'failed', messageText).catch(() => undefined);
    return { sent: false, skipped: false, error: messageText };
  }
}

async function maybeCaptureWechatSelfIntroduction(row: BridgeCredentialRow, message: ClawbotBridgeMessage) {
  if (message.type !== 'text' || !shouldCaptureWechatSelfIntroduction(row.binding_metadata)) {
    return { captured: false, skipped: true };
  }

  const profile = parseWechatSelfIntroduction(message.text);
  if (!profile) {
    return { captured: false, skipped: true };
  }

  const sql = sqlClient();
  const now = new Date().toISOString();
  const onboardingProfile = wechatSelfIntroductionMetadata(profile);

  if (profile.displayName) {
    await sql`
      UPDATE public.tenant_accounts
      SET display_name = ${profile.displayName}, updated_at = now()
      WHERE tenant_id = ${row.tenant_id}
    `;
  }

  if (profile.primaryMarkets?.length || profile.riskProfile || profile.interests?.length) {
    await sql`
      INSERT INTO public.tenant_settings (
        tenant_id,
        primary_markets,
        risk_profile,
        settings_payload
      )
      VALUES (
        ${row.tenant_id},
        ${profile.primaryMarkets?.length ? profile.primaryMarkets : ['US']},
        ${profile.riskProfile || 'balanced'},
        ${sql.json({
          source: 'wechat_self_intro',
          updated_at: now,
          interests: profile.interests || [],
          profile_fields: Object.keys(profile),
        } as any)}
      )
      ON CONFLICT (tenant_id) DO UPDATE SET
        primary_markets = CASE
          WHEN ${Boolean(profile.primaryMarkets?.length)} THEN EXCLUDED.primary_markets
          ELSE public.tenant_settings.primary_markets
        END,
        risk_profile = CASE
          WHEN ${Boolean(profile.riskProfile)} THEN EXCLUDED.risk_profile
          ELSE public.tenant_settings.risk_profile
        END,
        settings_payload = public.tenant_settings.settings_payload || EXCLUDED.settings_payload,
        updated_at = now()
    `;
  }

  await sql`
    UPDATE public.channel_bindings
    SET
      human_name = COALESCE(${profile.displayName || null}, human_name),
      binding_metadata = jsonb_set(
        coalesce(binding_metadata, '{}'::jsonb),
        '{onboarding}',
        coalesce(binding_metadata->'onboarding', '{}'::jsonb) || ${sql.json(onboardingProfile as any)}::jsonb,
        true
      ),
      updated_at = now()
    WHERE id = ${row.channel_binding_id}
  `;

  row.binding_metadata = {
    ...(row.binding_metadata || {}),
    onboarding: {
      ...((row.binding_metadata?.onboarding as Record<string, unknown> | undefined) || {}),
      ...onboardingProfile,
    },
  };

  return { captured: true, skipped: false, profile };
}

function hermesIngressBaseUrl() {
  return (
    process.env.HERMES_INGRESS_URL ||
    process.env.DATA_SERVICE_URL ||
    process.env.NEXT_PUBLIC_DATA_SERVICE_URL ||
    'http://data-service:8000'
  ).replace(/\/+$/, '');
}

function hermesIngressHeaders() {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = process.env.HERMES_DOMAIN_TOOLS_KEY || process.env.HERMES_INTERNAL_TOKEN || '';
  if (token) {
    headers['X-Hermes-Domain-Tools-Key'] = token;
    headers['X-Hermes-Internal-Token'] = token;
  }
  return headers;
}

function isForwardableImageReference(value?: string | null) {
  return typeof value === 'string' && (/^https?:\/\/.+/i.test(value) || /^data:image\//i.test(value));
}

function bridgeErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

async function postHermesMessage(row: BridgeCredentialRow, message: ClawbotBridgeMessage) {
  const imageMetadata: Record<string, unknown> = {
    source: 'clawbot_getupdates',
    raw_to_user_id: message.toUserId,
    media_id: message.mediaId,
    media_url: message.mediaUrl,
    mime_type: message.mimeType,
    bridge_message_type: message.type,
  };
  if (isForwardableImageReference(message.mediaUrl)) {
    imageMetadata.image_url = message.mediaUrl;
  }

  if (message.type === 'image' && !message.ocrText && !message.imageText) {
    if (message.cdnMedia) {
      try {
        const media = await downloadClawbotCdnMedia(message.cdnMedia);
        const contentType = media.contentType || message.mimeType || 'image/jpeg';
        imageMetadata.image_data_url = `data:${contentType};base64,${media.buffer.toString('base64')}`;
        imageMetadata.media_download = {
          status: 'ok',
          source: 'clawbot_cdn',
          byte_size: media.buffer.length,
          content_type: contentType,
        };
      } catch (error) {
        imageMetadata.media_download = {
          status: 'failed',
          source: 'clawbot_cdn',
          error: bridgeErrorMessage(error),
        };
      }
    } else if (!isForwardableImageReference(message.mediaUrl)) {
      imageMetadata.media_download = {
        status: 'missing_media_reference',
        source: 'clawbot_getupdates',
        media_id_present: Boolean(message.mediaId),
      };
    }
  }

  const hermesMessage =
    message.type === 'image'
      ? {
          id: message.id,
          type: 'image',
          media_id: message.mediaId,
          image_text: message.imageText,
          ocr_text: message.ocrText,
          metadata: {
            ...imageMetadata,
          },
        }
      : message.type === 'voice'
        ? {
            id: message.id,
            type: 'voice',
            transcript: message.transcript,
            transcript_confidence: message.transcriptConfidence,
            metadata: {
              source: 'clawbot_getupdates',
              raw_to_user_id: message.toUserId,
              bridge_message_type: message.type,
            },
          }
        : {
            id: message.id,
            type: 'text',
            text: message.text,
            metadata: {
              source: 'clawbot_getupdates',
              raw_to_user_id: message.toUserId,
              bridge_message_type: message.type,
            },
          };

  const response = await fetch(`${hermesIngressBaseUrl()}/api/hermes/wechat/messages`, {
    method: 'POST',
    cache: 'no-store',
    headers: hermesIngressHeaders(),
    body: JSON.stringify({
      routing: {
        tenant_id: row.tenant_id,
        channel_binding_id: row.channel_binding_id,
        channel_account_id: row.channel_account_id || row.openclaw_account_id,
        openclaw_account_id: row.openclaw_account_id,
        channel: 'hermes_wechat',
        session_space: row.session_space || `tenant:${row.tenant_id}:wechat`,
        context_token: message.contextToken,
        target_conversation: message.fromUserId,
        timezone: 'Asia/Shanghai',
      },
      message: hermesMessage,
    }),
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`Hermes ingress returned HTTP ${response.status}`);
  }
  return payload as Record<string, unknown>;
}

function hasSavedPersistence(payload: Record<string, unknown>) {
  const candidates = [
    payload,
    asRecord(payload.analysis),
    asRecord(payload.data),
    asRecord(payload.result),
  ].filter(Boolean) as Record<string, unknown>[];
  return candidates.some((candidate) => {
    const persistence = asRecord(candidate.persistence);
    return persistence?.status === 'saved';
  });
}

async function persistHermesAnalysisArtifact(
  row: BridgeCredentialRow,
  message: ClawbotBridgeMessage,
  hermesResult: Record<string, unknown>,
  replyText: string | null
) {
  if (hasSavedPersistence(hermesResult)) {
    return { ok: true, skipped: true, reason: 'already_saved' };
  }

  const hermesMessage =
    message.type === 'image'
      ? {
          id: message.id,
          type: 'image',
          media_id: message.mediaId,
          image_text: message.imageText,
          ocr_text: message.ocrText,
          metadata: {
            source: 'clawbot_getupdates',
            raw_to_user_id: message.toUserId,
            bridge_message_type: message.type,
          },
        }
      : message.type === 'voice'
        ? {
            id: message.id,
            type: 'voice',
            transcript: message.transcript,
            transcript_confidence: message.transcriptConfidence,
            metadata: {
              source: 'clawbot_getupdates',
              raw_to_user_id: message.toUserId,
              bridge_message_type: message.type,
            },
          }
        : {
            id: message.id,
            type: 'text',
            text: message.text,
            metadata: {
              source: 'clawbot_getupdates',
              raw_to_user_id: message.toUserId,
              bridge_message_type: message.type,
            },
          };

  const response = await fetch(`${hermesIngressBaseUrl()}/api/hermes/wechat/analysis-artifacts`, {
    method: 'POST',
    cache: 'no-store',
    headers: hermesIngressHeaders(),
    body: JSON.stringify({
      routing: {
        tenant_id: row.tenant_id,
        channel_binding_id: row.channel_binding_id,
        channel_account_id: row.channel_account_id || row.openclaw_account_id,
        openclaw_account_id: row.openclaw_account_id,
        channel: 'hermes_wechat',
        session_space: row.session_space || `tenant:${row.tenant_id}:wechat`,
        context_token: message.contextToken,
        target_conversation: message.fromUserId,
        timezone: 'Asia/Shanghai',
      },
      message: hermesMessage,
      hermes_result: hermesResult,
      reply_text: replyText,
      metadata: {
        source: 'wechat_clawbot_bridge',
        persisted_after_reply_generation: true,
      },
    }),
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`Hermes analysis artifact persist returned HTTP ${response.status}`);
  }
  return payload;
}

function replyTextFromHermes(payload: Record<string, unknown>) {
  const replyText = payload.reply_text;
  return typeof replyText === 'string' && replyText.trim() ? replyText.trim() : null;
}

async function sendText(row: BridgeCredentialRow, botToken: string, toUserId: string, contextToken: string, text: string) {
  await requestClawbotSendTextMessage(row.base_url, botToken, {
    toUserId,
    contextToken,
    text: text.slice(0, 1800),
  });
}

function typingIndicatorsEnabled() {
  return (process.env.WECHAT_CLAWBOT_TYPING_ENABLED || 'true').trim().toLowerCase() !== 'false';
}

function typingKeepaliveMs() {
  const configured = Number(process.env.WECHAT_CLAWBOT_TYPING_KEEPALIVE_MS || '4500');
  return Number.isFinite(configured) ? Math.max(2500, configured) : 4500;
}

function typingMinimumVisibleMs() {
  const configured = Number(process.env.WECHAT_CLAWBOT_TYPING_MIN_VISIBLE_MS || '1200');
  return Number.isFinite(configured) ? Math.max(0, configured) : 1200;
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function setTyping(
  row: BridgeCredentialRow,
  botToken: string,
  toUserId: string,
  contextToken: string,
  status: 'typing' | 'cancel',
) {
  if (!typingIndicatorsEnabled()) return false;
  await requestClawbotSendTyping(row.base_url, botToken, {
    toUserId,
    contextToken,
    status,
  });
  return true;
}

type TypingIndicatorHandle = {
  startedAt: number;
  stop: () => Promise<{ keepalives: number; failures: number }>;
};

async function startTypingIndicator(
  row: BridgeCredentialRow,
  botToken: string,
  toUserId: string,
  contextToken: string,
): Promise<TypingIndicatorHandle | null> {
  if (!typingIndicatorsEnabled()) return null;

  const startedAt = Date.now();
  await setTyping(row, botToken, toUserId, contextToken, 'typing');

  let keepalives = 0;
  let failures = 0;
  let stopped = false;
  const timer = setInterval(() => {
    if (stopped) return;
    setTyping(row, botToken, toUserId, contextToken, 'typing')
      .then((sent) => {
        if (sent) keepalives += 1;
      })
      .catch(() => {
        failures += 1;
      });
  }, typingKeepaliveMs());

  return {
    startedAt,
    stop: async () => {
      stopped = true;
      clearInterval(timer);
      const elapsed = Date.now() - startedAt;
      const remaining = typingMinimumVisibleMs() - elapsed;
      if (remaining > 0) await sleep(remaining);
      try {
        await setTyping(row, botToken, toUserId, contextToken, 'cancel');
      } catch {
        failures += 1;
      }
      return { keepalives, failures };
    },
  };
}

async function processWechatBridgeMessage(
  row: BridgeCredentialRow,
  botToken: string,
  message: ClawbotBridgeMessage
) {
  const summary = {
    messagesSkipped: 0,
    typingStarted: 0,
    typingKeepalives: 0,
    typingFailed: 0,
    messagesForwarded: 0,
    repliesSent: 0,
    errors: [] as string[],
  };

  if (!(await claimMessage(row.credential_id, message))) {
    summary.messagesSkipped += 1;
    return summary;
  }

  let typingHandle: TypingIndicatorHandle | null = null;
  let typingStopped = false;
  const stopTyping = async () => {
    if (!typingHandle || typingStopped) return;
    typingStopped = true;
    const result = await typingHandle.stop();
    summary.typingKeepalives += result.keepalives;
    summary.typingFailed += result.failures;
  };

  try {
    await rememberMessageRoute(row, message);
    const initialization = await maybeSendWechatInitialization(row, botToken, message);
    if (initialization.sent) {
      summary.repliesSent += 1;
    }
    if (initialization.error) {
      summary.errors.push(`Wechat onboarding initialization failed: ${initialization.error}`);
    }
    await maybeCaptureWechatSelfIntroduction(row, message);
    try {
      typingHandle = await startTypingIndicator(row, botToken, message.fromUserId, message.contextToken);
      if (typingHandle) summary.typingStarted += 1;
    } catch (error) {
      summary.typingFailed += 1;
      summary.errors.push(`ClawBot typing indicator failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    const hermesResult = await postHermesMessage(row, message);
    summary.messagesForwarded += 1;
    const replyText = replyTextFromHermes(hermesResult);
    try {
      await persistHermesAnalysisArtifact(row, message, hermesResult, replyText);
    } catch (error) {
      summary.errors.push(`Hermes analysis artifact persist failed: ${error instanceof Error ? error.message : String(error)}`);
    }
    if (replyText) {
      await sendText(row, botToken, message.fromUserId, message.contextToken, replyText);
      await stopTyping();
      summary.repliesSent += 1;
    }
  } catch (error) {
    await stopTyping().catch(() => undefined);
    await releaseMessageClaim(row.credential_id, message);
    throw error;
  } finally {
    await stopTyping().catch(() => undefined);
  }

  return summary;
}

export async function pollWechatClawbotMessages() {
  const rows = await activeWechatCredentials();
  const summary: BridgeSummary = {
    credentials: rows.length,
    rawMessagesReceived: 0,
    messagesSeen: 0,
    messagesSkipped: 0,
    imageMessagesSeen: 0,
    voiceMessagesSeen: 0,
    typingStarted: 0,
    typingKeepalives: 0,
    typingFailed: 0,
    messagesForwarded: 0,
    repliesSent: 0,
    errors: [] as string[],
  };

  for (const row of rows) {
    let botToken = '';
    try {
      botToken = decryptCredential(row.bot_token_ciphertext);
      const updates = await requestClawbotUpdates(row.base_url, botToken, row.get_updates_buf);

      summary.rawMessagesReceived += updates.messages.length;
      const messages = extractBridgeMessages(updates.messages, row.channel_account_id || row.openclaw_account_id);
      summary.messagesSeen += messages.length;
      summary.imageMessagesSeen += messages.filter((message) => message.type === 'image').length;
      summary.voiceMessagesSeen += messages.filter((message) => message.type === 'voice').length;
      for (const message of messages) {
        const result = await processWechatBridgeMessage(row, botToken, message);
        summary.messagesSkipped += result.messagesSkipped;
        summary.typingStarted += result.typingStarted;
        summary.typingKeepalives += result.typingKeepalives;
        summary.typingFailed += result.typingFailed;
        summary.messagesForwarded += result.messagesForwarded;
        summary.repliesSent += result.repliesSent;
        summary.errors.push(...result.errors);
      }
      if (updates.messages.length > 0 && messages.length === 0) {
        summary.errors.push(`ClawBot returned ${updates.messages.length} update(s), but none matched user text/image/voice payloads`);
      }
      await updateCredentialCursor(row.credential_id, updates.getUpdatesBuf || row.get_updates_buf);
    } catch (error) {
      summary.errors.push(error instanceof Error ? error.message : String(error));
    }
  }

  return summary;
}

export async function routeWechatClawbotMessageFromAdapter(payload: RouteAdapterPayload) {
  const accountId = payload.accountId || payload.rawAccountId || '';
  if (!accountId) {
    throw new Error('route adapter payload missing accountId');
  }
  if (!payload.message) {
    throw new Error('route adapter payload missing message');
  }

  const row = await activeWechatCredentialForOpenClawAccount(accountId);
  if (!row) {
    throw new Error(`未找到 Hermes 微信账号映射：${accountId}`);
  }

  const rawAccountId = payload.rawAccountId || row.channel_account_id || row.openclaw_account_id;
  const messages = extractBridgeMessages([payload.message], rawAccountId);
  const summary: BridgeSummary = {
    credentials: 1,
    rawMessagesReceived: 1,
    messagesSeen: messages.length,
    messagesSkipped: 0,
    imageMessagesSeen: messages.filter((message) => message.type === 'image').length,
    voiceMessagesSeen: messages.filter((message) => message.type === 'voice').length,
    typingStarted: 0,
    typingKeepalives: 0,
    typingFailed: 0,
    messagesForwarded: 0,
    repliesSent: 0,
    errors: [],
  };

  if (messages.length === 0) {
    summary.errors.push('route adapter message did not match supported text/image/voice payloads');
    return summary;
  }

  const botToken = decryptCredential(row.bot_token_ciphertext);
  for (const message of messages) {
    const result = await processWechatBridgeMessage(row, botToken, message);
    summary.messagesSkipped += result.messagesSkipped;
    summary.typingStarted += result.typingStarted;
    summary.typingKeepalives += result.typingKeepalives;
    summary.typingFailed += result.typingFailed;
    summary.messagesForwarded += result.messagesForwarded;
    summary.repliesSent += result.repliesSent;
    summary.errors.push(...result.errors);
  }

  if (payload.getUpdatesBuf) {
    await updateCredentialCursor(row.credential_id, payload.getUpdatesBuf);
  }

  return summary;
}

function contentText(content: unknown, contentType?: string | null) {
  if (typeof content === 'string') return content;
  const record = asRecord(content);
  if (!record) return contentType ? `已收到 ${contentType} 更新。` : '已收到系统更新。';

  const directText = pickString(record, ['text', 'reply_text', 'body', 'message']);
  if (directText) return directText;

  const title = pickString(record, ['title']);
  const body = pickString(record, ['body']);
  const commandHint = pickString(record, ['command_hint']);
  const deepLink = pickString(record, ['deep_link']);
  return [title, body, commandHint ? `回复“${commandHint}”继续。` : null, deepLink]
    .filter(Boolean)
    .join('\n');
}

async function credentialForDelivery(payload: DeliveryPayload): Promise<BridgeCredentialRow | null> {
  await ensureOnboardingSchema();
  const sql = sqlClient();
  const recipient = payload.recipient || {};
  const rows = await sql<BridgeCredentialRow[]>`
    SELECT
      c.id AS credential_id,
      c.tenant_id,
      c.bot_token_ciphertext,
      c.base_url,
      c.get_updates_buf,
      b.id AS channel_binding_id,
      b.channel_account_id,
      b.openclaw_account_id,
      b.channel_user_ref,
      b.session_space,
      b.binding_metadata
    FROM public.wechat_bot_credentials c
    JOIN public.channel_bindings b
      ON b.tenant_id = c.tenant_id
      AND b.channel IN ('hermes_wechat', 'openclaw_wechat')
      AND b.binding_status = 'active'
      AND b.id = ${recipient.channel_binding_id || ''}
    WHERE c.credential_status = 'active'
      AND c.tenant_id = ${payload.tenant_id || ''}
    LIMIT 1
  `;
  return rows[0] || null;
}

export async function deliverWechatOutboxMessage(payload: DeliveryPayload) {
  const row = await credentialForDelivery(payload);
  if (!row) {
    throw new Error('未找到可用的微信 ClawBot 绑定凭证');
  }

  const contentType = String(payload.message?.content_type || '')
    .trim()
    .toLowerCase();
  if (contentType && BLOCKED_WECHAT_DELIVERY_CONTENT_TYPES.has(contentType)) {
    return {
      ok: false,
      dropped: true,
      reason: `已过滤微信不下发消息类型：${contentType}`,
      content_type: payload.message?.content_type || null,
    };
  }

  const recipient = payload.recipient || {};
  const toUserId = row.channel_user_ref || recipient.target_conversation || '';
  const contextToken =
    recipient.context_token ||
    (asRecord(row.binding_metadata)?.context_token as string | undefined) ||
    '';
  if (!toUserId || !contextToken) {
    throw new Error('微信投递缺少目标用户或 context_token');
  }

  const text = contentText(payload.message?.content, payload.message?.content_type);
  const botToken = decryptCredential(row.bot_token_ciphertext);
  await sendText(row, botToken, toUserId, contextToken, text);
  return {
    ok: true,
    channel_binding_id: row.channel_binding_id,
    openclaw_account_id: row.openclaw_account_id,
  };
}
