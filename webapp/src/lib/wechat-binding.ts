import {
  decryptCredential,
  encryptCredential,
  findBindingCandidate,
  generateBindCode,
  requestClawbotQrSession,
  requestClawbotQrStatus,
  requestClawbotSendTextMessage,
  requestClawbotUpdates,
} from '@/lib/clawbot';
import {
  auditOnboardingEvent,
  ensureOnboardingSchema,
  ensureOnboardingSession,
  safeWechatAuth,
  safeWechatBinding,
  userDisplayName,
} from '@/lib/onboarding';
import type { AppUser } from '@/lib/supabase';
import {
  buildWechatBindingInitializationMessage,
  shouldDeliverWechatOnboardingInitialization,
  wechatOnboardingInitializationMetadata,
} from '@/lib/wechat-onboarding-init';
import postgres from 'postgres';

declare global {
  // eslint-disable-next-line no-var
  var __aiHoldingsWechatBindingSql: ReturnType<typeof postgres> | undefined;
}

function databaseUrl() {
  return process.env.WEBAPP_DATABASE_URL || process.env.DATABASE_URL || '';
}

function sqlClient() {
  const url = databaseUrl();
  if (!url) {
    throw new Error('微信 Claw 绑定需要配置 DATABASE_URL 或 WEBAPP_DATABASE_URL');
  }

  if (!globalThis.__aiHoldingsWechatBindingSql) {
    globalThis.__aiHoldingsWechatBindingSql = postgres(url, {
      max: 4,
      idle_timeout: 20,
      connect_timeout: 10,
      prepare: false,
    });
  }

  return globalThis.__aiHoldingsWechatBindingSql;
}

function nowIso() {
  return new Date().toISOString();
}

function isWeChatAccountConflictError(error: unknown) {
  const err = error as { code?: string; message?: string; constraint?: string };
  const code = String(err?.code || '');
  const message = String(err?.message || '').toLowerCase();
  const constraint = String(err?.constraint || '').toLowerCase();
  return (
    code === '23505' &&
    (constraint.includes('hermes_wechat_account_active') ||
      constraint.includes('openclaw_wechat_account_active') ||
      message.includes('channel_account_id') ||
      message.includes('openclaw_account_id') ||
      message.includes('channel_bindings_openclaw_wechat_account_active'))
  );
}

async function assertWeChatAccountNotBoundElsewhere({
  sql,
  userId,
  accountId,
}: {
  sql: ReturnType<typeof sqlClient>;
  userId: string;
  accountId: string;
}) {
  const rows = await sql<{ tenant_id: string }[]>`
    SELECT tenant_id
    FROM public.channel_bindings
    WHERE channel IN ('hermes_wechat', 'openclaw_wechat')
      AND binding_status = 'active'
      AND (channel_account_id = ${accountId} OR openclaw_account_id = ${accountId})
      AND tenant_id <> ${userId}
    LIMIT 1
  `;
  if (rows[0]) {
    throw new Error('该微信 ClawBot 已绑定到其他账号，请先在原账号解绑后再重试。');
  }
}

async function latestAuthorizedCredential(tenantId: string) {
  await ensureOnboardingSchema();
  const sql = sqlClient();
  const rows = await sql<Record<string, any>[]>`
    SELECT * FROM public.wechat_bot_credentials
    WHERE tenant_id = ${tenantId}
      AND credential_status = 'active'
    ORDER BY created_at DESC
    LIMIT 1
  `;
  return rows[0] || null;
}

async function storeWechatCredential(
  tenantId: string,
  authSessionId: string,
  botToken: string,
  baseUrl: string,
  getUpdatesBuf?: string | null,
  metadata: Record<string, unknown> = {}
) {
  await ensureOnboardingSchema();
  const sql = sqlClient();
  const ciphertext = encryptCredential(botToken);

  await sql`
    UPDATE public.wechat_bot_credentials
    SET credential_status = 'replaced', updated_at = now()
    WHERE tenant_id = ${tenantId}
      AND credential_status = 'active'
  `;

  await sql`
    INSERT INTO public.wechat_bot_credentials (
      tenant_id,
      clawbot_auth_session_id,
      bot_token_ciphertext,
      base_url,
      get_updates_buf,
      credential_status,
      credential_metadata
    )
    VALUES (
      ${tenantId},
      ${authSessionId},
      ${ciphertext},
      ${baseUrl},
      ${getUpdatesBuf || null},
      'active',
      ${sql.json(metadata as any)}
    )
  `;

  return ciphertext;
}

