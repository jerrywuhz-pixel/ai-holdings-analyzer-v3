-- AI 持仓投资分析系统 2.0 - 初始 Schema
-- Phase 0.1: Supabase 基础设施

-- 自动更新 updated_at 的通用函数
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 用户扩展表（与 Supabase Auth 关联）
CREATE TABLE public.users (
  id              UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email           TEXT UNIQUE,
  wechat_openid   TEXT UNIQUE,
  wechat_unionid  TEXT,
  wechat_nickname TEXT,
  wechat_avatar_url TEXT,
  openclaw_pairing_code TEXT,
  role            TEXT NOT NULL DEFAULT 'user',
  status          TEXT NOT NULL DEFAULT 'NEW',
  plan            TEXT NOT NULL DEFAULT 'free',
  migration_status TEXT DEFAULT 'pending',
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now(),

  -- 至少存在一种用户标识
  CONSTRAINT chk_users_login_identifier CHECK (email IS NOT NULL OR wechat_openid IS NOT NULL),
  -- 枚举约束
  CONSTRAINT chk_users_role CHECK (role IN ('user', 'admin')),
  CONSTRAINT chk_users_status CHECK (status IN ('NEW', 'ACTIVE', 'SUSPENDED', 'DELETED')),
  CONSTRAINT chk_users_plan CHECK (plan IN ('free', 'basic', 'pro', 'enterprise')),
  CONSTRAINT chk_users_migration_status CHECK (migration_status IN ('pending', 'migrated', 'rollback'))
);

-- 交易事件表（唯一真相源）
CREATE TABLE public.trade_events (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id               UUID NOT NULL REFERENCES users(id),
  symbol                  TEXT NOT NULL,
  provider_symbol         TEXT NOT NULL,
  market                  TEXT NOT NULL,
  exchange                TEXT NOT NULL,
  stock_name              TEXT,
  side                    TEXT NOT NULL,
  price                   NUMERIC(18,4) NOT NULL,
  quantity                INTEGER NOT NULL,
  trade_amount            NUMERIC(18,2),
  trade_date              DATE NOT NULL,
  note                    TEXT,
  strategy_tag            TEXT,
  source                  TEXT NOT NULL DEFAULT 'manual',
  broker_message_fingerprint TEXT,
  created_at              TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, broker_message_fingerprint),

  -- 枚举约束
  CONSTRAINT chk_trade_events_side CHECK (side IN ('BUY', 'SELL')),
  CONSTRAINT chk_trade_events_source CHECK (source IN ('manual', 'broker_wechat', 'ocr', 'batch_import')),
  -- trade_amount 与 price * quantity 一致性校验（允许 NULL 及 <=1 的舍入误差）
  CONSTRAINT chk_trade_amount_consistency CHECK (
    trade_amount IS NULL
    OR ABS(trade_amount - ROUND(price::numeric * quantity, 2)) <= 1
  ),
  -- broker_message_fingerprint 非空时不能是空字符串
  CONSTRAINT chk_fingerprint_not_empty CHECK (broker_message_fingerprint IS NULL OR broker_message_fingerprint <> '')
);

-- 持仓快照表（由 Trigger 从 trade_events 计算）
CREATE TABLE public.position_snapshots (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES users(id),
  symbol          TEXT NOT NULL,
  provider_symbol TEXT NOT NULL,
  market          TEXT NOT NULL,
  exchange        TEXT NOT NULL,
  stock_name      TEXT,
  total_quantity  INTEGER NOT NULL DEFAULT 0,
  average_cost    NUMERIC(18,4),
  total_cost      NUMERIC(18,2),
  snapshot_date   DATE NOT NULL DEFAULT CURRENT_DATE,
  computed_from_event_ids UUID[],
  created_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, symbol, snapshot_date)
);

