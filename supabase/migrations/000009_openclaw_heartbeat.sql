-- Phase 2: OpenClaw 健康探针表
-- 用于监控 Gateway / Agent 运行状态

CREATE TABLE IF NOT EXISTS public.openclaw_heartbeat (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deployment_mode     TEXT NOT NULL DEFAULT 'cloud',   -- 'local' / 'cloud'
  instance_id         TEXT NOT NULL,                    -- 实例标识（hostname / container-id）
  gateway_status      TEXT NOT NULL DEFAULT 'unknown',  -- 'healthy' / 'degraded' / 'down'
  last_cron_run_at    TIMESTAMPTZ,
  active_skills       TEXT[],
  claw_plugin_status  TEXT DEFAULT 'unknown',           -- 'connected' / 'disconnected' / 'error'
  memory_usage_mb     INTEGER,
  cpu_usage_percent   NUMERIC(5,2),
  reported_at         TIMESTAMPTZ DEFAULT now(),
  created_at          TIMESTAMPTZ DEFAULT now()
);

-- 枚举约束
ALTER TABLE public.openclaw_heartbeat
  ADD CONSTRAINT chk_oh_deploy_mode CHECK (deployment_mode IN ('local', 'cloud')),
  ADD CONSTRAINT chk_oh_gateway_status CHECK (gateway_status IN ('healthy', 'degraded', 'down', 'unknown')),
  ADD CONSTRAINT chk_oh_claw_status CHECK (claw_plugin_status IN ('connected', 'disconnected', 'error', 'unknown'));

-- 索引
CREATE INDEX IF NOT EXISTS idx_openclaw_heartbeat_reported
  ON openclaw_heartbeat(reported_at DESC);
CREATE INDEX IF NOT EXISTS idx_openclaw_heartbeat_instance
  ON openclaw_heartbeat(instance_id, reported_at DESC);

-- RLS（仅实例自身和 service_role 可读写）
ALTER TABLE public.openclaw_heartbeat ENABLE ROW LEVEL SECURITY;

CREATE POLICY "openclaw_heartbeat_select_all"
  ON public.openclaw_heartbeat FOR SELECT
  USING (true);

CREATE POLICY "openclaw_heartbeat_write_service"
  ON public.openclaw_heartbeat FOR ALL
  USING (false)
  WITH CHECK (false);
