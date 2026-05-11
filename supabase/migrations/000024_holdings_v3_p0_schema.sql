-- ============================================
-- AI Holdings Analyzer 3.0 P0 - Holdings Data Foundation
-- Tenant/channel/source/view/contracts/outbox/confirmation/Hermes foundation
-- ============================================

-- Helper: prefer tenant_id claim when present, otherwise fall back to auth.uid().
CREATE OR REPLACE FUNCTION public.current_tenant_id()
RETURNS UUID
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  claims_text TEXT;
  claims_json JSONB;
  tenant_text TEXT;
BEGIN
  claims_text := current_setting('request.jwt.claims', true);

  IF claims_text IS NOT NULL AND claims_text <> '' THEN
    claims_json := claims_text::jsonb;
    tenant_text := claims_json ->> 'tenant_id';

    IF tenant_text IS NOT NULL AND tenant_text <> '' THEN
      RETURN tenant_text::uuid;
    END IF;
  END IF;

  RETURN auth.uid();
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tenant_account_status') THEN
    CREATE TYPE public.tenant_account_status AS ENUM ('active', 'suspended', 'closed');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'channel_type') THEN
    CREATE TYPE public.channel_type AS ENUM ('openclaw_wechat', 'webapp_inbox', 'email', 'push');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'channel_binding_status') THEN
    CREATE TYPE public.channel_binding_status AS ENUM ('pending', 'active', 'paused', 'revoked');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'broker_name') THEN
    CREATE TYPE public.broker_name AS ENUM ('futu', 'longbridge', 'ptrade', 'manual');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'broker_auth_status') THEN
    CREATE TYPE public.broker_auth_status AS ENUM ('pending', 'connected', 'reauth_required', 'error', 'revoked');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'permission_scope') THEN
    CREATE TYPE public.permission_scope AS ENUM ('read_only', 'trade_draft_only', 'admin_write');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'asset_source_type') THEN
    CREATE TYPE public.asset_source_type AS ENUM ('manual', 'message_trade_input', 'broker_message', 'ocr', 'voice_asr', 'broker_api', 'derived');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'source_quality') THEN
    CREATE TYPE public.source_quality AS ENUM ('broker_verified', 'user_confirmed', 'estimated', 'conflicted', 'public_fallback');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'instrument_type') THEN
    CREATE TYPE public.instrument_type AS ENUM ('stock', 'etf', 'reit', 'adr', 'option_contract', 'index', 'cash');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'portfolio_view_type') THEN
    CREATE TYPE public.portfolio_view_type AS ENUM ('system_default', 'custom', 'watchlist', 'options_income');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'portfolio_position_status') THEN
    CREATE TYPE public.portfolio_position_status AS ENUM ('open', 'closing', 'closed', 'stale', 'disputed');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'reconciliation_status') THEN
    CREATE TYPE public.reconciliation_status AS ENUM ('matched', 'mismatch', 'unverified', 'needs_user_review');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'actionability_cap') THEN
    CREATE TYPE public.actionability_cap AS ENUM ('info_only', 'analysis_only', 'suggested_action', 'trade_draft', 'blocked');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'option_type') THEN
    CREATE TYPE public.option_type AS ENUM ('call', 'put');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'option_strategy') THEN
    CREATE TYPE public.option_strategy AS ENUM ('single_leg', 'cash_secured_put', 'covered_call', 'spread', 'unknown');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'position_side') THEN
    CREATE TYPE public.position_side AS ENUM ('long', 'short');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'assignment_intent') THEN
    CREATE TYPE public.assignment_intent AS ENUM ('willing_to_take', 'avoid_assignment', 'unknown');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'risk_level') THEN
    CREATE TYPE public.risk_level AS ENUM ('low', 'medium', 'high', 'admin');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'run_status') THEN
    CREATE TYPE public.run_status AS ENUM ('queued', 'running', 'partial', 'succeeded', 'failed', 'cancelled', 'timed_out');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'runtime_target') THEN
    CREATE TYPE public.runtime_target AS ENUM ('openclaw_side', 'hermes', 'domain_worker', 'system');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'trigger_type') THEN
    CREATE TYPE public.trigger_type AS ENUM ('wechat_message', 'webapp_action', 'cron', 'webhook', 'system_replay');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'run_contract_scope') THEN
    CREATE TYPE public.run_contract_scope AS ENUM ('canonical', 'narrowed', 'resume');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'context_pack_kind') THEN
    CREATE TYPE public.context_pack_kind AS ENUM ('page_context', 'research_bundle', 'replay_bundle', 'reply_context', 'memory_context', 'data_snapshot');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'pending_action_status') THEN
    CREATE TYPE public.pending_action_status AS ENUM ('drafting', 'awaiting_confirmation', 'confirmed', 'committing', 'committed', 'rejected', 'revoked', 'expired', 'deduplicated', 'failed_retryable', 'failed_terminal');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'confirmation_strength') THEN
    CREATE TYPE public.confirmation_strength AS ENUM ('light', 'structured', 'override', 'high_attention');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'confirmation_session_status') THEN
    CREATE TYPE public.confirmation_session_status AS ENUM ('active', 'consumed', 'expired', 'cancelled');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'confirmation_event_type') THEN
    CREATE TYPE public.confirmation_event_type AS ENUM ('created', 'presented', 'modified', 'confirmed', 'rejected', 'revoked', 'expired', 'duplicate_ignored', 'commit_succeeded', 'commit_failed');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'artifact_status') THEN
    CREATE TYPE public.artifact_status AS ENUM ('pending', 'ready', 'expired', 'deleted', 'failed');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'artifact_visibility') THEN
    CREATE TYPE public.artifact_visibility AS ENUM ('tenant', 'ops', 'internal');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'hermes_job_status') THEN
    CREATE TYPE public.hermes_job_status AS ENUM ('pending', 'running', 'waiting_tool', 'checkpointed', 'succeeded', 'failed', 'cancelled', 'timed_out');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'handoff_task_status') THEN
    CREATE TYPE public.handoff_task_status AS ENUM ('queued', 'running', 'waiting_external', 'partial', 'succeeded', 'failed', 'cancelled', 'failed_resumable', 'failed_terminal');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'handoff_event_type') THEN
    CREATE TYPE public.handoff_event_type AS ENUM ('accepted', 'queued', 'stage_started', 'stage_completed', 'waiting', 'checkpoint_saved', 'partial_ready', 'cancel_requested', 'cancelled', 'resumed', 'failed', 'succeeded');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'checkpoint_type') THEN
    CREATE TYPE public.checkpoint_type AS ENUM ('stage_checkpoint', 'data_checkpoint', 'artifact_checkpoint', 'resume_checkpoint');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'checkpoint_reuse_level') THEN
    CREATE TYPE public.checkpoint_reuse_level AS ENUM ('safe_reuse', 'refresh_before_resume', 'rerun_only');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'outbox_status') THEN
    CREATE TYPE public.outbox_status AS ENUM ('pending', 'sending', 'delivered', 'failed', 'retrying', 'expired', 'cancelled');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'message_event_type') THEN
    CREATE TYPE public.message_event_type AS ENUM ('queued', 'sending', 'delivered', 'failed', 'opened', 'acknowledged', 'expired');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tool_permission_class') THEN
    CREATE TYPE public.tool_permission_class AS ENUM ('read', 'controlled_write', 'proposal_write', 'admin_write');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tool_risk_class') THEN
    CREATE TYPE public.tool_risk_class AS ENUM ('low', 'medium', 'high');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tool_cost_class') THEN
    CREATE TYPE public.tool_cost_class AS ENUM ('free', 'metered', 'expensive');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tool_publish_status') THEN
    CREATE TYPE public.tool_publish_status AS ENUM ('draft', 'review', 'active', 'deprecated', 'blocked');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tool_rollout_mode') THEN
    CREATE TYPE public.tool_rollout_mode AS ENUM ('platform_default', 'canary', 'tenant_override');
  END IF;
END
$$;

ALTER TYPE public.asset_source_type ADD VALUE IF NOT EXISTS 'voice_asr';

