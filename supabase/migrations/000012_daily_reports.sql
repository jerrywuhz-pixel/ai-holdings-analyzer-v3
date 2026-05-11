-- Phase 5: 日报存储表
-- 用于存储 Hermes 机会猎手生成的市场日报

-- ============================================
-- 1. daily_reports 表
-- ============================================
CREATE TABLE IF NOT EXISTS public.daily_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES users(id),
  report_type TEXT NOT NULL,        -- 'opportunity_cn', 'opportunity_us', 'opportunity_hk', 'analysis'
  report_date DATE NOT NULL,
  market TEXT NOT NULL,              -- 'CN', 'US', 'HK'
  content JSONB NOT NULL,            -- 结构化报告数据
  formatted_markdown TEXT,           -- Markdown 格式报告
  job_run_id UUID REFERENCES job_runs(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),

  -- 同一用户同一天同一类型报告唯一
  UNIQUE(tenant_id, report_type, report_date),

  -- 枚举约束
  CONSTRAINT chk_daily_reports_market CHECK (market IN ('CN', 'US', 'HK')),
  CONSTRAINT chk_daily_reports_type CHECK (
    report_type IN (
      'opportunity_cn',
      'opportunity_us',
      'opportunity_hk',
      'weekly_summary',
      'analysis'
    )
  )
);

-- ============================================
-- 2. 索引
-- ============================================
CREATE INDEX IF NOT EXISTS idx_daily_reports_tenant_date
  ON public.daily_reports(tenant_id, report_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_reports_type_date
  ON public.daily_reports(report_type, report_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_reports_market_date
  ON public.daily_reports(market, report_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_reports_job_run
  ON public.daily_reports(job_run_id);

-- ============================================
-- 3. updated_at 自动更新 Trigger
-- ============================================
CREATE TRIGGER trg_daily_reports_updated_at
  BEFORE UPDATE ON public.daily_reports
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================
-- 4. RLS 策略
-- ============================================
ALTER TABLE public.daily_reports ENABLE ROW LEVEL SECURITY;

-- 租户隔离：用户只能查看自己的报告
CREATE POLICY "daily_reports_tenant_select"
  ON public.daily_reports FOR SELECT
  USING (tenant_id = auth.uid());

-- 租户隔离：用户不能直接插入（由 service_role 写入）
CREATE POLICY "daily_reports_tenant_insert"
  ON public.daily_reports FOR INSERT
  WITH CHECK (tenant_id = auth.uid());

-- 租户隔离：用户不能直接更新
CREATE POLICY "daily_reports_tenant_update"
  ON public.daily_reports FOR UPDATE
  USING (tenant_id = auth.uid());

-- service_role 全权限
CREATE POLICY "daily_reports_service_all"
  ON public.daily_reports FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- 系统级报告（tenant_id 为 NULL）仅 service_role 可见
CREATE POLICY "daily_reports_system_select"
  ON public.daily_reports FOR SELECT
  USING (tenant_id IS NULL);
