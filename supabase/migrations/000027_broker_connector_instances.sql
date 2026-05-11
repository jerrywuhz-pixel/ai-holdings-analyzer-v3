-- ============================================
-- Holdings 3.0 P0 - User-local broker connector instances
-- ============================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'broker_connector_instance_status') THEN
    CREATE TYPE public.broker_connector_instance_status AS ENUM ('pairing', 'online', 'offline', 'revoked', 'error');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'broker_connector_runtime_mode') THEN
    CREATE TYPE public.broker_connector_runtime_mode AS ENUM ('user_local_polling', 'relay_websocket', 'local_dev_direct');
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS public.broker_connector_instances (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  channel_binding_id UUID REFERENCES public.channel_bindings(id) ON DELETE SET NULL,
  broker public.broker_name NOT NULL,
  connector_kind TEXT NOT NULL DEFAULT 'futu_opend',
  runtime_mode public.broker_connector_runtime_mode NOT NULL DEFAULT 'user_local_polling',
  device_label TEXT NOT NULL,
  device_fingerprint_hash TEXT,
  pairing_status public.broker_connector_instance_status NOT NULL DEFAULT 'pairing',
  heartbeat_status public.broker_connector_instance_status NOT NULL DEFAULT 'offline',
  connector_version TEXT,
  capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
  permission_scope public.permission_scope NOT NULL DEFAULT 'read_only',
  endpoint_ref TEXT,
  last_seen_at TIMESTAMPTZ,
  last_successful_sync_at TIMESTAMPTZ,
  last_error_at TIMESTAMPTZ,
  last_error_message TEXT,
  instance_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT broker_connector_instances_read_only_p0 CHECK (permission_scope = 'read_only'),
  CONSTRAINT broker_connector_instances_device_label_not_blank CHECK (btrim(device_label) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_broker_connector_instances_device
  ON public.broker_connector_instances (tenant_id, device_fingerprint_hash)
  WHERE device_fingerprint_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_broker_connector_instances_tenant_status
  ON public.broker_connector_instances (tenant_id, heartbeat_status, broker, last_seen_at DESC);

ALTER TABLE public.broker_connections
  ADD COLUMN IF NOT EXISTS connector_instance_id UUID REFERENCES public.broker_connector_instances(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS connector_runtime_mode public.broker_connector_runtime_mode NOT NULL DEFAULT 'local_dev_direct';

CREATE INDEX IF NOT EXISTS idx_broker_connections_connector_instance
  ON public.broker_connections (connector_instance_id);

DROP TRIGGER IF EXISTS trg_broker_connector_instances_updated_at ON public.broker_connector_instances;
CREATE TRIGGER trg_broker_connector_instances_updated_at
  BEFORE UPDATE ON public.broker_connector_instances
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

ALTER TABLE public.broker_connector_instances ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "broker_connector_instances_select_tenant" ON public.broker_connector_instances;
CREATE POLICY "broker_connector_instances_select_tenant"
  ON public.broker_connector_instances FOR SELECT
  USING (tenant_id = public.current_tenant_id());

DROP POLICY IF EXISTS "broker_connector_instances_service_all" ON public.broker_connector_instances;
CREATE POLICY "broker_connector_instances_service_all"
  ON public.broker_connector_instances FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');
