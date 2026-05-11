# Agent Capability Matrix 设计

## 1. 目标

`Agent Capability Matrix` 是 AI 持仓投资分析系统 3.0 的控制面事实源之一，用来定义：

1. 哪个 agent role 可以调用哪些工具能力。
2. 这些能力在什么 write scope 内可执行。
3. 这些能力在哪个 runtime 中可运行、是否允许 handoff。
4. 高风险输出和受控写入分别要经过哪些 gate。
5. 失败时如何降级，而不是把错误能力暴露给 agent 自己“自由发挥”。

一句话口径：

> Capability Matrix 不是一张静态权限表，而是一条控制链：`role -> tool policy -> write scope -> runtime gate -> review/degrade`。

它的职责是“定义 agent 在产品层面能做什么、不能做什么，以及做到哪一步必须停下”，不是负责执行工具本身。执行仍由 `Tool Policy Gate`、`Domain Tools`、`RiskReviewTools`、`ConfirmationTools` 等控制面与工具面完成。

## 2. 设计原则

| 原则 | 产品口径 |
| --- | --- |
| 控制链优先 | Capability Matrix 必须把 role、tool policy、write scope、runtime gate、review/degrade 串起来，而不是只维护一列 allow list。 |
| 先限制，再放行 | 默认 deny；只有被明确声明的工具族、写范围、runtime 和 gate 才允许进入执行。 |
| Hermes 不可扩权 | Hermes 只能继承或收窄 OpenClaw / Orchestrator 下发的 `run contract`、`tool scope`、`data scope`，不能扩大权限。 |
| 高风险先审后出 | 所有高风险输出必须经过 `RiskReviewTools`；agent 不能自己把结果升级成 `trade_draft` 或等价的可执行结论。 |
| 受控写入必须确认 | 交易录入、OCR 修正、规则 override、敏感配置变更等受控写入必须经过 `ConfirmationTools`，先形成 pending action，再进入正式写入。 |
| 事实层只允许受控入口 | 跨 tenant、直接改持仓事实、自动下单、绕过规则检查，全部属于禁止能力。 |
| runtime 同构、策略异构 | OpenClaw-side、Hermes-side、domain worker 共用同一套工具契约；差异只能体现在 runtime gate、时延目标、恢复能力和 review 级别上。 |
| 产品角色与执行角色分离 | 面向用户展示的是稳定 role；Quick Portfolio、Broker Sync 等可以是 profile 或 worker contract，不必强行做成新的用户可见 agent。 |

### 2.1 通用禁止能力

以下能力不属于任何用户可见 role 的授权范围：

| 禁止能力 | 原因 |
| --- | --- |
| 跨 `tenant_id` 读取或写入 | 破坏账户与 memory 隔离 |
| 直接改写 `portfolio_positions`、`trade_events`、`trading_rules` 最终事实 | 会绕过确认、审计和来源链路 |
| 自动下单、自动生成真实券商交易指令 | 超出 3.0 受控自主边界 |
| 绕过 `DisciplineRuleTools` / `RiskReviewTools` 输出高风险建议 | 会把分析能力错误升级成行动能力 |
| 直接访问数据库、券商 API、外部行情 API | 必须统一走 Domain Tools 和 Tool Policy Gate |
| Hermes 修改生产规则、扩大工具权限、扩大 data scope | 与上游“只能继承或收窄”口径冲突 |

## 3. Agent Role 权限矩阵

### 3.1 8 个用户可见 role

Capability Matrix 首期以现有 8 个用户可见 role 为主：

1. `daily_chat_agent`
2. `portfolio_agent`
3. `deep_research_agent`
4. `equity_analyst_agent`
5. `options_sell_put_agent`
6. `delivery_agent`
7. `memory_curator`
8. `ops_agent`

说明：

