'use server';

import crypto from 'crypto';
import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { getDataServiceBaseUrl } from '@/lib/p0-api';
import {
  auditOnboardingEvent,
  getOnboardingState,
  completeOnboarding,
  createFutuPairing,
  saveTenantProfile,
} from '@/lib/onboarding';
import {
  refreshWechatBindingStatus,
  startWechatBindingSession,
  verifyWechatBindingConversation,
} from '@/lib/wechat-binding';
import { requireUser } from '@/lib/supabase';

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

export async function saveProfile(formData: FormData) {
  const { user } = await requireUser();
  const baseCurrency = formString(formData, 'base_currency', 'USD').toUpperCase();
  const timezone = formString(formData, 'timezone', 'Asia/Shanghai');
  const primaryMarkets = formStrings(formData, 'primary_markets', ['US']);
  const accountTypes = formStrings(formData, 'account_types', ['margin']);
  const riskProfile = formString(formData, 'risk_profile', 'balanced');
  const sellPutEnabled = formData.get('sell_put_enabled') === 'on';

  await saveTenantProfile(user, {
    baseCurrency,
    timezone,
    primaryMarkets,
    accountTypes,
    riskProfile,
    sellPutEnabled,
  });

  revalidatePath('/onboarding');
  redirect('/onboarding/wechat');
}

export async function startWechatBinding() {
  const { user } = await requireUser();
  await startWechatBindingSession(user);
  revalidatePath('/onboarding/wechat');
  redirect('/onboarding/wechat');
}

export async function refreshWechatStatus(formData: FormData) {
  const { user } = await requireUser();
  const authSessionId = formString(formData, 'auth_session_id');
  if (!authSessionId) redirect('/onboarding/wechat');

  await refreshWechatBindingStatus(user, authSessionId);
  revalidatePath('/onboarding/wechat');
  redirect('/onboarding/wechat');
}

export async function verifyWechatConversation(formData: FormData) {
  const { user } = await requireUser();
  const authSessionId = formString(formData, 'auth_session_id');
  if (!authSessionId) redirect('/onboarding/wechat');

  const result = await verifyWechatBindingConversation(user, authSessionId);
  revalidatePath('/onboarding/wechat');
  if (!result.binding) redirect('/onboarding/wechat');
  redirect('/onboarding/broker');
}

export async function startFutuPairing(formData: FormData) {
  const { user } = await requireUser();
  const connectorInstanceId = crypto.randomUUID();
  const deviceLabel = formString(formData, 'device_label', '本机 Futu OpenD');
  const baseUrl = getDataServiceBaseUrl();
  const pairingTokenConfigured = Boolean(process.env.FUTU_CONNECTOR_PAIRING_TOKEN);

  await createFutuPairing(user, {
    connectorInstanceId,
    deviceLabel,
    endpointRef: `${baseUrl}/api/v3/connectors/poll`,
    pollEndpoint: `${baseUrl}/api/v3/connectors/poll`,
    uploadEndpoint: `${baseUrl}/api/v3/connectors/upload`,
    pairingTokenConfigured,
  });

  revalidatePath('/onboarding/broker');
  redirect('/onboarding/review');
}

export async function finishOnboarding() {
  const state = await getOnboardingState();
  if (!state.checks.profile) redirect('/onboarding/profile');
  if (!state.checks.wechat) redirect('/onboarding/wechat');
  if (!state.checks.broker) redirect('/onboarding/broker');

  await completeOnboarding(state.tenantId);

  await auditOnboardingEvent(state.tenantId, state.session.id, 'onboarding_completed', {
    completed_at: new Date().toISOString(),
  });

  revalidatePath('/');
  redirect('/onboarding/done');
}
