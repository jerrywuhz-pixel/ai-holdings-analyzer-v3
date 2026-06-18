import postgres from 'postgres';
import { ensureUserAccount } from '@/lib/account-store';
import type { AppUser } from '@/lib/supabase';
import { requireUser } from '@/lib/supabase';

declare global {
  // eslint-disable-next-line no-var
  var __aiHoldingsOnboardingSql: ReturnType<typeof postgres> | undefined;
}

export type OnboardingStep = 'profile' | 'wechat' | 'review' | 'done';

export interface OnboardingState {
  tenantId: string;
  userEmail: string | null;
  session: Record<string, any>;
  settings: Record<string, any> | null;
  latestWechatAuth: Record<string, any> | null;
  wechatBinding: Record<string, any> | null;
  checks: {
    profile: boolean;
    wechat: boolean;
  };
}

export interface TenantProfileInput {
  baseCurrency: string;
  timezone: string;
  primaryMarkets: string[];
  accountTypes: string[];
  riskProfile: string;
  sellPutEnabled: boolean;
}

function databaseUrl() {
  return process.env.WEBAPP_DATABASE_URL || process.env.DATABASE_URL || '';
}

function sqlClient() {
  const url = databaseUrl();
  if (!url) {
    throw new Error('注册初始化需要配置 DATABASE_URL 或 WEBAPP_DATABASE_URL');
  }

  if (!globalThis.__aiHoldingsOnboardingSql) {
    globalThis.__aiHoldingsOnboardingSql = postgres(url, {
      max: 4,
      idle_timeout: 20,
      connect_timeout: 10,
      prepare: false,
    });
  }

  return globalThis.__aiHoldingsOnboardingSql;
}

function displayNameFor(user: AppUser) {
  return user.name || user.email || `tenant-${user.id.slice(0, 8)}`;
}

function nowIso() {
  return new Date().toISOString();
}

function serializeDate(value: unknown) {
  if (value instanceof Date) return value.toISOString();
  return value ? String(value) : null;
}

