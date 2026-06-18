# Holdings 3.0 P0 Data Contract

这是一版 Phase 0 / Phase 1 的最小落地 contract。目标不是一次覆盖全部 P0，而是先给 Agent 2/3/4/5 一个可对齐的 schema 骨架和写入边界。

## 已完成

- 租户与渠道映射：
  - `tenant_accounts`
  - `channel_bindings`
  - `broker_connector_instances`
  - `broker_connections`
  - `asset_sources`
- 展示与标的骨架：
  - `instruments`
  - `equity_instruments`
  - `option_contracts`
  - `portfolio_views`
  - `portfolio_view_sources`
- 运行与上下文：
  - `agent_runs`
  - `run_contracts`
  - `context_packs`
- 券商/市场快照骨架：
  - `broker_sync_snapshots`
  - `broker_position_snapshots`
  - `cash_balance_snapshots`
  - `margin_balance_snapshots`
  - `market_snapshot_groups`
  - `market_data_manifests`
- 持仓读模型骨架：
  - `portfolio_positions`
  - `equity_positions`
  - `option_positions`
- 确认链路：
  - `pending_actions`
  - `confirmation_sessions`
  - `confirmation_events`
- Hermes / artifact / delivery：
  - `artifact_registry`
  - `hermes_jobs`
  - `handoff_tasks`
  - `handoff_progress_events`
  - `handoff_checkpoints`
  - `handoff_control_actions`
  - `delivery_outbox`
  - `message_events`
- Tool registry：
  - `tool_contract_families`
  - `tool_contract_versions`
  - `tool_contract_bindings`
  - `tool_contract_overrides`
  - `tool_contract_proposals`

## 核心 ID / FK 约定

- `tenant_id`：
  - 3.0 数据隔离根。
  - Phase 0 仍与 `users.id` 1:1，对应 `tenant_accounts.tenant_id`。
- `channel_binding_id`：
  - 用于微信 / WebApp inbox / delivery 侧状态聚合。
  - 不是资产真相源。
- `broker_connection_id`：
  - 历史券商 read-only 连接边界，保留用于兼容旧表和导入数据。
  - 当前多用户生产口径不让普通用户绑定个人 Futu OpenD；普通用户持仓来自手工、消息、OCR 和确认写入。
  - Futu OpenD 只作为管理员侧系统行情源，用于行情、期权链和估值参考。
- `connector_instance_id`：
  - 历史本地连接器实例边界，生产用户注册流程不再创建 tenant 级 Futu connector。
  - 旧 `user_local_polling` / `local_dev_direct` 控制面仅作为兼容和内部运维能力保留，不能作为普通用户个人账户同步方案。
- `asset_source_id`：
  - 所有来源 lineage 根节点。
  - Agent 2 写 snapshot / read model 时应尽量带上它。
- `agent_runs.id`：
  - 统一 `run_id`。
  - `run_contracts.agent_run_id`、`pending_actions.source_run_id`、`artifact_registry.source_run_id`、`delivery_outbox.source_run_id` 都挂这个。
- `pending_actions.id`：
  - Controlled-write 主对象。
  - 不要跳过它直接让 Agent 写核心事实。
- `delivery_outbox.id`：
  - 微信与 WebApp inbox 的共享事实源。
- `hermes_jobs.id` / `handoff_tasks.id`：
  - `hermes_jobs` 是执行态。
  - `handoff_tasks` 是用户可见任务态。

## RLS / 写入策略

- 租户可读、service-only 写：
  - `channel_bindings`
  - `broker_connector_instances`
  - `broker_connections`
  - `asset_sources`
  - `agent_runs`
  - `run_contracts`
  - `context_packs`
  - 所有 snapshot / position / confirmation / artifact / Hermes / outbox 表
- 租户可读写：
  - `portfolio_views`
  - `portfolio_view_sources`
- 全局只读、service-only 写：
  - `instruments`
  - `equity_instruments`
  - `option_contracts`
  - `tool_contract_families`
  - `tool_contract_versions`
  - `tool_contract_bindings`
- 特殊：
  - `market_data_manifests.tenant_id IS NULL` 表示共享公共数据，可跨租户读。

这意味着后续 agent 默认应通过 domain service / BFF / worker 使用 service role 写表，不要假设前端可直接写 holdings 核心表。

## 最小字段对齐

### Agent 2: Data Service / Broker

- 写入优先对齐：
  - `asset_sources.source_key`
  - `broker_connector_instances.id`
  - `broker_connections.id`
  - `broker_sync_snapshots.sync_window_key`
  - `broker_sync_snapshots.coverage`
  - `broker_position_snapshots.position_payload`
  - `cash_balance_snapshots.buying_power`
  - `margin_balance_snapshots.cash_secured_requirement`
  - `market_snapshot_groups.cross_check_status`
  - `market_data_manifests.storage_uri`
- 如果开始投影 read model：
  - `portfolio_positions.source_lineage`
  - `portfolio_positions.reconciliation_status`
  - `portfolio_positions.actionability_cap`

### Agent 3: OpenClaw / Delivery

- 依赖主键：
  - `channel_bindings.id`
  - `pending_actions.id`
  - `confirmation_sessions.id`
  - `delivery_outbox.id`
- 需要对齐字段：
  - `confirmation_sessions.session_token`
  - `confirmation_sessions.confirmation_deeplink`
  - `delivery_outbox.dedupe_key`
  - `message_events.event_type`

### Agent 4: Hermes / Runtime / Memory

- 依赖主键：
  - `agent_runs.id`
  - `run_contracts.id`
  - `context_packs.id`
  - `artifact_registry.id`
  - `hermes_jobs.id`
  - `handoff_tasks.id`
  - `handoff_checkpoints.id`
- 需要对齐字段：
  - `run_contracts.policy_hash`
  - `artifact_registry.storage_backend`
  - `artifact_registry.storage_path`
  - `hermes_jobs.output_artifact_id`
  - `handoff_tasks.latest_checkpoint_id`
  - `handoff_progress_events.seq_no`

### Agent 5: WebApp

- 先按这些只读 DTO 骨架消费：
  - `portfolio_views`
  - `portfolio_positions`
  - `equity_positions`
  - `option_positions`
  - `pending_actions`
  - `confirmation_sessions`
  - `handoff_tasks`
  - `delivery_outbox`

## 当前刻意未完成

- 未实现完整 read model materialization / projector 逻辑。
- 未实现 `portfolio_view` 默认自动创建策略。
- 未实现 replay / eval manifest 表。
- 未引入 `discipline_checks`、`degradation_decisions`、`commit_results` 等更细控制面表。
- 未做跨表 trigger 级联一致性逻辑，例如：
  - `pending_actions.confirmed -> confirmation_events`
  - `handoff_checkpoints -> handoff_tasks.latest_checkpoint_id`
- `tool_contract_*` 目前只提供最小 registry 结构和 seed，不代表完整治理流程已就绪。

## TODO 建议

- Agent 2 先把 snapshot + position projection 跑通，不必首轮就填满所有 JSON 字段。
- Agent 3 首轮只需要保证 `pending_actions -> confirmation_sessions -> delivery_outbox` 这条链打通。
- Agent 4 首轮只需要保证 `agent_runs -> run_contracts -> hermes_jobs -> artifact_registry -> handoff_tasks` 可闭环。
- 后续如果要补复杂控制面，优先加新 migration，不要直接改写这版 contract 的字段语义。
