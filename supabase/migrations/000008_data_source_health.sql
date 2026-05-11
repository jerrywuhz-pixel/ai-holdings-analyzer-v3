-- Phase 2: 数据源健康监控表
-- Sprint 2.2: 数据源服务完善

CREATE TABLE IF NOT EXISTS public.data_source_health (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_name       TEXT NOT NULL UNIQUE,     -- 'yahoo', 'tushare', 'akshare', 'longbridge'
  display_name      TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'unknown',  -- 'healthy', 'degraded', 'down', 'unknown'
  last_success_at   TIMESTAMPTZ,
  last_failure_at   TIMESTAMPTZ,
  last_error_message TEXT,
  consecutive_failures INTEGER DEFAULT 0,
  total_requests    INTEGER DEFAULT 0,
  total_failures    INTEGER DEFAULT 0,
  avg_response_ms   INTEGER,
  priority_cn       INTEGER DEFAULT 99,       -- A股优先级（越小越优先）
  priority_hk       INTEGER DEFAULT 99,       -- 港股优先级
  priority_us       INTEGER DEFAULT 99,       -- 美股优先级
  config            JSONB DEFAULT '{}',       -- 数据源配置（如 API key 状态）
  created_at        TIMESTAMPTZ DEFAULT now(),
  updated_at        TIMESTAMPTZ DEFAULT now()
);

-- 枚举约束
ALTER TABLE public.data_source_health
  ADD CONSTRAINT chk_dsh_status CHECK (status IN ('healthy', 'degraded', 'down', 'unknown'));

-- 索引
CREATE INDEX IF NOT EXISTS idx_dsh_status ON data_source_health(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_dsh_source ON data_source_health(source_name);

-- updated_at 自动更新 Trigger
DROP TRIGGER IF EXISTS trg_data_source_health_updated_at ON public.data_source_health;
CREATE TRIGGER trg_data_source_health_updated_at
  BEFORE UPDATE ON public.data_source_health
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- RLS（全局可读，仅 service_role 可写）
ALTER TABLE public.data_source_health ENABLE ROW LEVEL SECURITY;

CREATE POLICY "data_source_health_select_all"
  ON public.data_source_health FOR SELECT
  USING (true);

CREATE POLICY "data_source_health_write_service"
  ON public.data_source_health FOR ALL
  USING (false)
  WITH CHECK (false);

-- 初始数据：注册已知数据源
INSERT INTO public.data_source_health (source_name, display_name, status, priority_cn, priority_hk, priority_us)
VALUES
  ('yahoo', 'Yahoo Finance', 'unknown', 2, 1, 1),
  ('tushare', 'Tushare Pro', 'unknown', 1, 2, 2),
  ('akshare', 'AkShare', 'unknown', 3, 3, 3),
  ('longbridge', 'Longbridge', 'unknown', 99, 1, 99)
ON CONFLICT (source_name) DO NOTHING;