export async function ensureOnboardingSchema() {
  const sql = sqlClient();

  await sql`
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'channel_type') THEN
        CREATE TYPE public.channel_type AS ENUM ('openclaw_wechat', 'hermes_wechat', 'webapp_inbox', 'email', 'push');
      ELSE
        ALTER TYPE public.channel_type ADD VALUE IF NOT EXISTS 'hermes_wechat';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'channel_binding_status') THEN
        CREATE TYPE public.channel_binding_status AS ENUM ('pending', 'active', 'paused', 'revoked');
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'onboarding_status') THEN
        CREATE TYPE public.onboarding_status AS ENUM (
          'created',
          'account_ready',
          'profile_configured',
          'wechat_qr_pending',
          'wechat_authorized',
          'wechat_conversation_verified',
          'broker_pairing',
          'broker_snapshot_ready',
          'data_initialized',
          'completed',
          'skipped_wechat',
          'skipped_broker'
        );
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'wechat_clawbot_auth_status') THEN
        CREATE TYPE public.wechat_clawbot_auth_status AS ENUM (
          'qr_pending',
          'authorized',
          'conversation_pending',
          'conversation_verified',
          'expired',
          'failed',
          'revoked'
        );
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'broker_connector_instance_status') THEN
        CREATE TYPE public.broker_connector_instance_status AS ENUM ('pairing', 'online', 'offline', 'revoked', 'error');
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'broker_connector_runtime_mode') THEN
        CREATE TYPE public.broker_connector_runtime_mode AS ENUM ('user_local_polling', 'relay_websocket', 'local_dev_direct');
      END IF;
    END
    $$;
  `;

  await sql`
    CREATE TABLE IF NOT EXISTS public.tenant_settings (
      tenant_id UUID PRIMARY KEY REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      base_currency TEXT NOT NULL DEFAULT 'USD',
      timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
      primary_markets TEXT[] NOT NULL DEFAULT ARRAY['US']::TEXT[],
      account_types TEXT[] NOT NULL DEFAULT ARRAY['margin']::TEXT[],
      sell_put_enabled BOOLEAN NOT NULL DEFAULT TRUE,
      risk_profile TEXT NOT NULL DEFAULT 'balanced',
      settings_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `;

  await sql`
    CREATE TABLE IF NOT EXISTS public.onboarding_sessions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      status public.onboarding_status NOT NULL DEFAULT 'created',
      current_step TEXT NOT NULL DEFAULT 'profile',
      profile_configured_at TIMESTAMPTZ,
      wechat_authorized_at TIMESTAMPTZ,
      wechat_conversation_verified_at TIMESTAMPTZ,
      broker_pairing_at TIMESTAMPTZ,
      broker_snapshot_ready_at TIMESTAMPTZ,
      data_initialized_at TIMESTAMPTZ,
      completed_at TIMESTAMPTZ,
      required_checks JSONB NOT NULL DEFAULT '{}'::jsonb,
      session_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (tenant_id)
    )
  `;

  await sql`
    CREATE TABLE IF NOT EXISTS public.wechat_clawbot_auth_sessions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      onboarding_session_id UUID REFERENCES public.onboarding_sessions(id) ON DELETE SET NULL,
      bot_type INTEGER NOT NULL DEFAULT 3,
      qrcode TEXT,
      qrcode_url TEXT,
      session_key TEXT,
      status public.wechat_clawbot_auth_status NOT NULL DEFAULT 'qr_pending',
      bot_token_ciphertext TEXT,
      base_url TEXT,
      get_updates_buf TEXT,
      bind_code TEXT,
      expires_at TIMESTAMPTZ,
      confirmed_at TIMESTAMPTZ,
      conversation_verified_at TIMESTAMPTZ,
      last_checked_at TIMESTAMPTZ,
      error_message TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `;
  await sql`ALTER TABLE public.wechat_clawbot_auth_sessions ADD COLUMN IF NOT EXISTS session_key TEXT`;
  await sql`CREATE INDEX IF NOT EXISTS idx_wechat_clawbot_auth_sessions_tenant ON public.wechat_clawbot_auth_sessions (tenant_id, status, created_at DESC)`;

  await sql`
    CREATE TABLE IF NOT EXISTS public.wechat_bot_credentials (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      clawbot_auth_session_id UUID REFERENCES public.wechat_clawbot_auth_sessions(id) ON DELETE SET NULL,
      bot_token_ciphertext TEXT NOT NULL,
      base_url TEXT NOT NULL,
      get_updates_buf TEXT,
      credential_status TEXT NOT NULL DEFAULT 'active',
      credential_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `;
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_wechat_bot_credentials_active
      ON public.wechat_bot_credentials (tenant_id)
      WHERE credential_status = 'active'
  `;

  await sql`
    CREATE TABLE IF NOT EXISTS public.channel_bindings (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      channel public.channel_type NOT NULL,
      openclaw_account_id TEXT NOT NULL,
      channel_account_id TEXT,
      channel_user_ref TEXT,
      account_label TEXT,
      human_name TEXT,
      session_space TEXT,
      memory_root TEXT,
      session_root TEXT,
      identity_root TEXT,
      data_root TEXT,
      binding_status public.channel_binding_status NOT NULL DEFAULT 'pending',
      is_primary BOOLEAN NOT NULL DEFAULT FALSE,
      bound_at TIMESTAMPTZ,
      last_seen_at TIMESTAMPTZ,
      binding_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT channel_bindings_openclaw_not_blank CHECK (btrim(openclaw_account_id) <> '')
    )
  `;
  await sql`ALTER TABLE public.channel_bindings ADD COLUMN IF NOT EXISTS channel_account_id TEXT`;
  await sql`UPDATE public.channel_bindings SET channel_account_id = openclaw_account_id WHERE channel_account_id IS NULL`;
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_tenant_channel_account
      ON public.channel_bindings (tenant_id, channel, openclaw_account_id)
  `;
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_tenant_channel_channel_account
      ON public.channel_bindings (tenant_id, channel, channel_account_id)
  `;
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_wechat_active
      ON public.channel_bindings (tenant_id, channel)
      WHERE channel IN ('openclaw_wechat', 'hermes_wechat')
        AND binding_status = 'active'
  `;
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_hermes_wechat_active
      ON public.channel_bindings (tenant_id, channel)
      WHERE channel = 'hermes_wechat'
        AND binding_status = 'active'
  `;
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_primary
      ON public.channel_bindings (tenant_id, channel)
      WHERE is_primary = TRUE
  `;

  await sql`
    CREATE TABLE IF NOT EXISTS public.onboarding_audit_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      onboarding_session_id UUID REFERENCES public.onboarding_sessions(id) ON DELETE SET NULL,
      event_type TEXT NOT NULL,
      event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `;
}