| 特殊归属 | 设计口径 |
| --- | --- |
| `Quick Portfolio` | 不是独立用户可见 role，而是 `portfolio_agent` 在 OpenClaw-side 的轻量 profile；它只能继承并收窄 Portfolio 的能力，不应拥有独立扩权。 |
| `Broker Sync` | 不作为用户可见 role 管理，而是 `domain worker + Hermes diagnostic` 的 worker contract；同步本身尽量 deterministic，异常解释才进入 Hermes。 |
| `Ops` | 属于控制面/后台角色，默认不进入终端用户路由；虽然纳入矩阵治理，但应被标记为 `admin_only`。 |

### 3.2 Role Matrix

| Role | 用户可见 | 默认 runtime | 主要任务 | 允许工具族 | 最大写范围 | 必经 gate | 明确禁止 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Daily Chat Agent | 是 | OpenClaw-side | 轻量问答、账号确认、状态查询 | `AccountContextTools`、`PortfolioTools.read`、`MarketDataTools.read`、`DeliveryTools.reply_draft` | `outbox_draft`、`confirmation_session` | `ToolPolicyGate`、必要时 `RiskReviewTools` | 深研 artifact、broker sync、规则删除、任何交易动作升级 |
| Portfolio Agent | 是 | Hybrid | 持仓查询、交易录入、组合分析、复杂复盘 | `AssetSourceTools`、`PortfolioTools`、`HistoricalDataTools.read`、`MarketDataTools.read`、`DisciplineRuleTools` | `pending_fact_change` | `ConfirmationTools`、`RiskReviewTools`、`DisciplineRuleTools` | 直接覆盖持仓事实、跨 tenant 读取、自动下单 |
| Deep Research Agent | 是 | Hermes-side | 行业/公司深研、机会研究、长报告 | `ResearchArtifactTools`、`MarketDataTools.read`、`HistoricalDataTools.read` | `research_artifact`、`proposal_artifact` | `RiskReviewTools`、`CostQuotaTools`、`HandoffProgressTools` | 写持仓事实、改券商连接、直接生成可执行交易 |
| Equity Analyst Agent | 是 | Hermes-side | 个股分析、止盈止损、二次买入判断 | `EquityTools`、`MarketDataTools.read`、`HistoricalDataTools.read`、`ResearchArtifactTools`、`DisciplineRuleTools` | `research_artifact`、`watchlist_analysis_field` | `RiskReviewTools`、必要时 `CostQuotaTools` | 修改交易事实、放宽规则、绕过数据质量门 |
| Options Sell Put Agent | 是 | Hermes-side | sell put 筛选、监控、roll/assignment 分析 | `OptionsTools`、`BrokerTools.read`、`MarketDataTools.read`、`HistoricalDataTools.read`、`DisciplineRuleTools` | `strategy_report`、`monitoring_draft` | `RiskReviewTools`、`DisciplineRuleTools`、`CostQuotaTools` | 在现金/保证金不明时给出可执行候选、自动下单 |
| Delivery Agent | 是 | OpenClaw-side | 推送、补偿、状态更新 | `DeliveryTools`、`AccountContextTools`、`AuditObservabilityTools.read` | `delivery_outbox`、`delivery_status` | `DeliveryGuard`、`ToolPolicyGate` | 改写报告结论、修改业务事实、跨账号投递 |
| Memory Curator | 是 | Hermes-side | 偏好、经验、复盘沉淀 | `MemoryTools`、`ResearchArtifactTools.read`、`AuditObservabilityTools.read` | `tenant_memory` | `MemoryGuard`、必要时 `RiskReviewTools` | 写持仓事实、写交易规则、跨 tenant memory |
| Ops Agent | 是，但 `admin_only` | Hermes-side 后置 | 任务诊断、数据源健康、失败修复建议 | `SchedulerTools`、`AuditObservabilityTools`、`BrokerTools.read`、`MarketDataTools.read` | `repair_job`、`pause_resume_job` | `AdminEntitlementGate`、`AuditReview` | 终端用户直接调用、读取未授权敏感明细、直接改策略规则 |

### 3.3 控制链解释

同一个 role 的能力不是一次性放行，而是逐层收口：

