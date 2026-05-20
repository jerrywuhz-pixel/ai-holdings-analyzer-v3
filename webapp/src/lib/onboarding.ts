import type { AppUser } from '@/lib/supabase';
import { createAdminClient, requireUser } from '@/lib/supabase';

export type OnboardingStep = 'profile' | 'wechat' | 'broker' | 'review' | 'done';

export interface OnboardingState {
  tenantId: string;
  userEmail: string | null;
  session: Record<string, any>;
  settings: Record<string, any> | null;
  latestWechatAuth: Record<string, any> | null;
  wechatBinding: Record<string, any> | null;
  brokerConnector: Record<string, any> | null;
  checks: {
    profile: boolean;
    wechat: boolean;
    broker: boolean;
  };
}

async function ensureTenantAccount(user: AppUser) {
  const supabaseAdmin = createAdminClient();
  const displayName = user.email || `tenant-${user.id.slice(0, 8)}`;

  const { error: userError } = await supabaseAdmin
    .from('users')
    .upsert(
      {
        id: user.id,
        email: user.email,
        status: 'ACTIVE',
      },
      { onConflict: 'id' }
    );

  if (userError) {
    throw new Error(`Failed to initialize user profile: ${userError.message}`);
  }

  const { error: tenantError } = await supabaseAdmin
    .from('tenant_accounts')
    .upsert(
      {
        tenant_id: user.id,
        owner_user_id: user.id,
        display_name: displayName,
      },
      { onConflict: 'tenant_id' }
    );

  if (tenantError) {
    throw new Error(`Failed to initialize tenant account: ${tenantError.message}`);
  }
}

export async function ensureOnboardingSession(user: AppUser) {
  await ensureTenantAccount(user);

  const supabaseAdmin = createAdminClient();
  const { data: existing, error: existingError } = await supabaseAdmin
    .from('onboarding_sessions')
    .select('*')
    .eq('tenant_id', user.id)
    .maybeSingle();

  if (existingError) {
    throw new Error(`Failed to load onboarding session: ${existingError.message}`);
  }
  if (existing) {
    return existing as Record<string, any>;
  }

  const { data, error } = await supabaseAdmin
    .from('onboarding_sessions')
    .insert({
      tenant_id: user.id,
      status: 'account_ready',
      current_step: 'profile',
      session_metadata: {
        email: user.email,
        initialized_from: 'webapp_registration',
      },
    })
    .select('*')
    .single();

  if (error) {
    throw new Error(`Failed to initialize onboarding session: ${error.message}`);
  }

  return data as Record<string, any>;
}

export async function auditOnboardingEvent(
  tenantId: string,
  onboardingSessionId: string | null | undefined,
  eventType: string,
  eventPayload: Record<string, unknown> = {}
) {
  const supabaseAdmin = createAdminClient();
  const { error } = await supabaseAdmin.from('onboarding_audit_events').insert({
    tenant_id: tenantId,
    onboarding_session_id: onboardingSessionId,
    event_type: eventType,
    event_payload: eventPayload,
  });

  if (error) {
    throw new Error(`Failed to write onboarding audit event: ${error.message}`);
  }
}

export async function getOnboardingState(): Promise<OnboardingState> {
  const { user } = await requireUser();
  const session = await ensureOnboardingSession(user);
  const supabaseAdmin = createAdminClient();

  const [
    settingsResult,
    wechatAuthResult,
    bindingResult,
    connectorResult,
  ] = await Promise.all([
    supabaseAdmin
      .from('tenant_settings')
      .select('*')
      .eq('tenant_id', user.id)
      .maybeSingle(),
    supabaseAdmin
      .from('wechat_clawbot_auth_sessions')
      .select('*')
      .eq('tenant_id', user.id)
      .order('created_at', { ascending: false })
      .limit(1)
      .maybeSingle(),
    supabaseAdmin
      .from('channel_bindings')
      .select('*')
      .eq('tenant_id', user.id)
      .eq('channel', 'openclaw_wechat')
      .eq('binding_status', 'active')
      .order('updated_at', { ascending: false })
      .limit(1)
      .maybeSingle(),
    supabaseAdmin
      .from('broker_connector_instances')
      .select('*')
      .eq('tenant_id', user.id)
      .eq('broker', 'futu')
      .order('updated_at', { ascending: false })
      .limit(1)
      .maybeSingle(),
  ]);

  for (const result of [settingsResult, wechatAuthResult, bindingResult, connectorResult]) {
    if (result.error) {
      throw new Error(`Failed to load onboarding state: ${result.error.message}`);
    }
  }

  const settings = settingsResult.data as Record<string, any> | null;
  const latestWechatAuth = wechatAuthResult.data as Record<string, any> | null;
  const wechatBinding = bindingResult.data as Record<string, any> | null;
  const brokerConnector = connectorResult.data as Record<string, any> | null;

  return {
    tenantId: user.id,
    userEmail: user.email ?? null,
    session,
    settings,
    latestWechatAuth,
    wechatBinding,
    brokerConnector,
    checks: {
      profile: Boolean(settings),
      wechat: Boolean(wechatBinding),
      broker: Boolean(brokerConnector),
    },
  };
}

export function isOnboardingComplete(state: OnboardingState) {
  return state.session.status === 'completed' && state.checks.profile && state.checks.wechat && state.checks.broker;
}

export function nextOnboardingPath(state: OnboardingState) {
  if (isOnboardingComplete(state)) return '/';
  if (!state.checks.profile) return '/onboarding/profile';
  if (!state.checks.wechat) return '/onboarding/wechat';
  if (!state.checks.broker) return '/onboarding/broker';
  return '/onboarding/review';
}
