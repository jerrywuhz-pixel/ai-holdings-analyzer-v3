-- ============================================
-- AI 持仓投资分析系统 2.0 — 套餐限制配置表
-- Phase 7 Sprint 7.1: 套餐/支付/用量包
-- ============================================

-- 套餐限制配置表
CREATE TABLE IF NOT EXISTS public.plan_limits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plan TEXT NOT NULL,                -- free/basic/pro/enterprise
  action TEXT NOT NULL,              -- 'max_positions', 'max_trades', 'daily_ai_calls', etc.
  limit_value INTEGER NOT NULL,
  description TEXT,
  UNIQUE(plan, action)
);

-- ============================================
-- 插入各套餐限制配置
-- ============================================

-- ---- free 套餐 ----
INSERT INTO public.plan_limits (plan, action, limit_value, description) VALUES
  ('free', 'max_positions', 5, '最大持仓数'),
  ('free', 'max_trades', 50, '最大交易记录数'),
  ('free', 'daily_ai_calls', 10, '每日AI分析调用次数'),
  ('free', 'data_sources', 1, '数据源：仅 Yahoo Finance'),
  ('free', 'push_notifications', 0, '不推送通知'),
  ('free', 'watchlist', 5, '目标池最大数量'),
  ('free', 'webapp', 0, '基础版 Web 应用')
ON CONFLICT (plan, action) DO NOTHING;

-- ---- basic 套餐（29元/月）----
INSERT INTO public.plan_limits (plan, action, limit_value, description) VALUES
  ('basic', 'max_positions', 999999, '无限持仓'),
  ('basic', 'max_trades', 999999, '无限交易记录'),
  ('basic', 'daily_ai_calls', 200, '每日AI分析调用次数'),
  ('basic', 'data_sources', 2, '数据源：Yahoo Finance + Tushare'),
  ('basic', 'push_notifications', 1, '基础推送通知'),
  ('basic', 'watchlist', 999999, '无限目标池'),
  ('basic', 'webapp', 1, '完整版 Web 应用')
ON CONFLICT (plan, action) DO NOTHING;

-- ---- pro 套餐（99元/月）----
INSERT INTO public.plan_limits (plan, action, limit_value, description) VALUES
  ('pro', 'max_positions', 999999, '无限持仓'),
  ('pro', 'max_trades', 999999, '无限交易记录'),
  ('pro', 'daily_ai_calls', 999999, '无限AI分析调用'),
  ('pro', 'data_sources', 999, '所有数据源'),
  ('pro', 'push_notifications', 2, '高级推送通知'),
  ('pro', 'watchlist', 999999, '无限目标池 + StrikeZone'),
  ('pro', 'webapp', 2, '完整版 Web + Hunter 猎手')
ON CONFLICT (plan, action) DO NOTHING;

-- ---- enterprise 套餐 ----
INSERT INTO public.plan_limits (plan, action, limit_value, description) VALUES
  ('enterprise', 'max_positions', 999999, '无限持仓'),
  ('enterprise', 'max_trades', 999999, '无限交易记录'),
  ('enterprise', 'daily_ai_calls', 999999, '无限AI分析调用'),
  ('enterprise', 'data_sources', 999, '所有数据源'),
  ('enterprise', 'push_notifications', 2, '高级推送通知'),
  ('enterprise', 'watchlist', 999999, '无限目标池 + StrikeZone'),
  ('enterprise', 'webapp', 2, '完整版 Web + Hunter 猎手')
ON CONFLICT (plan, action) DO NOTHING;

-- ============================================
-- RLS 策略
-- ============================================
ALTER TABLE public.plan_limits ENABLE ROW LEVEL SECURITY;

-- 所有认证用户可读取套餐限制
CREATE POLICY "plan_limits_authenticated_select"
  ON public.plan_limits FOR SELECT
  TO authenticated
  USING (true);

-- 允许匿名用户也查询套餐限制（展示定价页场景）
CREATE POLICY "plan_limits_anon_select"
  ON public.plan_limits FOR SELECT
  TO anon
  USING (true);

-- service_role 全权限
CREATE POLICY "plan_limits_service_all"
  ON public.plan_limits FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 注释
-- ============================================
COMMENT ON TABLE public.plan_limits IS
  '套餐限制配置表：定义各套餐的功能限制与额度。';
COMMENT ON COLUMN public.plan_limits.limit_value IS
  '限制值，999999 表示无限制（业务层视为 unlimited）。';
