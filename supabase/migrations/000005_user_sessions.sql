-- AI 持仓投资分析系统 2.0 - 用户会话表
-- Phase 1 Sprint 1.3: 用户与会话管理

-- 用户会话表（持久化 OpenClaw contextToken）
CREATE TABLE public.user_sessions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_type    TEXT NOT NULL DEFAULT 'wechat_claw',  -- wechat_claw / telegram / web
  context_token   TEXT NOT NULL,                         -- OpenClaw 会话 token
  conversation_id TEXT,                                  -- 微信对话 ID
  device_info     TEXT,
  ip_address      INET,
  is_active       BOOLEAN DEFAULT TRUE,
  last_active_at  TIMESTAMPTZ DEFAULT now(),
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, session_type, conversation_id)
);

CREATE INDEX idx_user_sessions_tenant_active ON user_sessions(tenant_id, is_active);
CREATE INDEX idx_user_sessions_context_token ON user_sessions(context_token);

ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_sessions_select_tenant" ON user_sessions FOR SELECT USING (tenant_id = auth.uid());
CREATE POLICY "user_sessions_insert_tenant" ON user_sessions FOR INSERT WITH CHECK (tenant_id = auth.uid());
CREATE POLICY "user_sessions_update_tenant" ON user_sessions FOR UPDATE USING (tenant_id = auth.uid());
CREATE POLICY "user_sessions_delete_tenant" ON user_sessions FOR DELETE USING (tenant_id = auth.uid());
CREATE POLICY "user_sessions_service_all" ON user_sessions FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 自动更新 updated_at
CREATE TRIGGER trg_user_sessions_updated_at BEFORE UPDATE ON public.user_sessions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
