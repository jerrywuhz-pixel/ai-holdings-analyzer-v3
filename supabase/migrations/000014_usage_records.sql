-- ============================================
-- AI 持仓投资分析系统 2.0 — 用量记录表
-- Phase 7 Sprint 7.1: 套餐/支付/用量包
-- ============================================

-- 用量记录表：跟踪每个操作的详细使用
CREATE TABLE IF NOT EXISTS public.usage_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES users(id),
  action TEXT NOT NULL,              -- 'trade_write', 'ai_analysis', 'data_read', etc.
  quantity INTEGER NOT NULL DEFAULT 1,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- 索引
-- ============================================
CREATE INDEX IF NOT EXISTS idx_usage_tenant_action
  ON public.usage_records(tenant_id, action, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_usage_tenant_month
  ON public.usage_records(tenant_id, created_at DESC);

-- ============================================
-- RLS 策略
-- ============================================
ALTER TABLE public.usage_records ENABLE ROW LEVEL SECURITY;

-- 租户隔离：用户只能查看自己的用量记录
CREATE POLICY "usage_records_tenant_select"
  ON public.usage_records FOR SELECT
  USING (tenant_id = auth.uid());

-- 租户隔离：用户不能直接插入（由 service_role / 后端写入）
-- 仅允许 service_role 写入
CREATE POLICY "usage_records_service_all"
  ON public.usage_records FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 更新 quota_status 视图：整合 subscriptions 与 usage_records
-- ============================================
DROP VIEW IF EXISTS public.quota_status;

CREATE OR REPLACE VIEW public.quota_status AS
SELECT
  qt.tenant_id,
  COALESCE(s.plan, u.plan) AS plan,
  s.status AS subscription_status,
  qt.daily_writes,
  qt.daily_reads,
  qt.daily_ai_calls,
  -- 当月用量汇总（从 usage_records 统计）
  COALESCE(ur_month.monthly_ai_calls, 0) AS monthly_ai_calls,
  COALESCE(ur_month.monthly_trade_writes, 0) AS monthly_trade_writes,
  COALESCE(ur_month.monthly_data_reads, 0) AS monthly_data_reads,
  -- 套餐上限（从 plan_limits 表读取，降级为硬编码兜底）
  CASE COALESCE(s.plan, u.plan)
    WHEN 'free' THEN 50
    WHEN 'basic' THEN 500
    WHEN 'pro' THEN 5000
    WHEN 'enterprise' THEN 999999
  END AS max_daily_writes,
  CASE COALESCE(s.plan, u.plan)
    WHEN 'free' THEN 200
    WHEN 'basic' THEN 2000
    WHEN 'pro' THEN 20000
    WHEN 'enterprise' THEN 999999
  END AS max_daily_reads,
  CASE COALESCE(s.plan, u.plan)
    WHEN 'free' THEN 20
    WHEN 'basic' THEN 200
    WHEN 'pro' THEN 2000
    WHEN 'enterprise' THEN 999999
  END AS max_daily_ai_calls,
  qt.quota_reset_at,
  qt.updated_at
FROM quota_tracking qt
JOIN users u ON qt.tenant_id = u.id
LEFT JOIN subscriptions s ON s.tenant_id = qt.tenant_id
LEFT JOIN LATERAL (
  SELECT
    SUM(CASE WHEN ur.action = 'ai_analysis' THEN ur.quantity ELSE 0 END) AS monthly_ai_calls,
    SUM(CASE WHEN ur.action = 'trade_write' THEN ur.quantity ELSE 0 END) AS monthly_trade_writes,
    SUM(CASE WHEN ur.action = 'data_read' THEN ur.quantity ELSE 0 END) AS monthly_data_reads
  FROM usage_records ur
  WHERE ur.tenant_id = qt.tenant_id
    AND ur.created_at >= date_trunc('month', now())
) ur_month ON true;

-- ============================================
-- 注释
-- ============================================
COMMENT ON TABLE public.usage_records IS
  '用量记录表：跟踪每个操作的详细使用，用于配额检查和用量统计。';
COMMENT ON COLUMN public.usage_records.action IS
  '操作类型：trade_write（交易写入）、ai_analysis（AI分析）、data_read（数据读取）等。';
