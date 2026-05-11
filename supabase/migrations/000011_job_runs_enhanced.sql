-- ============================================
-- AI 持仓投资分析系统 2.0 — job_runs / delivery_runs 增强
-- Phase 4 Sprint 4.1: Cron 外置化与状态持久化
-- ============================================

-- ============================================================
-- 1. job_runs 增强：扩展状态值 + 新增字段
-- ============================================================

-- 新增 task_definition_id 外键
ALTER TABLE public.job_runs
  ADD COLUMN IF NOT EXISTS task_definition_id UUID REFERENCES public.task_definitions(id);

-- 新增 timeout_seconds 字段（从 task_definitions 继承或覆盖）
ALTER TABLE public.job_runs
  ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER;

-- 扩展 job_runs 状态 CHECK 约束
-- 原: 'PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'CANCELLED'
-- 新增: 'PARTIAL_SUCCESS', 'TIMED_OUT', 'ABANDONED'
ALTER TABLE public.job_runs DROP CONSTRAINT IF EXISTS chk_job_runs_status;
ALTER TABLE public.job_runs
  ADD CONSTRAINT chk_job_runs_status
  CHECK (status IN (
    'PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'CANCELLED',
    'PARTIAL_SUCCESS', 'TIMED_OUT', 'ABANDONED'
  ));

-- task_definition_id 索引：按任务定义查找执行记录
CREATE INDEX IF NOT EXISTS idx_job_runs_task_definition
  ON public.job_runs(task_definition_id);

-- Heartbeat 专用索引：快速扫描需要干预的 job
-- PENDING 超过5分钟 → 可能丢失启动信号
-- RUNNING 超时 → 可能卡死
-- PARTIAL_SUCCESS / TIMED_OUT → 需要关注
CREATE INDEX IF NOT EXISTS idx_job_runs_heartbeat
  ON public.job_runs(status, created_at)
  WHERE status IN ('PENDING', 'RUNNING', 'PARTIAL_SUCCESS', 'TIMED_OUT');

-- ============================================================
-- 2. delivery_runs 增强：扩展状态值
-- ============================================================

-- 扩展 delivery_runs 状态 CHECK 约束
-- 原: 'PENDING', 'SENT', 'DELIVERED', 'FAILED'
-- 新增: 'DELIVERY_FAILED', 'DELIVERY_TIMEOUT', 'ABANDONED'
ALTER TABLE public.delivery_runs DROP CONSTRAINT IF EXISTS chk_delivery_runs_status;
ALTER TABLE public.delivery_runs
  ADD CONSTRAINT chk_delivery_runs_status
  CHECK (status IN (
    'PENDING', 'SENT', 'DELIVERED', 'FAILED',
    'DELIVERY_FAILED', 'DELIVERY_TIMEOUT', 'ABANDONED'
  ));

-- Heartbeat 专用索引：快速扫描需要重试或关注的 delivery
-- PENDING → 可能未发送
-- FAILED / DELIVERY_FAILED → 需要重试
CREATE INDEX IF NOT EXISTS idx_delivery_runs_heartbeat
  ON public.delivery_runs(status, created_at)
  WHERE status IN ('PENDING', 'FAILED', 'DELIVERY_FAILED');

-- ============================================================
-- 3. 注释
-- ============================================================

COMMENT ON COLUMN public.job_runs.task_definition_id IS
  '关联 task_definitions 表，标识该 job 由哪个定时任务触发；NULL 表示手动触发或迁移前记录';
COMMENT ON COLUMN public.job_runs.timeout_seconds IS
  '该次执行的超时阈值（秒），通常从 task_definitions.timeout_seconds 继承';
COMMENT ON COLUMN public.job_runs.started_at IS
  '任务开始执行时间，由 JobManager.start_job() 设置';
COMMENT ON COLUMN public.job_runs.completed_at IS
  '任务完成时间（成功/失败/超时均记录），由 JobManager 终态方法设置';
