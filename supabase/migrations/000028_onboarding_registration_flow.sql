-- ============================================
-- Holdings 3.0 - Registration onboarding flow
-- ============================================

DO $$
BEGIN
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
END
$$;

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
);

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
);

CREATE TABLE IF NOT EXISTS public.wechat_clawbot_auth_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  onboarding_session_id UUID REFERENCES public.onboarding_sessions(id) ON DELETE SET NULL,
  bot_type INTEGER NOT NULL DEFAULT 3,
  qrcode TEXT,
  qrcode_url TEXT,
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
);

CREATE INDEX IF NOT EXISTS idx_wechat_clawbot_auth_sessions_tenant
  ON public.wechat_clawbot_auth_sessions (tenant_id, status, created_at DESC);

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
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_wechat_bot_credentials_active
  ON public.wechat_bot_credentials (tenant_id)
  WHERE credential_status = 'active';

CREATE TABLE IF NOT EXISTS public.onboarding_audit_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  onboarding_session_id UUID REFERENCES public.onboarding_sessions(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_tenant_settings_updated_at ON public.tenant_settings;
CREATE TRIGGER trg_tenant_settings_updated_at
  BEFORE UPDATE ON public.tenant_settings
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_onboarding_sessions_updated_at ON public.onboarding_sessions;
CREATE TRIGGER trg_onboarding_sessions_updated_at
  BEFORE UPDATE ON public.onboarding_sessions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_wechat_clawbot_auth_sessions_updated_at ON public.wechat_clawbot_auth_sessions;
CREATE TRIGGER trg_wechat_clawbot_auth_sessions_updated_at
  BEFORE UPDATE ON public.wechat_clawbot_auth_sessions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_wechat_bot_credentials_updated_at ON public.wechat_bot_credentials;
CREATE TRIGGER trg_wechat_bot_credentials_updated_at
  BEFORE UPDATE ON public.wechat_bot_credentials
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

ALTER TABLE public.tenant_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.onboarding_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wechat_clawbot_auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wechat_bot_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.onboarding_audit_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tenant_settings_select_tenant" ON public.tenant_settings;
CREATE POLICY "tenant_settings_select_tenant"
  ON public.tenant_settings FOR SELECT
  USING (tenant_id = public.current_tenant_id());

DROP POLICY IF EXISTS "onboarding_sessions_select_tenant" ON public.onboarding_sessions;
CREATE POLICY "onboarding_sessions_select_tenant"
  ON public.onboarding_sessions FOR SELECT
  USING (tenant_id = public.current_tenant_id());

DROP POLICY IF EXISTS "wechat_clawbot_auth_sessions_select_tenant" ON public.wechat_clawbot_auth_sessions;
CREATE POLICY "wechat_clawbot_auth_sessions_select_tenant"
  ON public.wechat_clawbot_auth_sessions FOR SELECT
  USING (tenant_id = public.current_tenant_id());

DROP POLICY IF EXISTS "wechat_bot_credentials_select_tenant" ON public.wechat_bot_credentials;
CREATE POLICY "wechat_bot_credentials_select_tenant"
  ON public.wechat_bot_credentials FOR SELECT
  USING (tenant_id = public.current_tenant_id());

DROP POLICY IF EXISTS "onboarding_audit_events_select_tenant" ON public.onboarding_audit_events;
CREATE POLICY "onboarding_audit_events_select_tenant"
  ON public.onboarding_audit_events FOR SELECT
  USING (tenant_id = public.current_tenant_id());

DROP POLICY IF EXISTS "tenant_settings_service_all" ON public.tenant_settings;
CREATE POLICY "tenant_settings_service_all"
  ON public.tenant_settings FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

DROP POLICY IF EXISTS "onboarding_sessions_service_all" ON public.onboarding_sessions;
CREATE POLICY "onboarding_sessions_service_all"
  ON public.onboarding_sessions FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

DROP POLICY IF EXISTS "wechat_clawbot_auth_sessions_service_all" ON public.wechat_clawbot_auth_sessions;
CREATE POLICY "wechat_clawbot_auth_sessions_service_all"
  ON public.wechat_clawbot_auth_sessions FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

DROP POLICY IF EXISTS "wechat_bot_credentials_service_all" ON public.wechat_bot_credentials;
CREATE POLICY "wechat_bot_credentials_service_all"
  ON public.wechat_bot_credentials FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

DROP POLICY IF EXISTS "onboarding_audit_events_service_all" ON public.onboarding_audit_events;
CREATE POLICY "onboarding_audit_events_service_all"
  ON public.onboarding_audit_events FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
