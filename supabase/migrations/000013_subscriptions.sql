-- ============================================
-- AI 持仓投资分析系统 2.0 — 订阅表
-- Phase 7 Sprint 7.1: 套餐/支付/用量包
-- ============================================

-- 订阅表：跟踪用户当前套餐和支付状态
CREATE TABLE IF NOT EXISTS public.subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES users(id),
  plan TEXT NOT NULL DEFAULT 'free',  -- free/basic/pro/enterprise
  status TEXT NOT NULL DEFAULT 'active',  -- active/past_due/canceled/trialing
  current_period_start TIMESTAMPTZ NOT NULL DEFAULT now(),
  current_period_end TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '1 month'),
  cancel_at_period_end BOOLEAN DEFAULT FALSE,
  stripe_customer_id TEXT,           -- Stripe Customer ID
  stripe_subscription_id TEXT,       -- Stripe Subscription ID
  stripe_price_id TEXT,              -- Stripe Price ID
  wechat_transaction_id TEXT,        -- 微信支付交易号
  payment_method TEXT,               -- stripe/wechat
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),

  -- 一个用户只有一个活跃订阅
  UNIQUE(tenant_id),

  -- 枚举约束
  CONSTRAINT chk_sub_plan CHECK (plan IN ('free', 'basic', 'pro', 'enterprise')),
  CONSTRAINT chk_sub_status CHECK (status IN ('active', 'past_due', 'canceled', 'trialing')),
  CONSTRAINT chk_sub_payment_method CHECK (payment_method IS NULL OR payment_method IN ('stripe', 'wechat'))
);

-- ============================================
-- 索引
-- ============================================
CREATE INDEX IF NOT EXISTS idx_sub_tenant
  ON public.subscriptions(tenant_id);

CREATE INDEX IF NOT EXISTS idx_sub_stripe_customer
  ON public.subscriptions(stripe_customer_id);

CREATE INDEX IF NOT EXISTS idx_sub_stripe_subscription
  ON public.subscriptions(stripe_subscription_id);

-- ============================================
-- updated_at 自动更新 Trigger
-- ============================================
CREATE TRIGGER trg_subscriptions_updated_at
  BEFORE UPDATE ON public.subscriptions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================
-- RLS 策略
-- ============================================
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;

-- 租户隔离：用户只能查看自己的订阅
CREATE POLICY "subscriptions_tenant_select"
  ON public.subscriptions FOR SELECT
  USING (tenant_id = auth.uid());

-- 租户隔离：用户可创建自己的订阅（Checkout 完成时）
CREATE POLICY "subscriptions_tenant_insert"
  ON public.subscriptions FOR INSERT
  WITH CHECK (tenant_id = auth.uid());

-- 租户隔离：用户可更新自己的订阅
CREATE POLICY "subscriptions_tenant_update"
  ON public.subscriptions FOR UPDATE
  USING (tenant_id = auth.uid());

-- service_role 全权限（Webhook 回调使用）
CREATE POLICY "subscriptions_service_all"
  ON public.subscriptions FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 注释
-- ============================================
COMMENT ON TABLE public.subscriptions IS
  '用户订阅表：跟踪当前套餐、支付状态和 Stripe/微信支付关联信息。';
COMMENT ON COLUMN public.subscriptions.cancel_at_period_end IS
  '若为 true，当前周期结束后将自动取消订阅。';
COMMENT ON COLUMN public.subscriptions.payment_method IS
  '支付方式：stripe 或 wechat，NULL 表示尚未付费（free 套餐）。';
