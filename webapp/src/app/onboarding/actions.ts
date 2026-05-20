'use server';

import crypto from 'crypto';
import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import {
  decryptCredential,
  encryptCredential,
  findBindingCandidate,
  generateBindCode,
  requestClawbotQrSession,
  requestClawbotQrStatus,
  requestClawbotUpdates,
} from '@/lib/clawbot';
import { getDataServiceBaseUrl } from '@/lib/p0-api';
import {
  auditOnboardingEvent,
  ensureOnboardingSession,
  getOnboardingState,
} from '@/lib/onboarding';
import { createAdminClient, requireUser } from '@/lib/supabase';

function formString(formData: FormData, name: string, fallback = '') {
  const value = String(formData.get(name) || '').trim();
  return value || fallback;
}

function formStrings(formData: FormData, name: string, fallback: string[]) {
  const values = formData
    .getAll(name)
    .map((value) => String(value).trim())
    .filter(Boolean);
  return values.length ? values : fallback;
}

function nowIso() {
  return new Date().toISOString();
}

function assertSupabaseResult(error: { message: string } | null, action: string) {
  if (error) {
    throw new Error(`${action}: ${error.message}`);
  }
}

async function latestAuthorizedCredential(tenantId: string) {
  const supabaseAdmin = createAdminClient();
  const { data, error } = await supabaseAdmin
    .from('wechat_bot_credentials')
    .select('*')
    .eq('tenant_id', tenantId)
    .eq('credential_status', 'active')
    .order('created_at', { ascending: false })
    .limit(1)
    .maybeSingle();

  if (error) {
    throw new Error(`Failed to load WeChat credential: ${error.message}`);
  }

  return data as Record<string, any> | null;
}

async function storeWechatCredential(
  tenantId: string,
  authSessionId: string,
  botToken: string,
  baseUrl: string,
  getUpdatesBuf?: string | null,
  metadata: Record<string, unknown> = {}
) {
  const supabaseAdmin = createAdminClient();
  const ciphertext = encryptCredential(botToken);

  const { error: resetError } = await supabaseAdmin
    .from('wechat_bot_credentials')
    .update({ credential_status: 'replaced' })
    .eq('tenant_id', tenantId)
    .eq('credential_status', 'active');
  assertSupabaseResult(resetError, 'Failed to rotate WeChat credential');

  const { error } = await supabaseAdmin.from('wechat_bot_credentials').insert({
    tenant_id: tenantId,
    clawbot_auth_session_id: authSessionId,
    bot_token_ciphertext: ciphertext,
    base_url: baseUrl,
    get_updates_buf: getUpdatesBuf,
    credential_status: 'active',
    credential_metadata: metadata,
  });
  assertSupabaseResult(error, 'Failed to store WeChat credential');

  return ciphertext;
}

export async function saveProfile(formData: FormData) {
  const { user } = await requireUser();
  const session = await ensureOnboardingSession(user);
  const supabaseAdmin = createAdminClient();
  const now = nowIso();
  const baseCurrency = formString(formData, 'base_currency', 'USD').toUpperCase();
  const timezone = formString(formData, 'timezone', 'Asia/Shanghai');
  const primaryMarkets = formStrings(formData, 'primary_markets', ['US']);
  const accountTypes = formStrings(formData, 'account_types', ['margin']);
  const riskProfile = formString(formData, 'risk_profile', 'balanced');
  const sellPutEnabled = formData.get('sell_put_enabled') === 'on';

  const { error: settingsError } = await supabaseAdmin
    .from('tenant_settings')
    .upsert(
      {
        tenant_id: user.id,
        base_currency: baseCurrency,
        timezone,
        primary_markets: primaryMarkets,
        account_types: accountTypes,
        sell_put_enabled: sellPutEnabled,
        risk_profile: riskProfile,
        settings_payload: {
          source: 'registration_onboarding',
          configured_at: now,
        },
      },
      { onConflict: 'tenant_id' }
    );
  assertSupabaseResult(settingsError, 'Failed to save tenant settings');

  const { error: sessionError } = await supabaseAdmin
    .from('onboarding_sessions')
    .update({
      status: 'profile_configured',
      current_step: 'wechat',
      profile_configured_at: now,
      required_checks: {
        profile: true,
        wechat: false,
        broker: false,
      },
    })
    .eq('tenant_id', user.id);
  assertSupabaseResult(sessionError, 'Failed to update onboarding session');

  await auditOnboardingEvent(user.id, session.id, 'profile_configured', {
    base_currency: baseCurrency,
    timezone,
    primary_markets: primaryMarkets,
    account_types: accountTypes,
    risk_profile: riskProfile,
  });

  revalidatePath('/onboarding');
  redirect('/onboarding/wechat');
}

