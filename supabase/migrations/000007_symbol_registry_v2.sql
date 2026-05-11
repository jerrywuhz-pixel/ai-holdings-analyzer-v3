-- Phase 2: symbol_registry 版本控制与数据质量字段
-- Sprint 2.1: symbol_registry 建设

-- 版本控制与生命周期字段
ALTER TABLE public.symbol_registry
  ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1,
  ADD COLUMN IF NOT EXISTS valid_from DATE DEFAULT CURRENT_DATE,
  ADD COLUMN IF NOT EXISTS valid_to DATE DEFAULT '9999-12-31',
  ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ;

-- 数据质量索引：快速查询当前有效的股票
CREATE INDEX IF NOT EXISTS idx_symbol_registry_active
  ON symbol_registry(is_active, valid_from, valid_to)
  WHERE is_active = TRUE;

-- 版本索引：支持按版本号查询
CREATE INDEX IF NOT EXISTS idx_symbol_registry_version
  ON symbol_registry(symbol, version DESC);

COMMENT ON COLUMN symbol_registry.version IS '数据版本号，每次更新自增';
COMMENT ON COLUMN symbol_registry.valid_from IS '记录生效日期';
COMMENT ON COLUMN symbol_registry.valid_to IS '记录失效日期，9999-12-31 表示当前有效';
COMMENT ON COLUMN symbol_registry.last_verified_at IS '上次数据校验时间';
