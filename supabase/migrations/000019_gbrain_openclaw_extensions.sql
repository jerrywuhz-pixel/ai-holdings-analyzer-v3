-- ============================================
-- gbrain for OpenClaw — OpenClaw 扩展
-- Phase 1: 桥接表、同步日志、RLS、Source 触发器、Cron 种子
-- ============================================

-- ============================================================
-- A. memory_entity_bridge: 连接 gbrain pages 与业务实体
-- ============================================================
CREATE TABLE IF NOT EXISTS memory_entity_bridge (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  gbrain_page_id  UUID NOT NULL REFERENCES gbrain_pages(id) ON DELETE CASCADE,
  entity_type     TEXT NOT NULL,
  entity_id       UUID NOT NULL,
  entity_symbol   TEXT,
  sync_status     TEXT NOT NULL DEFAULT 'pending',
  last_synced_at  TIMESTAMPTZ,
  sync_error      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT memory_bridge_unique UNIQUE (gbrain_page_id, entity_type, entity_id),
  CONSTRAINT memory_bridge_entity_type_check CHECK (entity_type IN (
    'trade_event', 'position_snapshot', 'daily_report', 'symbol', 'sector', 'strategy'
  )),
  CONSTRAINT memory_bridge_sync_status_check CHECK (sync_status IN (
    'pending', 'synced', 'error'
  ))
);

