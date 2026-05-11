-- Minimal control-plane/tool-registry seed for Holdings 3.0 P0.
-- This seed intentionally excludes any broker.order.* contract.

INSERT INTO public.tool_contract_families (tool_name, tool_namespace, owner, description)
VALUES
  ('portfolio.read.overview', 'portfolio', 'holdings_product', 'Read portfolio overview and summary DTOs'),
  ('portfolio.read.positions', 'portfolio', 'holdings_product', 'Read equity and option position DTOs'),
  ('market.quote.read', 'market', 'data_service', 'Read primary/fallback market quotes'),
  ('market.options_chain.read', 'market', 'data_service', 'Read option chain snapshots for analysis'),
  ('broker.position.read', 'broker', 'data_service', 'Read broker holdings and normalized position snapshots'),
  ('broker.cash_margin.read', 'broker', 'data_service', 'Read broker cash and margin snapshots'),
  ('broker.sync.snapshot', 'broker', 'data_service', 'Run read-only broker snapshot sync into internal tables'),
  ('confirmation.create_pending_action', 'confirmation', 'control_plane', 'Create normalized pending actions for controlled writes'),
  ('confirmation.commit', 'confirmation', 'control_plane', 'Commit a confirmed pending action into downstream facts'),
  ('artifact.write', 'artifact', 'hermes_runtime', 'Write artifact metadata and object-storage references'),
  ('delivery.enqueue', 'delivery', 'openclaw_gateway', 'Enqueue a message into delivery_outbox'),
  ('handoff.progress.append', 'handoff', 'hermes_runtime', 'Append Hermes user-visible progress events'),
  ('handoff.checkpoint.write', 'handoff', 'hermes_runtime', 'Persist Hermes checkpoints for resume/replay'),
  ('reference.ima.search', 'reference', 'openclaw_gateway', 'Search IMA notes and knowledge-base content as a research reference source'),
  ('reference.ima.read', 'reference', 'openclaw_gateway', 'Read IMA note/media content as cited reference material'),
  ('reference.ima.import_url', 'reference', 'openclaw_gateway', 'Import webpage or WeChat article URLs into an IMA knowledge base')
ON CONFLICT (tool_name) DO NOTHING;

WITH family_map AS (
  SELECT
    id,
    tool_name
  FROM public.tool_contract_families
  WHERE tool_name IN (
    'portfolio.read.overview',
    'portfolio.read.positions',
    'market.quote.read',
    'market.options_chain.read',
    'broker.position.read',
    'broker.cash_margin.read',
    'broker.sync.snapshot',
    'confirmation.create_pending_action',
    'confirmation.commit',
    'artifact.write',
    'delivery.enqueue',
    'handoff.progress.append',
    'handoff.checkpoint.write',
    'reference.ima.search',
    'reference.ima.read',
    'reference.ima.import_url'
  )
)
INSERT INTO public.tool_contract_versions (
  family_id,
  tool_version,
  input_schema_version,
  output_schema_version,
  permission_class,
  risk_class,
  cost_class,
  runtime_scope,
  forbidden_runtimes,
  requires_freshness_gate,
  requires_reconciliation_gate,
  requires_rule_check,
  requires_confirmation,
  lineage_required,
  idempotency_required,
  timeout_ms,
  publish_status,
  rollout_mode,
  degradation_policy_key,
  handoff_profile,
  contract_payload
)
SELECT
  fm.id,
  '1.0.0',
  'v1',
  'v1',
  CASE
    WHEN fm.tool_name IN ('broker.sync.snapshot', 'confirmation.create_pending_action', 'confirmation.commit', 'artifact.write', 'delivery.enqueue', 'handoff.progress.append', 'handoff.checkpoint.write', 'reference.ima.import_url')
      THEN 'controlled_write'::public.tool_permission_class
    ELSE 'read'::public.tool_permission_class
  END,
  CASE
    WHEN fm.tool_name IN ('confirmation.commit', 'market.options_chain.read') THEN 'high'::public.tool_risk_class
    WHEN fm.tool_name IN ('broker.sync.snapshot', 'confirmation.create_pending_action', 'handoff.checkpoint.write', 'reference.ima.import_url') THEN 'medium'::public.tool_risk_class
    ELSE 'low'::public.tool_risk_class
  END,
  CASE
    WHEN fm.tool_name IN ('market.options_chain.read', 'artifact.write', 'reference.ima.search', 'reference.ima.read', 'reference.ima.import_url') THEN 'metered'::public.tool_cost_class
    ELSE 'free'::public.tool_cost_class
  END,
  CASE
    WHEN fm.tool_name IN ('artifact.write', 'handoff.progress.append', 'handoff.checkpoint.write')
      THEN '["hermes"]'::jsonb
    WHEN fm.tool_name IN ('reference.ima.search', 'reference.ima.read')
      THEN '["openclaw_side","hermes"]'::jsonb
    WHEN fm.tool_name IN ('reference.ima.import_url')
      THEN '["openclaw_side"]'::jsonb
    WHEN fm.tool_name IN ('delivery.enqueue')
      THEN '["openclaw_side","domain_worker","hermes"]'::jsonb
    ELSE '["openclaw_side","hermes","domain_worker"]'::jsonb
  END,
  '[]'::jsonb,
  fm.tool_name IN ('market.quote.read', 'market.options_chain.read', 'broker.position.read', 'broker.cash_margin.read', 'broker.sync.snapshot'),
  fm.tool_name IN ('broker.position.read', 'broker.cash_margin.read', 'confirmation.commit'),
  fm.tool_name IN ('market.options_chain.read', 'confirmation.commit'),
  fm.tool_name IN ('confirmation.commit', 'reference.ima.import_url'),
  TRUE,
  TRUE,
  CASE
    WHEN fm.tool_name = 'market.options_chain.read' THEN 30000
    WHEN fm.tool_name LIKE 'reference.ima.%' THEN 30000
    WHEN fm.tool_name IN ('artifact.write', 'handoff.checkpoint.write') THEN 45000
    ELSE 15000
  END,
  'active'::public.tool_publish_status,
  'platform_default'::public.tool_rollout_mode,
  CASE
    WHEN fm.tool_name = 'market.options_chain.read' THEN 'options_high_risk_fallback'
    WHEN fm.tool_name LIKE 'reference.ima.%' THEN 'reference_source_unavailable_fallback'
    WHEN fm.tool_name IN ('broker.position.read', 'broker.cash_margin.read', 'broker.sync.snapshot') THEN 'broker_snapshot_stale_fallback'
    ELSE NULL
  END,
  CASE
    WHEN fm.tool_name LIKE 'handoff.%'
      THEN '{"supports_checkpoint": true, "supports_resume": true}'::jsonb
    ELSE '{}'::jsonb
  END,
  jsonb_build_object(
    'tool_name', fm.tool_name,
    'p0_notes', CASE
      WHEN fm.tool_name LIKE 'broker.%' THEN 'read-only broker surface; no order methods in P0'
      WHEN fm.tool_name LIKE 'reference.ima.%' THEN 'IMA content is a reference source only; cite source and freshness; do not write portfolio facts from it'
      WHEN fm.tool_name LIKE 'confirmation.%' THEN 'must preserve pending_action version + idempotency semantics'
      WHEN fm.tool_name LIKE 'handoff.%' THEN 'append-only event/checkpoint semantics'
      ELSE 'minimal v1 placeholder contract'
    END
  )
