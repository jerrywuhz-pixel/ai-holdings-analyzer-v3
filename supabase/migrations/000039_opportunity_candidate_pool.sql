-- ============================================
-- Hermes opportunity research workflow: dynamic candidate pool
-- ============================================

CREATE TABLE IF NOT EXISTS public.opportunity_candidate_pool (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  market TEXT NOT NULL,
  symbol TEXT NOT NULL,
  asset_path TEXT,
  asset_theme TEXT,
  five_layer TEXT,
  playbook_key TEXT NOT NULL DEFAULT 'default',
  status TEXT NOT NULL DEFAULT 'watching',
  strength_score NUMERIC(10,4),
  leader_rank INTEGER,
  move_decision TEXT,
  move_reason TEXT,
  last_price NUMERIC(18,6),
  change_pct NUMERIC(12,4),
  relative_strength NUMERIC(10,4),
  source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT opportunity_candidate_pool_market_not_blank CHECK (btrim(market) <> ''),
  CONSTRAINT opportunity_candidate_pool_symbol_not_blank CHECK (btrim(symbol) <> ''),
  CONSTRAINT opportunity_candidate_pool_status_check CHECK (status IN ('active', 'watching', 'removed', 'blocked')),
  CONSTRAINT opportunity_candidate_pool_move_check CHECK (move_decision IS NULL OR move_decision IN ('add', 'keep', 'remove', 'watch', 'block'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_opportunity_candidate_pool_tenant_symbol
  ON public.opportunity_candidate_pool(tenant_id, market, symbol);

CREATE INDEX IF NOT EXISTS idx_opportunity_candidate_pool_tenant_status
  ON public.opportunity_candidate_pool(tenant_id, status, strength_score DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_opportunity_candidate_pool_theme_layer
  ON public.opportunity_candidate_pool(tenant_id, market, asset_path, five_layer, leader_rank);

ALTER TABLE public.opportunity_candidate_pool ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "opportunity_candidate_pool_tenant_select" ON public.opportunity_candidate_pool;
CREATE POLICY "opportunity_candidate_pool_tenant_select"
  ON public.opportunity_candidate_pool FOR SELECT
  USING (tenant_id = public.current_tenant_id());

DROP POLICY IF EXISTS "opportunity_candidate_pool_service_all" ON public.opportunity_candidate_pool;
CREATE POLICY "opportunity_candidate_pool_service_all"
  ON public.opportunity_candidate_pool FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP TRIGGER IF EXISTS trg_opportunity_candidate_pool_updated_at ON public.opportunity_candidate_pool;
CREATE TRIGGER trg_opportunity_candidate_pool_updated_at
  BEFORE UPDATE ON public.opportunity_candidate_pool
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

COMMENT ON TABLE public.opportunity_candidate_pool IS
  'Daily rotating Hermes opportunity candidate pool. The workflow promotes only current theme/layer leaders into deep research and keeps add/keep/remove/watch decisions for audit.';