export async function ensureOnboardingSession(user: AppUser) {
  await ensureUserAccount(user);
  await ensureOnboardingSchema();

  const sql = sqlClient();
  const rows = await sql<Record<string, any>[]>`
    INSERT INTO public.onboarding_sessions (tenant_id, status, current_step, session_metadata)
    VALUES (
      ${user.id},
      'account_ready',
      'profile',
      ${sql.json({ email: user.email, initialized_from: 'webapp_registration' } as any)}
    )
    ON CONFLICT (tenant_id) DO UPDATE SET
      updated_at = now()
    RETURNING *
  `;

  return rows[0];
}

export async function auditOnboardingEvent(
  tenantId: string,
  onboardingSessionId: string | null | undefined,
  eventType: string,
  eventPayload: Record<string, unknown> = {}
) {
  await ensureOnboardingSchema();
  const sql = sqlClient();
  await sql`
    INSERT INTO public.onboarding_audit_events (
      tenant_id, onboarding_session_id, event_type, event_payload
    )
    VALUES (${tenantId}, ${onboardingSessionId || null}, ${eventType}, ${sql.json(eventPayload as any)})
  `;
}

export async function saveTenantProfile(user: AppUser, input: TenantProfileInput) {
  const session = await ensureOnboardingSession(user);
  const sql = sqlClient();
  const now = nowIso();

  await sql`
    INSERT INTO public.tenant_settings (
      tenant_id, base_currency, timezone, primary_markets, account_types,
      sell_put_enabled, risk_profile, settings_payload
    )
    VALUES (
      ${user.id},
      ${input.baseCurrency},
      ${input.timezone},
      ${input.primaryMarkets},
      ${input.accountTypes},
      ${input.sellPutEnabled},
      ${input.riskProfile},
      ${sql.json({ source: 'registration_onboarding', configured_at: now } as any)}
    )
    ON CONFLICT (tenant_id) DO UPDATE SET
      base_currency = EXCLUDED.base_currency,
      timezone = EXCLUDED.timezone,
      primary_markets = EXCLUDED.primary_markets,
      account_types = EXCLUDED.account_types,
      sell_put_enabled = EXCLUDED.sell_put_enabled,
      risk_profile = EXCLUDED.risk_profile,
      settings_payload = EXCLUDED.settings_payload,
      updated_at = now()
  `;

  await sql`
    UPDATE public.onboarding_sessions
    SET
      status = 'profile_configured',
      current_step = 'wechat',
      profile_configured_at = ${now},
      required_checks = ${sql.json({ profile: true, wechat: false } as any)},
      updated_at = now()
    WHERE tenant_id = ${user.id}
  `;

  await auditOnboardingEvent(user.id, session.id, 'profile_configured', {
    base_currency: input.baseCurrency,
    timezone: input.timezone,
    primary_markets: input.primaryMarkets,
    account_types: input.accountTypes,
    risk_profile: input.riskProfile,
  });
}