| 控制层 | 问题 | 例子 |
| --- | --- | --- |
| `role` | 这个角色理论上负责什么任务 | `options_sell_put_agent` 只负责期权策略，不负责券商写入 |
| `tool policy` | 它能调用哪些工具族、哪些工具永远拒绝 | 允许 `options.chain.read`，拒绝 `broker.trade.place_order` |
| `write scope` | 即使允许写，也最多写到哪里 | 允许写 `strategy_report`，不允许写 `portfolio_positions` |
| `runtime gate` | 这个动作能在哪个 runtime 中执行 | Quick Portfolio 仅允许 OpenClaw-side；深研类默认 Hermes-side |
| `review/degrade` | 通过什么门才能输出给用户；失败时如何处理 | 高风险输出过 `RiskReviewTools`，写入走 `ConfirmationTools`，失败则降级为 `analysis_only` 或 `blocked` |

## 4. 工具 allow/deny

### 4.1 工具族授权规则

| 工具族 | 允许角色 | 额外条件 | 默认拒绝给谁 |
| --- | --- | --- | --- |
| `AccountContextTools` | Daily Chat、Portfolio、Delivery | 必须带 `tenant_id`、`channel_binding_id` | 所有 domain worker 以外的匿名调用 |
| `PortfolioTools.read` | Daily Chat、Portfolio、Equity、Options、Deep Research | 只读视图优先，复杂归因可 handoff Hermes | Delivery、Memory 默认不直接调用 |
| `MarketDataTools.read` | Daily Chat、Portfolio、Deep Research、Equity、Options、Ops | 受 `DataQualityGate` 和 freshness 约束 | Memory 仅在必要时读摘要，不读全量实时行情 |
| `HistoricalDataTools.read` | Portfolio、Deep Research、Equity、Options | 仅允许读取已验证历史数据 | Daily Chat 默认拒绝深度历史查询 |
| `ResearchArtifactTools` | Deep Research、Equity、Memory | 写 artifact 时保留 lineage 和引用快照 | Daily Chat、Delivery |
| `EquityTools` | Equity、Portfolio（仅摘要型）、Deep Research（只读分析） | 不得直接输出高风险建议 | Daily Chat、Delivery、Memory |
| `OptionsTools` | Options Sell Put | 必须联动 `BrokerTools.read`、`DisciplineRuleTools` | 其他全部默认拒绝 |
| `BrokerTools.read` | Options、Ops、Broker Sync worker | 只读 entitlement，不能升级成交易能力 | Daily Chat、Delivery、Memory、Deep Research |
| `AssetSourceTools` | Portfolio、Broker Sync worker | OCR/手工修正必须先进入确认流 | Deep Research、Delivery、Memory |
| `MemoryTools` | Memory Curator | 仅限 `tenant` scope，写入要分 fact/preference/lesson | 其他全部默认拒绝写 |
| `DeliveryTools` | Daily Chat、Delivery、HandoffProgress 流程 | 统一经 outbox，不允许直推 | Hermes 深任务不能直接触达用户 |
| `SchedulerTools` | Ops、Broker Sync worker | `admin_only` 或系统任务 | 终端用户路由 |
| `AuditObservabilityTools` | Delivery、Memory、Ops、Broker Sync worker | 默认读聚合，不读敏感 payload | Daily Chat、终端用户暴露 |

### 4.2 通用 deny 列表

以下工具或等价能力不应出现在任何用户可见 role 的 allow list 中：

| deny 项 | 说明 |
| --- | --- |
| `broker.trade.place_order` / `broker.trade.cancel_order` | 自动下单、撤单均禁止 |
| `portfolio_positions.direct_update` | 直接改持仓事实禁止 |
| `trade_events.direct_commit` | 跳过确认直接提交交易事实禁止 |
| `trading_rules.delete` / `trading_rules.relax_without_review` | 绕过纪律规则治理禁止 |
| 任意 `cross_tenant.*` | 跨租户数据访问禁止 |
| 任意 `raw_db.*` / `external_provider.direct_call` | 绕过 Domain Tools 的直接调用禁止 |