CREATE TABLE IF NOT EXISTS public.tenant_accounts (
  tenant_id UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  owner_user_id UUID NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
  display_name TEXT,
  account_status public.tenant_account_status NOT NULL DEFAULT 'active',
  base_currency TEXT NOT NULL DEFAULT 'USD',
  quiet_hours JSONB NOT NULL DEFAULT '{}'::jsonb,
  account_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT tenant_accounts_same_owner CHECK (tenant_id = owner_user_id)
);

INSERT INTO public.tenant_accounts (tenant_id, owner_user_id, display_name)
SELECT
  u.id,
  u.id,
  COALESCE(u.wechat_nickname, u.email, 'tenant-' || left(u.id::text, 8))
FROM public.users u
ON CONFLICT (tenant_id) DO NOTHING;

CREATE OR REPLACE FUNCTION public.create_tenant_account()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  INSERT INTO public.tenant_accounts (tenant_id, owner_user_id, display_name)
  VALUES (
    NEW.id,
    NEW.id,
    COALESCE(NEW.wechat_nickname, NEW.email, 'tenant-' || left(NEW.id::text, 8))
  )
  ON CONFLICT (tenant_id) DO NOTHING;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_users_create_tenant_account ON public.users;
CREATE TRIGGER trg_users_create_tenant_account
  AFTER INSERT ON public.users
  FOR EACH ROW EXECUTE FUNCTION public.create_tenant_account();