export async function startWechatBinding() {
  const { user } = await requireUser();
  const session = await ensureOnboardingSession(user);
  const supabaseAdmin = createAdminClient();
  const qr = await requestClawbotQrSession();
  const bindCode = generateBindCode();
  const expiresAt = new Date(Date.now() + 10 * 60 * 1000).toISOString();
  const now = nowIso();
  const botTokenCiphertext = qr.botToken ? encryptCredential(qr.botToken) : null;

  const { data, error } = await supabaseAdmin
    .from('wechat_clawbot_auth_sessions')
    .insert({
      tenant_id: user.id,
      onboarding_session_id: session.id,
      bot_type: 3,
      qrcode: qr.qrcode,
      qrcode_url: qr.qrcodeUrl,
      status: qr.botToken ? 'authorized' : 'qr_pending',
      bot_token_ciphertext: botTokenCiphertext,
      base_url: qr.baseUrl,
      get_updates_buf: qr.getUpdatesBuf,
      bind_code: bindCode,
      expires_at: expiresAt,
      confirmed_at: qr.botToken ? now : null,
    })
    .select('*')
    .single();
  assertSupabaseResult(error, 'Failed to create WeChat binding session');

  if (qr.botToken) {
    await storeWechatCredential(user.id, data.id, qr.botToken, qr.baseUrl || '', qr.getUpdatesBuf, {
      source: 'qrcode_session',
    });
  }

  const { error: sessionError } = await supabaseAdmin
    .from('onboarding_sessions')
    .update({
      status: qr.botToken ? 'wechat_authorized' : 'wechat_qr_pending',
      current_step: 'wechat',
      wechat_authorized_at: qr.botToken ? now : null,
    })
    .eq('tenant_id', user.id);
  assertSupabaseResult(sessionError, 'Failed to update WeChat onboarding state');

  await auditOnboardingEvent(user.id, session.id, 'wechat_qr_created', {
    auth_session_id: data.id,
    has_inline_token: Boolean(qr.botToken),
  });

  revalidatePath('/onboarding/wechat');
  redirect('/onboarding/wechat');
}

export async function refreshWechatStatus(formData: FormData) {
  const { user } = await requireUser();
  const authSessionId = formString(formData, 'auth_session_id');
  if (!authSessionId) redirect('/onboarding/wechat');

  const supabaseAdmin = createAdminClient();
  const { data: authSession, error: loadError } = await supabaseAdmin
    .from('wechat_clawbot_auth_sessions')
    .select('*')
    .eq('id', authSessionId)
    .eq('tenant_id', user.id)
    .single();
  assertSupabaseResult(loadError, 'Failed to load WeChat auth session');

  const status = await requestClawbotQrStatus(authSession.qrcode);
  const normalizedStatus = status.status.toLowerCase();
  const now = nowIso();
  const botToken = status.botToken;
  const baseUrl = status.baseUrl || authSession.base_url || '';
  const authorized = Boolean(botToken) || ['confirmed', 'authorized', 'success'].includes(normalizedStatus);
  const failed = ['expired', 'failed', 'revoked', 'cancelled', 'canceled'].includes(normalizedStatus);
  let botTokenCiphertext = authSession.bot_token_ciphertext;

  if (botToken) {
    botTokenCiphertext = await storeWechatCredential(
      user.id,
      authSession.id,
      botToken,
      baseUrl,
      status.getUpdatesBuf || authSession.get_updates_buf,
      { source: 'qrcode_status', raw_status: status.status }
    );
  }

  const { error: authUpdateError } = await supabaseAdmin
    .from('wechat_clawbot_auth_sessions')
    .update({
      status: failed ? 'failed' : authorized ? 'authorized' : 'qr_pending',
      bot_token_ciphertext: botTokenCiphertext,
      base_url: baseUrl || authSession.base_url,
      get_updates_buf: status.getUpdatesBuf || authSession.get_updates_buf,
      confirmed_at: authorized ? now : authSession.confirmed_at,
      last_checked_at: now,
      error_message: failed ? `Clawbot status: ${status.status}` : null,
    })
    .eq('id', authSession.id);
  assertSupabaseResult(authUpdateError, 'Failed to update WeChat auth session');

  if (authorized) {
    const { error: sessionError } = await supabaseAdmin
      .from('onboarding_sessions')
      .update({
        status: 'wechat_authorized',
        current_step: 'wechat',
        wechat_authorized_at: now,
      })
      .eq('tenant_id', user.id);
    assertSupabaseResult(sessionError, 'Failed to update onboarding session after WeChat authorization');
  }

  await auditOnboardingEvent(user.id, authSession.onboarding_session_id, 'wechat_qr_status_checked', {
    auth_session_id: authSession.id,
    status: status.status,
    authorized,
  });

  revalidatePath('/onboarding/wechat');
  redirect('/onboarding/wechat');
}