### 4.3 高风险工具的强制 gate

| 情况 | 强制 gate | 原因 |
| --- | --- | --- |
| 输出可能被用户理解为可执行建议 | `RiskReviewTools` | 统一落 `actionability_level`，避免 agent 自行升级 |
| 交易录入、OCR 修正、规则 override、受控状态变更 | `ConfirmationTools` | 先形成 pending action，再受控写入 |
| 使用昂贵模型、付费行情、期权链批量扫描 | `CostQuotaTools` | 防止预算与 provider 被打爆 |
| Hermes 深任务交付、排队、取消、恢复 | `HandoffProgressTools` | 提供用户可见状态与恢复控制 |

## 5. Write Scope

### 5.1 Write Scope 分层

| write scope | 含义 | 允许的典型对象 | 不允许写入的对象 |
| --- | --- | --- | --- |
| `none` | 完全只读 | 无 | 所有业务表 |
| `outbox_draft` | 仅可写投递草稿或回复草稿 | `delivery_outbox`、`reply_draft` | 业务事实、研究结论源数据 |
| `confirmation_session` | 仅可创建确认会话 | `confirmation_sessions`、`pending_actions` | 最终交易事实 |
| `pending_fact_change` | 可创建待确认事实草稿 | `pending_trade_event`、`pending_position_correction` | `portfolio_positions`、`trade_events` 最终表 |
| `research_artifact` | 可写研究产物 | `research_artifacts`、`strategy_reports` | 券商连接、规则事实 |
| `proposal_artifact` | 可写优化/策略提案 | `optimization_proposals` | 生产规则、生产配置 |
| `tenant_memory` | 可写租户 memory | `preferences`、`lessons`、`review_notes` | 持仓事实、跨租户 memory |
| `delivery_status` | 可写投递状态 | `delivery_attempts`、`delivery_receipts` | 分析结论内容 |
| `broker_snapshot` | 可写券商快照与对账结果 | `broker_snapshots`、`reconcile_results` | 订单、交易规则、用户确认事实 |
| `repair_job` | 可写修复任务与暂停状态 | `repair_jobs`、`job_pauses` | 用户投资事实 |

### 5.2 Role 与 Write Scope 映射

| Role | 最大 write scope | 说明 |
| --- | --- | --- |
| Daily Chat Agent | `outbox_draft` + `confirmation_session` | 只负责轻量回复与确认入口，不负责事实提交 |
| Portfolio Agent | `pending_fact_change` + `portfolio_view_pref` | 可以发起交易录入/修正，但必须确认后才进事实层 |
| Deep Research Agent | `research_artifact` + `proposal_artifact` | 可写报告与提案，不写持仓事实 |
| Equity Analyst Agent | `research_artifact` | 可写分析结果和 watchlist 字段，不写交易事实 |
| Options Sell Put Agent | `research_artifact` | 可写策略报告、监控草案，不写订单或持仓事实 |
| Delivery Agent | `outbox_draft` + `delivery_status` | 只碰投递对象，不碰结论生成逻辑 |
| Memory Curator | `tenant_memory` | 只写 tenant scoped memory，禁止事实污染 |
| Ops Agent | `repair_job` | 只在后台受控修改任务状态，不修改投资业务事实 |

### 5.3 关键约束

1. `pending_fact_change` 不等于允许直接改事实；它只允许创建待确认动作。
2. `research_artifact` 不能被下游系统误当成 `portfolio fact` 或 `trade fact`。
3. `tenant_memory` 必须区分 `fact / preference / lesson / research_ref`，避免 memory 污染事实层。
4. `repair_job` 属于运维控制，不得变相作为写业务事实的后门。

## 6. Runtime 差异（OpenClaw-side / Hermes-side / Domain Worker）