export async function completeOnboarding(tenantId: string) {
  await ensureOnboardingSchema();
  const sql = sqlClient();
  const now = nowIso();
  await sql`
    UPDATE public.onboarding_sessions
    SET
      status = 'completed',
      current_step = 'done',
      data_initialized_at = ${now},
      completed_at = ${now},
      required_checks = ${sql.json({ profile: true, wechat: true, system_market_data: 'admin_managed' } as any)},
      updated_at = now()
    WHERE tenant_id = ${tenantId}
  `;
}

export async function getOnboardingState(): Promise<OnboardingState> {
  const { user } = await requireUser();
  const session = await ensureOnboardingSession(user);
  const sql = sqlClient();

  const [
    settingsRows,
    wechatAuthRows,
    bindingRows,
  ] = await Promise.all([
    sql<Record<string, any>[]>`
      SELECT * FROM public.tenant_settings
      WHERE tenant_id = ${user.id}
      LIMIT 1
    `,
    sql<Record<string, any>[]>`
      SELECT
        id,
        tenant_id,
        onboarding_session_id,
        bot_type,
        qrcode,
        qrcode_url,
        session_key,
        status,
        base_url,
        get_updates_buf,
        bind_code,
        expires_at,
        confirmed_at,
        conversation_verified_at,
        last_checked_at,
        error_message,
        created_at,
        updated_at
      FROM public.wechat_clawbot_auth_sessions
      WHERE tenant_id = ${user.id}
      ORDER BY created_at DESC
      LIMIT 1
    `,
    sql<Record<string, any>[]>`
      SELECT * FROM public.channel_bindings
      WHERE tenant_id = ${user.id}
        AND channel IN ('hermes_wechat', 'openclaw_wechat')
        AND binding_status = 'active'
      ORDER BY updated_at DESC
      LIMIT 1
    `,
  ]);

  const settings = settingsRows[0] || null;
  const latestWechatAuth = wechatAuthRows[0] || null;
  const wechatBinding = bindingRows[0] || null;
  return {
    tenantId: user.id,
    userEmail: user.email ?? null,
    session,
    settings,
    latestWechatAuth,
    wechatBinding,
    checks: {
      profile: Boolean(settings),
      wechat: Boolean(wechatBinding),
    },
  };
}

export function isOnboardingComplete(state: OnboardingState) {
  return state.session.status === 'completed' && state.checks.profile && state.checks.wechat;
}

export function nextOnboardingPath(state: OnboardingState) {
  if (isOnboardingComplete(state)) return '/dashboard';
  if (!state.checks.profile) return '/onboarding/welcome';
  if (!state.checks.wechat) return '/onboarding/wechat';
  return '/onboarding/review';
}

export function safeWechatAuth(auth: Record<string, any> | null) {
  if (!auth) return null;
  return {
    id: auth.id,
    qrcode_url: auth.qrcode_url,
    session_key: auth.session_key,
    status: auth.status,
    bind_code: auth.bind_code,
    expires_at: serializeDate(auth.expires_at),
    confirmed_at: serializeDate(auth.confirmed_at),
    conversation_verified_at: serializeDate(auth.conversation_verified_at),
    last_checked_at: serializeDate(auth.last_checked_at),
    error_message: auth.error_message,
    created_at: serializeDate(auth.created_at),
  };
}

export function safeWechatBinding(binding: Record<string, any> | null) {
  if (!binding) return null;
  return {
    id: binding.id,
    channel_account_id: binding.channel_account_id || binding.openclaw_account_id,
    openclaw_account_id: binding.openclaw_account_id,
    channel_user_ref: binding.channel_user_ref,
    account_label: binding.account_label,
    binding_status: binding.binding_status,
    is_primary: binding.is_primary,
    bound_at: serializeDate(binding.bound_at),
    last_seen_at: serializeDate(binding.last_seen_at),
  };
}

export function userDisplayName(user: AppUser) {
  return displayNameFor(user);
}
