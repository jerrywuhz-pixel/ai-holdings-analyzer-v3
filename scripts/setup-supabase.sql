-- ============================================================
-- AI Holdings Analyzer 2.0 - Phase 1 Supabase 初始化辅助脚本
-- 执行所有迁移后，运行此脚本完成 Phase 1 初始化
-- ============================================================

-- ------------------------------------------------------------
-- 1. 为所有现有用户创建 quota_tracking 记录
-- ------------------------------------------------------------
INSERT INTO quota_tracking (tenant_id)
SELECT id FROM users
ON CONFLICT (tenant_id) DO NOTHING;

-- ------------------------------------------------------------
-- 2. 创建 audit_logs 常用查询索引（如尚未在迁移中创建）
-- ------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_created
    ON audit_logs (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_skill_created
    ON audit_logs (skill_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_channel_created
    ON audit_logs (channel, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_status_created
    ON audit_logs (status, created_at DESC);

-- ------------------------------------------------------------
-- 3. 查看配额整体使用情况
-- ------------------------------------------------------------
SELECT * FROM quota_status;

-- ------------------------------------------------------------
-- 4. 查看今日各 Skill 调用统计
-- ------------------------------------------------------------
SELECT
    skill_name,
    COUNT(*) AS total_calls,
    COUNT(CASE WHEN status = 'success' THEN 1 END) AS success_count,
    COUNT(CASE WHEN status = 'error' THEN 1 END) AS error_count,
    ROUND(
        COUNT(CASE WHEN status = 'success' THEN 1 END)::numeric
        / NULLIF(COUNT(*), 0) * 100,
        2
    ) AS success_rate_pct
FROM audit_logs
WHERE created_at >= CURRENT_DATE
GROUP BY skill_name
ORDER BY total_calls DESC;

-- ------------------------------------------------------------
-- 5. 查看微信渠道近期消息
-- ------------------------------------------------------------
SELECT
    tenant_id,
    skill_name,
    status,
    created_at
FROM audit_logs
WHERE channel = 'wechat_claw'
  AND created_at >= CURRENT_DATE
ORDER BY created_at DESC
LIMIT 20;