| 维度 | OpenClaw-side | Hermes-side | Domain Worker |
| --- | --- | --- | --- |
| 主要职责 | 渠道入口、同步问答、轻量查询、推送闭环 | 深研、长任务、复杂分析、复盘、memory 沉淀 | 确定性同步、采集、修复、定时任务 |
| 典型角色 | Daily Chat、Portfolio 轻量 profile、Delivery | Portfolio 深度模式、Deep Research、Equity、Options、Memory、Ops | Broker Sync、历史数据 backfill、批处理 repair |
| 时延目标 | 秒级 | 分钟级，可异步 | 任务级，可排队 |
| 输出形态 | 直接回复或创建确认会话 | artifact、proposal、长任务结果、阶段状态 | snapshot、reconcile result、job status |
| run contract 处理 | 接收 Canonical Run Contract 原始版本 | 只能继承或收窄，不可扩权 | 只接受系统/控制面下发的 worker contract |
| 工具策略 | 白名单更窄，偏同步安全 | 可以更深，但必须受 Risk/Quota/Handoff 治理 | 最窄、最确定性，不允许自然语言扩展 |
| 写入范围 | 偏 `outbox_draft`、`confirmation_session` | 偏 `artifact`、`proposal`、`tenant_memory` | 偏 `broker_snapshot`、`reconcile_result`、`repair_job` |
| 用户可见性 | 直接可见 | 通过 OpenClaw / Delivery 间接可见 | 默认不可见，只暴露结果或异常状态 |
| 失败处理 | 快速降级为只读说明 | 进入 `HandoffProgressTools`、可恢复/可取消 | 重试、DLQ、交 Ops 诊断 |

### 6.1 特殊归属补充

| 对象 | runtime 归属 | Capability Matrix 处理方式 |
| --- | --- | --- |
| Quick Portfolio | OpenClaw-side | 作为 `portfolio_agent.quick_profile`，只收窄 allow list、write scope 和 latency 目标 |
| Broker Sync | Domain Worker + Hermes diagnostic | 不进入 8 个用户可见 role 主矩阵；单独维护 worker contract，并允许 Ops/Hermes 读取异常结果 |
| Ops | Hermes-side 后置 | role 在矩阵中存在，但必须有 `admin_only=true` 和独立 entitlement gate |

## 7. 配置模型

### 7.1 配置目标

Capability Matrix 配置必须支持：

1. 按 role 声明 allow/deny、write scope、runtime gate。
2. 声明 profile 或 worker contract，而不是用 prompt 文本隐含权限。
3. 在运行时可被 `Environment Orchestrator` 和 `Tool Policy Gate` 直接读取。
4. 在审计中能回答“当时哪个 role 用了哪版矩阵、为什么允许”。

### 7.2 建议配置字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `matrix_version` | string | 能力矩阵版本 |
| `policy_status` | enum | `draft / review / active / deprecated / blocked` |
| `role_id` | string | 稳定 role 标识 |
| `user_visible` | bool | 是否属于用户可见主矩阵 |
| `admin_only` | bool | 是否只能在后台或管理员入口触发 |
| `default_runtime` | enum | `openclaw / hermes / hybrid / domain_worker` |
| `runtime_profiles` | object[] | 支持同一 role 的 profile，例如 `quick_profile` |
| `tool_policy.allow` | string[] | 允许的工具族/工具 contract key |
| `tool_policy.deny` | string[] | 显式禁止的工具族/工具 contract key |
| `tool_policy.max_risk_class` | enum | role 可接触的最高风险等级 |
| `tool_policy.mandatory_gates` | string[] | 进入执行前必须经过的 gate |
| `write_scope.max_scope` | string | role 最大写范围 |
| `write_scope.allowed_targets` | string[] | 可写对象白名单 |
| `write_scope.forbidden_targets` | string[] | 显式禁止写入对象 |
| `runtime_gate.hermes_may_expand` | bool | 固定为 `false` |
| `runtime_gate.handoff_allowed` | bool | 是否允许从 OpenClaw handoff Hermes |
| `runtime_gate.worker_only` | bool | 是否只能由 domain worker 执行 |
| `review_policy.high_risk_output` | string | 例如 `risk_review_required` |
| `review_policy.controlled_write` | string | 例如 `confirmation_required` |
| `review_policy.actionability_ceiling` | string | `info_only / analysis_only / suggested_action / trade_draft / blocked` |
| `degrade_policy.on_stale_data` | string | 数据过期时如何降级 |
| `degrade_policy.on_scope_violation` | string | scope 不匹配时如何处理 |
| `audit.policy_hash` | string | 便于与 tool calls 对齐 |

