-- ============================================
-- AI Holdings Analyzer 3.0 P0 - Account Lists, Manual Positions, Trading Rules
-- Formalizes tables that were previously created defensively by the WebApp runtime.
-- ============================================

ALTER TABLE public.tenant_accounts
  ADD COLUMN IF NOT EXISTS account_id UUID;

UPDATE public.tenant_accounts
SET account_id = gen_random_uuid()
WHERE account_id IS NULL;

ALTER TABLE public.tenant_accounts
  ALTER COLUMN account_id SET DEFAULT gen_random_uuid();

CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_accounts_account_id
  ON public.tenant_accounts(account_id);

CREATE TABLE IF NOT EXISTS public.follow_views (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  strategy_focus TEXT NOT NULL DEFAULT 'watchlist',
  base_currency TEXT NOT NULL DEFAULT 'USD',
  is_default BOOLEAN NOT NULL DEFAULT FALSE,
  settings JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT follow_views_slug_not_blank CHECK (btrim(slug) <> ''),
  CONSTRAINT follow_views_strategy_focus_not_blank CHECK (btrim(strategy_focus) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_follow_views_tenant_slug
  ON public.follow_views(tenant_id, slug);

CREATE UNIQUE INDEX IF NOT EXISTS idx_follow_views_default
  ON public.follow_views(tenant_id)
  WHERE is_default = TRUE;

CREATE TABLE IF NOT EXISTS public.follow_view_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  follow_view_id UUID NOT NULL REFERENCES public.follow_views(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  name TEXT,
  market TEXT NOT NULL DEFAULT 'US',
  target_action TEXT NOT NULL DEFAULT 'watch',
  thesis TEXT,
  target_buy_zone JSONB NOT NULL DEFAULT '{}'::jsonb,
  sell_put_preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
  trigger_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
  risk_flags TEXT[] NOT NULL DEFAULT '{}'::text[],
  next_review_at TIMESTAMPTZ,
  data_lineage JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT follow_view_items_symbol_not_blank CHECK (btrim(symbol) <> ''),
  CONSTRAINT follow_view_items_market_not_blank CHECK (btrim(market) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_follow_view_items_unique
  ON public.follow_view_items(follow_view_id, symbol, market);

CREATE INDEX IF NOT EXISTS idx_follow_view_items_tenant_review
  ON public.follow_view_items(tenant_id, next_review_at)
  WHERE next_review_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.list_views (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  list_type TEXT NOT NULL DEFAULT 'closed_positions',
  base_currency TEXT NOT NULL DEFAULT 'USD',
  is_default BOOLEAN NOT NULL DEFAULT FALSE,
  settings JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT list_views_slug_not_blank CHECK (btrim(slug) <> ''),
  CONSTRAINT list_views_list_type_not_blank CHECK (btrim(list_type) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_list_views_tenant_slug
  ON public.list_views(tenant_id, slug);

CREATE UNIQUE INDEX IF NOT EXISTS idx_list_views_default
  ON public.list_views(tenant_id)
  WHERE is_default = TRUE;

CREATE TABLE IF NOT EXISTS public.list_view_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  list_view_id UUID NOT NULL REFERENCES public.list_views(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  name TEXT,
  market TEXT NOT NULL DEFAULT 'US',
  opened_at TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  realized_pnl NUMERIC(18,2),
  exit_reason TEXT,
  review_summary TEXT,
  rebuy_status TEXT NOT NULL DEFAULT 'not_reviewed',
  rebuy_conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
  data_lineage JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT list_view_items_symbol_not_blank CHECK (btrim(symbol) <> ''),
  CONSTRAINT list_view_items_market_not_blank CHECK (btrim(market) <> '')
);

CREATE INDEX IF NOT EXISTS idx_list_view_items_symbol
  ON public.list_view_items(tenant_id, symbol, closed_at DESC);

CREATE TABLE IF NOT EXISTS public.webapp_manual_positions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  portfolio_view_id UUID NOT NULL REFERENCES public.portfolio_views(id) ON DELETE CASCADE,
  asset_source_id UUID NOT NULL REFERENCES public.asset_sources(id) ON DELETE RESTRICT,
  instrument_type public.instrument_type NOT NULL DEFAULT 'stock',
  symbol TEXT NOT NULL,
  name TEXT,
  market TEXT NOT NULL DEFAULT 'US',
  exchange TEXT,
  position_side public.position_side NOT NULL DEFAULT 'long',
  quantity NUMERIC(24,8) NOT NULL,
  average_cost NUMERIC(18,6),
  market_price NUMERIC(18,6),
  market_value NUMERIC(18,2),
  currency TEXT NOT NULL DEFAULT 'USD',
  source_quality public.source_quality NOT NULL DEFAULT 'user_confirmed',
  note TEXT,
  position_status public.portfolio_position_status NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT webapp_manual_positions_symbol_not_blank CHECK (btrim(symbol) <> ''),
  CONSTRAINT webapp_manual_positions_market_not_blank CHECK (btrim(market) <> ''),
  CONSTRAINT webapp_manual_positions_quantity_non_negative CHECK (quantity >= 0)
);

CREATE INDEX IF NOT EXISTS idx_webapp_manual_positions_tenant_status
  ON public.webapp_manual_positions(tenant_id, position_status, updated_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_webapp_manual_positions_open_unique
  ON public.webapp_manual_positions(tenant_id, portfolio_view_id, symbol, instrument_type)
  WHERE position_status = 'open';

CREATE TABLE IF NOT EXISTS public.trading_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  rule_key TEXT NOT NULL,
  rule_type TEXT NOT NULL,
  scopes TEXT[] NOT NULL DEFAULT '{}'::text[],
  markets TEXT[] NOT NULL DEFAULT '{}'::text[],
  instruments TEXT[] NOT NULL DEFAULT '{}'::text[],
  condition JSONB NOT NULL DEFAULT '{}'::jsonb,
  message TEXT NOT NULL,
  action_on_violation TEXT NOT NULL DEFAULT 'warn',
  priority INTEGER NOT NULL DEFAULT 100,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  source TEXT NOT NULL DEFAULT 'user',
  last_triggered_at TIMESTAMPTZ,
  trigger_count BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT trading_rules_rule_key_not_blank CHECK (btrim(rule_key) <> ''),
  CONSTRAINT trading_rules_name_not_blank CHECK (btrim(name) <> ''),
  CONSTRAINT trading_rules_rule_type_check CHECK (rule_type IN ('allowlist', 'blocklist', 'time_window', 'position_limit', 'risk_budget', 'confirmation_required', 'custom')),
  CONSTRAINT trading_rules_action_check CHECK (action_on_violation IN ('warn', 'block', 'require_confirmation')),
  CONSTRAINT trading_rules_priority_positive CHECK (priority > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_trading_rules_tenant_key
  ON public.trading_rules(tenant_id, rule_key);

CREATE INDEX IF NOT EXISTS idx_trading_rules_tenant_active
  ON public.trading_rules(tenant_id, is_active, priority);

CREATE TABLE IF NOT EXISTS public.discipline_checks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  pending_action_id UUID REFERENCES public.pending_actions(id) ON DELETE SET NULL,
  agent_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  symbol TEXT,
  instrument_type public.instrument_type,
  action_type TEXT NOT NULL,
  result TEXT NOT NULL,
  triggered_rule_ids UUID[] NOT NULL DEFAULT '{}'::uuid[],
  highest_action TEXT NOT NULL DEFAULT 'none',
  check_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT discipline_checks_action_type_not_blank CHECK (btrim(action_type) <> ''),
  CONSTRAINT discipline_checks_result_check CHECK (result IN ('passed', 'warned', 'blocked', 'requires_confirmation')),
  CONSTRAINT discipline_checks_highest_action_check CHECK (highest_action IN ('none', 'warn', 'block', 'require_confirmation'))
);

CREATE INDEX IF NOT EXISTS idx_discipline_checks_tenant_created
  ON public.discipline_checks(tenant_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_follow_views_updated_at ON public.follow_views;
CREATE TRIGGER trg_follow_views_updated_at
  BEFORE UPDATE ON public.follow_views
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_follow_view_items_updated_at ON public.follow_view_items;
CREATE TRIGGER trg_follow_view_items_updated_at
  BEFORE UPDATE ON public.follow_view_items
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_list_views_updated_at ON public.list_views;
CREATE TRIGGER trg_list_views_updated_at
  BEFORE UPDATE ON public.list_views
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_list_view_items_updated_at ON public.list_view_items;
CREATE TRIGGER trg_list_view_items_updated_at
  BEFORE UPDATE ON public.list_view_items
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_webapp_manual_positions_updated_at ON public.webapp_manual_positions;
CREATE TRIGGER trg_webapp_manual_positions_updated_at
  BEFORE UPDATE ON public.webapp_manual_positions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_trading_rules_updated_at ON public.trading_rules;
CREATE TRIGGER trg_trading_rules_updated_at
  BEFORE UPDATE ON public.trading_rules
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

ALTER TABLE public.follow_views ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.follow_view_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.list_views ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.list_view_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.webapp_manual_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trading_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.discipline_checks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "follow_views_tenant_all" ON public.follow_views;
CREATE POLICY "follow_views_tenant_all"
  ON public.follow_views FOR ALL
  USING (tenant_id = public.current_tenant_id())
  WITH CHECK (tenant_id = public.current_tenant_id());
DROP POLICY IF EXISTS "follow_views_service_all" ON public.follow_views;
CREATE POLICY "follow_views_service_all"
  ON public.follow_views FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "follow_view_items_tenant_all" ON public.follow_view_items;
CREATE POLICY "follow_view_items_tenant_all"
  ON public.follow_view_items FOR ALL
  USING (tenant_id = public.current_tenant_id())
  WITH CHECK (tenant_id = public.current_tenant_id());
DROP POLICY IF EXISTS "follow_view_items_service_all" ON public.follow_view_items;
CREATE POLICY "follow_view_items_service_all"
  ON public.follow_view_items FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "list_views_tenant_all" ON public.list_views;
CREATE POLICY "list_views_tenant_all"
  ON public.list_views FOR ALL
  USING (tenant_id = public.current_tenant_id())
  WITH CHECK (tenant_id = public.current_tenant_id());
DROP POLICY IF EXISTS "list_views_service_all" ON public.list_views;
CREATE POLICY "list_views_service_all"
  ON public.list_views FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "list_view_items_tenant_all" ON public.list_view_items;
CREATE POLICY "list_view_items_tenant_all"
  ON public.list_view_items FOR ALL
  USING (tenant_id = public.current_tenant_id())
  WITH CHECK (tenant_id = public.current_tenant_id());
DROP POLICY IF EXISTS "list_view_items_service_all" ON public.list_view_items;
CREATE POLICY "list_view_items_service_all"
  ON public.list_view_items FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "webapp_manual_positions_tenant_all" ON public.webapp_manual_positions;
CREATE POLICY "webapp_manual_positions_tenant_all"
  ON public.webapp_manual_positions FOR ALL
  USING (tenant_id = public.current_tenant_id())
  WITH CHECK (tenant_id = public.current_tenant_id());
DROP POLICY IF EXISTS "webapp_manual_positions_service_all" ON public.webapp_manual_positions;
CREATE POLICY "webapp_manual_positions_service_all"
  ON public.webapp_manual_positions FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "trading_rules_tenant_all" ON public.trading_rules;
CREATE POLICY "trading_rules_tenant_all"
  ON public.trading_rules FOR ALL
  USING (tenant_id = public.current_tenant_id())
  WITH CHECK (tenant_id = public.current_tenant_id());
DROP POLICY IF EXISTS "trading_rules_service_all" ON public.trading_rules;
CREATE POLICY "trading_rules_service_all"
  ON public.trading_rules FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "discipline_checks_tenant_select" ON public.discipline_checks;
CREATE POLICY "discipline_checks_tenant_select"
  ON public.discipline_checks FOR SELECT
  USING (tenant_id = public.current_tenant_id());
DROP POLICY IF EXISTS "discipline_checks_service_all" ON public.discipline_checks;
CREATE POLICY "discipline_checks_service_all"
  ON public.discipline_checks FOR ALL TO service_role
  USING (true) WITH CHECK (true);

COMMENT ON TABLE public.follow_views IS
  'Tenant-scoped pre-position watchlist views for candidates, triggers, and strategy focus.';
COMMENT ON TABLE public.list_views IS
  'Tenant-scoped post-position lists for closed positions, reviews, and rebuy conditions.';
COMMENT ON TABLE public.webapp_manual_positions IS
  'User-confirmed manual position input source used before broker sync is available.';
COMMENT ON TABLE public.trading_rules IS
  'Tenant-scoped trading discipline rules evaluated before position-changing actions and trade drafts.';
COMMENT ON TABLE public.discipline_checks IS
  'Auditable outcomes of trading discipline rule evaluation.';