FROM family_map fm
WHERE NOT EXISTS (
  SELECT 1
  FROM public.tool_contract_versions v
  WHERE v.family_id = fm.id
    AND v.tool_version = '1.0.0'
);

WITH family_map AS (
  SELECT id, tool_name FROM public.tool_contract_families
)
INSERT INTO public.tool_contract_bindings (
  family_id,
  capability_role,
  default_runtime,
  allowed_intents,
  max_actionability_cap,
  is_active
)
SELECT *
FROM (
  VALUES
    ((SELECT id FROM family_map WHERE tool_name = 'portfolio.read.overview'), 'daily_chat_agent', 'openclaw_side'::public.runtime_target, '["portfolio_query"]'::jsonb, 'info_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'portfolio.read.positions'), 'portfolio_agent', 'openclaw_side'::public.runtime_target, '["portfolio_query","position_detail"]'::jsonb, 'analysis_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'market.quote.read'), 'daily_chat_agent', 'openclaw_side'::public.runtime_target, '["portfolio_query","quote_lookup"]'::jsonb, 'info_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'market.options_chain.read'), 'options_sell_put_agent', 'hermes'::public.runtime_target, '["sell_put_analysis"]'::jsonb, 'trade_draft'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'broker.position.read'), 'broker_sync_agent', 'domain_worker'::public.runtime_target, '["broker_sync","portfolio_reconcile"]'::jsonb, 'analysis_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'broker.cash_margin.read'), 'broker_sync_agent', 'domain_worker'::public.runtime_target, '["broker_sync","portfolio_reconcile"]'::jsonb, 'analysis_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'broker.sync.snapshot'), 'broker_sync_agent', 'domain_worker'::public.runtime_target, '["broker_sync"]'::jsonb, 'analysis_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'confirmation.create_pending_action'), 'portfolio_agent', 'openclaw_side'::public.runtime_target, '["trade_record_input","sell_put_analysis","ocr_correction"]'::jsonb, 'analysis_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'confirmation.commit'), 'portfolio_agent', 'domain_worker'::public.runtime_target, '["confirmation_commit","post_confirmation"]'::jsonb, 'trade_draft'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'artifact.write'), 'deep_research_agent', 'hermes'::public.runtime_target, '["deep_research","sell_put_analysis"]'::jsonb, 'analysis_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'delivery.enqueue'), 'delivery_agent', 'openclaw_side'::public.runtime_target, '["notification","task_update","confirmation_push"]'::jsonb, 'info_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'handoff.progress.append'), 'deep_research_agent', 'hermes'::public.runtime_target, '["deep_research","sell_put_analysis"]'::jsonb, 'analysis_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'handoff.checkpoint.write'), 'deep_research_agent', 'hermes'::public.runtime_target, '["deep_research","sell_put_analysis"]'::jsonb, 'analysis_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'reference.ima.search'), 'daily_chat_agent', 'openclaw_side'::public.runtime_target, '["reference_lookup","wechat_article_lookup","portfolio_query"]'::jsonb, 'info_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'reference.ima.search'), 'deep_research_agent', 'hermes'::public.runtime_target, '["deep_research","sell_put_analysis","equity_analysis"]'::jsonb, 'analysis_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'reference.ima.read'), 'deep_research_agent', 'hermes'::public.runtime_target, '["deep_research","sell_put_analysis","equity_analysis"]'::jsonb, 'analysis_only'::public.actionability_cap, TRUE),
    ((SELECT id FROM family_map WHERE tool_name = 'reference.ima.import_url'), 'reference_capture_agent', 'openclaw_side'::public.runtime_target, '["wechat_article_capture","reference_capture"]'::jsonb, 'info_only'::public.actionability_cap, TRUE)
) AS rows (family_id, capability_role, default_runtime, allowed_intents, max_actionability_cap, is_active)
WHERE family_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM public.tool_contract_bindings b
    WHERE b.family_id = rows.family_id
      AND b.capability_role = rows.capability_role
  );