### 7.3 配置示例

```yaml
matrix_version: capability-matrix.v1
policy_status: active
applies_to:
  tool_contract_registry_version: tool-contracts.v1
  run_contract_version: run-contract.v1

role_policies:
  - role_id: portfolio_agent
    display_name: Portfolio Agent
    user_visible: true
    admin_only: false
    default_runtime: hybrid
    runtime_profiles:
      - profile_id: default
        runtime: hermes
        handoff_allowed: true
      - profile_id: quick_portfolio
        runtime: openclaw
        inherits_from: default
        narrows:
          allow:
            - account.context.read
            - portfolio.summary.read
            - market.quote.read
            - discipline.rule.summary
          max_scope: none
          actionability_ceiling: analysis_only
    tool_policy:
      allow:
        - asset.source.read
        - asset.source.propose_correction
        - portfolio.summary.read
        - portfolio.risk.snapshot
        - market.quote.read
        - historical.positions.read
        - discipline.rule.check
      deny:
        - broker.trade.place_order
        - portfolio_positions.direct_update
        - trade_events.direct_commit
        - cross_tenant.read
      max_risk_class: high
      mandatory_gates:
        - tool_policy_gate
        - data_quality_gate
        - risk_review
        - confirmation_for_controlled_write
    write_scope:
      max_scope: pending_fact_change
      allowed_targets:
        - pending_trade_event
        - pending_position_correction
        - portfolio_view_preferences
      forbidden_targets:
        - portfolio_positions
        - trade_events
        - trading_rules
    runtime_gate:
      hermes_may_expand: false
      worker_only: false
      allowed_runtimes:
        - openclaw
        - hermes
    review_policy:
      high_risk_output: risk_review_required
      controlled_write: confirmation_required
      actionability_ceiling: trade_draft
    degrade_policy:
      on_stale_data: analysis_only
      on_reconcile_conflict: blocked
      on_scope_violation: deny_and_audit

  - role_id: options_sell_put_agent
    display_name: Options Sell Put Agent
    user_visible: true
    admin_only: false
    default_runtime: hermes
    tool_policy:
      allow:
        - options.chain.read
        - options.sell_put.rank_candidates
        - broker.cash_margin.read
        - market.quote.read
        - historical.options.read
        - discipline.rule.check
        - research_artifact.write
      deny:
        - broker.trade.place_order
        - broker.trade.cancel_order
        - portfolio_positions.direct_update
      max_risk_class: high
      mandatory_gates:
        - tool_policy_gate
        - data_quality_gate
        - discipline_rule_gate
        - risk_review
        - cost_quota
    write_scope:
      max_scope: research_artifact
      allowed_targets:
        - strategy_report
        - monitoring_draft
      forbidden_targets:
        - orders
        - portfolio_positions
        - trade_events
    runtime_gate:
      hermes_may_expand: false
      worker_only: false
      allowed_runtimes:
        - hermes
    review_policy:
      high_risk_output: risk_review_required
      controlled_write: not_applicable
      actionability_ceiling: trade_draft
    degrade_policy:
      on_missing_cash_margin: blocked
      on_stale_option_chain: analysis_only
      on_rule_check_unavailable: blocked

worker_contracts:
  - worker_id: broker_sync_worker
    user_visible: false
    runtime: domain_worker
    tool_policy:
      allow:
        - broker.positions.sync
        - broker.cash_margin.sync
        - asset.reconcile.write
        - audit.sync_trace.write
      deny:
        - broker.trade.place_order
        - trading_rules.update
    write_scope:
      max_scope: broker_snapshot
      allowed_targets:
        - broker_snapshots
        - reconcile_results
    runtime_gate:
      hermes_may_expand: false
      worker_only: true
```