-- 股票注册表（替代硬编码）
CREATE TABLE public.symbol_registry (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol              TEXT NOT NULL UNIQUE,
  provider_symbols    JSONB NOT NULL,
  market              TEXT NOT NULL,
  exchange            TEXT NOT NULL,
  exchange_name       TEXT NOT NULL,
  name_zh             TEXT,
  name_en             TEXT,
  aliases             TEXT[],
  sector              TEXT,
  industry            TEXT,
  is_index            BOOLEAN DEFAULT FALSE,
  is_active           BOOLEAN DEFAULT TRUE,
  created_at          TIMESTAMPTZ DEFAULT now(),
  updated_at          TIMESTAMPTZ DEFAULT now()
);

-- 任务执行表（tenant_id 可为 NULL，支持系统级后台任务）
CREATE TABLE public.job_runs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID REFERENCES users(id),
  job_type        TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'PENDING',
  config          JSONB,
  result_summary  JSONB,
  started_at      TIMESTAMPTZ,
  completed_at    TIMESTAMPTZ,
  error_message   TEXT,
  retry_count     INTEGER DEFAULT 0,
  created_at      TIMESTAMPTZ DEFAULT now(),

  -- 枚举约束
  CONSTRAINT chk_job_runs_status CHECK (status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'CANCELLED'))
);

-- 发送表
CREATE TABLE public.delivery_runs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_run_id      UUID NOT NULL REFERENCES job_runs(id),
  tenant_id       UUID NOT NULL REFERENCES users(id),
  channel         TEXT NOT NULL DEFAULT 'wechat_claw',
  status          TEXT NOT NULL DEFAULT 'PENDING',
  content         JSONB,
  context_token   TEXT,
  target_conversation TEXT,
  delivery_key    TEXT,
  idempotency_key TEXT NOT NULL,
  sent_at         TIMESTAMPTZ,
  error_message   TEXT,
  retry_count     INTEGER DEFAULT 0,
  created_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, idempotency_key),

  -- 枚举约束
  CONSTRAINT chk_delivery_runs_status CHECK (status IN ('PENDING', 'SENT', 'DELIVERED', 'FAILED')),
  CONSTRAINT chk_delivery_runs_channel CHECK (channel IN ('wechat_claw', 'email', 'sms', 'push'))
);

-- 索引
CREATE INDEX idx_trade_events_tenant_date ON trade_events(tenant_id, trade_date DESC);
CREATE INDEX idx_trade_events_tenant_symbol ON trade_events(tenant_id, symbol);
CREATE INDEX idx_symbol_registry_aliases ON symbol_registry USING GIN(aliases);
CREATE INDEX idx_symbol_registry_provider_symbols ON symbol_registry USING GIN(provider_symbols jsonb_path_ops);
CREATE INDEX idx_position_snapshots_tenant_date ON position_snapshots(tenant_id, snapshot_date DESC);
CREATE INDEX idx_job_runs_tenant_status ON job_runs(tenant_id, status);
CREATE INDEX idx_delivery_runs_tenant_status ON delivery_runs(tenant_id, status);
CREATE INDEX idx_delivery_runs_job_run_id ON delivery_runs(job_run_id);
CREATE INDEX idx_position_snapshots_event_ids ON position_snapshots USING GIN(computed_from_event_ids);

-- Check Constraint（tenant_id 非空）
ALTER TABLE trade_events ADD CONSTRAINT chk_tenant_not_null CHECK (tenant_id IS NOT NULL);
ALTER TABLE position_snapshots ADD CONSTRAINT chk_snap_tenant_not_null CHECK (tenant_id IS NOT NULL);
-- job_runs 允许 NULL tenant_id（系统级任务），不加 chk_job_tenant_not_null
ALTER TABLE delivery_runs ADD CONSTRAINT chk_delivery_tenant_not_null CHECK (tenant_id IS NOT NULL);

-- updated_at 自动更新 Trigger
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON public.users
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
CREATE TRIGGER trg_symbol_registry_updated_at BEFORE UPDATE ON public.symbol_registry
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- RLS
ALTER TABLE trade_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE position_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE symbol_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE delivery_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
