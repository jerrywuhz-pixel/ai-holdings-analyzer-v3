-- Phase 8: Performance Indexes
-- Target: All frequent queries < 100ms

-- 1. position_snapshots: tenant isolation + market filter (dashboard, positions page)
CREATE INDEX IF NOT EXISTS idx_position_snapshots_tenant_market
  ON position_snapshots (tenant_id, market)
  WHERE total_quantity > 0;

-- 2. trade_events: tenant + date range (transactions page, position detail)
CREATE INDEX IF NOT EXISTS idx_trade_events_tenant_date
  ON trade_events (tenant_id, created_at DESC);

-- 3. trade_events: tenant + symbol (position detail trade history)
CREATE INDEX IF NOT EXISTS idx_trade_events_tenant_symbol
  ON trade_events (tenant_id, symbol);

-- 4. job_runs: status + created_at (dashboard, jobs page)
CREATE INDEX IF NOT EXISTS idx_job_runs_status_created
  ON job_runs (status, created_at DESC);

-- 5. job_runs: tenant_id (user-scoped queries)
CREATE INDEX IF NOT EXISTS idx_job_runs_tenant
  ON job_runs (tenant_id)
  WHERE tenant_id IS NOT NULL;

-- 6. delivery_runs: status + retry_count (heartbeat retry scan)
CREATE INDEX IF NOT EXISTS idx_delivery_runs_status_retry
  ON delivery_runs (status, retry_count)
  WHERE status IN ('FAILED', 'DELIVERY_FAILED', 'DELIVERY_TIMEOUT');

-- 7. usage_records: tenant + action + created_at (quota check, usage summary)
CREATE INDEX IF NOT EXISTS idx_usage_records_tenant_action_date
  ON usage_records (tenant_id, action, created_at DESC);

-- 8. subscriptions: tenant_id (billing page, quota check)
CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant
  ON subscriptions (tenant_id);

-- 9. daily_reports: tenant + report_type + date (weekly page, report lookup)
CREATE INDEX IF NOT EXISTS idx_daily_reports_lookup
  ON daily_reports (tenant_id, report_type, report_date DESC);

-- 10. audit_logs: tenant_id + created_at (admin audit log)
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_date
  ON audit_logs (tenant_id, created_at DESC);

-- 11. quota_tracking: tenant_id (quota check hot path)
CREATE INDEX IF NOT EXISTS idx_quota_tracking_tenant
  ON quota_tracking (tenant_id);

-- 12. user_addon_packs: tenant + expires_at (addon remaining check)
CREATE INDEX IF NOT EXISTS idx_user_addon_packs_tenant_active
  ON user_addon_packs (tenant_id, expires_at)
  WHERE remaining_quota > 0;

-- 13. plan_limits: plan + action (frequently looked up during quota check)
CREATE INDEX IF NOT EXISTS idx_plan_limits_plan_action
  ON plan_limits (plan, action);

-- 14. symbol_registry: active symbols search (symbol resolver)
CREATE INDEX IF NOT EXISTS idx_symbol_registry_active
  ON symbol_registry (symbol, market)
  WHERE valid_to IS NULL;

-- 15. data_source_health: source_name (health check lookup)
CREATE INDEX IF NOT EXISTS idx_data_source_health_source
  ON data_source_health (source_name);

-- 16. openclaw_heartbeat: instance_id (upsert target)
CREATE INDEX IF NOT EXISTS idx_openclaw_heartbeat_instance
  ON openclaw_heartbeat (instance_id);

-- 17. task_definitions: name + is_enabled (job creation lookup)
CREATE INDEX IF NOT EXISTS idx_task_definitions_name_enabled
  ON task_definitions (name)
  WHERE is_enabled = true;

-- Add table comment
COMMENT ON TABLE position_snapshots IS 'Position snapshots with partial index on active positions';