CREATE INDEX IF NOT EXISTS idx_memory_bridge_tenant ON memory_entity_bridge(tenant_id);
CREATE INDEX IF NOT EXISTS idx_memory_bridge_entity ON memory_entity_bridge(tenant_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_memory_bridge_symbol ON memory_entity_bridge(entity_symbol)
  WHERE entity_symbol IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_bridge_status ON memory_entity_bridge(sync_status)
  WHERE sync_status IN ('pending', 'error');

CREATE TRIGGER trg_memory_bridge_updated_at
  BEFORE UPDATE ON memory_entity_bridge
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================
-- B. memory_sync_log: 同步操作日志
-- ============================================================
CREATE TABLE IF NOT EXISTS memory_sync_log (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sync_type         TEXT NOT NULL,
  direction         TEXT NOT NULL DEFAULT 'to_brain',
  entity_type       TEXT,
  entity_ids        UUID[],
  status            TEXT NOT NULL DEFAULT 'pending',
  records_processed INTEGER NOT NULL DEFAULT 0,
  records_failed    INTEGER NOT NULL DEFAULT 0,
  error_message     TEXT,
  started_at        TIMESTAMPTZ,
  completed_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT memory_sync_direction_check CHECK (direction IN ('to_brain', 'from_brain')),
  CONSTRAINT memory_sync_status_check CHECK (status IN (
    'pending', 'running', 'completed', 'failed'
  )),
  CONSTRAINT memory_sync_type_check CHECK (sync_type IN (
    'trade_event', 'daily_report', 'position_snapshot', 'full_reindex', 'dream_cycle'
  ))
);

CREATE INDEX IF NOT EXISTS idx_memory_sync_tenant ON memory_sync_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_memory_sync_type_status ON memory_sync_log(tenant_id, sync_type, status);
CREATE INDEX IF NOT EXISTS idx_memory_sync_created ON memory_sync_log(created_at DESC);

-- ============================================================
-- C. gbrain_pages 增强: last_analysis_at + analysis_version
-- ============================================================
ALTER TABLE gbrain_pages ADD COLUMN IF NOT EXISTS last_analysis_at TIMESTAMPTZ;
ALTER TABLE gbrain_pages ADD COLUMN IF NOT EXISTS analysis_version INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_gbrain_pages_last_analysis
  ON gbrain_pages(last_analysis_at) WHERE last_analysis_at IS NOT NULL;

-- ============================================================
-- D. 用户创建时自动创建 gbrain source
-- ============================================================
CREATE OR REPLACE FUNCTION public.create_gbrain_source()
RETURNS TRIGGER AS $$
DECLARE
  new_slug TEXT;
BEGIN
  -- 生成 slug：优先 wechat_nickname，其次 email，最后 fallback
  new_slug := COALESCE(
    NEW.wechat_nickname,
    split_part(NEW.email, '@', 1),
    'user-' || NEW.id::text
  );
  -- slug 清理：只保留字母数字和连字符
  new_slug := lower(regexp_replace(new_slug, '[^a-z0-9\u4e00-\u9fff-]', '-', 'gi'));
  new_slug := regexp_replace(new_slug, '-+', '-', 'g');
  new_slug := trim(BOTH '-' FROM new_slug);

  INSERT INTO gbrain_sources (id, tenant_id, slug, display_name, config)
  VALUES (
    gen_random_uuid(),
    NEW.id,
    new_slug,
    COALESCE(NEW.wechat_nickname, NEW.email, 'user-' || NEW.id::text),
    '{"federated": false}'::jsonb
  )
  ON CONFLICT (tenant_id) DO NOTHING;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_users_create_gbrain_source ON public.users;
CREATE TRIGGER trg_users_create_gbrain_source
  AFTER INSERT ON public.users
  FOR EACH ROW EXECUTE FUNCTION public.create_gbrain_source();

-- ============================================================
-- E. RLS 策略 — 所有 gbrain_* 和 memory_* 表
-- ============================================================

-- gbrain_sources: 用户只能看自己的 source
ALTER TABLE gbrain_sources ENABLE ROW LEVEL SECURITY;
CREATE POLICY "gbrain_sources_tenant_select" ON gbrain_sources
  FOR SELECT USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_sources_tenant_insert" ON gbrain_sources
  FOR INSERT WITH CHECK (tenant_id = auth.uid());
CREATE POLICY "gbrain_sources_service_all" ON gbrain_sources
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- gbrain_pages: tenant_id 隔离
ALTER TABLE gbrain_pages ENABLE ROW LEVEL SECURITY;
CREATE POLICY "gbrain_pages_tenant_select" ON gbrain_pages
  FOR SELECT USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_pages_tenant_insert" ON gbrain_pages
  FOR INSERT WITH CHECK (tenant_id = auth.uid());
CREATE POLICY "gbrain_pages_tenant_update" ON gbrain_pages
  FOR UPDATE USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_pages_tenant_delete" ON gbrain_pages
  FOR DELETE USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_pages_service_all" ON gbrain_pages
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- gbrain_content_chunks: tenant_id 隔离
ALTER TABLE gbrain_content_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "gbrain_chunks_tenant_select" ON gbrain_content_chunks
  FOR SELECT USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_chunks_tenant_insert" ON gbrain_content_chunks
  FOR INSERT WITH CHECK (tenant_id = auth.uid());
CREATE POLICY "gbrain_chunks_tenant_delete" ON gbrain_content_chunks
  FOR DELETE USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_chunks_service_all" ON gbrain_content_chunks
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- gbrain_links: tenant_id 隔离
ALTER TABLE gbrain_links ENABLE ROW LEVEL SECURITY;
CREATE POLICY "gbrain_links_tenant_select" ON gbrain_links
  FOR SELECT USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_links_tenant_insert" ON gbrain_links
  FOR INSERT WITH CHECK (tenant_id = auth.uid());
CREATE POLICY "gbrain_links_tenant_delete" ON gbrain_links
  FOR DELETE USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_links_service_all" ON gbrain_links
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- gbrain_tags: 全局只读（跨租户共享标签）
ALTER TABLE gbrain_tags ENABLE ROW LEVEL SECURITY;
CREATE POLICY "gbrain_tags_select_all" ON gbrain_tags
  FOR SELECT USING (true);
CREATE POLICY "gbrain_tags_service_all" ON gbrain_tags
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- gbrain_page_tags: 通过 page 间接隔离
ALTER TABLE gbrain_page_tags ENABLE ROW LEVEL SECURITY;
CREATE POLICY "gbrain_page_tags_select" ON gbrain_page_tags
  FOR SELECT USING (
    page_id IN (SELECT id FROM gbrain_pages WHERE tenant_id = auth.uid())
  );
CREATE POLICY "gbrain_page_tags_service_all" ON gbrain_page_tags
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- gbrain_timeline_entries: tenant_id 隔离
ALTER TABLE gbrain_timeline_entries ENABLE ROW LEVEL SECURITY;
CREATE POLICY "gbrain_timeline_tenant_select" ON gbrain_timeline_entries
  FOR SELECT USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_timeline_tenant_insert" ON gbrain_timeline_entries
  FOR INSERT WITH CHECK (tenant_id = auth.uid());
CREATE POLICY "gbrain_timeline_tenant_delete" ON gbrain_timeline_entries
  FOR DELETE USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_timeline_service_all" ON gbrain_timeline_entries
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- gbrain_search_cache: tenant_id 隔离
ALTER TABLE gbrain_search_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "gbrain_cache_tenant_select" ON gbrain_search_cache
  FOR SELECT USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_cache_tenant_insert" ON gbrain_search_cache
  FOR INSERT WITH CHECK (tenant_id = auth.uid());
CREATE POLICY "gbrain_cache_tenant_delete" ON gbrain_search_cache
  FOR DELETE USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_cache_service_all" ON gbrain_search_cache
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- gbrain_minion_jobs: tenant_id 隔离
ALTER TABLE gbrain_minion_jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "gbrain_minion_tenant_select" ON gbrain_minion_jobs
  FOR SELECT USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_minion_tenant_insert" ON gbrain_minion_jobs
  FOR INSERT WITH CHECK (tenant_id = auth.uid());
CREATE POLICY "gbrain_minion_tenant_update" ON gbrain_minion_jobs
  FOR UPDATE USING (tenant_id = auth.uid());
CREATE POLICY "gbrain_minion_service_all" ON gbrain_minion_jobs
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- gbrain_config: 通过 source 间接隔离
ALTER TABLE gbrain_config ENABLE ROW LEVEL SECURITY;
CREATE POLICY "gbrain_config_select" ON gbrain_config
  FOR SELECT USING (
    source_id IN (SELECT id FROM gbrain_sources WHERE tenant_id = auth.uid())
  );
CREATE POLICY "gbrain_config_service_all" ON gbrain_config
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- memory_entity_bridge: tenant_id 隔离
ALTER TABLE memory_entity_bridge ENABLE ROW LEVEL SECURITY;
CREATE POLICY "memory_bridge_tenant_select" ON memory_entity_bridge
  FOR SELECT USING (tenant_id = auth.uid());
CREATE POLICY "memory_bridge_tenant_insert" ON memory_entity_bridge
  FOR INSERT WITH CHECK (tenant_id = auth.uid());
CREATE POLICY "memory_bridge_tenant_update" ON memory_entity_bridge
  FOR UPDATE USING (tenant_id = auth.uid());
CREATE POLICY "memory_bridge_service_all" ON memory_entity_bridge
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- memory_sync_log: tenant_id 隔离
ALTER TABLE memory_sync_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "memory_sync_tenant_select" ON memory_sync_log
  FOR SELECT USING (tenant_id = auth.uid());
CREATE POLICY "memory_sync_tenant_insert" ON memory_sync_log
  FOR INSERT WITH CHECK (tenant_id = auth.uid());
CREATE POLICY "memory_sync_tenant_update" ON memory_sync_log
  FOR UPDATE USING (tenant_id = auth.uid());
CREATE POLICY "memory_sync_service_all" ON memory_sync_log
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ============================================================
-- F. Cron 任务种子
-- ============================================================
INSERT INTO public.task_definitions (name, job_type, cron_expression, skill_name, config, is_enabled, timeout_seconds, max_retries)
VALUES
  ('gbrain-sync', 'gbrain_sync', '*/15 * * * *', 'gbrain-sync',
   '{"sync_types": ["trade_event", "daily_report"], "batch_size": 50}'::jsonb,
   TRUE, 120, 3),
  ('gbrain-dream', 'gbrain_dream', '0 2 * * *', 'gbrain-dream',
   '{"ops": ["reindex", "links", "compile"]}'::jsonb,
   TRUE, 600, 2)
ON CONFLICT (name) DO NOTHING;
