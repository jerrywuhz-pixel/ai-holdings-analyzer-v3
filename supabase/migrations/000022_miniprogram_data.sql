-- ============================================================
-- 000022_miniprogram_data.sql
-- 小程序专用数据表：review_notes + watchlist_items 扩展
-- ============================================================

-- 复盘笔记表
CREATE TABLE IF NOT EXISTS review_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note_key TEXT NOT NULL,
    note_value JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, note_key)
);

-- 确认 watchlist_items 表存在（如果之前迁移未创建）
-- 使用 DO 块避免重复创建错误
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'watchlist_items'
    ) THEN
        CREATE TABLE watchlist_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            local_id TEXT,
            symbol TEXT NOT NULL,
            provider_symbol TEXT NOT NULL DEFAULT '',
            market TEXT NOT NULL DEFAULT 'A',
            exchange TEXT NOT NULL DEFAULT '',
            stock_name TEXT,
            investment_thesis TEXT,
            strike_zone JSONB,
            last_fundamentals JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(tenant_id, symbol)
        );
    END IF;
END
$$;

-- 为 watchlist_items 添加可能缺少的列
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'watchlist_items') THEN
        -- 添加 local_id 列（如果不存在）
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'watchlist_items' AND column_name = 'local_id'
        ) THEN
            ALTER TABLE watchlist_items ADD COLUMN local_id TEXT;
        END IF;

        -- 添加 provider_symbol 列
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'watchlist_items' AND column_name = 'provider_symbol'
        ) THEN
            ALTER TABLE watchlist_items ADD COLUMN provider_symbol TEXT NOT NULL DEFAULT '';
        END IF;

        -- 添加 investment_thesis 列
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'watchlist_items' AND column_name = 'investment_thesis'
        ) THEN
            ALTER TABLE watchlist_items ADD COLUMN investment_thesis TEXT;
        END IF;
    END IF;
END
$$;

-- 索引
CREATE INDEX IF NOT EXISTS idx_review_notes_tenant ON review_notes(tenant_id);
CREATE INDEX IF NOT EXISTS idx_review_notes_key ON review_notes(tenant_id, note_key);
CREATE INDEX IF NOT EXISTS idx_watchlist_items_tenant ON watchlist_items(tenant_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_items_symbol ON watchlist_items(tenant_id, symbol);

-- updated_at 触发器
DROP TRIGGER IF EXISTS trg_review_notes_updated_at ON review_notes;
CREATE TRIGGER trg_review_notes_updated_at
    BEFORE UPDATE ON review_notes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_watchlist_items_updated_at ON watchlist_items;
CREATE TRIGGER trg_watchlist_items_updated_at
    BEFORE UPDATE ON watchlist_items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- RLS
ALTER TABLE review_notes ENABLE ROW LEVEL SECURITY;

CREATE POLICY review_notes_user_access ON review_notes
    FOR ALL USING (tenant_id::text = current_setting('request.jwt.claims', true)::json->>'tenant_id')
    WITH CHECK (tenant_id::text = current_setting('request.jwt.claims', true)::json->>'tenant_id');

CREATE POLICY review_notes_service_access ON review_notes
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- watchlist_items RLS（如果表是新创建的）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'watchlist_items' AND policyname = 'watchlist_items_user_access'
    ) THEN
        EXECUTE 'ALTER TABLE watchlist_items ENABLE ROW LEVEL SECURITY';
        EXECUTE 'CREATE POLICY watchlist_items_user_access ON watchlist_items
            FOR ALL USING (tenant_id::text = current_setting(''request.jwt.claims'', true)::json->>''tenant_id'')
            WITH CHECK (tenant_id::text = current_setting(''request.jwt.claims'', true)::json->>''tenant_id'')';
        EXECUTE 'CREATE POLICY watchlist_items_service_access ON watchlist_items
            FOR ALL USING (auth.role() = ''service_role'')
            WITH CHECK (auth.role() = ''service_role'')';
    END IF;
END
$$;
