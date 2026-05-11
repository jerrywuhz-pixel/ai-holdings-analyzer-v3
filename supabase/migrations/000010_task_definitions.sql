-- ============================================
-- AI 持仓投资分析系统 2.0 — 任务定义表
-- Phase 4 Sprint 4.1: Cron 外置化与状态持久化
-- ============================================

-- 任务定义表：将 cron 配置从代码/配置文件外置到数据库
CREATE TABLE IF NOT EXISTS public.task_definitions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name            TEXT NOT NULL UNIQUE,       -- 任务唯一名称，如 'daily-analysis'
  job_type        TEXT NOT NULL,              -- 对应 job_runs.job_type 的值
  cron_expression TEXT NOT NULL,              -- cron 表达式，如 '0 18 * * 1-5'
  skill_name      TEXT NOT NULL,              -- 对应 Skill 目录名，如 'daily-analysis'
  config          JSONB DEFAULT '{}',         -- 任务级配置（可覆盖 Skill 默认配置）
  is_enabled      BOOLEAN DEFAULT TRUE,       -- 是否启用
  timeout_seconds INTEGER DEFAULT 120,        -- 单次执行超时（秒）
  max_retries     INTEGER DEFAULT 3,          -- 最大重试次数
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 索引：按启用状态快速查找活跃任务
CREATE INDEX IF NOT EXISTS idx_task_definitions_enabled
  ON public.task_definitions(is_enabled)
  WHERE is_enabled = TRUE;

-- 索引：按 skill_name 查找关联任务
CREATE INDEX IF NOT EXISTS idx_task_definitions_skill
  ON public.task_definitions(skill_name);

-- 自动更新 updated_at
DROP TRIGGER IF EXISTS trg_task_definitions_updated_at ON public.task_definitions;
CREATE TRIGGER trg_task_definitions_updated_at
  BEFORE UPDATE ON public.task_definitions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- RLS：全局可读，仅 service_role 可写
ALTER TABLE public.task_definitions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "task_definitions_select_all"
  ON public.task_definitions FOR SELECT
  USING (true);

CREATE POLICY "task_definitions_write_service"
  ON public.task_definitions FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- 初始 cron 定义：核心定时任务
INSERT INTO public.task_definitions (name, job_type, cron_expression, skill_name, config, is_enabled, timeout_seconds, max_retries)
VALUES
  ('daily-analysis', 'daily_analysis', '0 18 * * 1-5', 'daily-analysis',
   '{"trigger_type": "cron", "user_scope": "all_active_with_trades"}'::jsonb,
   TRUE, 120, 3),
  ('daily-review', 'daily_review', '0 9 * * 1-5', 'daily-review',
   '{"trigger_type": "cron", "review_type": "morning_brief"}'::jsonb,
   TRUE, 120, 3),
  ('heartbeat', 'heartbeat', '*/5 * * * *', 'heartbeat',
   '{}'::jsonb,
   TRUE, 60, 3),
  ('weekly-report', 'weekly_report', '0 18 * * 5', 'weekly-report',
   '{"trigger_type": "cron", "report_type": "weekly"}'::jsonb,
   TRUE, 180, 3)
ON CONFLICT (name) DO NOTHING;
