import {
  decryptCredential,
  encryptCredential,
  findBindingCandidate,
  generateBindCode,
  requestClawbotQrSession,
  requestClawbotQrStatus,
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

function redirectHostToBaseUrl(redirectHost?: string | null) {
  const host = redirectHost?.trim();
  if (!host) return '';
  return `https://${host.replace(/^https?:\/\//, '').replace(/\/+$/, '')}`;
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
    SET is_primary = false, updated_at = now()
    WHERE tenant_id = ${user.id}
      AND channel = 'openclaw_wechat'
  `;

  const rows = await sql<Record<string, any>[]>`
    INSERT INTO public.channel_bindings (
      tenant_id,
      channel,
      openclaw_account_id,
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
      'openclaw_wechat',
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
    ON CONFLICT (tenant_id, channel, openclaw_account_id) DO UPDATE SET
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
      current_step = 'broker',
      wechat_authorized_at = COALESCE(wechat_authorized_at, ${now}),
      wechat_conversation_verified_at = ${now},
      required_checks = ${sql.json({ profile: true, wechat: true, broker: false } as any)},
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

async function loadVerifiedWechatBinding(user: AppUser, authSessionId: string) {
  await ensureOnboardingSchema();
  const sql = sqlClient();
  const rows = await sql<Record<string, any>[]>`
    SELECT * FROM public.channel_bindings
    WHERE tenant_id = ${user.id}
      AND channel = 'openclaw_wechat'
      AND binding_status = 'active'
      AND COALESCE(binding_metadata->>'context_token', '') <> ''
      AND (
        binding_metadata->>'auth_session_id' = ${authSessionId}
        OR is_primary = true
      )
    ORDER BY
      CASE WHEN binding_metadata->>'auth_session_id' = ${authSessionId} THEN 0 ELSE 1 END,
      is_primary DESC,
      updated_at DESC
    LIMIT 1
  `;
  return rows[0] || null;
}

export async function startWechatBindingSession(user: AppUser) {
  const session = await ensureOnboardingSession(user);
  const sql = sqlClient();
  const credential = await latestAuthorizedCredential(user.id);
  const localTokenList = credential?.bot_token_ciphertext ? [decryptCredential(credential.bot_token_ciphertext)] : [];
  const qr = await requestClawbotQrSession(localTokenList);
  const bindCode = generateBindCode();
  const expiresAt = new Date(Date.now() + 5 * 60 * 1000).toISOString();
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
  options: { verifyCode?: string | null } = {}
) {
  const authSession = await loadAuthSession(user, authSessionId);
  const sql = sqlClient();
  const verifiedBinding = await loadVerifiedWechatBinding(user, authSession.id);
  if (authSession.conversation_verified_at || authSession.status === 'conversation_verified') {
    if (verifiedBinding) {
      const now = nowIso();
      await sql`
        UPDATE public.wechat_clawbot_auth_sessions
        SET
          status = 'conversation_verified',
          last_checked_at = ${now},
          error_message = null,
          updated_at = now()
        WHERE id = ${authSession.id}
          AND tenant_id = ${user.id}
      `;
      const updatedAuth = await loadAuthSession(user, authSession.id);
      return {
        auth: safeWechatAuth(updatedAuth),
        binding: safeWechatBinding(verifiedBinding),
      };
    }
  }

  const credential = await latestAuthorizedCredential(user.id);
  const hasStoredCredential = Boolean(authSession.bot_token_ciphertext || credential?.bot_token_ciphertext);
  const hasConfirmedCredential =
    hasStoredCredential &&
    Boolean(
      authSession.confirmed_at ||
        authSession.status === 'authorized' ||
        authSession.status === 'conversation_pending'
    );
  if (hasConfirmedCredential) {
    const now = nowIso();
    const nextStatus = authSession.status === 'conversation_pending' ? 'conversation_pending' : 'authorized';
    await sql`
      UPDATE public.wechat_clawbot_auth_sessions
      SET
        status = ${nextStatus},
        last_checked_at = ${now},
        error_message = null,
        updated_at = now()
      WHERE id = ${authSession.id}
        AND tenant_id = ${user.id}
    `;
    const updatedAuth = await loadAuthSession(user, authSession.id);
    return {
      auth: safeWechatAuth(updatedAuth),
      binding: null,
    };
  }

  const status = await requestClawbotQrStatus(authSession.qrcode, {
    baseUrl: authSession.base_url,
    verifyCode: options.verifyCode,
  });
  const normalizedStatus = status.status.toLowerCase();
  const now = nowIso();
  const botToken = status.botToken;
  const redirectBaseUrl = redirectHostToBaseUrl(status.redirectHost);
  const baseUrl = status.baseUrl || redirectBaseUrl || authSession.base_url || '';
  const authorized =
    Boolean(botToken) ||
    ((normalizedStatus === 'authorized' || normalizedStatus === 'success') && hasStoredCredential) ||
    (normalizedStatus === 'confirmed' && Boolean(botToken || authSession.bot_token_ciphertext)) ||
    Boolean(status.alreadyConnected && credential);
  const failed = ['expired', 'failed', 'revoked', 'cancelled', 'canceled', 'verify_code_blocked'].includes(normalizedStatus);
  let botTokenCiphertext = authSession.bot_token_ciphertext;
  const errorMessage = failed
    ? `Clawbot status: ${status.status}`
    : normalizedStatus === 'need_verifycode'
      ? '请输入手机微信显示的数字验证码'
      : null;

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
      error_message = ${errorMessage},
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
  }

  await auditOnboardingEvent(user.id, authSession.onboarding_session_id, 'wechat_qr_status_checked', {
    auth_session_id: authSession.id,
    status: status.status,
    authorized,
    account_id_present: Boolean(status.accountId),
  });

  const updatedAuth = await loadAuthSession(user, authSession.id);
  return {
    auth: safeWechatAuth(updatedAuth),
    binding: null,
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

  if (!candidate.contextToken || !candidate.fromUserId) {
    await sql`
      UPDATE public.wechat_clawbot_auth_sessions
      SET
        status = 'conversation_pending',
        get_updates_buf = ${updates.getUpdatesBuf || authSession.get_updates_buf || null},
        last_checked_at = ${now},
        error_message = '收到绑定码，但缺少微信会话上下文，请在当前 ClawBot 对话里重新发送绑定码',
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

  const credentialMetadata =
    credential?.credential_metadata && typeof credential.credential_metadata === 'object'
      ? credential.credential_metadata
      : {};
  const credentialAccountId =
    typeof credentialMetadata.account_id === 'string' && credentialMetadata.account_id.trim()
      ? credentialMetadata.account_id.trim()
      : null;
  const binding = await upsertWechatBinding({
    user,
    authSessionId: authSession.id,
    accountId: candidate.toUserId || credentialAccountId || `clawbot:${authSession.id}`,
    channelUserRef: candidate.fromUserId,
    contextToken: candidate.contextToken,
    source: 'bind_code_message',
    bindCode,
  });

  await auditOnboardingEvent(user.id, authSession.onboarding_session_id, 'wechat_conversation_verified', {
    auth_session_id: authSession.id,
    from_user_id: candidate.fromUserId,
    to_user_id: candidate.toUserId,
  });

  const updatedAuth = await loadAuthSession(user, authSession.id);
  return {
    auth: safeWechatAuth(updatedAuth),
    binding: safeWechatBinding(binding),
    pending: false,
  };
}
