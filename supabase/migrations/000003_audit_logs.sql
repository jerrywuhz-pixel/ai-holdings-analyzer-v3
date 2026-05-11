-- ============================================
-- AI 持仓投资分析系统 2.0 — 审计日志表
-- Phase 1 Sprint 1.1: Gateway 数据访问中间件
-- ============================================

CREATE TABLE public.audit_logs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES users(id),
  skill_name  TEXT NOT NULL,
  table_name  TEXT NOT NULL,
  action      TEXT NOT NULL,  -- INSERT / UPDATE / DELETE
  record_id   UUID,
  data_before JSONB,
  data_after  JSONB,
  ip_address  INET,
  user_agent  TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- 索引：按租户 + 时间倒序查询（最常见的审计翻页场景）
CREATE INDEX idx_audit_logs_tenant_created
  ON audit_logs(tenant_id, created_at DESC);

-- 索引：按 Skill 维度聚合调用量
CREATE INDEX idx_audit_logs_skill
  ON audit_logs(skill_name);

-- 索引：按表名查询
CREATE INDEX idx_audit_logs_table
  ON audit_logs(table_name);

-- 索引：按操作类型过滤
CREATE INDEX idx_audit_logs_action
  ON audit_logs(action);

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- 租户只能查看自己的审计日志
CREATE POLICY "audit_logs_select_tenant"
  ON audit_logs
  FOR SELECT
  USING (tenant_id = auth.uid());

-- service_role 拥有完全权限（Gateway 中间件通过 service_role 写入）
CREATE POLICY "audit_logs_service_all"
  ON audit_logs
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
