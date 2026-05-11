-- ============================================
-- AI 持仓投资分析系统 2.0 — 用量包定义与用户购买记录
-- Phase 7 Sprint 7.1: 套餐/支付/用量包
-- ============================================

-- ============================================
-- 1. 用量包定义表
-- ============================================
CREATE TABLE IF NOT EXISTS public.addon_packs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE,         -- 'ai_analysis_pack', 'a_share_deep_pack', 'realtime_news_pack'
  display_name TEXT NOT NULL,
  description TEXT,
  price_cny NUMERIC(10,2) NOT NULL,  -- 9.90, 19.90, 29.90
  price_stripe_id TEXT,              -- Stripe Price ID
  quota_action TEXT NOT NULL,        -- Which action this pack adds quota to
  quota_amount INTEGER NOT NULL,     -- How many units this pack adds
  validity_days INTEGER DEFAULT 30,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- 2. 用户已购买的用量包
-- ============================================
CREATE TABLE IF NOT EXISTS public.user_addon_packs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES users(id),
  addon_pack_id UUID NOT NULL REFERENCES addon_packs(id),
  quantity INTEGER NOT NULL DEFAULT 1,
  remaining_quota INTEGER NOT NULL,
  purchased_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  stripe_session_id TEXT,
  wechat_transaction_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- 3. 索引
-- ============================================
CREATE INDEX IF NOT EXISTS idx_user_addon_tenant
  ON public.user_addon_packs(tenant_id, expires_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_addon_pack
  ON public.user_addon_packs(addon_pack_id);

CREATE INDEX IF NOT EXISTS idx_addon_packs_active
  ON public.addon_packs(is_active) WHERE is_active = TRUE;

-- ============================================
-- 4. 插入用量包定义
-- ============================================

-- AI分析包: 9.9元/50次
INSERT INTO public.addon_packs (name, display_name, description, price_cny, quota_action, quota_amount, validity_days) VALUES
  ('ai_analysis_pack', 'AI分析包', '50次AI分析调用额度，有效期30天', 9.90, 'daily_ai_calls', 50, 30)
ON CONFLICT (name) DO NOTHING;

-- A股深度数据包: 19.9元/月
INSERT INTO public.addon_packs (name, display_name, description, price_cny, quota_action, quota_amount, validity_days) VALUES
  ('a_share_deep_pack', 'A股深度数据包', '1000次A股深度数据读取，有效期30天', 19.90, 'data_read', 1000, 30)
ON CONFLICT (name) DO NOTHING;

-- 实时快讯包: 29.9元/月
INSERT INTO public.addon_packs (name, display_name, description, price_cny, quota_action, quota_amount, validity_days) VALUES
  ('realtime_news_pack', '实时快讯包', '5000次实时快讯数据读取，有效期30天', 29.90, 'data_read', 5000, 30)
ON CONFLICT (name) DO NOTHING;

-- ============================================
-- 5. RLS 策略 — addon_packs
-- ============================================
ALTER TABLE public.addon_packs ENABLE ROW LEVEL SECURITY;

-- 所有认证用户可查看可购买的用量包
CREATE POLICY "addon_packs_authenticated_select"
  ON public.addon_packs FOR SELECT
  TO authenticated
  USING (true);

-- 允许匿名用户查看用量包（定价页展示）
CREATE POLICY "addon_packs_anon_select"
  ON public.addon_packs FOR SELECT
  TO anon
  USING (true);

-- service_role 全权限
CREATE POLICY "addon_packs_service_all"
  ON public.addon_packs FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 6. RLS 策略 — user_addon_packs
-- ============================================
ALTER TABLE public.user_addon_packs ENABLE ROW LEVEL SECURITY;

-- 租户隔离：用户只能查看自己购买的用量包
CREATE POLICY "user_addon_packs_tenant_select"
  ON public.user_addon_packs FOR SELECT
  USING (tenant_id = auth.uid());

-- 租户隔离：用户可创建自己的购买记录（Checkout 完成时）
CREATE POLICY "user_addon_packs_tenant_insert"
  ON public.user_addon_packs FOR INSERT
  WITH CHECK (tenant_id = auth.uid());

-- 租户隔离：用户可更新自己的购买记录（配额扣减）
CREATE POLICY "user_addon_packs_tenant_update"
  ON public.user_addon_packs FOR UPDATE
  USING (tenant_id = auth.uid());

-- service_role 全权限（Webhook 回调 + 配额扣减使用）
CREATE POLICY "user_addon_packs_service_all"
  ON public.user_addon_packs FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 7. 注释
-- ============================================
COMMENT ON TABLE public.addon_packs IS
  '用量包定义表：定义可购买的额外额度包，如AI分析包、A股深度数据包等。';
COMMENT ON TABLE public.user_addon_packs IS
  '用户已购买的用量包：记录购买详情、剩余额度和过期时间。';
COMMENT ON COLUMN public.user_addon_packs.remaining_quota IS
  '剩余额度，每次使用时递减，归零后不再可用。';
