-- ============================================
-- Hermes stock analysis P1: decisions, alerts, sector snapshots
-- ============================================

CREATE TABLE IF NOT EXISTS public.decision_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  source_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  source_artifact_id UUID REFERENCES public.artifact_registry(id) ON DELETE SET NULL,
  symbol TEXT NOT NULL,
  name TEXT,
  market TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'stock_analysis',
  source_agent TEXT NOT NULL DEFAULT 'hermes_stock_analysis',
  action TEXT NOT NULL,
  action_label TEXT,
  actionability_cap public.actionability_cap NOT NULL DEFAULT 'analysis_only',
  confidence_score NUMERIC(5,4),
  score INTEGER,
  horizon TEXT,
  entry_low NUMERIC(18,6),
  entry_high NUMERIC(18,6),
  stop_loss NUMERIC(18,6),
  take_profit NUMERIC(18,6),
  invalidation JSONB NOT NULL DEFAULT '{}'::jsonb,
  watch_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
  reason JSONB NOT NULL DEFAULT '{}'::jsonb,
  risk_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  catalyst_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  data_quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  plan_quality TEXT NOT NULL DEFAULT 'minimal',
  status TEXT NOT NULL DEFAULT 'active',
  expires_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT decision_signals_symbol_not_blank CHECK (btrim(symbol) <> ''),
  CONSTRAINT decision_signals_market_not_blank CHECK (btrim(market) <> ''),
  CONSTRAINT decision_signals_action_not_blank CHECK (btrim(action) <> ''),
  CONSTRAINT decision_signals_score_range CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
  CONSTRAINT decision_signals_confidence_range CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)),
  CONSTRAINT decision_signals_plan_quality_check CHECK (plan_quality IN ('complete', 'partial', 'minimal', 'unknown')),
  CONSTRAINT decision_signals_status_check CHECK (status IN ('active', 'expired', 'invalidated', 'closed', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_decision_signals_tenant_symbol_status
  ON public.decision_signals(tenant_id, symbol, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_decision_signals_tenant_created
  ON public.decision_signals(tenant_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_decision_signals_updated_at ON public.decision_signals;
CREATE TRIGGER trg_decision_signals_updated_at
  BEFORE UPDATE ON public.decision_signals
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TABLE IF NOT EXISTS public.alert_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  decision_signal_id UUID REFERENCES public.decision_signals(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  target_scope TEXT NOT NULL DEFAULT 'single_symbol',
  target_symbol TEXT NOT NULL,
  market TEXT NOT NULL DEFAULT 'US',
  alert_type TEXT NOT NULL,
  parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
  severity TEXT NOT NULL DEFAULT 'warning',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  cooldown_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  notification_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  source TEXT NOT NULL DEFAULT 'hermes_stock_analysis',
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT alert_rules_name_not_blank CHECK (btrim(name) <> ''),
  CONSTRAINT alert_rules_target_not_blank CHECK (btrim(target_symbol) <> ''),
  CONSTRAINT alert_rules_type_check CHECK (alert_type IN ('price_cross', 'price_change_percent', 'volume_spike', 'decision_watch_condition', 'discipline_violation', 'sector_rotation')),
  CONSTRAINT alert_rules_severity_check CHECK (severity IN ('info', 'warning', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_alert_rules_tenant_enabled
  ON public.alert_rules(tenant_id, enabled, target_symbol);

CREATE TABLE IF NOT EXISTS public.alert_triggers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  rule_id UUID REFERENCES public.alert_rules(id) ON DELETE SET NULL,
  target_symbol TEXT NOT NULL,
  observed_value JSONB NOT NULL DEFAULT '{}'::jsonb,
  threshold JSONB NOT NULL DEFAULT '{}'::jsonb,
  reason TEXT,
  data_source TEXT,
  data_timestamp TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'triggered',
  diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
  triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT alert_triggers_target_not_blank CHECK (btrim(target_symbol) <> ''),
  CONSTRAINT alert_triggers_status_check CHECK (status IN ('triggered', 'skipped', 'degraded', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_alert_triggers_tenant_time
  ON public.alert_triggers(tenant_id, triggered_at DESC);

CREATE TABLE IF NOT EXISTS public.alert_notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  trigger_id UUID REFERENCES public.alert_triggers(id) ON DELETE SET NULL,
  channel TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  success BOOLEAN NOT NULL DEFAULT FALSE,
  error_code TEXT,
  retryable BOOLEAN NOT NULL DEFAULT FALSE,
  latency_ms INTEGER,
  diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT alert_notifications_attempt_positive CHECK (attempt > 0)
);

CREATE INDEX IF NOT EXISTS idx_alert_notifications_tenant_created
  ON public.alert_notifications(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.alert_cooldowns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  rule_id UUID REFERENCES public.alert_rules(id) ON DELETE CASCADE,
  target_symbol TEXT NOT NULL,
  severity TEXT,
  last_triggered_at TIMESTAMPTZ,
  cooldown_until TIMESTAMPTZ,
  reason TEXT,
  state TEXT NOT NULL DEFAULT 'active',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT alert_cooldowns_target_not_blank CHECK (btrim(target_symbol) <> ''),
  CONSTRAINT alert_cooldowns_state_check CHECK (state IN ('active', 'expired'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_cooldowns_rule_target
  ON public.alert_cooldowns(rule_id, target_symbol);

CREATE TABLE IF NOT EXISTS public.sector_daily_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  market TEXT NOT NULL,
  sector TEXT NOT NULL,
  industry TEXT,
  snapshot_date DATE NOT NULL,
  change_pct NUMERIC(10,4),
  relative_strength NUMERIC(10,4),
  breadth JSONB NOT NULL DEFAULT '{}'::jsonb,
  leaders JSONB NOT NULL DEFAULT '[]'::jsonb,
  laggards JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_key TEXT NOT NULL DEFAULT 'unknown',
  quality_status TEXT NOT NULL DEFAULT 'partial',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT sector_daily_snapshots_market_not_blank CHECK (btrim(market) <> ''),
  CONSTRAINT sector_daily_snapshots_sector_not_blank CHECK (btrim(sector) <> ''),
  CONSTRAINT sector_daily_snapshots_quality_check CHECK (quality_status IN ('validated', 'partial', 'stale', 'failed'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sector_daily_snapshots_unique
  ON public.sector_daily_snapshots(COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), market, sector, snapshot_date);

CREATE INDEX IF NOT EXISTS idx_sector_daily_snapshots_market_date
  ON public.sector_daily_snapshots(market, snapshot_date DESC);

ALTER TABLE public.decision_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alert_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alert_triggers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alert_notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alert_cooldowns ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sector_daily_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "decision_signals_tenant_select"
  ON public.decision_signals FOR SELECT
  USING (tenant_id = public.current_tenant_id());
CREATE POLICY "decision_signals_service_all"
  ON public.decision_signals FOR ALL TO service_role
  USING (true) WITH CHECK (true);

CREATE POLICY "alert_rules_tenant_select"
  ON public.alert_rules FOR SELECT
  USING (tenant_id = public.current_tenant_id());
CREATE POLICY "alert_rules_service_all"
  ON public.alert_rules FOR ALL TO service_role
  USING (true) WITH CHECK (true);

CREATE POLICY "alert_triggers_tenant_select"
  ON public.alert_triggers FOR SELECT
  USING (tenant_id = public.current_tenant_id());
CREATE POLICY "alert_triggers_service_all"
  ON public.alert_triggers FOR ALL TO service_role
  USING (true) WITH CHECK (true);

CREATE POLICY "alert_notifications_tenant_select"
  ON public.alert_notifications FOR SELECT
  USING (tenant_id = public.current_tenant_id());
CREATE POLICY "alert_notifications_service_all"
  ON public.alert_notifications FOR ALL TO service_role
  USING (true) WITH CHECK (true);

CREATE POLICY "alert_cooldowns_tenant_select"
  ON public.alert_cooldowns FOR SELECT
  USING (tenant_id = public.current_tenant_id());
CREATE POLICY "alert_cooldowns_service_all"
  ON public.alert_cooldowns FOR ALL TO service_role
  USING (true) WITH CHECK (true);

CREATE POLICY "sector_daily_snapshots_tenant_select"
  ON public.sector_daily_snapshots FOR SELECT
  USING (tenant_id IS NULL OR tenant_id = public.current_tenant_id());
CREATE POLICY "sector_daily_snapshots_service_all"
  ON public.sector_daily_snapshots FOR ALL TO service_role
  USING (true) WITH CHECK (true);
