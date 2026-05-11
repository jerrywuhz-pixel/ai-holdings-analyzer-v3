-- ============================================
-- AI 持仓投资分析系统 2.0 — 配额追踪与视图
-- Phase 1 Sprint 1.1: Gateway 数据访问中间件
-- ============================================

-- 配额计数器表（每个租户一行）
CREATE TABLE public.quota_tracking (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES users(id) UNIQUE,
  daily_writes    INTEGER NOT NULL DEFAULT 0,
  daily_reads     INTEGER NOT NULL DEFAULT 0,
  daily_ai_calls  INTEGER NOT NULL DEFAULT 0,
  quota_reset_at  TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 自动更新 updated_at（复用已有函数）
CREATE TRIGGER trg_quota_tracking_updated_at
  BEFORE UPDATE ON public.quota_tracking
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

-- 索引：按租户快速定位
CREATE INDEX idx_quota_tracking_tenant
  ON quota_tracking(tenant_id);

-- RLS：租户只能查看自己的配额
ALTER TABLE quota_tracking ENABLE ROW LEVEL SECURITY;

CREATE POLICY "quota_tracking_select_tenant"
  ON quota_tracking
  FOR SELECT
  USING (tenant_id = auth.uid());

CREATE POLICY "quota_tracking_service_all"
  ON quota_tracking
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 配额状态视图：将原始计数与套餐上限关联
-- ============================================

CREATE OR REPLACE VIEW public.quota_status AS
SELECT
  qt.tenant_id,
  u.plan,
  qt.daily_writes,
  qt.daily_reads,
  qt.daily_ai_calls,
  CASE u.plan
    WHEN 'free' THEN 50
    WHEN 'basic' THEN 500
    WHEN 'pro' THEN 5000
    WHEN 'enterprise' THEN 999999
  END AS max_daily_writes,
  CASE u.plan
    WHEN 'free' THEN 200
    WHEN 'basic' THEN 2000
    WHEN 'pro' THEN 20000
    WHEN 'enterprise' THEN 999999
  END AS max_daily_reads,
  CASE u.plan
    WHEN 'free' THEN 20
    WHEN 'basic' THEN 200
    WHEN 'pro' THEN 2000
    WHEN 'enterprise' THEN 999999
  END AS max_daily_ai_calls,
  qt.quota_reset_at,
  qt.updated_at
FROM quota_tracking qt
JOIN users u ON qt.tenant_id = u.id;

-- 视图 RLS（quota_status 是视图，不直接存数据，RLS 由底层表承担）
-- 但为兼容部分客户端的 ORM 反射，显式注释视图语义
COMMENT ON VIEW public.quota_status IS
  '实时配额状态：将 quota_tracking 计数器与 users.plan 套餐上限关联。'
  ' Gateway 中间件通过此视图检查配额。';
