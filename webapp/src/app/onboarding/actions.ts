'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import {
  auditOnboardingEvent,
  getOnboardingState,
  completeOnboarding,
  saveTenantProfile,
} from '@/lib/onboarding';
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
  redirect('/onboarding/review');
}

export async function finishOnboarding() {
  const state = await getOnboardingState();
  if (!state.checks.profile) redirect('/onboarding/profile');

  await completeOnboarding(state.tenantId);

  await auditOnboardingEvent(state.tenantId, state.session.id, 'onboarding_completed', {
    completed_at: new Date().toISOString(),
  });

  revalidatePath('/dashboard');
  redirect('/onboarding/done');
}