export async function verifyWechatConversation(formData: FormData) {
  const { user } = await requireUser();
  const authSessionId = formString(formData, 'auth_session_id');
  if (!authSessionId) redirect('/onboarding/wechat');

  const supabaseAdmin = createAdminClient();
  const { data: authSession, error: loadError } = await supabaseAdmin
    .from('wechat_clawbot_auth_sessions')
    .select('*')
    .eq('id', authSessionId)
    .eq('tenant_id', user.id)
    .single();
  assertSupabaseResult(loadError, 'Failed to load WeChat auth session');

  const credential = await latestAuthorizedCredential(user.id);
  const ciphertext = credential?.bot_token_ciphertext || authSession.bot_token_ciphertext;
  if (!ciphertext) {
    throw new Error('WeChat Clawbot is not authorized yet');
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

  await supabaseAdmin
    .from('wechat_bot_credentials')
    .update({ get_updates_buf: updates.getUpdatesBuf || credential?.get_updates_buf })
    .eq('tenant_id', user.id)
    .eq('credential_status', 'active');

  if (!candidate) {
    const { error } = await supabaseAdmin
      .from('wechat_clawbot_auth_sessions')
      .update({
        status: 'conversation_pending',
        get_updates_buf: updates.getUpdatesBuf || authSession.get_updates_buf,
        last_checked_at: now,
        error_message: `未收到包含绑定码 ${bindCode} 的微信消息`,
      })
      .eq('id', authSession.id);
    assertSupabaseResult(error, 'Failed to update WeChat conversation polling state');

    revalidatePath('/onboarding/wechat');
    redirect('/onboarding/wechat');
  }

  const openclawAccountId = candidate.toUserId || `clawbot:${authSession.id}`;
  const { error: resetError } = await supabaseAdmin
    .from('channel_bindings')
    .update({ is_primary: false })
    .eq('tenant_id', user.id)
    .eq('channel', 'openclaw_wechat');
  assertSupabaseResult(resetError, 'Failed to reset existing WeChat binding');

  const { error: bindingError } = await supabaseAdmin
    .from('channel_bindings')
    .upsert(
      {
        tenant_id: user.id,
        channel: 'openclaw_wechat',
        openclaw_account_id: openclawAccountId,
        channel_user_ref: candidate.fromUserId,
        account_label: '微信 ClawBot',
        human_name: user.email,
        session_space: `tenant:${user.id}:wechat`,
        binding_status: 'active',
        is_primary: true,
        bound_at: now,
        last_seen_at: now,
        binding_metadata: {
          source: 'registration_onboarding',
          auth_session_id: authSession.id,
          context_token: candidate.contextToken,
          bind_code: bindCode,
        },
      },
      { onConflict: 'tenant_id,channel,openclaw_account_id' }
    );
  assertSupabaseResult(bindingError, 'Failed to store WeChat channel binding');

  const { error: authUpdateError } = await supabaseAdmin
    .from('wechat_clawbot_auth_sessions')
    .update({
      status: 'conversation_verified',
      get_updates_buf: updates.getUpdatesBuf || authSession.get_updates_buf,
      conversation_verified_at: now,
      last_checked_at: now,
      error_message: null,
    })
    .eq('id', authSession.id);
  assertSupabaseResult(authUpdateError, 'Failed to update WeChat auth verification state');

  const { error: sessionError } = await supabaseAdmin
    .from('onboarding_sessions')
    .update({
      status: 'wechat_conversation_verified',
      current_step: 'broker',
      wechat_conversation_verified_at: now,
      required_checks: {
        profile: true,
        wechat: true,
        broker: false,
      },
    })
    .eq('tenant_id', user.id);
  assertSupabaseResult(sessionError, 'Failed to advance onboarding after WeChat verification');

  await auditOnboardingEvent(user.id, authSession.onboarding_session_id, 'wechat_conversation_verified', {
    auth_session_id: authSession.id,
    from_user_id: candidate.fromUserId,
    to_user_id: candidate.toUserId,
  });

  revalidatePath('/onboarding/wechat');
  redirect('/onboarding/broker');
}

export async function startFutuPairing(formData: FormData) {
  const { user } = await requireUser();
  const session = await ensureOnboardingSession(user);
  const supabaseAdmin = createAdminClient();
  const now = nowIso();
  const connectorInstanceId = crypto.randomUUID();
  const deviceLabel = formString(formData, 'device_label', '本机 Futu OpenD');
  const baseUrl = getDataServiceBaseUrl();
  const pairingTokenConfigured = Boolean(process.env.FUTU_CONNECTOR_PAIRING_TOKEN);

  const { error } = await supabaseAdmin.from('broker_connector_instances').insert({
    id: connectorInstanceId,
    tenant_id: user.id,
    broker: 'futu',
    connector_kind: 'futu_opend',
    runtime_mode: 'user_local_polling',
    device_label: deviceLabel,
    pairing_status: 'pairing',
    heartbeat_status: 'offline',
    capabilities: {
      positions: true,
      cash: true,
      option_chain: true,
      read_only: true,
    },
    permission_scope: 'read_only',
    endpoint_ref: `${baseUrl}/api/v3/connectors/poll`,
    instance_metadata: {
      source: 'registration_onboarding',
      pairing_token_configured: pairingTokenConfigured,
      poll_endpoint: `${baseUrl}/api/v3/connectors/poll`,
      upload_endpoint: `${baseUrl}/api/v3/connectors/upload`,
    },
  });
  assertSupabaseResult(error, 'Failed to create Futu connector pairing');

  const { error: sessionError } = await supabaseAdmin
    .from('onboarding_sessions')
    .update({
      status: 'broker_pairing',
      current_step: 'review',
      broker_pairing_at: now,
      required_checks: {
        profile: true,
        wechat: true,
        broker: true,
      },
    })
    .eq('tenant_id', user.id);
  assertSupabaseResult(sessionError, 'Failed to update onboarding after Futu pairing');

  await auditOnboardingEvent(user.id, session.id, 'futu_connector_pairing_created', {
    connector_instance_id: connectorInstanceId,
    pairing_token_configured: pairingTokenConfigured,
  });

  revalidatePath('/onboarding/broker');
  redirect('/onboarding/review');
}

export async function finishOnboarding() {
  const state = await getOnboardingState();
  if (!state.checks.profile) redirect('/onboarding/profile');
  if (!state.checks.wechat) redirect('/onboarding/wechat');
  if (!state.checks.broker) redirect('/onboarding/broker');

  const supabaseAdmin = createAdminClient();
  const now = nowIso();
  const { error } = await supabaseAdmin
    .from('onboarding_sessions')
    .update({
      status: 'completed',
      current_step: 'done',
      data_initialized_at: now,
      completed_at: now,
      required_checks: {
        profile: true,
        wechat: true,
        broker: true,
      },
    })
    .eq('tenant_id', state.tenantId);
  assertSupabaseResult(error, 'Failed to complete onboarding');

  await auditOnboardingEvent(state.tenantId, state.session.id, 'onboarding_completed', {
    completed_at: now,
  });

  revalidatePath('/');
  redirect('/onboarding/done');
}
