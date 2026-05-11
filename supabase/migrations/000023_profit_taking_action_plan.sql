-- ============================================
-- AI 持仓投资分析系统 2.0 — 止盈行动计划
-- Phase 9: Profit-taking strategy and morning action plan
-- ============================================

-- 每个交易日前生成的个股止盈行动计划。
CREATE TABLE IF NOT EXISTS public.profit_taking_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  stock_name TEXT,
  plan_date DATE NOT NULL,
  action TEXT NOT NULL DEFAULT 'HOLD',
  target_price NUMERIC(18,4),
  stop_price NUMERIC(18,4),
  reduce_ratio NUMERIC(6,4) DEFAULT 0,
  today_reach_probability TEXT NOT NULL DEFAULT 'low',
  strategy_name TEXT NOT NULL DEFAULT 'market-adaptive-atr-rsi-v1',
  backtest_summary JSONB NOT NULL DEFAULT '{}',
  metrics JSONB NOT NULL DEFAULT '{}',
  reason TEXT,
  instruction TEXT,
  delivery_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
  job_run_id UUID REFERENCES public.job_runs(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),

  UNIQUE(tenant_id, symbol, plan_date),

  CONSTRAINT chk_profit_taking_action CHECK (
    action IN ('HOLD', 'WATCH_TARGET', 'TAKE_PROFIT')
  ),
  CONSTRAINT chk_profit_taking_probability CHECK (
    today_reach_probability IN ('low', 'medium', 'high')
  ),
  CONSTRAINT chk_profit_taking_delivery_status CHECK (
    delivery_status IN (
      'NOT_REQUIRED',
      'PENDING',
      'QUEUED',
      'SKIPPED_NO_SESSION',
      'FAILED'
    )
  ),
  CONSTRAINT chk_profit_taking_reduce_ratio CHECK (
    reduce_ratio >= 0 AND reduce_ratio <= 1
  )
);

CREATE INDEX IF NOT EXISTS idx_profit_taking_tenant_date
  ON public.profit_taking_plans(tenant_id, plan_date DESC);

CREATE INDEX IF NOT EXISTS idx_profit_taking_action_date
  ON public.profit_taking_plans(action, plan_date DESC)
  WHERE action IN ('WATCH_TARGET', 'TAKE_PROFIT');

CREATE INDEX IF NOT EXISTS idx_profit_taking_symbol
  ON public.profit_taking_plans(tenant_id, symbol, plan_date DESC);

DROP TRIGGER IF EXISTS trg_profit_taking_plans_updated_at ON public.profit_taking_plans;
CREATE TRIGGER trg_profit_taking_plans_updated_at
  BEFORE UPDATE ON public.profit_taking_plans
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

ALTER TABLE public.profit_taking_plans ENABLE ROW LEVEL SECURITY;

CREATE POLICY "profit_taking_select_tenant"
  ON public.profit_taking_plans FOR SELECT
  USING (tenant_id = auth.uid());

CREATE POLICY "profit_taking_insert_tenant"
  ON public.profit_taking_plans FOR INSERT
  WITH CHECK (tenant_id = auth.uid());

CREATE POLICY "profit_taking_update_tenant"
  ON public.profit_taking_plans FOR UPDATE
  USING (tenant_id = auth.uid());

CREATE POLICY "profit_taking_service_all"
  ON public.profit_taking_plans FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

COMMENT ON TABLE public.profit_taking_plans IS
  '每日开盘前生成的持仓个股止盈行动计划，包含回测摘要、关键指标、目标价和推送状态。';
COMMENT ON COLUMN public.profit_taking_plans.backtest_summary IS
  '历史回测验证摘要：样本数、胜率、回撤规避、选中规则等。';
COMMENT ON COLUMN public.profit_taking_plans.metrics IS
  '生成计划时跟踪的关键指标：浮盈、ATR、RSI、均线、大盘状态等。';

-- 定时任务定义：工作日 09:00（本地交易日前半小时）生成止盈行动计划。
INSERT INTO public.task_definitions (
  name,
  job_type,
  cron_expression,
  skill_name,
  config,
  is_enabled,
  timeout_seconds,
  max_retries
)
VALUES (
  'daily-profit-taking',
  'profit_taking',
  '0 9 * * 1-5',
  'profit-taking',
  '{"trigger_type": "cron", "run_at": "09:00", "purpose": "pre-open profit-taking action plan"}'::jsonb,
  TRUE,
  300,
  3
)
ON CONFLICT (name) DO UPDATE SET
  job_type = EXCLUDED.job_type,
  cron_expression = EXCLUDED.cron_expression,
  skill_name = EXCLUDED.skill_name,
  config = EXCLUDED.config,
  is_enabled = EXCLUDED.is_enabled,
  timeout_seconds = EXCLUDED.timeout_seconds,
  max_retries = EXCLUDED.max_retries,
  updated_at = now();
