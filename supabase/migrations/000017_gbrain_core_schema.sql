-- ============================================
-- gbrain for OpenClaw — Core Schema
-- Phase 1: 记忆知识库 10 张核心表
-- ============================================

-- 启用必要扩展
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 自动更新 updated_at 的通用函数（如已存在则跳过）
DO $outer$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
    CREATE OR REPLACE FUNCTION public.update_updated_at_column()
    RETURNS TRIGGER AS $fn$
    BEGIN
      NEW.updated_at = now();
      RETURN NEW;
    END;
    $fn$ LANGUAGE plpgsql;
  END IF;
END $outer$;

-- ============================================================
-- 1. gbrain_sources: 多租户映射（每个用户一个 source）
-- ============================================================
CREATE TABLE IF NOT EXISTS gbrain_sources (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  slug          TEXT NOT NULL,
  display_name  TEXT NOT NULL,
  config        JSONB NOT NULL DEFAULT '{"federated": false}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gbrain_sources_tenant ON gbrain_sources(tenant_id);

-- ============================================================
-- 2. gbrain_pages: 知识页面（核心表）
-- ============================================================
-- path 为 brain 目录路径，如 stocks/600519.SH, sectors/军工, insights/2026-04-23-daily
-- page_type: compiled_truth | timeline | insight | inbox | portfolio
-- tenant_id 冗余列用于 RLS 效率（避免 JOIN sources）
CREATE TABLE IF NOT EXISTS gbrain_pages (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id     UUID NOT NULL REFERENCES gbrain_sources(id) ON DELETE CASCADE,
  path          TEXT NOT NULL,
  title         TEXT NOT NULL,
  content       TEXT NOT NULL DEFAULT '',
  search_vector tsvector,
  page_type     TEXT NOT NULL DEFAULT 'compiled_truth',
  metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
  content_hash  TEXT,
  tenant_id     UUID REFERENCES users(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT gbrain_pages_source_path_unique UNIQUE (source_id, path),
  CONSTRAINT gbrain_pages_page_type_check CHECK (page_type IN (
    'compiled_truth', 'timeline', 'insight', 'inbox', 'portfolio',
    'stock', 'sector', 'strategy', 'event', 'concept'
  ))
);

CREATE INDEX IF NOT EXISTS idx_gbrain_pages_source_id ON gbrain_pages(source_id);
CREATE INDEX IF NOT EXISTS idx_gbrain_pages_tenant ON gbrain_pages(tenant_id);
CREATE INDEX IF NOT EXISTS idx_gbrain_pages_type ON gbrain_pages(page_type);
CREATE INDEX IF NOT EXISTS idx_gbrain_pages_trgm ON gbrain_pages USING GIN(title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_gbrain_pages_search ON gbrain_pages USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_gbrain_pages_updated_at ON gbrain_pages(updated_at DESC);

-- tsvector 自动更新触发器
CREATE OR REPLACE FUNCTION gbrain_pages_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('simple', COALESCE(NEW.title, '')), 'A') ||
    setweight(to_tsvector('simple', COALESCE(NEW.content, '')), 'B');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_gbrain_pages_sv ON gbrain_pages;
CREATE TRIGGER trg_gbrain_pages_sv
  BEFORE INSERT OR UPDATE OF title, content ON gbrain_pages
  FOR EACH ROW EXECUTE FUNCTION gbrain_pages_search_vector_update();

-- updated_at 自动更新
CREATE TRIGGER trg_gbrain_pages_updated_at
  BEFORE UPDATE ON gbrain_pages
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================
-- 3. gbrain_content_chunks: 分块嵌入（混合搜索）
-- ============================================================
CREATE TABLE IF NOT EXISTS gbrain_content_chunks (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id       UUID NOT NULL REFERENCES gbrain_pages(id) ON DELETE CASCADE,
  chunk_index   INTEGER NOT NULL,
  chunk_text    TEXT NOT NULL,
  chunk_source  TEXT NOT NULL DEFAULT 'compiled_truth',
  embedding     vector(1536),
  search_vector tsvector,
  model         TEXT NOT NULL DEFAULT 'text-embedding-3-small',
  token_count   INTEGER,
  embedded_at   TIMESTAMPTZ,
  tenant_id     UUID REFERENCES users(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_gbrain_chunks_page_index
  ON gbrain_content_chunks(page_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_gbrain_chunks_page ON gbrain_content_chunks(page_id);
CREATE INDEX IF NOT EXISTS idx_gbrain_chunks_embedding
  ON gbrain_content_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_gbrain_chunks_search
  ON gbrain_content_chunks USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_gbrain_chunks_tenant ON gbrain_content_chunks(tenant_id);

-- chunk tsvector 触发器
CREATE OR REPLACE FUNCTION gbrain_chunks_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector := to_tsvector('simple', COALESCE(NEW.chunk_text, ''));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_gbrain_chunks_sv ON gbrain_content_chunks;
CREATE TRIGGER trg_gbrain_chunks_sv
  BEFORE INSERT OR UPDATE OF chunk_text ON gbrain_content_chunks
  FOR EACH ROW EXECUTE FUNCTION gbrain_chunks_search_vector_update();

-- ============================================================
-- 4. gbrain_links: 类型化关系（知识图谱）
-- ============================================================
-- link_type: HOLDS | IN_SECTOR | ANALYZES | MENTIONS | RELATED | FOUNDED | ADVISES
-- confidence: 0.0-1.0，启发式推断默认 0.7，LLM 确认默认 0.9
CREATE TABLE IF NOT EXISTS gbrain_links (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_page_id  UUID NOT NULL REFERENCES gbrain_pages(id) ON DELETE CASCADE,
  target_page_id  UUID NOT NULL REFERENCES gbrain_pages(id) ON DELETE CASCADE,
  link_type       TEXT NOT NULL DEFAULT 'MENTIONS',
  confidence      REAL NOT NULL DEFAULT 0.7,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  tenant_id       UUID REFERENCES users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT gbrain_links_unique UNIQUE (source_page_id, target_page_id, link_type),
  CONSTRAINT gbrain_links_confidence_check CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_gbrain_links_source ON gbrain_links(source_page_id);
CREATE INDEX IF NOT EXISTS idx_gbrain_links_target ON gbrain_links(target_page_id);
CREATE INDEX IF NOT EXISTS idx_gbrain_links_type ON gbrain_links(link_type);
CREATE INDEX IF NOT EXISTS idx_gbrain_links_tenant ON gbrain_links(tenant_id);

-- ============================================================
-- 5. gbrain_tags: 标签定义
-- ============================================================
CREATE TABLE IF NOT EXISTS gbrain_tags (
  id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name      TEXT NOT NULL UNIQUE,
  category  TEXT NOT NULL DEFAULT 'general',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gbrain_tags_category ON gbrain_tags(category);

-- ============================================================
-- 6. gbrain_page_tags: 页面-标签多对多关联
-- ============================================================
CREATE TABLE IF NOT EXISTS gbrain_page_tags (
  page_id UUID NOT NULL REFERENCES gbrain_pages(id) ON DELETE CASCADE,
  tag_id  UUID NOT NULL REFERENCES gbrain_tags(id) ON DELETE CASCADE,
  PRIMARY KEY (page_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_gbrain_page_tags_tag ON gbrain_page_tags(tag_id);

-- ============================================================
-- 7. gbrain_timeline_entries: 时间线条目
-- ============================================================
-- event_type: TRADE_BUY | TRADE_SELL | ANALYSIS | MARKET_EVENT | ENRICHMENT | MANUAL
-- importance: 1-10，默认 5，交易事件 7，AI 分析 5
CREATE TABLE IF NOT EXISTS gbrain_timeline_entries (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id     UUID NOT NULL REFERENCES gbrain_pages(id) ON DELETE CASCADE,
  event_date  DATE NOT NULL,
  event_type  TEXT NOT NULL DEFAULT 'MANUAL',
  title       TEXT NOT NULL,
  content     TEXT NOT NULL DEFAULT '',
  metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
  importance  INTEGER NOT NULL DEFAULT 5,
  tenant_id   UUID REFERENCES users(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT gbrain_timeline_importance_check CHECK (importance >= 1 AND importance <= 10),
  CONSTRAINT gbrain_timeline_event_type_check CHECK (event_type IN (
    'TRADE_BUY', 'TRADE_SELL', 'ANALYSIS', 'MARKET_EVENT', 'ENRICHMENT', 'MANUAL'
  ))
);

CREATE INDEX IF NOT EXISTS idx_gbrain_timeline_page ON gbrain_timeline_entries(page_id);
CREATE INDEX IF NOT EXISTS idx_gbrain_timeline_date ON gbrain_timeline_entries(event_date DESC);
CREATE INDEX IF NOT EXISTS idx_gbrain_timeline_page_date
  ON gbrain_timeline_entries(page_id, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_gbrain_timeline_tenant ON gbrain_timeline_entries(tenant_id);
-- 去重约束
CREATE UNIQUE INDEX IF NOT EXISTS idx_gbrain_timeline_dedup
  ON gbrain_timeline_entries(page_id, event_date, title);

-- ============================================================
-- 8. gbrain_search_cache: 搜索结果缓存
-- ============================================================
CREATE TABLE IF NOT EXISTS gbrain_search_cache (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id   UUID NOT NULL REFERENCES gbrain_sources(id) ON DELETE CASCADE,
  query_hash  TEXT NOT NULL,
  query_text  TEXT NOT NULL,
  results     JSONB NOT NULL,
  search_type TEXT NOT NULL DEFAULT 'hybrid',
  tenant_id   UUID REFERENCES users(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at  TIMESTAMPTZ,
  CONSTRAINT gbrain_search_cache_unique UNIQUE (source_id, query_hash)
);

CREATE INDEX IF NOT EXISTS idx_gbrain_search_cache_tenant ON gbrain_search_cache(tenant_id);

-- ============================================================
-- 9. gbrain_minion_jobs: 异步任务队列
-- ============================================================
-- status: pending | running | completed | failed | cancelled
CREATE TABLE IF NOT EXISTS gbrain_minion_jobs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id     UUID NOT NULL REFERENCES gbrain_sources(id) ON DELETE CASCADE,
  job_type      TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending',
  payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
  result        JSONB,
  scheduled_at  TIMESTAMPTZ,
  started_at    TIMESTAMPTZ,
  completed_at  TIMESTAMPTZ,
  error_message TEXT,
  retry_count   INTEGER NOT NULL DEFAULT 0,
  tenant_id     UUID REFERENCES users(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT gbrain_minion_status_check CHECK (status IN (
    'pending', 'running', 'completed', 'failed', 'cancelled'
  ))
);

CREATE INDEX IF NOT EXISTS idx_gbrain_minion_status ON gbrain_minion_jobs(status)
  WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_gbrain_minion_tenant ON gbrain_minion_jobs(tenant_id);

-- ============================================================
-- 10. gbrain_config: 每 brain 配置
-- ============================================================
CREATE TABLE IF NOT EXISTS gbrain_config (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id       UUID NOT NULL UNIQUE REFERENCES gbrain_sources(id) ON DELETE CASCADE,
  embedding_model TEXT NOT NULL DEFAULT 'text-embedding-3-small',
  chunk_size      INTEGER NOT NULL DEFAULT 500,
  chunk_overlap   INTEGER NOT NULL DEFAULT 50,
  search_config   JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_gbrain_config_updated_at
  BEFORE UPDATE ON gbrain_config
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================
-- 种子数据：默认 source（系统级）
-- ============================================================
-- 注意：每个用户的 source 由 trigger 在用户创建时自动生成
-- 这里只创建系统级默认 source（用于系统任务）
INSERT INTO auth.users (
  instance_id,
  id,
  aud,
  role,
  email,
  encrypted_password,
  email_confirmed_at,
  raw_app_meta_data,
  raw_user_meta_data,
  created_at,
  updated_at
)
VALUES (
  '00000000-0000-0000-0000-000000000000'::uuid,
  '00000000-0000-0000-0000-000000000000'::uuid,
  'authenticated',
  'authenticated',
  'system@gbrain.local',
  '',
  now(),
  '{"provider": "email", "providers": ["email"]}'::jsonb,
  '{"system": true}'::jsonb,
  now(),
  now()
) ON CONFLICT (id) DO NOTHING;

INSERT INTO public.users (
  id,
  email,
  role,
  status,
  plan,
  migration_status,
  created_at,
  updated_at
)
VALUES (
  '00000000-0000-0000-0000-000000000000'::uuid,
  'system@gbrain.local',
  'admin',
  'ACTIVE',
  'enterprise',
  'migrated',
  now(),
  now()
)
ON CONFLICT (id) DO UPDATE
SET
  role = EXCLUDED.role,
  status = EXCLUDED.status,
  plan = EXCLUDED.plan,
  migration_status = EXCLUDED.migration_status,
  updated_at = now();

INSERT INTO gbrain_sources (id, tenant_id, slug, display_name, config)
VALUES (
  gen_random_uuid(),
  '00000000-0000-0000-0000-000000000000'::uuid,
  'system',
  'System Brain',
  '{"federated": false, "system": true}'::jsonb
) ON CONFLICT (tenant_id) DO NOTHING;

-- 注意：系统 source 的 tenant_id 使用零 UUID，
-- 实际用户的 source 由 trg_users_create_gbrain_source trigger 创建（在 000017 迁移中定义）
