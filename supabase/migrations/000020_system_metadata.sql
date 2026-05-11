-- Phase 8: Migration Completion Marker
-- 标记系统已完成从旧系统到 2.0 的迁移
-- 供运维脚本查询迁移状态使用

-- 创建系统元数据表（用于存储系统级配置和状态标记）
CREATE TABLE IF NOT EXISTS system_metadata (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 标记迁移完成
INSERT INTO system_metadata (key, value) VALUES
    ('migration_status', '{"status": "completed", "version": "2.0.0", "migrated_at": "2026-04-23"}'),
    ('legacy_system', '{"status": "deprecated", "decommission_date": "2026-05-01", "cloud_functions_stopped": false}')
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    updated_at = now();

-- 索引
CREATE INDEX IF NOT EXISTS idx_system_metadata_key
    ON system_metadata (key);

-- RLS: 只有 service_role 可以写入
ALTER TABLE system_metadata ENABLE ROW LEVEL SECURITY;

CREATE POLICY "system_metadata_read_all" ON system_metadata
    FOR SELECT USING (true);

CREATE POLICY "system_metadata_write_service" ON system_metadata
    FOR ALL USING (auth.role() = 'service_role');

COMMENT ON TABLE system_metadata IS 'System-level metadata and migration status markers';