async function markWechatInitializationDelivery(
  sql: ReturnType<typeof sqlClient>,
  bindingId: string,
  status: 'sent' | 'failed',
  error?: string
) {
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

async function deliverWechatInitializationAfterBinding({
  user,
  binding,
  toUserId,
  contextToken,
}: {
  user: AppUser;
  binding: Record<string, any> | null;
  toUserId?: string | null;
  contextToken?: string | null;
}) {
  if (!binding?.id || !toUserId || !contextToken || !shouldDeliverWechatOnboardingInitialization(binding.binding_metadata)) {
    return { delivered: false, skipped: true };
  }

  const sql = sqlClient();
  try {
    const credential = await latestAuthorizedCredential(user.id);
    const ciphertext = credential?.bot_token_ciphertext;
    if (!credential || !ciphertext) {
      throw new Error('missing_active_wechat_credential');
    }

    await requestClawbotSendTextMessage(credential.base_url, decryptCredential(ciphertext), {
      toUserId,
      contextToken,
      text: buildWechatBindingInitializationMessage(userDisplayName(user)),
    });
    await markWechatInitializationDelivery(sql, binding.id, 'sent');
    await auditOnboardingEvent(user.id, undefined, 'wechat_initialization_delivered', {
      channel_binding_id: binding.id,
      source: 'binding_completed',
    });
    return { delivered: true, skipped: false };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await markWechatInitializationDelivery(sql, binding.id, 'failed', message).catch(() => undefined);
    await auditOnboardingEvent(user.id, binding.onboarding_session_id, 'wechat_initialization_delivery_failed', {
      channel_binding_id: binding.id,
      error: message,
    });
    return { delivered: false, skipped: false, error: message };
  }
}

async function upsertWechatBinding({
  user,
  authSessionId,
  accountId,
  channelUserRef,
  contextToken,
  source,
  bindCode,
}: {
  user: AppUser;
  authSessionId: string;
  accountId: string;
  channelUserRef?: string | null;
  contextToken?: string | null;
  source: string;
  bindCode?: string | null;
}) {
  await ensureOnboardingSchema();
  const sql = sqlClient();
  const now = nowIso();

  await sql`
    UPDATE public.channel_bindings
    SET
      is_primary = false,
      binding_status = CASE
        WHEN binding_status = 'active' THEN 'revoked'
        ELSE binding_status
      END,
      updated_at = now()
    WHERE tenant_id = ${user.id}
      AND channel IN ('hermes_wechat', 'openclaw_wechat')
  `;

  await assertWeChatAccountNotBoundElsewhere({
    sql,
    userId: user.id,
    accountId,
  });

  let rows: Record<string, any>[];
  try {
    rows = await sql<Record<string, any>[]>`
      INSERT INTO public.channel_bindings (
        tenant_id,
        channel,
        openclaw_account_id,
        channel_account_id,
        channel_user_ref,
        account_label,
        human_name,
        session_space,
        binding_status,
        is_primary,
        bound_at,
        last_seen_at,
        binding_metadata
      )
      VALUES (
        ${user.id},
        'hermes_wechat',
        ${accountId},
        ${accountId},
        ${channelUserRef || null},
        '微信 ClawBot',
        ${userDisplayName(user)},
        ${`tenant:${user.id}:wechat`},
        'active',
        true,
        ${now},
        ${now},
        ${sql.json({
        source,
        auth_session_id: authSessionId,
        context_token: contextToken || null,
        bind_code: bindCode || null,
      } as any)}
      )
      ON CONFLICT (tenant_id, channel) WHERE (channel = 'hermes_wechat' AND binding_status = 'active') DO UPDATE SET
        openclaw_account_id = EXCLUDED.openclaw_account_id,
        channel_account_id = EXCLUDED.channel_account_id,
        channel_user_ref = EXCLUDED.channel_user_ref,
        account_label = EXCLUDED.account_label,
        human_name = EXCLUDED.human_name,
        session_space = EXCLUDED.session_space,
        binding_status = 'active',
        is_primary = true,
        bound_at = COALESCE(public.channel_bindings.bound_at, EXCLUDED.bound_at),
        last_seen_at = EXCLUDED.last_seen_at,
        binding_metadata = public.channel_bindings.binding_metadata || EXCLUDED.binding_metadata,
        updated_at = now()
      RETURNING *
    `;
  } catch (error) {
    if (isWeChatAccountConflictError(error)) {
      throw new Error('该微信 ClawBot 已绑定到其他账号，请先在原账号解绑后再重试。');
    }
    throw error;
  }

  await sql`
    UPDATE public.wechat_clawbot_auth_sessions
    SET
      status = 'conversation_verified',
      conversation_verified_at = ${now},
      last_checked_at = ${now},
      error_message = null,
      updated_at = now()
    WHERE id = ${authSessionId}
      AND tenant_id = ${user.id}
  `;

  await sql`
    UPDATE public.onboarding_sessions
    SET
      status = 'wechat_conversation_verified',
      current_step = 'review',
      wechat_authorized_at = COALESCE(wechat_authorized_at, ${now}),
      wechat_conversation_verified_at = ${now},
      required_checks = ${sql.json({ profile: true, wechat: true } as any)},
      updated_at = now()
    WHERE tenant_id = ${user.id}
  `;

  return rows[0] || null;
}

async function loadAuthSession(user: AppUser, authSessionId: string) {
  await ensureOnboardingSchema();
  const sql = sqlClient();
  const rows = await sql<Record<string, any>[]>`
    SELECT * FROM public.wechat_clawbot_auth_sessions
    WHERE id = ${authSessionId}
      AND tenant_id = ${user.id}
    LIMIT 1
  `;
  const authSession = rows[0];
  if (!authSession) {
    throw new Error('未找到当前微信绑定会话，请重新生成二维码');
  }
  return authSession;
}

export async function getWechatQrTargetUrl(user: AppUser, authSessionId: string) {
  const authSession = await loadAuthSession(user, authSessionId);
  const targetUrl =
    typeof authSession.qrcode_url === 'string' && authSession.qrcode_url.trim()
      ? authSession.qrcode_url.trim()
      : '';

  if (!targetUrl) {
    throw new Error('当前微信绑定会话没有可生成二维码的授权链接，请重新生成二维码');
  }

  return targetUrl;
}

export async function startWechatBindingSession(user: AppUser) {
  const session = await ensureOnboardingSession(user);
  const sql = sqlClient();
  const qr = await requestClawbotQrSession();
  const bindCode = generateBindCode();
  const expiresAt = new Date(Date.now() + 10 * 60 * 1000).toISOString();
  const now = nowIso();
  const botTokenCiphertext = qr.botToken ? encryptCredential(qr.botToken) : null;

  const rows = await sql<Record<string, any>[]>`
    INSERT INTO public.wechat_clawbot_auth_sessions (
      tenant_id,
      onboarding_session_id,
      bot_type,
      qrcode,
      qrcode_url,
      session_key,
      status,
      bot_token_ciphertext,
      base_url,
      get_updates_buf,
      bind_code,
      expires_at,
      confirmed_at
    )
    VALUES (
      ${user.id},
      ${session.id},
      3,
      ${qr.qrcode},
      ${qr.qrcodeUrl},
      ${qr.sessionKey || null},
      ${qr.botToken ? 'authorized' : 'qr_pending'},
      ${botTokenCiphertext},
      ${qr.baseUrl || null},
      ${qr.getUpdatesBuf || null},
      ${bindCode},
      ${expiresAt},
      ${qr.botToken ? now : null}
    )
    RETURNING *
  `;

  if (qr.botToken) {
    await storeWechatCredential(user.id, rows[0].id, qr.botToken, qr.baseUrl || '', qr.getUpdatesBuf, {
      source: 'qrcode_session',
      account_id: qr.accountId || null,
      user_id: qr.userId || null,
    });
  }

  await sql`
    UPDATE public.onboarding_sessions
    SET
      status = ${qr.botToken ? 'wechat_authorized' : 'wechat_qr_pending'},
      current_step = 'wechat',
      wechat_authorized_at = ${qr.botToken ? now : null},
      updated_at = now()
    WHERE tenant_id = ${user.id}
  `;

  await auditOnboardingEvent(user.id, session.id, 'wechat_qr_created', {
    auth_session_id: rows[0].id,
    has_inline_token: Boolean(qr.botToken),
  });

  return {
    auth: safeWechatAuth(rows[0]),
    binding: null,
  };
}

export async function refreshWechatBindingStatus(
  user: AppUser,
  authSessionId: string,
  _options: { verifyCode?: string } = {}
) {
  const authSession = await loadAuthSession(user, authSessionId);
  const sql = sqlClient();
  const status = await requestClawbotQrStatus(authSession.qrcode);
  const normalizedStatus = status.status.toLowerCase();
  const now = nowIso();
  const botToken = status.botToken;
  const baseUrl = status.baseUrl || authSession.base_url || '';
  const accountId = status.accountId || authSession.openclaw_account_id || '';
  const authorized = Boolean(botToken) || ['confirmed', 'authorized', 'success', 'binded_redirect'].includes(normalizedStatus);
  const failed = ['expired', 'failed', 'revoked', 'cancelled', 'canceled', 'verify_code_blocked'].includes(normalizedStatus);
  let botTokenCiphertext = authSession.bot_token_ciphertext;
  let binding: Record<string, any> | null = null;

  if (botToken) {
    botTokenCiphertext = await storeWechatCredential(
      user.id,
      authSession.id,
      botToken,
      baseUrl,
      status.getUpdatesBuf || authSession.get_updates_buf,
      { source: 'qrcode_status', raw_status: status.status, account_id: status.accountId || null }
    );
  }

  await sql`
    UPDATE public.wechat_clawbot_auth_sessions
    SET
      status = ${failed ? 'failed' : authorized ? 'authorized' : 'qr_pending'},
      bot_token_ciphertext = ${botTokenCiphertext || null},
      base_url = ${baseUrl || authSession.base_url || null},
      get_updates_buf = ${status.getUpdatesBuf || authSession.get_updates_buf || null},
      confirmed_at = ${authorized ? now : authSession.confirmed_at},
      last_checked_at = ${now},
      error_message = ${failed ? `Clawbot status: ${status.status}` : null},
      updated_at = now()
    WHERE id = ${authSession.id}
  `;

  if (authorized) {
    await sql`
      UPDATE public.onboarding_sessions
      SET
        status = 'wechat_authorized',
        current_step = 'wechat',
        wechat_authorized_at = COALESCE(wechat_authorized_at, ${now}),
        updated_at = now()
      WHERE tenant_id = ${user.id}
    `;

    if (accountId || status.alreadyConnected) {
      binding = await upsertWechatBinding({
        user,
        authSessionId: authSession.id,
        accountId: accountId || `clawbot:${authSession.id}`,
        channelUserRef: status.userId || null,
        source: status.alreadyConnected ? 'qrcode_already_connected' : 'qrcode_confirmed',
      });
    }
  }

  await auditOnboardingEvent(user.id, authSession.onboarding_session_id, 'wechat_qr_status_checked', {
    auth_session_id: authSession.id,
    status: status.status,
    authorized,
    account_id_present: Boolean(accountId),
  });

  const updatedAuth = await loadAuthSession(user, authSession.id);
  return {
    auth: safeWechatAuth(updatedAuth),
    binding: safeWechatBinding(binding),
  };
}

export async function verifyWechatBindingConversation(user: AppUser, authSessionId: string) {
  const authSession = await loadAuthSession(user, authSessionId);
  const sql = sqlClient();
  const credential = await latestAuthorizedCredential(user.id);
  const ciphertext = credential?.bot_token_ciphertext || authSession.bot_token_ciphertext;
  if (!ciphertext) {
    throw new Error('微信 ClawBot 尚未完成扫码授权');
  }

  const botToken = decryptCredential(ciphertext);
  const updates = await requestClawbotUpdates(
    credential?.base_url || authSession.base_url,
    botToken,
    credential?.get_updates_buf || authSession.get_updates_buf
  );
  const bindCode = authSession.bind_code || '';
  const candidate = findBindingCandidate(updates.messages, bindCode);
  const now = nowIso();

  await sql`
    UPDATE public.wechat_bot_credentials
    SET get_updates_buf = ${updates.getUpdatesBuf || credential?.get_updates_buf || null},
      updated_at = now()
    WHERE tenant_id = ${user.id}
      AND credential_status = 'active'
  `;

  if (!candidate) {
    await sql`
      UPDATE public.wechat_clawbot_auth_sessions
      SET
        status = 'conversation_pending',
        get_updates_buf = ${updates.getUpdatesBuf || authSession.get_updates_buf || null},
        last_checked_at = ${now},
        error_message = ${`未收到包含绑定码 ${bindCode} 的微信消息`},
        updated_at = now()
      WHERE id = ${authSession.id}
    `;

    const updatedAuth = await loadAuthSession(user, authSession.id);
    return {
      auth: safeWechatAuth(updatedAuth),
      binding: null,
      pending: true,
    };
  }

  const binding = await upsertWechatBinding({
    user,
    authSessionId: authSession.id,
    accountId: candidate.toUserId || `clawbot:${authSession.id}`,
    channelUserRef: candidate.fromUserId,
    contextToken: candidate.contextToken,
    source: 'bind_code_message',
    bindCode,
  });
  const initialization = await deliverWechatInitializationAfterBinding({
    user,
    binding,
    toUserId: candidate.fromUserId,
    contextToken: candidate.contextToken,
  });

  await auditOnboardingEvent(user.id, authSession.onboarding_session_id, 'wechat_conversation_verified', {
    auth_session_id: authSession.id,
    from_user_id: candidate.fromUserId,
    to_user_id: candidate.toUserId,
    initialization,
  });

  const updatedAuth = await loadAuthSession(user, authSession.id);
  return {
    auth: safeWechatAuth(updatedAuth),
    binding: safeWechatBinding(binding),
    pending: false,
  };
}