### 7.4 运行时求值顺序

| 步骤 | 问题 | 结果 |
| --- | --- | --- |
| 1 | 当前 run 属于哪个 `role_id/profile_id/worker_id` | 解析 role contract |
| 2 | 当前 runtime 是否在 `allowed_runtimes` 内 | 不在则拒绝或 handoff |
| 3 | 当前工具是否在 `allow`，且不在 `deny` | 否则拒绝并审计 |
| 4 | 目标写入是否落在 `max_scope + allowed_targets` 内 | 否则拒绝并审计 |
| 5 | 是否满足 `mandatory_gates` | 未满足则转 review / confirmation / degrade |
| 6 | 输出是否超过 `actionability_ceiling` | 超过则由 `RiskReviewTools` 降级或阻断 |

## 8. 审核流程

### 8.1 触发场景

以下变更必须进入 Capability Matrix 审核流：

| 变更类型 | 是否必须审核 | 说明 |
| --- | --- | --- |
| 新增 role | 是 | 需要明确用户可见性、runtime、写范围 |
| 扩大 allow list | 是 | 属于扩权 |
| 放宽 deny、放宽 write scope | 是 | 属于高风险扩权 |
| 新增或放宽 `trade_draft` 上限 | 是 | 影响行动能力边界 |
| 收窄 allow list、增加 deny | 可自动验证后生效 | 属于降权，风险较低 |
| 修改降级文案或等待态说明 | 可轻审 | 前提是不影响能力边界 |

### 8.2 审核流程本体

| 阶段 | 负责人 | 核心检查 |
| --- | --- | --- |
| 提案 | Product / Platform / Hermes proposal | 是否说明 role、工具、写范围、runtime、风险变化 |
| 静态校验 | 控制面配置校验器 | 工具 contract 是否存在；是否出现禁止能力；`hermes_may_expand` 是否为 `false` |
| 产品/风控审核 | Product + Risk/Platform | 是否符合角色定位；是否突破上游 P0/P1 边界 |
| Shadow / Replay | 控制面验证 | 用历史 run 回放是否出现越权、误升级、错误降级 |
| 激活 | 控制面发布 | 更新 `matrix_version`，写审计和生效时间 |

### 8.3 Hermes 参与边界

| 能力 | Hermes 是否可做 | 限制 |
| --- | --- | --- |
| 生成 capability change proposal | 可以 | 只能生成 proposal，不可直接生效 |
| 运行时收窄 contract | 可以 | 只能收窄，不可扩大 |
| 扩大 allow list / write scope / actionability ceiling | 不可以 | 必须人工审核 |
| 修改生产 worker contract | 不可以 | 只能提案 |

## 9. P0 / P1 范围

### 9.1 P0 上线前必须有

| P0 项 | 与上游口径关系 |
| --- | --- |
| 8 个用户可见 role 的固定矩阵配置 | 与 `12-openclaw-hermes-agent-runtime.md` 的 role 划分一致 |
| `Quick Portfolio` 作为 `portfolio_agent` 轻量 profile | 与上游“不是新增用户可见 role”的口径一致 |
| `Broker Sync` 独立 worker contract | 与上游“domain worker + Hermes diagnostic”一致 |
| `Ops` 的 `admin_only` gate | 与上游“后置管理能力”一致 |
| `role -> tool policy -> write scope -> runtime gate -> review/degrade` 的执行链 | 与 `11-domain-tools-layer.md`、`13-architecture-hardening.md` 的控制面口径一致 |
| 高风险输出接入 `RiskReviewTools` | 与上游强制要求一致 |
| 受控写入接入 `ConfirmationTools` | 与上游强制要求一致 |
| 禁止跨 tenant、直接改持仓事实、自动下单、绕过规则检查 | 与上游硬约束一致 |
| 审计字段：`matrix_version / role_id / profile_id / policy_hash` | 支撑回放与事故定位 |

