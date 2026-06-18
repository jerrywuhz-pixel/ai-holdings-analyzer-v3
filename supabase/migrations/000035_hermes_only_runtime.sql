-- Holdings 3.0 P0 — Hermes-only runtime compatibility
--
-- New cloud/lightweight deployments run Hermes only. OpenClaw-named columns are
-- kept as legacy aliases for existing data, but new channel semantics use
-- hermes_wechat + channel_account_id.

ALTER TYPE public.channel_type ADD VALUE IF NOT EXISTS 'hermes_wechat';

ALTER TABLE public.channel_bindings
  ADD COLUMN IF NOT EXISTS channel_account_id TEXT;

UPDATE public.channel_bindings
SET channel_account_id = openclaw_account_id
WHERE channel_account_id IS NULL
  AND openclaw_account_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_hermes_wechat_active
  ON public.channel_bindings (tenant_id, channel)
  WHERE channel = 'hermes_wechat'
    AND binding_status = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_hermes_wechat_account_active
  ON public.channel_bindings (channel_account_id)
  WHERE channel = 'hermes_wechat'
    AND binding_status = 'active'
    AND channel_account_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.hermes_heartbeat (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  instance_id TEXT NOT NULL,
  hermes_status TEXT NOT NULL DEFAULT 'healthy',
  deployment_mode TEXT NOT NULL DEFAULT 'lightweight_server',
  active_skills TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  runtime_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  reported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_hermes_heartbeat_instance
  ON public.hermes_heartbeat (instance_id);

CREATE INDEX IF NOT EXISTS idx_hermes_heartbeat_reported_at
  ON public.hermes_heartbeat (reported_at DESC);
