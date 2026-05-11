-- AI 持仓投资分析系统 2.0 - RLS 策略
-- Phase 0.2: 行级安全策略

-- ============================================
-- 1. trade_events: 租户隔离 + service_role 绕过
-- ============================================
CREATE POLICY "trade_events_tenant_select"
  ON public.trade_events FOR SELECT
  USING (tenant_id = auth.uid());

CREATE POLICY "trade_events_tenant_insert"
  ON public.trade_events FOR INSERT
  WITH CHECK (tenant_id = auth.uid());

CREATE POLICY "trade_events_tenant_update"
  ON public.trade_events FOR UPDATE
  USING (tenant_id = auth.uid());

CREATE POLICY "trade_events_tenant_delete"
  ON public.trade_events FOR DELETE
  USING (tenant_id = auth.uid());

CREATE POLICY "trade_events_service_all"
  ON public.trade_events FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 2. position_snapshots: 租户隔离 + service_role 绕过
-- ============================================
CREATE POLICY "position_snapshots_tenant_select"
  ON public.position_snapshots FOR SELECT
  USING (tenant_id = auth.uid());

CREATE POLICY "position_snapshots_tenant_insert"
  ON public.position_snapshots FOR INSERT
  WITH CHECK (tenant_id = auth.uid());

CREATE POLICY "position_snapshots_tenant_update"
  ON public.position_snapshots FOR UPDATE
  USING (tenant_id = auth.uid());

CREATE POLICY "position_snapshots_tenant_delete"
  ON public.position_snapshots FOR DELETE
  USING (tenant_id = auth.uid());

CREATE POLICY "position_snapshots_service_all"
  ON public.position_snapshots FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 3. job_runs: 租户隔离 + service_role 绕过
-- ============================================
CREATE POLICY "job_runs_tenant_select"
  ON public.job_runs FOR SELECT
  USING (tenant_id = auth.uid());

CREATE POLICY "job_runs_tenant_insert"
  ON public.job_runs FOR INSERT
  WITH CHECK (tenant_id = auth.uid());

CREATE POLICY "job_runs_tenant_update"
  ON public.job_runs FOR UPDATE
  USING (tenant_id = auth.uid());

CREATE POLICY "job_runs_tenant_delete"
  ON public.job_runs FOR DELETE
  USING (tenant_id = auth.uid());

CREATE POLICY "job_runs_service_all"
  ON public.job_runs FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 4. delivery_runs: 租户隔离 + service_role 绕过
-- ============================================
CREATE POLICY "delivery_runs_tenant_select"
  ON public.delivery_runs FOR SELECT
  USING (tenant_id = auth.uid());

CREATE POLICY "delivery_runs_tenant_insert"
  ON public.delivery_runs FOR INSERT
  WITH CHECK (tenant_id = auth.uid());

CREATE POLICY "delivery_runs_tenant_update"
  ON public.delivery_runs FOR UPDATE
  USING (tenant_id = auth.uid());

CREATE POLICY "delivery_runs_tenant_delete"
  ON public.delivery_runs FOR DELETE
  USING (tenant_id = auth.uid());

CREATE POLICY "delivery_runs_service_all"
  ON public.delivery_runs FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 5. users: 自可见 + service_role 绕过
--    users 表无主键 tenant_id，其 id 即 auth.uid()
-- ============================================
CREATE POLICY "users_self_select"
  ON public.users FOR SELECT
  USING (id = auth.uid());

CREATE POLICY "users_self_insert"
  ON public.users FOR INSERT
  WITH CHECK (id = auth.uid());

CREATE POLICY "users_self_update"
  ON public.users FOR UPDATE
  USING (id = auth.uid());

CREATE POLICY "users_self_delete"
  ON public.users FOR DELETE
  USING (id = auth.uid());

CREATE POLICY "users_service_all"
  ON public.users FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- 6. symbol_registry: 所有认证用户只读，service_role 可写
-- ============================================
CREATE POLICY "symbol_registry_public_select"
  ON public.symbol_registry FOR SELECT
  TO authenticated
  USING (true);

-- 允许匿名用户也查询 symbol_registry（搜索行情场景）
CREATE POLICY "symbol_registry_anon_select"
  ON public.symbol_registry FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "symbol_registry_service_all"
  ON public.symbol_registry FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