### 9.2 P1 首个可用版本建议补齐

| P1 项 | 价值 |
| --- | --- |
| tenant/tier 级 override | 支持灰度和套餐差异，但不改变全局禁止能力 |
| Capability Matrix 管理台或配置编辑器 | 方便产品/平台管理 role 政策 |
| Policy simulator / replay | 变更前先用历史 run 验证越权和误降级 |
| 与 `CostQuotaTools`、`HandoffProgressTools` 的可视化联动 | 让 runtime gate、排队和成本一起可解释 |
| 变更 diff 与审批记录 | 支持审计和复盘 |

不建议放入 P0 的内容：

1. 细粒度 A/B 实验型角色能力。
2. 允许 Hermes 自动发布任何扩权变更。
3. 把 Broker Sync 改成自然语言 agent 优先链路。

## 10. 失败模式与降级

| 失败模式 | 典型表现 | 系统动作 | 用户可见降级 |
| --- | --- | --- | --- |
| role 未命中矩阵 | 无法识别当前能力边界 | 直接拒绝并审计 | 返回“当前角色未启用该能力” |
| Hermes 尝试扩权 | tool scope / write scope 超出 run contract | 阻断调用，记录 policy violation | 返回“该深度任务超出当前授权范围” |
| 工具不在 allow list | agent 幻觉调用不存在或未授权工具 | Tool Policy Gate 拒绝 | 返回只读说明或改走可用路径 |
| 高风险输出未过 `RiskReviewTools` | 结论看似可执行但未审查 | 降级为 `analysis_only` 或 `blocked` | 明确提示“仅供观察，不构成可执行建议” |
| 受控写入未过 `ConfirmationTools` | 交易录入/OCR 修正缺确认 | 只保留 pending action | 提示用户先确认 |
| 持仓/现金/保证金对账失败 | Options / Portfolio 关键事实不可靠 | 阻断高风险建议 | 只返回分析，禁止行动建议 |
| 数据过期或 fallback 到低等级源 | 不能给交易级结论 | 降级 `actionability_level` | 标注“非交易级/可能延迟” |
| Broker Sync worker 失败 | 同步异常、snapshot 缺失 | 进入 retry / DLQ，暴露给 Ops | 告知数据同步异常，稍后重试 |
| Ops role 从用户入口被触发 | 非管理员尝试访问运维能力 | entitlement 拒绝 | 返回“仅后台可用” |

### 10.1 建议的降级输出等级

| 等级 | 适用条件 |
| --- | --- |
| `info_only` | 普通查询、状态类回复 |
| `analysis_only` | 数据不够新、fallback 源、缺少关键校验 |
| `suggested_action` | 数据和规则检查通过，但仍需用户自行判断 |
| `trade_draft` | 仅在高风险审查通过后可出现，且仍不等于自动执行 |
| `blocked` | 权限不足、对账失败、规则检查失败、跨 tenant 或 scope 冲突 |

## 11. 开发前已确认

| 问题 | 说明 |
| --- | --- |
| `Ops Agent` 是否应继续算在“8 个用户可见 role”口径内 | 不计入用户可见 role，归为后台系统角色 |
| `Quick Portfolio` 是否需要独立埋点/运营看板 | 单独埋点使用量和误路由率，但不作为独立 role |
| `Portfolio Agent` 的 `actionability_ceiling` 是否允许到 `trade_draft` | 允许创建待确认交易/调整草稿，但不得绕过 Options/Equity 专属策略检查 |
| `Broker Sync` 异常是否要以“系统角色”形式对用户可见 | 不作为用户可见 agent 暴露，只展示同步状态和异常解释 |
| `tenant override` 的审批粒度 | P0 只允许 rollout/feature flag 级 override，不允许绕过 runtime_scope 和高风险审批 |
| Capability Matrix 与 Tool Contract Registry 的发布顺序 | 新 contract 先 registry shadow，再 capability matrix 灰度，最后激活 |
