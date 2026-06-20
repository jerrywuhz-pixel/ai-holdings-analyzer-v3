-- ============================================
-- Hermes opportunity research workflow: paper signal ledger
-- ============================================

CREATE TABLE IF NOT EXISTS public.opportunity_cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  source_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  source_artifact_id UUID REFERENCES public.artifact_registry(id) ON DELETE SET NULL,
  decision_signal_id UUID REFERENCES public.decision_signals(id) ON DELETE SET NULL,
  market TEXT NOT NULL,
  symbol TEXT NOT NULL,
  instrument_type TEXT NOT NULL DEFAULT 'stock',
  asset_theme TEXT,
  narrative TEXT,
  playbook_key TEXT NOT NULL DEFAULT 'default',
  horizon TEXT NOT NULL DEFAULT '3d',
  actionability_cap public.actionability_cap NOT NULL DEFAULT 'analysis_only',
  position_layer TEXT,
  budget_layer TEXT,
  entry_rule JSONB NOT NULL DEFAULT '{}'::jsonb,
  exit_rule JSONB NOT NULL DEFAULT '{}'::jsonb,
  benchmark_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  strategy_model_version TEXT NOT NULL DEFAULT 'opportunity-research-v1',
  status TEXT NOT NULL DEFAULT 'tracking',
  invalidation JSONB NOT NULL DEFAULT '{}'::jsonb,
  trigger_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  data_quality JSONB NOT NULL DEFAULT '{}'::jsonb,
  discipline_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  dedupe_key TEXT NOT NULL,
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT opportunity_cases_market_not_blank CHECK (btrim(market) <> ''),
  CONSTRAINT opportunity_cases_symbol_not_blank CHECK (btrim(symbol) <> ''),
  CONSTRAINT opportunity_cases_dedupe_not_blank CHECK (btrim(dedupe_key) <> ''),
  CONSTRAINT opportunity_cases_instrument_check CHECK (instrument_type IN ('stock', 'etf', 'sell_put', 'basket')),
  CONSTRAINT opportunity_cases_status_check CHECK (status IN ('tracking', 'open', 'confirmed', 'invalidated', 'closed', 'expired', 'archived'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_opportunity_cases_tenant_dedupe
  ON public.opportunity_cases(tenant_id, dedupe_key);

CREATE INDEX IF NOT EXISTS idx_opportunity_cases_tenant_status
  ON public.opportunity_cases(tenant_id, status, opened_at DESC);

CREATE INDEX IF NOT EXISTS idx_opportunity_cases_tenant_symbol
  ON public.opportunity_cases(tenant_id, symbol, opened_at DESC);

CREATE TABLE IF NOT EXISTS public.opportunity_case_marks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  opportunity_case_id UUID NOT NULL REFERENCES public.opportunity_cases(id) ON DELETE CASCADE,
  mark_date DATE NOT NULL DEFAULT CURRENT_DATE,
  mark_type TEXT NOT NULL DEFAULT 'daily',
  mark_price NUMERIC(18,6),
  mark_nav NUMERIC(18,6),
  paper_pnl NUMERIC(18,6),
  paper_pnl_pct NUMERIC(12,4),
  benchmark_return NUMERIC(12,4),
  stretch_return NUMERIC(12,4),
  excess_return NUMERIC(12,4),
  drawdown_pct NUMERIC(12,4),
  thesis_status TEXT NOT NULL DEFAULT 'waiting_confirmation',
  discipline_status TEXT NOT NULL DEFAULT 'unknown',
  review_note TEXT,
  fact_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  benchmark_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT opportunity_case_marks_type_check CHECK (mark_type IN ('daily', 'event', 'close', 'manual')),
  CONSTRAINT opportunity_case_marks_thesis_check CHECK (thesis_status IN ('confirmed', 'invalidated', 'waiting_confirmation', 'expired', 'not_applicable')),
  CONSTRAINT opportunity_case_marks_discipline_check CHECK (discipline_status IN ('adhered', 'violated', 'unknown', 'not_applicable'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_opportunity_case_marks_once
  ON public.opportunity_case_marks(opportunity_case_id, mark_date, mark_type);

CREATE INDEX IF NOT EXISTS idx_opportunity_case_marks_tenant_date
  ON public.opportunity_case_marks(tenant_id, mark_date DESC, created_at DESC);

ALTER TABLE public.opportunity_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.opportunity_case_marks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "opportunity_cases_tenant_select" ON public.opportunity_cases;
CREATE POLICY "opportunity_cases_tenant_select"
  ON public.opportunity_cases FOR SELECT
  USING (tenant_id = public.current_tenant_id());

DROP POLICY IF EXISTS "opportunity_cases_service_all" ON public.opportunity_cases;
CREATE POLICY "opportunity_cases_service_all"
  ON public.opportunity_cases FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "opportunity_case_marks_tenant_select" ON public.opportunity_case_marks;
CREATE POLICY "opportunity_case_marks_tenant_select"
  ON public.opportunity_case_marks FOR SELECT
  USING (tenant_id = public.current_tenant_id());

DROP POLICY IF EXISTS "opportunity_case_marks_service_all" ON public.opportunity_case_marks;
CREATE POLICY "opportunity_case_marks_service_all"
  ON public.opportunity_case_marks FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP TRIGGER IF EXISTS trg_opportunity_cases_updated_at ON public.opportunity_cases;
CREATE TRIGGER trg_opportunity_cases_updated_at
  BEFORE UPDATE ON public.opportunity_cases
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_opportunity_case_marks_updated_at ON public.opportunity_case_marks;
CREATE TRIGGER trg_opportunity_case_marks_updated_at
  BEFORE UPDATE ON public.opportunity_case_marks
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

COMMENT ON TABLE public.opportunity_cases IS
  'Hermes opportunity hypotheses created by the research workflow. These are paper signal ledger cases, not live orders.';

COMMENT ON TABLE public.opportunity_case_marks IS
  'Daily/event marks for opportunity cases, including paper PnL, benchmark returns, stretch comparator, thesis status, and discipline status.';
