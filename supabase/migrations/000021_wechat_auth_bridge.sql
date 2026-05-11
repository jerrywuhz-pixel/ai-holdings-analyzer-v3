-- ============================================================
-- 000021_wechat_auth_bridge.sql
-- 微信小程序认证桥接：openid → Supabase auth
-- ============================================================

-- 微信认证提供商表（一个 Supabase user 可关联多个微信 openid）
CREATE TABLE IF NOT EXISTS weixin_auth_providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    openid TEXT NOT NULL,
    unionid TEXT,
    session_key TEXT NOT NULL,  -- 加密存储，仅服务端使用
    appid TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(openid, appid)
);

-- 小程序会话表
CREATE TABLE IF NOT EXISTS miniprogram_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    device_id TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    revoked_at TIMESTAMPTZ
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_weixin_auth_openid ON weixin_auth_providers(openid);
CREATE INDEX IF NOT EXISTS idx_weixin_auth_user_id ON weixin_auth_providers(user_id);
CREATE INDEX IF NOT EXISTS idx_miniprogram_sessions_tenant ON miniprogram_sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_miniprogram_sessions_expires ON miniprogram_sessions(expires_at);

-- updated_at 自动更新触发器
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_weixin_auth_updated_at ON weixin_auth_providers;
CREATE TRIGGER trg_weixin_auth_updated_at
    BEFORE UPDATE ON weixin_auth_providers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- RLS
ALTER TABLE weixin_auth_providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE miniprogram_sessions ENABLE ROW LEVEL SECURITY;

-- 用户只能访问自己的记录
CREATE POLICY weixin_auth_user_access ON weixin_auth_providers
    FOR ALL USING (user_id = auth.uid() OR user_id::text = current_setting('request.jwt.claims', true)::json->>'tenant_id')
    WITH CHECK (user_id = auth.uid() OR user_id::text = current_setting('request.jwt.claims', true)::json->>'tenant_id');

CREATE POLICY miniprogram_sessions_user_access ON miniprogram_sessions
    FOR ALL USING (tenant_id = auth.uid() OR tenant_id::text = current_setting('request.jwt.claims', true)::json->>'tenant_id')
    WITH CHECK (tenant_id = auth.uid() OR tenant_id::text = current_setting('request.jwt.claims', true)::json->>'tenant_id');

-- service_role 完全访问
CREATE POLICY weixin_auth_service_access ON weixin_auth_providers
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

CREATE POLICY miniprogram_sessions_service_access ON miniprogram_sessions
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- 清理过期会话的函数
CREATE OR REPLACE FUNCTION clean_expired_sessions()
RETURNS void AS $$
BEGIN
    DELETE FROM miniprogram_sessions WHERE expires_at < NOW();
END;
$$ LANGUAGE plpgsql;