CREATE TABLE IF NOT EXISTS public.channel_bindings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  channel public.channel_type NOT NULL,
  openclaw_account_id TEXT NOT NULL,
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
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_tenant_channel_account
  ON public.channel_bindings (tenant_id, channel, openclaw_account_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_primary
  ON public.channel_bindings (tenant_id, channel)
  WHERE is_primary = TRUE;

CREATE TABLE IF NOT EXISTS public.broker_connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  channel_binding_id UUID REFERENCES public.channel_bindings(id) ON DELETE SET NULL,
  broker public.broker_name NOT NULL,
  connection_label TEXT NOT NULL,
  permission_scope public.permission_scope NOT NULL DEFAULT 'read_only',
  auth_status public.broker_auth_status NOT NULL DEFAULT 'pending',
  connection_mode TEXT NOT NULL DEFAULT 'local_connector',
  connector_kind TEXT NOT NULL DEFAULT 'futu_opend',
  token_storage_mode TEXT NOT NULL DEFAULT 'not_stored',
  capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
  status_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_successful_sync_at TIMESTAMPTZ,
  last_error_at TIMESTAMPTZ,
  last_error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT broker_connections_read_only_p0 CHECK (permission_scope = 'read_only'),
  CONSTRAINT broker_connections_no_cloud_token CHECK (token_storage_mode IN ('not_stored', 'local_only'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_broker_connections_tenant_label
  ON public.broker_connections (tenant_id, connection_label);

CREATE INDEX IF NOT EXISTS idx_broker_connections_tenant_status
  ON public.broker_connections (tenant_id, auth_status, broker);

CREATE TABLE IF NOT EXISTS public.asset_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  source_key TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_type public.asset_source_type NOT NULL,
  provider TEXT NOT NULL,
  provider_account_ref TEXT,
  broker_connection_id UUID REFERENCES public.broker_connections(id) ON DELETE SET NULL,
  channel_binding_id UUID REFERENCES public.channel_bindings(id) ON DELETE SET NULL,
  priority INTEGER NOT NULL DEFAULT 100,
  source_quality public.source_quality NOT NULL DEFAULT 'estimated',
  lineage_policy JSONB NOT NULL DEFAULT '[]'::jsonb,
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT asset_sources_source_key_not_blank CHECK (btrim(source_key) <> ''),
  CONSTRAINT asset_sources_priority_positive CHECK (priority > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_sources_tenant_source_key
  ON public.asset_sources (tenant_id, source_key);

CREATE INDEX IF NOT EXISTS idx_asset_sources_tenant_type
  ON public.asset_sources (tenant_id, source_type, is_active);

CREATE TABLE IF NOT EXISTS public.instruments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol TEXT NOT NULL,
  provider_symbol TEXT,
  market TEXT NOT NULL,
  exchange TEXT,
  currency TEXT NOT NULL,
  instrument_type public.instrument_type NOT NULL,
  name TEXT,
  symbol_registry_id UUID REFERENCES public.symbol_registry(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'active',
  instrument_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT instruments_symbol_not_blank CHECK (btrim(symbol) <> ''),
  CONSTRAINT instruments_status_check CHECK (status IN ('active', 'inactive', 'expired'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_instruments_market_symbol_type
  ON public.instruments (market, symbol, instrument_type);

CREATE INDEX IF NOT EXISTS idx_instruments_symbol
  ON public.instruments (symbol, market);

CREATE TABLE IF NOT EXISTS public.equity_instruments (
  instrument_id UUID PRIMARY KEY REFERENCES public.instruments(id) ON DELETE CASCADE,
  equity_type public.instrument_type NOT NULL,
  sector TEXT,
  industry TEXT,
  country TEXT,
  lot_size NUMERIC(18,4),
  is_marginable BOOLEAN,
  is_shortable BOOLEAN,
  dividend_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  fundamentals_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT equity_instruments_type_check CHECK (equity_type IN ('stock', 'etf', 'reit', 'adr'))
);

CREATE TABLE IF NOT EXISTS public.option_contracts (
  instrument_id UUID PRIMARY KEY REFERENCES public.instruments(id) ON DELETE CASCADE,
  underlying_instrument_id UUID NOT NULL REFERENCES public.instruments(id) ON DELETE RESTRICT,
  option_type public.option_type NOT NULL,
  exercise_style TEXT,
  settlement_type TEXT,
  expiry_date DATE NOT NULL,
  strike NUMERIC(18,4) NOT NULL,
  contract_multiplier NUMERIC(18,4) NOT NULL DEFAULT 100,
  contract_symbol TEXT NOT NULL,
  deliverable JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT option_contracts_contract_symbol_not_blank CHECK (btrim(contract_symbol) <> ''),
  CONSTRAINT option_contracts_positive_strike CHECK (strike > 0),
  CONSTRAINT option_contracts_positive_multiplier CHECK (contract_multiplier > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_option_contracts_contract_symbol
  ON public.option_contracts (contract_symbol);

CREATE INDEX IF NOT EXISTS idx_option_contracts_underlying_expiry
  ON public.option_contracts (underlying_instrument_id, expiry_date, strike);

CREATE TABLE IF NOT EXISTS public.portfolio_views (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  view_type public.portfolio_view_type NOT NULL DEFAULT 'custom',
  base_currency TEXT NOT NULL DEFAULT 'USD',
  is_default BOOLEAN NOT NULL DEFAULT FALSE,
  market_filters TEXT[] NOT NULL DEFAULT '{}'::text[],
  source_filters JSONB NOT NULL DEFAULT '{}'::jsonb,
  sort_preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
  settings JSONB NOT NULL DEFAULT '{}'::jsonb,
  material_change_requires_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
  last_material_change_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT portfolio_views_slug_not_blank CHECK (btrim(slug) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_portfolio_views_tenant_slug
  ON public.portfolio_views (tenant_id, slug);

CREATE UNIQUE INDEX IF NOT EXISTS idx_portfolio_views_default
  ON public.portfolio_views (tenant_id)
  WHERE is_default = TRUE;

CREATE TABLE IF NOT EXISTS public.portfolio_view_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  portfolio_view_id UUID NOT NULL REFERENCES public.portfolio_views(id) ON DELETE CASCADE,
  asset_source_id UUID NOT NULL REFERENCES public.asset_sources(id) ON DELETE CASCADE,
  include_mode TEXT NOT NULL DEFAULT 'include',
  source_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
  display_rank INTEGER NOT NULL DEFAULT 100,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT portfolio_view_sources_include_mode CHECK (include_mode IN ('include', 'exclude', 'fallback')),
  CONSTRAINT portfolio_view_sources_rank_positive CHECK (display_rank > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_portfolio_view_sources_unique
  ON public.portfolio_view_sources (portfolio_view_id, asset_source_id);

CREATE INDEX IF NOT EXISTS idx_portfolio_view_sources_tenant_rank
  ON public.portfolio_view_sources (tenant_id, portfolio_view_id, display_rank);

CREATE TABLE IF NOT EXISTS public.agent_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  channel_binding_id UUID REFERENCES public.channel_bindings(id) ON DELETE SET NULL,
  parent_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  trigger public.trigger_type NOT NULL,
  entry_surface TEXT NOT NULL,
  intent TEXT NOT NULL,
  complexity TEXT NOT NULL,
  risk_level public.risk_level NOT NULL DEFAULT 'low',
  runtime_target public.runtime_target NOT NULL,
  actionability_cap public.actionability_cap NOT NULL DEFAULT 'info_only',
  status public.run_status NOT NULL DEFAULT 'queued',
  page_context JSONB NOT NULL DEFAULT '{}'::jsonb,
  input_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  output_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  idempotency_key TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  CONSTRAINT agent_runs_entry_surface_check CHECK (entry_surface IN ('wechat', 'webapp', 'system')),
  CONSTRAINT agent_runs_complexity_check CHECK (complexity IN ('quick', 'standard', 'deep', 'background')),
  CONSTRAINT agent_runs_idempotency_not_blank CHECK (btrim(idempotency_key) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_tenant_idempotency
  ON public.agent_runs (tenant_id, idempotency_key);

CREATE INDEX IF NOT EXISTS idx_agent_runs_tenant_status
  ON public.agent_runs (tenant_id, status, runtime_target, created_at DESC);

CREATE TABLE IF NOT EXISTS public.run_contracts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  agent_run_id UUID NOT NULL REFERENCES public.agent_runs(id) ON DELETE CASCADE,
  contract_scope public.run_contract_scope NOT NULL DEFAULT 'canonical',
  runtime_target public.runtime_target NOT NULL,
  policy_version TEXT NOT NULL DEFAULT 'v1',
  policy_hash TEXT NOT NULL,
  model_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  tool_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  memory_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  data_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  audit_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  contract_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT run_contracts_policy_hash_not_blank CHECK (btrim(policy_hash) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_run_contracts_run_scope
  ON public.run_contracts (agent_run_id, contract_scope);

CREATE INDEX IF NOT EXISTS idx_run_contracts_tenant_runtime
  ON public.run_contracts (tenant_id, runtime_target, created_at DESC);

CREATE TABLE IF NOT EXISTS public.context_packs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  agent_run_id UUID NOT NULL REFERENCES public.agent_runs(id) ON DELETE CASCADE,
  run_contract_id UUID REFERENCES public.run_contracts(id) ON DELETE SET NULL,
  pack_kind public.context_pack_kind NOT NULL,
  pack_key TEXT NOT NULL,
  manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
  storage_backend TEXT,
  storage_uri TEXT,
  payload_hash TEXT,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT context_packs_pack_key_not_blank CHECK (btrim(pack_key) <> ''),
  CONSTRAINT context_packs_storage_pair CHECK (
    (storage_backend IS NULL AND storage_uri IS NULL)
    OR (storage_backend IS NOT NULL AND storage_uri IS NOT NULL)
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_context_packs_run_key
  ON public.context_packs (agent_run_id, pack_key);

CREATE INDEX IF NOT EXISTS idx_context_packs_tenant_kind
  ON public.context_packs (tenant_id, pack_kind, created_at DESC);

CREATE TABLE IF NOT EXISTS public.broker_sync_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  broker_connection_id UUID NOT NULL REFERENCES public.broker_connections(id) ON DELETE CASCADE,
  asset_source_id UUID REFERENCES public.asset_sources(id) ON DELETE SET NULL,
  source_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  job_run_id UUID REFERENCES public.job_runs(id) ON DELETE SET NULL,
  sync_window_key TEXT NOT NULL,
  trigger public.trigger_type NOT NULL,
  status public.run_status NOT NULL DEFAULT 'queued',
  as_of TIMESTAMPTZ NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  coverage JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  missing_fields TEXT[] NOT NULL DEFAULT '{}'::text[],
  partial_components TEXT[] NOT NULL DEFAULT '{}'::text[],
  source_quality public.source_quality NOT NULL DEFAULT 'broker_verified',
  raw_payload_ref TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT broker_sync_snapshots_sync_window_not_blank CHECK (btrim(sync_window_key) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_broker_sync_snapshots_window
  ON public.broker_sync_snapshots (broker_connection_id, sync_window_key);

CREATE INDEX IF NOT EXISTS idx_broker_sync_snapshots_tenant_asof
  ON public.broker_sync_snapshots (tenant_id, as_of DESC);

CREATE TABLE IF NOT EXISTS public.broker_position_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  broker_sync_snapshot_id UUID NOT NULL REFERENCES public.broker_sync_snapshots(id) ON DELETE CASCADE,
  asset_source_id UUID REFERENCES public.asset_sources(id) ON DELETE SET NULL,
  instrument_id UUID REFERENCES public.instruments(id) ON DELETE SET NULL,
  instrument_type public.instrument_type NOT NULL,
  provider_symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  exchange TEXT,
  position_side public.position_side NOT NULL DEFAULT 'long',
  quantity NUMERIC(24,8) NOT NULL,
  average_cost NUMERIC(18,6),
  cost_basis NUMERIC(18,2),
  market_price NUMERIC(18,6),
  market_value NUMERIC(18,2),
  currency TEXT NOT NULL,
  source_quality public.source_quality NOT NULL DEFAULT 'broker_verified',
  reconciliation_status public.reconciliation_status NOT NULL DEFAULT 'unverified',
  position_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_lineage JSONB NOT NULL DEFAULT '[]'::jsonb,
  as_of TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT broker_position_snapshots_quantity_non_negative CHECK (quantity >= 0)
);

CREATE INDEX IF NOT EXISTS idx_broker_position_snapshots_snapshot
  ON public.broker_position_snapshots (broker_sync_snapshot_id, instrument_type);

CREATE INDEX IF NOT EXISTS idx_broker_position_snapshots_tenant_instrument
  ON public.broker_position_snapshots (tenant_id, instrument_id, as_of DESC);

CREATE TABLE IF NOT EXISTS public.cash_balance_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  broker_sync_snapshot_id UUID NOT NULL REFERENCES public.broker_sync_snapshots(id) ON DELETE CASCADE,
  broker_connection_id UUID NOT NULL REFERENCES public.broker_connections(id) ON DELETE CASCADE,
  asset_source_id UUID REFERENCES public.asset_sources(id) ON DELETE SET NULL,
  currency TEXT NOT NULL,
  total_cash NUMERIC(18,2),
  available_cash NUMERIC(18,2),
  settled_cash NUMERIC(18,2),
  withdrawable_cash NUMERIC(18,2),
  buying_power NUMERIC(18,2),
  source_quality public.source_quality NOT NULL DEFAULT 'broker_verified',
  balance_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_lineage JSONB NOT NULL DEFAULT '[]'::jsonb,
  as_of TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cash_balance_snapshots_unique
  ON public.cash_balance_snapshots (broker_sync_snapshot_id, currency);

CREATE TABLE IF NOT EXISTS public.margin_balance_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  broker_sync_snapshot_id UUID NOT NULL REFERENCES public.broker_sync_snapshots(id) ON DELETE CASCADE,
  broker_connection_id UUID NOT NULL REFERENCES public.broker_connections(id) ON DELETE CASCADE,
  asset_source_id UUID REFERENCES public.asset_sources(id) ON DELETE SET NULL,
  currency TEXT NOT NULL,
  margin_required NUMERIC(18,2),
  margin_available NUMERIC(18,2),
  maintenance_margin NUMERIC(18,2),
  option_buying_power NUMERIC(18,2),
  cash_secured_requirement NUMERIC(18,2),
  source_quality public.source_quality NOT NULL DEFAULT 'broker_verified',
  balance_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_lineage JSONB NOT NULL DEFAULT '[]'::jsonb,
  as_of TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_margin_balance_snapshots_unique
  ON public.margin_balance_snapshots (broker_sync_snapshot_id, currency);

CREATE TABLE IF NOT EXISTS public.market_snapshot_groups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  source_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  broker_connection_id UUID REFERENCES public.broker_connections(id) ON DELETE SET NULL,
  primary_source TEXT NOT NULL,
  cross_check_source TEXT,
  symbols TEXT[] NOT NULL DEFAULT '{}'::text[],
  as_of TIMESTAMPTZ NOT NULL,
  freshness_seconds INTEGER,
  cross_check_status TEXT NOT NULL DEFAULT 'unchecked',
  fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
  actionability_cap public.actionability_cap NOT NULL DEFAULT 'info_only',
  missing_fields TEXT[] NOT NULL DEFAULT '{}'::text[],
  quality_report JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT market_snapshot_groups_primary_not_blank CHECK (btrim(primary_source) <> ''),
  CONSTRAINT market_snapshot_groups_cross_check_status CHECK (cross_check_status IN ('matched', 'mismatch', 'unchecked')),
  CONSTRAINT market_snapshot_groups_freshness_non_negative CHECK (freshness_seconds IS NULL OR freshness_seconds >= 0)
);

CREATE INDEX IF NOT EXISTS idx_market_snapshot_groups_tenant_asof
  ON public.market_snapshot_groups (tenant_id, as_of DESC);

CREATE TABLE IF NOT EXISTS public.market_data_manifests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  market_snapshot_group_id UUID REFERENCES public.market_snapshot_groups(id) ON DELETE SET NULL,
  job_run_id UUID REFERENCES public.job_runs(id) ON DELETE SET NULL,
  source_key TEXT NOT NULL,
  market TEXT NOT NULL,
  symbol TEXT,
  instrument_id UUID REFERENCES public.instruments(id) ON DELETE SET NULL,
  instrument_type public.instrument_type NOT NULL,
  data_kind TEXT NOT NULL,
  interval TEXT NOT NULL,
  adjustment TEXT NOT NULL DEFAULT 'raw',
  coverage_start DATE NOT NULL,
  coverage_end DATE NOT NULL,
  as_of TIMESTAMPTZ,
  trading_days_expected INTEGER,
  trading_days_available INTEGER,
  missing_trading_days DATE[] NOT NULL DEFAULT '{}'::date[],
  storage_backend TEXT NOT NULL,
  storage_uri TEXT NOT NULL,
  row_count BIGINT,
  schema_version TEXT NOT NULL DEFAULT 'v1',
  checksum TEXT,
  quality_status TEXT NOT NULL,
  quality_report JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT market_data_manifests_source_not_blank CHECK (btrim(source_key) <> ''),
  CONSTRAINT market_data_manifests_storage_uri_not_blank CHECK (btrim(storage_uri) <> ''),
  CONSTRAINT market_data_manifests_coverage_valid CHECK (coverage_end >= coverage_start),
  CONSTRAINT market_data_manifests_quality_status CHECK (quality_status IN ('validated', 'partial', 'stale', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_market_data_manifests_tenant_created
  ON public.market_data_manifests (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_market_data_manifests_symbol_kind
  ON public.market_data_manifests (market, symbol, data_kind, interval);

CREATE TABLE IF NOT EXISTS public.portfolio_positions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  portfolio_view_id UUID NOT NULL REFERENCES public.portfolio_views(id) ON DELETE CASCADE,
  asset_source_id UUID NOT NULL REFERENCES public.asset_sources(id) ON DELETE RESTRICT,
  broker_connection_id UUID REFERENCES public.broker_connections(id) ON DELETE SET NULL,
  source_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  instrument_id UUID NOT NULL REFERENCES public.instruments(id) ON DELETE RESTRICT,
  instrument_type public.instrument_type NOT NULL,
  position_status public.portfolio_position_status NOT NULL DEFAULT 'open',
  quantity NUMERIC(24,8) NOT NULL,
  average_cost NUMERIC(18,6),
  cost_basis NUMERIC(18,2),
  market_price NUMERIC(18,6),
  market_value NUMERIC(18,2),
  currency TEXT NOT NULL,
  unrealized_pnl NUMERIC(18,2),
  realized_pnl NUMERIC(18,2),
  pnl_percent NUMERIC(10,4),
  source_quality public.source_quality NOT NULL DEFAULT 'estimated',
  as_of TIMESTAMPTZ NOT NULL,
  source_lineage JSONB NOT NULL DEFAULT '[]'::jsonb,
  reconciliation_status public.reconciliation_status NOT NULL DEFAULT 'unverified',
  actionability_cap public.actionability_cap NOT NULL DEFAULT 'info_only',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT portfolio_positions_quantity_non_negative CHECK (quantity >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_portfolio_positions_view_instrument
  ON public.portfolio_positions (portfolio_view_id, instrument_id);

CREATE INDEX IF NOT EXISTS idx_portfolio_positions_tenant_status
  ON public.portfolio_positions (tenant_id, position_status, as_of DESC);

CREATE TABLE IF NOT EXISTS public.equity_positions (
  position_id UUID PRIMARY KEY REFERENCES public.portfolio_positions(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  instrument_id UUID NOT NULL REFERENCES public.instruments(id) ON DELETE RESTRICT,
  shares NUMERIC(24,8) NOT NULL,
  avg_buy_price NUMERIC(18,6),
  latest_price NUMERIC(18,6),
  market_value NUMERIC(18,2),
  portfolio_weight NUMERIC(10,4),
  sector TEXT,
  industry TEXT,
  beta NUMERIC(10,6),
  dividend_yield NUMERIC(10,6),
  next_earnings_date DATE,
  stop_loss_price NUMERIC(18,6),
  take_profit_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
  technical_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  fundamental_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT equity_positions_shares_non_negative CHECK (shares >= 0)
);

CREATE INDEX IF NOT EXISTS idx_equity_positions_tenant_instrument
  ON public.equity_positions (tenant_id, instrument_id);

CREATE TABLE IF NOT EXISTS public.option_positions (
  position_id UUID PRIMARY KEY REFERENCES public.portfolio_positions(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  instrument_id UUID NOT NULL REFERENCES public.instruments(id) ON DELETE RESTRICT,
  underlying_instrument_id UUID NOT NULL REFERENCES public.instruments(id) ON DELETE RESTRICT,
  option_strategy public.option_strategy NOT NULL DEFAULT 'unknown',
  position_side public.position_side NOT NULL,
  option_type public.option_type NOT NULL,
  contracts NUMERIC(24,8) NOT NULL,
  contract_multiplier NUMERIC(18,4) NOT NULL DEFAULT 100,
  strike NUMERIC(18,4) NOT NULL,
  expiry_date DATE NOT NULL,
  dte INTEGER,
  avg_premium NUMERIC(18,6),
  mark_price NUMERIC(18,6),
  bid NUMERIC(18,6),
  ask NUMERIC(18,6),
  implied_volatility NUMERIC(10,6),
  delta NUMERIC(10,6),
  gamma NUMERIC(10,6),
  theta NUMERIC(10,6),
  vega NUMERIC(10,6),
  open_interest NUMERIC(18,2),
  volume NUMERIC(18,2),
  underlying_price NUMERIC(18,6),
  moneyness TEXT,
  breakeven_price NUMERIC(18,6),
  margin_required NUMERIC(18,2),
  cash_secured_amount NUMERIC(18,2),
  assignment_risk public.risk_level NOT NULL DEFAULT 'low',
  assignment_intent public.assignment_intent NOT NULL DEFAULT 'unknown',
  roll_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
  event_risk JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT option_positions_contracts_non_negative CHECK (contracts >= 0),
  CONSTRAINT option_positions_positive_strike CHECK (strike > 0),
  CONSTRAINT option_positions_positive_multiplier CHECK (contract_multiplier > 0),
  CONSTRAINT option_positions_moneyness_check CHECK (moneyness IS NULL OR moneyness IN ('itm', 'atm', 'otm')),
  CONSTRAINT option_positions_assignment_risk_check CHECK (assignment_risk IN ('low', 'medium', 'high'))
);

CREATE INDEX IF NOT EXISTS idx_option_positions_tenant_underlying
  ON public.option_positions (tenant_id, underlying_instrument_id, expiry_date);

CREATE TABLE IF NOT EXISTS public.pending_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  channel_binding_id UUID REFERENCES public.channel_bindings(id) ON DELETE SET NULL,
  source_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  source_agent_role TEXT,
  action_type TEXT NOT NULL,
  action_scope TEXT NOT NULL,
  target_entity_type TEXT NOT NULL,
  target_entity_id UUID,
  source_type public.asset_source_type NOT NULL,
  source_surface TEXT NOT NULL DEFAULT 'unknown',
  action_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  normalized_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  rule_check_ref TEXT,
  risk_review_ref TEXT,
  requires_override BOOLEAN NOT NULL DEFAULT FALSE,
  confirmation_strength public.confirmation_strength NOT NULL,
  risk_level public.risk_level NOT NULL,
  actionability_cap public.actionability_cap NOT NULL DEFAULT 'analysis_only',
  status public.pending_action_status NOT NULL DEFAULT 'drafting',
  fingerprint TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  expires_at TIMESTAMPTZ NOT NULL,
  confirmed_at TIMESTAMPTZ,
  committed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT pending_actions_fingerprint_not_blank CHECK (btrim(fingerprint) <> ''),
  CONSTRAINT pending_actions_version_positive CHECK (version > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_actions_tenant_fingerprint_version
  ON public.pending_actions (tenant_id, fingerprint, version);

CREATE INDEX IF NOT EXISTS idx_pending_actions_tenant_status_expiry
  ON public.pending_actions (tenant_id, status, expires_at);

CREATE TABLE IF NOT EXISTS public.confirmation_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pending_action_id UUID NOT NULL REFERENCES public.pending_actions(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  channel public.channel_type NOT NULL,
  channel_binding_id UUID REFERENCES public.channel_bindings(id) ON DELETE SET NULL,
  session_status public.confirmation_session_status NOT NULL DEFAULT 'active',
  session_token TEXT NOT NULL,
  presented_version INTEGER NOT NULL,
  decision_deadline TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ,
  cancel_reason TEXT,
  confirmation_deeplink TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT confirmation_sessions_token_not_blank CHECK (btrim(session_token) <> ''),
  CONSTRAINT confirmation_sessions_presented_version_positive CHECK (presented_version > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_confirmation_sessions_token
  ON public.confirmation_sessions (session_token);

CREATE UNIQUE INDEX IF NOT EXISTS idx_confirmation_sessions_active_pending_action
  ON public.confirmation_sessions (pending_action_id)
  WHERE session_status = 'active';

CREATE TABLE IF NOT EXISTS public.confirmation_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  pending_action_id UUID NOT NULL REFERENCES public.pending_actions(id) ON DELETE CASCADE,
  confirmation_session_id UUID REFERENCES public.confirmation_sessions(id) ON DELETE SET NULL,
  event_type public.confirmation_event_type NOT NULL,
  actor_type TEXT NOT NULL,
  actor_ref TEXT,
  event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT confirmation_events_actor_type_check CHECK (actor_type IN ('user', 'system', 'runtime'))
);

CREATE INDEX IF NOT EXISTS idx_confirmation_events_pending_action
  ON public.confirmation_events (pending_action_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.artifact_registry (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  source_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  run_contract_id UUID REFERENCES public.run_contracts(id) ON DELETE SET NULL,
  artifact_key TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  artifact_status public.artifact_status NOT NULL DEFAULT 'pending',
  visibility public.artifact_visibility NOT NULL DEFAULT 'tenant',
  storage_backend TEXT NOT NULL,
  storage_bucket TEXT,
  storage_path TEXT NOT NULL,
  mime_type TEXT,
  content_hash TEXT,
  source_lineage JSONB NOT NULL DEFAULT '[]'::jsonb,
  artifact_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  retention_until TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '90 days'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT artifact_registry_key_not_blank CHECK (btrim(artifact_key) <> ''),
  CONSTRAINT artifact_registry_path_not_blank CHECK (btrim(storage_path) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_artifact_registry_tenant_key
  ON public.artifact_registry (tenant_id, artifact_key);

CREATE INDEX IF NOT EXISTS idx_artifact_registry_tenant_type
  ON public.artifact_registry (tenant_id, artifact_type, created_at DESC);

CREATE TABLE IF NOT EXISTS public.hermes_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  source_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  channel_binding_id UUID REFERENCES public.channel_bindings(id) ON DELETE SET NULL,
  openclaw_account_id TEXT,
  job_run_id UUID REFERENCES public.job_runs(id) ON DELETE SET NULL,
  job_type TEXT NOT NULL,
  objective TEXT NOT NULL,
  complexity TEXT NOT NULL,
  status public.hermes_job_status NOT NULL DEFAULT 'pending',
  tool_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  input_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  output_artifact_id UUID REFERENCES public.artifact_registry(id) ON DELETE SET NULL,
  checkpoint_ref TEXT,
  model_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_heartbeat_at TIMESTAMPTZ,
  timeout_seconds INTEGER NOT NULL DEFAULT 1800,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT hermes_jobs_complexity_check CHECK (complexity IN ('quick', 'standard', 'deep', 'background')),
  CONSTRAINT hermes_jobs_timeout_positive CHECK (timeout_seconds > 0)
);

CREATE INDEX IF NOT EXISTS idx_hermes_jobs_tenant_status
  ON public.hermes_jobs (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.handoff_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  channel_binding_id UUID NOT NULL REFERENCES public.channel_bindings(id) ON DELETE CASCADE,
  openclaw_account_id TEXT NOT NULL,
  source_run_id UUID NOT NULL REFERENCES public.agent_runs(id) ON DELETE CASCADE,
  hermes_job_id UUID NOT NULL UNIQUE REFERENCES public.hermes_jobs(id) ON DELETE CASCADE,
  task_type TEXT NOT NULL,
  task_title TEXT NOT NULL,
  user_prompt TEXT,
  status public.handoff_task_status NOT NULL DEFAULT 'queued',
  user_visible_status TEXT NOT NULL,
  current_stage TEXT,
  stage_index INTEGER,
  stage_total INTEGER,
  progress_percent INTEGER,
  waiting_reason TEXT,
  latest_summary TEXT,
  latest_checkpoint_id UUID,
  last_heartbeat_at TIMESTAMPTZ,
  resume_capability TEXT NOT NULL DEFAULT 'none',
  push_mode TEXT NOT NULL DEFAULT 'completion_only',
  degradation_code TEXT,
  idempotency_key TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT handoff_tasks_progress_range CHECK (progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)),
  CONSTRAINT handoff_tasks_resume_capability CHECK (resume_capability IN ('available', 'needs_refresh', 'none')),
  CONSTRAINT handoff_tasks_push_mode CHECK (push_mode IN ('completion_only', 'stage_updates', 'muted')),
  CONSTRAINT handoff_tasks_idempotency_not_blank CHECK (btrim(idempotency_key) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_handoff_tasks_tenant_idempotency
  ON public.handoff_tasks (tenant_id, idempotency_key);

CREATE INDEX IF NOT EXISTS idx_handoff_tasks_tenant_status
  ON public.handoff_tasks (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.handoff_progress_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  handoff_task_id UUID NOT NULL REFERENCES public.handoff_tasks(id) ON DELETE CASCADE,
  seq_no BIGINT NOT NULL,
  event_type public.handoff_event_type NOT NULL,
  status_after public.handoff_task_status NOT NULL,
  user_visible_status TEXT NOT NULL,
  stage_key TEXT,
  stage_label TEXT,
  progress_percent INTEGER,
  summary TEXT,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT handoff_progress_events_progress_range CHECK (progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)),
  CONSTRAINT handoff_progress_events_unique_seq UNIQUE (handoff_task_id, seq_no)
);

CREATE INDEX IF NOT EXISTS idx_handoff_progress_events_task_created
  ON public.handoff_progress_events (handoff_task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.handoff_checkpoints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  handoff_task_id UUID NOT NULL REFERENCES public.handoff_tasks(id) ON DELETE CASCADE,
  checkpoint_type public.checkpoint_type NOT NULL,
  stage_key TEXT,
  stage_label TEXT,
  resume_token TEXT,
  data_reuse_level public.checkpoint_reuse_level NOT NULL,
  input_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  freshness_deadline TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_handoff_checkpoints_task_created
  ON public.handoff_checkpoints (handoff_task_id, created_at DESC);

ALTER TABLE public.handoff_tasks
  ADD CONSTRAINT handoff_tasks_latest_checkpoint_fk
  FOREIGN KEY (latest_checkpoint_id) REFERENCES public.handoff_checkpoints(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS public.handoff_control_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  handoff_task_id UUID NOT NULL REFERENCES public.handoff_tasks(id) ON DELETE CASCADE,
  action_type TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  request_channel TEXT NOT NULL,
  target_checkpoint_id UUID REFERENCES public.handoff_checkpoints(id) ON DELETE SET NULL,
  status TEXT NOT NULL,
  reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  applied_at TIMESTAMPTZ,
  CONSTRAINT handoff_control_actions_type CHECK (action_type IN ('cancel', 'resume', 'mute_push', 'retry_push')),
  CONSTRAINT handoff_control_actions_requested_by CHECK (requested_by IN ('user', 'system', 'ops')),
  CONSTRAINT handoff_control_actions_request_channel CHECK (request_channel IN ('wechat', 'webapp', 'ops_console')),
  CONSTRAINT handoff_control_actions_status CHECK (status IN ('pending', 'accepted', 'applied', 'rejected', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_handoff_control_actions_task_created
  ON public.handoff_control_actions (handoff_task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.delivery_outbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  channel_binding_id UUID NOT NULL REFERENCES public.channel_bindings(id) ON DELETE CASCADE,
  source_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  pending_action_id UUID REFERENCES public.pending_actions(id) ON DELETE SET NULL,
  confirmation_session_id UUID REFERENCES public.confirmation_sessions(id) ON DELETE SET NULL,
  handoff_task_id UUID REFERENCES public.handoff_tasks(id) ON DELETE SET NULL,
  artifact_id UUID REFERENCES public.artifact_registry(id) ON DELETE SET NULL,
  openclaw_account_id TEXT,
  content_type TEXT NOT NULL,
  content JSONB NOT NULL DEFAULT '{}'::jsonb,
  content_snapshot_hash TEXT NOT NULL,
  content_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  priority TEXT NOT NULL DEFAULT 'normal',
  dedupe_key TEXT NOT NULL,
  status public.outbox_status NOT NULL DEFAULT 'pending',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_retry_at TIMESTAMPTZ,
  last_attempt_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ,
  last_error TEXT,
  target_conversation TEXT,
  context_token TEXT,
  asset_source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  data_snapshot_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  held_reason TEXT,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT delivery_outbox_priority_check CHECK (priority IN ('normal', 'high')),
  CONSTRAINT delivery_outbox_hash_not_blank CHECK (btrim(content_snapshot_hash) <> ''),
  CONSTRAINT delivery_outbox_dedupe_not_blank CHECK (btrim(dedupe_key) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_outbox_tenant_dedupe
  ON public.delivery_outbox (tenant_id, dedupe_key);

CREATE INDEX IF NOT EXISTS idx_delivery_outbox_status_retry
  ON public.delivery_outbox (status, next_retry_at, created_at);

CREATE TABLE IF NOT EXISTS public.message_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  delivery_outbox_id UUID NOT NULL REFERENCES public.delivery_outbox(id) ON DELETE CASCADE,
  channel_binding_id UUID REFERENCES public.channel_bindings(id) ON DELETE SET NULL,
  delivery_run_id UUID REFERENCES public.delivery_runs(id) ON DELETE SET NULL,
  event_type public.message_event_type NOT NULL,
  event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_message_events_outbox_occurred
  ON public.message_events (delivery_outbox_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS public.tool_contract_families (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tool_name TEXT NOT NULL UNIQUE,
  tool_namespace TEXT NOT NULL,
  owner TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT tool_contract_families_name_not_blank CHECK (btrim(tool_name) <> ''),
  CONSTRAINT tool_contract_families_namespace_not_blank CHECK (btrim(tool_namespace) <> '')
);

CREATE TABLE IF NOT EXISTS public.tool_contract_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id UUID NOT NULL REFERENCES public.tool_contract_families(id) ON DELETE CASCADE,
  tool_version TEXT NOT NULL,
  input_schema_version TEXT NOT NULL,
  output_schema_version TEXT NOT NULL,
  permission_class public.tool_permission_class NOT NULL,
  risk_class public.tool_risk_class NOT NULL,
  cost_class public.tool_cost_class NOT NULL DEFAULT 'free',
  runtime_scope JSONB NOT NULL DEFAULT '[]'::jsonb,
  forbidden_runtimes JSONB NOT NULL DEFAULT '[]'::jsonb,
  requires_freshness_gate BOOLEAN NOT NULL DEFAULT FALSE,
  requires_reconciliation_gate BOOLEAN NOT NULL DEFAULT FALSE,
  requires_rule_check BOOLEAN NOT NULL DEFAULT FALSE,
  requires_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
  lineage_required BOOLEAN NOT NULL DEFAULT TRUE,
  idempotency_required BOOLEAN NOT NULL DEFAULT TRUE,
  timeout_ms INTEGER NOT NULL DEFAULT 30000,
  publish_status public.tool_publish_status NOT NULL DEFAULT 'draft',
  rollout_mode public.tool_rollout_mode NOT NULL DEFAULT 'platform_default',
  degradation_policy_key TEXT,
  handoff_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
  schema_uri TEXT,
  contract_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  published_at TIMESTAMPTZ,
  deprecated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT tool_contract_versions_timeout_positive CHECK (timeout_ms > 0),
  CONSTRAINT tool_contract_versions_unique_version UNIQUE (family_id, tool_version)
);

CREATE INDEX IF NOT EXISTS idx_tool_contract_versions_publish
  ON public.tool_contract_versions (publish_status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.tool_contract_bindings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id UUID NOT NULL REFERENCES public.tool_contract_families(id) ON DELETE CASCADE,
  capability_role TEXT NOT NULL,
  default_runtime public.runtime_target NOT NULL,
  allowed_intents JSONB NOT NULL DEFAULT '[]'::jsonb,
  max_actionability_cap public.actionability_cap NOT NULL DEFAULT 'info_only',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT tool_contract_bindings_role_not_blank CHECK (btrim(capability_role) <> ''),
  CONSTRAINT tool_contract_bindings_unique UNIQUE (family_id, capability_role)
);

CREATE TABLE IF NOT EXISTS public.tool_contract_overrides (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  family_id UUID NOT NULL REFERENCES public.tool_contract_families(id) ON DELETE CASCADE,
  contract_version_id UUID NOT NULL REFERENCES public.tool_contract_versions(id) ON DELETE CASCADE,
  override_type TEXT NOT NULL,
  override_reason TEXT NOT NULL,
  override_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  expires_at TIMESTAMPTZ,
  approved_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'active',
  CONSTRAINT tool_contract_overrides_type_check CHECK (override_type IN ('rollout_flag', 'feature_flag', 'emergency_block')),
  CONSTRAINT tool_contract_overrides_status_check CHECK (status IN ('active', 'expired', 'revoked'))
);

CREATE INDEX IF NOT EXISTS idx_tool_contract_overrides_tenant_status
  ON public.tool_contract_overrides (tenant_id, status, expires_at);

CREATE TABLE IF NOT EXISTS public.tool_contract_proposals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  family_id UUID NOT NULL REFERENCES public.tool_contract_families(id) ON DELETE CASCADE,
  from_contract_version_id UUID REFERENCES public.tool_contract_versions(id) ON DELETE SET NULL,
  proposed_version TEXT NOT NULL,
  proposal_type TEXT NOT NULL DEFAULT 'tool_contract_change',
  change_scope JSONB NOT NULL DEFAULT '[]'::jsonb,
  risk_level public.tool_risk_class NOT NULL,
  proposed_by TEXT NOT NULL,
  activation_mode TEXT NOT NULL DEFAULT 'manual_approval_required',
  status TEXT NOT NULL,
  rationale TEXT,
  eval_result JSONB NOT NULL DEFAULT '{}'::jsonb,
  review_notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT tool_contract_proposals_status_check CHECK (status IN ('draft', 'pending_review', 'approved', 'rejected', 'activated')),
  CONSTRAINT tool_contract_proposals_activation_mode_check CHECK (activation_mode IN ('manual_approval_required', 'auto_apply_low_risk'))
);

CREATE INDEX IF NOT EXISTS idx_tool_contract_proposals_family_status
  ON public.tool_contract_proposals (family_id, status, created_at DESC);

ALTER TABLE public.job_runs
  ADD COLUMN IF NOT EXISTS agent_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL;

ALTER TABLE public.job_runs
  ADD COLUMN IF NOT EXISTS runtime_target public.runtime_target;

ALTER TABLE public.job_runs
  ADD COLUMN IF NOT EXISTS broker_connection_id UUID REFERENCES public.broker_connections(id) ON DELETE SET NULL;

ALTER TABLE public.job_runs
  ADD COLUMN IF NOT EXISTS handoff_task_id UUID REFERENCES public.handoff_tasks(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_job_runs_agent_run_id
  ON public.job_runs (agent_run_id);

ALTER TABLE public.delivery_runs
  ADD COLUMN IF NOT EXISTS delivery_outbox_id UUID REFERENCES public.delivery_outbox(id) ON DELETE SET NULL;

ALTER TABLE public.delivery_runs
  ADD COLUMN IF NOT EXISTS channel_binding_id UUID REFERENCES public.channel_bindings(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_delivery_runs_outbox_id
  ON public.delivery_runs (delivery_outbox_id);

DROP TRIGGER IF EXISTS trg_tenant_accounts_updated_at ON public.tenant_accounts;
CREATE TRIGGER trg_tenant_accounts_updated_at
  BEFORE UPDATE ON public.tenant_accounts
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_channel_bindings_updated_at ON public.channel_bindings;
CREATE TRIGGER trg_channel_bindings_updated_at
  BEFORE UPDATE ON public.channel_bindings
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_broker_connections_updated_at ON public.broker_connections;
CREATE TRIGGER trg_broker_connections_updated_at
  BEFORE UPDATE ON public.broker_connections
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_asset_sources_updated_at ON public.asset_sources;
CREATE TRIGGER trg_asset_sources_updated_at
  BEFORE UPDATE ON public.asset_sources
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_instruments_updated_at ON public.instruments;
CREATE TRIGGER trg_instruments_updated_at
  BEFORE UPDATE ON public.instruments
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_equity_instruments_updated_at ON public.equity_instruments;
CREATE TRIGGER trg_equity_instruments_updated_at
  BEFORE UPDATE ON public.equity_instruments
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_option_contracts_updated_at ON public.option_contracts;
CREATE TRIGGER trg_option_contracts_updated_at
  BEFORE UPDATE ON public.option_contracts
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_portfolio_views_updated_at ON public.portfolio_views;
CREATE TRIGGER trg_portfolio_views_updated_at
  BEFORE UPDATE ON public.portfolio_views
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_portfolio_view_sources_updated_at ON public.portfolio_view_sources;
CREATE TRIGGER trg_portfolio_view_sources_updated_at
  BEFORE UPDATE ON public.portfolio_view_sources
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_run_contracts_updated_at ON public.run_contracts;
CREATE TRIGGER trg_run_contracts_updated_at
  BEFORE UPDATE ON public.run_contracts
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_context_packs_updated_at ON public.context_packs;
CREATE TRIGGER trg_context_packs_updated_at
  BEFORE UPDATE ON public.context_packs
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_broker_sync_snapshots_updated_at ON public.broker_sync_snapshots;
CREATE TRIGGER trg_broker_sync_snapshots_updated_at
  BEFORE UPDATE ON public.broker_sync_snapshots
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_market_snapshot_groups_updated_at ON public.market_snapshot_groups;
CREATE TRIGGER trg_market_snapshot_groups_updated_at
  BEFORE UPDATE ON public.market_snapshot_groups
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_market_data_manifests_updated_at ON public.market_data_manifests;
CREATE TRIGGER trg_market_data_manifests_updated_at
  BEFORE UPDATE ON public.market_data_manifests
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_portfolio_positions_updated_at ON public.portfolio_positions;
CREATE TRIGGER trg_portfolio_positions_updated_at
  BEFORE UPDATE ON public.portfolio_positions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_equity_positions_updated_at ON public.equity_positions;
CREATE TRIGGER trg_equity_positions_updated_at
  BEFORE UPDATE ON public.equity_positions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_option_positions_updated_at ON public.option_positions;
CREATE TRIGGER trg_option_positions_updated_at
  BEFORE UPDATE ON public.option_positions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_pending_actions_updated_at ON public.pending_actions;
CREATE TRIGGER trg_pending_actions_updated_at
  BEFORE UPDATE ON public.pending_actions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_confirmation_sessions_updated_at ON public.confirmation_sessions;
CREATE TRIGGER trg_confirmation_sessions_updated_at
  BEFORE UPDATE ON public.confirmation_sessions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_artifact_registry_updated_at ON public.artifact_registry;
CREATE TRIGGER trg_artifact_registry_updated_at
  BEFORE UPDATE ON public.artifact_registry
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_hermes_jobs_updated_at ON public.hermes_jobs;
CREATE TRIGGER trg_hermes_jobs_updated_at
  BEFORE UPDATE ON public.hermes_jobs
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_handoff_tasks_updated_at ON public.handoff_tasks;
CREATE TRIGGER trg_handoff_tasks_updated_at
  BEFORE UPDATE ON public.handoff_tasks
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_delivery_outbox_updated_at ON public.delivery_outbox;
CREATE TRIGGER trg_delivery_outbox_updated_at
  BEFORE UPDATE ON public.delivery_outbox
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_tool_contract_families_updated_at ON public.tool_contract_families;
CREATE TRIGGER trg_tool_contract_families_updated_at
  BEFORE UPDATE ON public.tool_contract_families
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_tool_contract_versions_updated_at ON public.tool_contract_versions;
CREATE TRIGGER trg_tool_contract_versions_updated_at
  BEFORE UPDATE ON public.tool_contract_versions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_tool_contract_bindings_updated_at ON public.tool_contract_bindings;
CREATE TRIGGER trg_tool_contract_bindings_updated_at
  BEFORE UPDATE ON public.tool_contract_bindings
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_tool_contract_overrides_updated_at ON public.tool_contract_overrides;
CREATE TRIGGER trg_tool_contract_overrides_updated_at
  BEFORE UPDATE ON public.tool_contract_overrides
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_tool_contract_proposals_updated_at ON public.tool_contract_proposals;
CREATE TRIGGER trg_tool_contract_proposals_updated_at
  BEFORE UPDATE ON public.tool_contract_proposals
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

ALTER TABLE public.tenant_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.broker_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.asset_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.instruments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.equity_instruments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.option_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.portfolio_views ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.portfolio_view_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.run_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.context_packs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.broker_sync_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.broker_position_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cash_balance_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.margin_balance_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.market_snapshot_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.market_data_manifests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.portfolio_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.equity_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.option_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pending_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.confirmation_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.confirmation_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.artifact_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hermes_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.handoff_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.handoff_progress_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.handoff_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.handoff_control_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.delivery_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.message_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tool_contract_families ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tool_contract_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tool_contract_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tool_contract_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tool_contract_proposals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_accounts_select_self"
  ON public.tenant_accounts FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "tenant_accounts_service_all"
  ON public.tenant_accounts FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "channel_bindings_select_tenant"
  ON public.channel_bindings FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "channel_bindings_service_all"
  ON public.channel_bindings FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "broker_connections_select_tenant"
  ON public.broker_connections FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "broker_connections_service_all"
  ON public.broker_connections FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "asset_sources_select_tenant"
  ON public.asset_sources FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "asset_sources_service_all"
  ON public.asset_sources FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "instruments_authenticated_select"
  ON public.instruments FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "instruments_anon_select"
  ON public.instruments FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "instruments_service_all"
  ON public.instruments FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "equity_instruments_authenticated_select"
  ON public.equity_instruments FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "equity_instruments_anon_select"
  ON public.equity_instruments FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "equity_instruments_service_all"
  ON public.equity_instruments FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "option_contracts_authenticated_select"
  ON public.option_contracts FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "option_contracts_anon_select"
  ON public.option_contracts FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "option_contracts_service_all"
  ON public.option_contracts FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "portfolio_views_select_tenant"
  ON public.portfolio_views FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "portfolio_views_insert_tenant"
  ON public.portfolio_views FOR INSERT
  WITH CHECK (tenant_id = public.current_tenant_id());

CREATE POLICY "portfolio_views_update_tenant"
  ON public.portfolio_views FOR UPDATE
  USING (tenant_id = public.current_tenant_id())
  WITH CHECK (tenant_id = public.current_tenant_id());

CREATE POLICY "portfolio_views_delete_tenant"
  ON public.portfolio_views FOR DELETE
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "portfolio_views_service_all"
  ON public.portfolio_views FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "portfolio_view_sources_select_tenant"
  ON public.portfolio_view_sources FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "portfolio_view_sources_insert_tenant"
  ON public.portfolio_view_sources FOR INSERT
  WITH CHECK (tenant_id = public.current_tenant_id());

CREATE POLICY "portfolio_view_sources_update_tenant"
  ON public.portfolio_view_sources FOR UPDATE
  USING (tenant_id = public.current_tenant_id())
  WITH CHECK (tenant_id = public.current_tenant_id());

CREATE POLICY "portfolio_view_sources_delete_tenant"
  ON public.portfolio_view_sources FOR DELETE
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "portfolio_view_sources_service_all"
  ON public.portfolio_view_sources FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "agent_runs_select_tenant"
  ON public.agent_runs FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "agent_runs_service_all"
  ON public.agent_runs FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "run_contracts_select_tenant"
  ON public.run_contracts FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "run_contracts_service_all"
  ON public.run_contracts FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "context_packs_select_tenant"
  ON public.context_packs FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "context_packs_service_all"
  ON public.context_packs FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "broker_sync_snapshots_select_tenant"
  ON public.broker_sync_snapshots FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "broker_sync_snapshots_service_all"
  ON public.broker_sync_snapshots FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "broker_position_snapshots_select_tenant"
  ON public.broker_position_snapshots FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "broker_position_snapshots_service_all"
  ON public.broker_position_snapshots FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "cash_balance_snapshots_select_tenant"
  ON public.cash_balance_snapshots FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "cash_balance_snapshots_service_all"
  ON public.cash_balance_snapshots FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "margin_balance_snapshots_select_tenant"
  ON public.margin_balance_snapshots FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "margin_balance_snapshots_service_all"
  ON public.margin_balance_snapshots FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "market_snapshot_groups_select_tenant"
  ON public.market_snapshot_groups FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "market_snapshot_groups_service_all"
  ON public.market_snapshot_groups FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "market_data_manifests_select_scope"
  ON public.market_data_manifests FOR SELECT
  USING (tenant_id IS NULL OR tenant_id = public.current_tenant_id());

CREATE POLICY "market_data_manifests_service_all"
  ON public.market_data_manifests FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "portfolio_positions_select_tenant"
  ON public.portfolio_positions FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "portfolio_positions_service_all"
  ON public.portfolio_positions FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "equity_positions_select_tenant"
  ON public.equity_positions FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "equity_positions_service_all"
  ON public.equity_positions FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "option_positions_select_tenant"
  ON public.option_positions FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "option_positions_service_all"
  ON public.option_positions FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "pending_actions_select_tenant"
  ON public.pending_actions FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "pending_actions_service_all"
  ON public.pending_actions FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "confirmation_sessions_select_tenant"
  ON public.confirmation_sessions FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "confirmation_sessions_service_all"
  ON public.confirmation_sessions FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "confirmation_events_select_tenant"
  ON public.confirmation_events FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "confirmation_events_service_all"
  ON public.confirmation_events FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "artifact_registry_select_tenant"
  ON public.artifact_registry FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "artifact_registry_service_all"
  ON public.artifact_registry FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "hermes_jobs_select_tenant"
  ON public.hermes_jobs FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "hermes_jobs_service_all"
  ON public.hermes_jobs FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "handoff_tasks_select_tenant"
  ON public.handoff_tasks FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "handoff_tasks_service_all"
  ON public.handoff_tasks FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "handoff_progress_events_select_tenant"
  ON public.handoff_progress_events FOR SELECT
  USING (
    handoff_task_id IN (
      SELECT id FROM public.handoff_tasks WHERE tenant_id = public.current_tenant_id()
    )
  );

CREATE POLICY "handoff_progress_events_service_all"
  ON public.handoff_progress_events FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "handoff_checkpoints_select_tenant"
  ON public.handoff_checkpoints FOR SELECT
  USING (
    handoff_task_id IN (
      SELECT id FROM public.handoff_tasks WHERE tenant_id = public.current_tenant_id()
    )
  );

CREATE POLICY "handoff_checkpoints_service_all"
  ON public.handoff_checkpoints FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "handoff_control_actions_select_tenant"
  ON public.handoff_control_actions FOR SELECT
  USING (
    handoff_task_id IN (
      SELECT id FROM public.handoff_tasks WHERE tenant_id = public.current_tenant_id()
    )
  );

CREATE POLICY "handoff_control_actions_service_all"
  ON public.handoff_control_actions FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "delivery_outbox_select_tenant"
  ON public.delivery_outbox FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "delivery_outbox_service_all"
  ON public.delivery_outbox FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "message_events_select_tenant"
  ON public.message_events FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "message_events_service_all"
  ON public.message_events FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "tool_contract_families_select_all"
  ON public.tool_contract_families FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "tool_contract_families_service_all"
  ON public.tool_contract_families FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "tool_contract_versions_select_all"
  ON public.tool_contract_versions FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "tool_contract_versions_service_all"
  ON public.tool_contract_versions FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "tool_contract_bindings_select_all"
  ON public.tool_contract_bindings FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "tool_contract_bindings_service_all"
  ON public.tool_contract_bindings FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "tool_contract_overrides_select_scope"
  ON public.tool_contract_overrides FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "tool_contract_overrides_service_all"
  ON public.tool_contract_overrides FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "tool_contract_proposals_select_scope"
  ON public.tool_contract_proposals FOR SELECT
  USING (tenant_id IS NULL OR tenant_id = public.current_tenant_id());

CREATE POLICY "tool_contract_proposals_service_all"
  ON public.tool_contract_proposals FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

COMMENT ON FUNCTION public.current_tenant_id() IS
  'Returns tenant_id from JWT claims when available; falls back to auth.uid() for legacy 2.0 flows.';

COMMENT ON TABLE public.tenant_accounts IS
  '3.0 tenant root. P0 keeps a 1:1 mapping with public.users while preserving an explicit tenant contract.';

COMMENT ON TABLE public.broker_connections IS
  'Broker connection metadata only. P0 is read-only and must not store production broker tokens in cloud.';

COMMENT ON COLUMN public.broker_connections.permission_scope IS
  'Hard-pinned to read_only in P0. No place_order, modify_order, or cancel_order capability is allowed.';

COMMENT ON TABLE public.asset_sources IS
  'Source lineage root for manual input, broker snapshots, OCR, message parsing, and derived facts.';

COMMENT ON TABLE public.portfolio_views IS
  'Display and aggregation scope only. portfolio_views are not broker accounts and are not fact sources.';

COMMENT ON TABLE public.market_data_manifests IS
  'Manifest registry for historical and snapshot-derived market data payloads stored in object storage.';

COMMENT ON TABLE public.portfolio_positions IS
  'Derived portfolio read-model skeleton. Service writes only; agents and clients must not write holdings facts directly.';

COMMENT ON TABLE public.pending_actions IS
  'Controlled-write queue for confirmations. confirmed and committed are intentionally separate states.';

COMMENT ON TABLE public.artifact_registry IS
  'DB metadata registry for Hermes/OpenClaw artifacts stored in Supabase Storage or compatible object storage.';

COMMENT ON TABLE public.hermes_jobs IS
  'Hermes runtime execution state. Hermes may create artifacts, proposals, and pending confirmations but must not write core holdings facts.';

COMMENT ON TABLE public.delivery_outbox IS
  'Shared outbox fact source for WeChat and WebApp inbox. Delivery retries must fan out from this table instead of direct sends.';

COMMENT ON TABLE public.tool_contract_families IS
  'Tool registry root. P0 should seed broker read families only and intentionally excludes broker.order.* contracts.';

COMMENT ON TABLE public.tool_contract_versions IS
  'Versioned contract snapshots used by Tool Policy Gate and replay/audit flows.';
