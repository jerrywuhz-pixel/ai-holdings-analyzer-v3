-- ============================================
-- Hermes alert center P2: rule taxonomy + commitment reviews
-- ============================================

ALTER TABLE public.alert_rules
  DROP CONSTRAINT IF EXISTS alert_rules_type_check;

ALTER TABLE public.alert_rules
  ADD CONSTRAINT alert_rules_type_check CHECK (
    alert_type IN (
      'price_cross',
      'price_change_pct',
      'price_change_percent',
      'volume_spike',
      'position_concentration',
      'sell_put_dte_delta',
      'earnings_window',
      'discipline_violation',
      'decision_watch_condition',
      'sector_rotation'
    )
  );

CREATE TABLE IF NOT EXISTS public.decision_signal_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  decision_signal_id UUID REFERENCES public.decision_signals(id) ON DELETE SET NULL,
  source_artifact_id UUID REFERENCES public.artifact_registry(id) ON DELETE SET NULL,
  review_date DATE NOT NULL DEFAULT CURRENT_DATE,
  review_type TEXT NOT NULL DEFAULT 'postmarket',
  commitment_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  trigger_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
  checklist JSONB NOT NULL DEFAULT '[]'::jsonb,
  user_feedback JSONB NOT NULL DEFAULT '{}'::jsonb,
  execution_status TEXT NOT NULL DEFAULT 'pending_user_review',
  violation_status TEXT NOT NULL DEFAULT 'unknown',
  reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT decision_signal_reviews_type_check CHECK (review_type IN ('premarket', 'intraday', 'postmarket', 'manual')),
  CONSTRAINT decision_signal_reviews_execution_check CHECK (execution_status IN ('pending_user_review', 'executed', 'not_executed', 'not_applicable')),
  CONSTRAINT decision_signal_reviews_violation_check CHECK (violation_status IN ('unknown', 'no_violation', 'violated', 'needs_reason'))
);

CREATE INDEX IF NOT EXISTS idx_decision_signal_reviews_tenant_date
  ON public.decision_signal_reviews(tenant_id, review_date DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_decision_signal_reviews_signal
  ON public.decision_signal_reviews(decision_signal_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_signal_reviews_once_per_day
  ON public.decision_signal_reviews(tenant_id, decision_signal_id, review_date, review_type)
  WHERE decision_signal_id IS NOT NULL;

ALTER TABLE public.decision_signal_reviews ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "decision_signal_reviews_tenant_select" ON public.decision_signal_reviews;
CREATE POLICY "decision_signal_reviews_tenant_select"
  ON public.decision_signal_reviews FOR SELECT
  USING (tenant_id = public.current_tenant_id());

DROP POLICY IF EXISTS "decision_signal_reviews_service_all" ON public.decision_signal_reviews;
CREATE POLICY "decision_signal_reviews_service_all"
  ON public.decision_signal_reviews FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP TRIGGER IF EXISTS trg_decision_signal_reviews_updated_at ON public.decision_signal_reviews;
CREATE TRIGGER trg_decision_signal_reviews_updated_at
  BEFORE UPDATE ON public.decision_signal_reviews
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
