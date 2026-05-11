# 持仓核心产品系统分析

## 1. 系统目标

本文件定义持仓核心产品的系统分层、模块边界、接口契约、状态机、降级规则和测试策略，覆盖以下范围：

1. Dashboard 持仓摘要。
2. 持仓工作台。
3. 多 `portfolio_view`。
4. 股票 / ETF 详情。
5. Sell Put 工作台。
6. 确认中心联动所依赖的读写边界。

本分析遵循以下硬性系统口径：

1. **股票 / ETF 与期权是独立模型。** 两者共享统一持仓骨架与统一资产总览，但分析模型、风控字段、read model 和工作流分开实现。
2. **`portfolio_view` 不是资产真相源。** 它只定义展示、筛选和聚合口径；真实资产事实来自 `asset_sources`、`trade_events`、broker snapshot、cash/margin snapshot 和对账结果。
3. **Dashboard 不做富途同步主入口。** Dashboard 只展示 freshness、同步状态、异常提示和跳转入口；手动同步入口在数据页 / 账户页。
4. **自动下单不做。** 任何页面都不直接生成真实券商下单动作。
5. **确认不等于自动下单授权。** 确认中心只承接事实写入、交易草稿、执行清单、OCR 修正、规则 override 和冲突处理。
6. **所有高注意动作进入确认中心。** 包括交易录入、Sell Put 草稿、规则 override、OCR 修正、批量导入和对账冲突。

系统目标不是再定义产品卖点，而是把 P0 已确认页面收敛成稳定的实现边界：用户先读取可信持仓状态，再在受控前提下生成建议或草稿，最后由确认中心完成显式人审与审计闭环。

## 2. 分层架构

### 2.1 分层定义

| 层级 | 职责 | 本范围内的核心对象 |
| --- | --- | --- |
| WebApp Shell / Channel Layer | 登录态、`tenant_id`、当前 `portfolio_view`、导航、全局 freshness / inbox badge | Dashboard、持仓、详情、Sell Put、确认中心 |
| Product BFF Layer | 页面级 DTO 聚合、鉴权、分页、筛选、只读接口编排、受控写入入口 | `dashboard overview`、`portfolio overview`、`confirmation inbox` |
| Read Model Layer | 面向页面的稳定读模型，隔离底层数据表、快照、对账复杂度 | `equity_positions_read_model`、`option_positions_read_model` |
| Domain Tools + Control Plane Layer | 领域计算、规则检查、风险审查、确认、降级、审计 | `PortfolioTools`、`OptionsTools`、`ConfirmationTools` |
| Fact / Source Layer | 真实来源、标准化事实、券商快照、现金保证金、市场数据、对账输出 | `asset_sources`、broker snapshots、`trade_events` |

### 2.2 两条主业务路径

| 路径 | 页面 | 读模型 | 主要工具 | 汇合点 |
| --- | --- | --- | --- | --- |
| 股票 / ETF 路径 | 持仓工作台 -> 股票 / ETF 详情 | `portfolio overview`、`equity positions`、`position timeline` | `PortfolioTools`、`EquityTools`、`DisciplineRuleTools` | `RiskReviewTools` -> `ConfirmationTools` |
| Sell Put 路径 | 持仓工作台 -> Sell Put 工作台 | `option positions`、`portfolio risk`、`confirmation inbox` | `OptionsTools`、`BrokerTools.read`、`DisciplineRuleTools` | `RiskReviewTools` -> `ConfirmationTools` |

两条路径在读层分离，在高风险控制层汇合：

1. 股票 / ETF 页可以生成分析结论、纪律提醒、策略草稿，但不直接写交易事实。
2. Sell Put 工作台可以生成候选、监控草稿、交易草稿和执行清单，但不直接下单。
3. 任何会被用户理解为动作建议的结果，都必须落到 `actionability_level`，并在高风险场景进入确认中心。

### 2.3 架构约束

1. BFF 只消费 read model 和 Domain Tools 暴露的稳定契约，不直接拼底层事实表。
2. WebApp 页面不直接访问 broker sync 或规则写入底表，所有写路径都经 Domain Tools。
3. `portfolio_view` 切换只刷新读模型上下文，不触发任何事实写入。
4. Data / Account 页面拥有同步入口；持仓核心页面只消费同步状态，不拥有同步控制权。

## 3. 模块边界

### 3.1 页面与模块边界

| 模块 | 负责 | 不负责 | 上下游依赖 |
| --- | --- | --- | --- |
| Dashboard 持仓摘要 | 资产摘要、风险摘要、待处理、freshness、当前 `portfolio_view` | 富途同步操作、深度分析、交易事实写入 | `dashboard overview`、`confirmation inbox` |
| 持仓工作台 | 多 `portfolio_view` 切换、股票 / ETF 分区、期权分区、风险雷达 | 券商同步、交易事实写入、自动下单 | `portfolio overview`、`equity positions`、`option positions` |
| `portfolio_view` 配置 | 维护展示口径：来源、市场、品种、默认货币、排序 | 复制资产、改变真实持仓、跨租户共享 | `PortfolioTools`、`ConfirmationTools`、`AuditObservabilityTools` |
| 股票 / ETF 详情 | 单标的持仓摘要、纪律命中、收益路径、时间线、分析/策略草稿 | 直接下单、直接写 `trade_events` | `equity positions`、`position timeline`、`EquityTools` |
| Sell Put 工作台 | short put 持仓、现金占用、到期梯队、候选比较、纪律门、草稿入口 | 自动下单、在关键字段缺失时继续给候选 | `option positions`、`portfolio risk`、`OptionsTools`、`BrokerTools.read` |
| 确认中心 | 待处理项读取、结构化预览、确认/拒绝/退回、跨端状态收敛 | 风险计算、事实解析、自动执行券商动作 | `confirmation inbox`、`ConfirmationTools` |
| Data / Account 模块 | 券商连接、同步触发、freshness 来源说明、异常处理 | Dashboard 摘要渲染 | `BrokerTools`、reconcile 流程 |

### 3.2 事实边界

| 对象 | 真相源 | 页面可见形态 | 说明 |
| --- | --- | --- | --- |
| 当前持仓 | broker snapshot + confirmed `trade_events` + reconcile output | 持仓表、详情页、Dashboard 摘要 | 页面只读，不直接改写 |
| 现金 / 保证金 | broker cash / margin snapshot | Dashboard KPI、Sell Put 现金摘要 | Sell Put 依赖其 freshness 与 reconcile 状态 |
| `portfolio_view` | `portfolio_views` + `portfolio_view_sources` | 视图切换器、视图配置页 | 不是资产真相源 |
| 交易草稿 / override / OCR 修正 | `pending_action` / `confirmation_session` | 确认中心、页面内待确认 badge | 确认后才落正式结果 |
| 规则命中 | `discipline_checks` / 规则引擎输出 | 纪律状态、风险标签 | 不由页面自行推导 |

## 4. 关键数据实体

### 4.1 账号与视图实体

| 实体 | 作用 | 关键字段 |
| --- | --- | --- |
| `tenant_id` | 最高数据隔离边界 | 登录身份、所有业务表必带 |
| `asset_source_id` | 资产来源标识 | `source_type`、provider、priority、quality |
| `broker_connection_id` | 券商连接 | broker、auth status、last sync、permission scope |
| `portfolio_view_id` | 展示 / 聚合视图 | 名称、默认货币、市场过滤、品种过滤 |
| `portfolio_view_sources` | 视图纳入哪些来源 | `asset_source_id`、include mode、rules |

### 4.2 持仓与风险实体

| 实体 | 作用 | 关键字段 |
| --- | --- | --- |
| `portfolio_positions` | 统一持仓骨架 | `instrument_id`、`instrument_type`、`quantity`、`market_value`、`source_lineage`、`reconciliation_status` |
| `equity_positions` | 股票 / ETF 扩展 | shares、avg cost、latest price、sector、stop loss、take profit |
| `option_positions` | 期权扩展 | strategy、side、strike、expiry、DTE、IV、Greeks、cash secured amount、assignment risk |
| `cash_balances` | 分币种现金状态 | currency、available cash、as_of、source |
| `margin_balances` | 保证金状态 | margin required、available buying power、as_of |
| position snapshot | 趋势 / 时间线 / 历史对比 | snapshot time、portfolio view、aggregates |

### 4.3 控制面实体

| 实体 | 作用 | 关键字段 |
| --- | --- | --- |
| `pending_action` | 待确认动作标准化对象 | object type、risk level、lineage、TTL |
| `confirmation_session` | 面向用户的确认会话 | session id、status、channel、object ref |
| `confirmation_event` | 确认审计事件流 | created、viewed、confirmed、rejected、expired、commit failed |
| `commit_result` | 确认后的正式提交结果 | target type、result status、idempotency key |
| `degradation_decision` | 降级决策对象 | level、actionability cap、blocked reason、template key |

### 4.4 关键实体约束

1. 股票 / ETF 与期权必须保持独立扩展表、独立分析字段、独立风控字段。
2. 期权合约必须关联 `underlying_instrument_id`，Sell Put 不能只看合约自身。
3. `portfolio_view_id` 只出现在视图层和读模型层，不可被当作真实券商账户。
4. 现金与保证金必须是独立实体，不从股票市值反推。

## 5. read model 设计

read model 的职责是为页面提供稳定、快速、可解释的数据投影，而不是直接暴露标准化事实表。

### 5.1 `dashboard overview`

| 项 | 设计 |
| --- | --- |
| 消费页面 | Dashboard |
| 数据来源 | `portfolio_overview_read_model` + `portfolio_risk_read_model` + `confirmation inbox` 摘要 |
| 关键字段 | total assets、cash、equity MV、option cash usage、today pnl、freshness、todo count |
| 约束 | 只给状态结论和入口，不承载同步动作 |

建议 DTO：

```json
{
  "portfolio_view_id": "pv_default",
  "summary": {
    "total_assets": 1250000,
    "cash": 280000,
    "equity_market_value": 760000,
    "option_cash_secured": 150000,
    "today_pnl": 8200
  },
  "data_status": {
    "source": "futu_primary",
    "freshness_status": "fresh",
    "last_sync_at": "2026-05-09T09:20:00Z",
    "reconcile_status": "matched"
  },
  "todo": {
    "confirmation_count": 3,
    "conflict_count": 1
  }
}
```

### 5.2 `portfolio overview`

| 项 | 设计 |
| --- | --- |
| 消费页面 | 持仓工作台 |
| 关键字段 | 当前视图、总资产、现金、股票/ETF 市值、期权占用、过滤条件、来源 badge |
| 关键能力 | 视图切换后整页刷新；不改事实 |
| 约束 | 聚合口径随 `portfolio_view` 变化，事实来源不变 |

### 5.3 `equity positions`

| 项 | 设计 |
| --- | --- |
| 消费页面 | 持仓工作台、股票 / ETF 详情 |
| 关键字段 | symbol、market、shares、cost、latest price、market value、pnl、discipline status、lineage |
| 支持能力 | 分页、排序、市场/来源过滤、点击下钻 |
| 约束 | 只承载股票 / ETF，不混入期权字段 |

### 5.4 `option positions`

| 项 | 设计 |
| --- | --- |
| 消费页面 | 持仓工作台、Sell Put 工作台 |
| 关键字段 | contract、underlying、strategy、DTE、delta、IV、premium、cash required、assignment risk |
| 支持能力 | 到期梯队、风险标签、流动性状态、候选上下文 |
| 约束 | 只承载期权，不复用股票详情模型 |

### 5.5 `portfolio risk`

| 项 | 设计 |
| --- | --- |
| 消费页面 | Dashboard、持仓工作台、Sell Put 工作台 |
| 关键字段 | concentration、sector exposure、single-name exposure、cash usage、expiry ladder、discipline alerts |
| 关键依赖 | 现金/保证金、持仓聚合、规则检查、reconcile 状态 |
| 约束 | 当关键来源降级时只保留观察级风险结论 |

### 5.6 `position timeline`

| 项 | 设计 |
| --- | --- |
| 消费页面 | 股票 / ETF 详情 |
| 关键字段 | 买入、卖出、加仓、修正、确认、规则命中、分析事件 |
| 输入来源 | `trade_events`、confirmed corrections、analysis artifacts、confirmation events |
| 约束 | 时间线用于解释，不反向生成事实 |

### 5.7 `confirmation inbox`

| 项 | 设计 |
| --- | --- |
| 消费页面 | Dashboard、确认中心、页面内待处理 badge |
| 关键字段 | object type、risk level、status、ttl、source snapshot、channel state |
| 关键能力 | WebApp / 微信状态一致；列表和详情分离 |
| 约束 | inbox 是确认入口，不替代对象本身的领域详情 |

### 5.8 freshness 与对账投影

所有 read model 都必须带以下控制字段：

| 字段 | 说明 |
| --- | --- |
| `freshness_status` | `fresh / stale / degraded / unavailable` |
| `last_sync_at` | 最近成功同步时间 |
| `reconcile_status` | `matched / mismatch / unverified / needs_user_review` |
| `source_tier` | `L1 / L2 / L3 / L4` |
| `confidence` | 页面展示使用的置信等级 |

## 6. BFF/API 契约

### 6.1 读接口

| 接口 | 页面 | 说明 |
| --- | --- | --- |
| `GET /api/dashboard/overview?portfolio_view_id=` | Dashboard | 返回资产摘要、risk summary、todo、data status |
| `GET /api/portfolio/overview?portfolio_view_id=` | 持仓工作台 | 返回当前视图、聚合指标、过滤配置 |
| `GET /api/positions/equity?portfolio_view_id=&page=&sort=&filters=` | 持仓工作台、股票详情入口 | 返回股票 / ETF 列表 |
| `GET /api/positions/options?portfolio_view_id=&bucket=&filters=` | 持仓工作台、Sell Put 工作台 | 返回期权持仓和分层 |
| `GET /api/portfolio/risk?portfolio_view_id=` | Dashboard、持仓工作台、Sell Put 工作台 | 返回组合风险、现金占用、到期风险 |
| `GET /api/equities/{position_id}` | 股票 / ETF 详情 | 返回单标的详情页 DTO |
| `GET /api/equities/{position_id}/timeline` | 股票 / ETF 详情 | 返回交易 / 确认 / 分析时间线 |
| `GET /api/options/sell-put/workbench?portfolio_view_id=` | Sell Put 工作台 | 返回 KPI、持仓、候选上下文、纪律门状态 |
| `GET /api/confirmations/inbox?status=&type=` | Dashboard、确认中心 | 返回待处理摘要或列表 |
| `GET /api/confirmations/{session_id}` | 确认中心 | 返回结构化确认详情 |

### 6.2 写接口

#### `portfolio_view` 配置写接口

`PUT /api/portfolio-views/{portfolio_view_id}`

用途：修改名称、默认货币、包含来源、市场、品种、排序规则。

约束：

1. 只修改展示口径，不触碰真实资产。
2. 写入需审计；如果规则要求，可进入轻量确认。
3. 修改后触发 read model 失效和重算，但不触发 broker sync。

示例：

```json
{
  "name": "期权策略账户",
  "base_currency": "USD",
  "included_asset_source_ids": ["src_futu_main", "src_manual_option_fix"],
  "instrument_types": ["option_contract"],
  "markets": ["US"],
  "is_default": false
}
```

#### 确认会话提交接口

`POST /api/confirmations/{session_id}/submit`

用途：确认、拒绝或退回某个待确认动作。

约束：

1. 幂等提交，必须带 `idempotency_key`。
2. 确认只代表用户同意记录事实、草稿或执行清单，不等于自动下单授权。
3. 过期会话不可提交；若源数据已变化，需重新开会话。

示例：

```json
{
  "decision": "confirm",
  "user_note": "确认作为人工执行草稿，稍后我自己去券商下单",
  "idempotency_key": "confirm-20260509-001"
}
```

### 6.3 页面写路径边界

| 页面 | 允许写入 | 禁止写入 |
| --- | --- | --- |
| Dashboard | 无业务事实写入 | 同步主入口、交易写入 |
| 持仓工作台 | `portfolio_view` 配置 | 交易事实、券商同步 |
| 股票 / ETF 详情 | 策略草稿、确认入口、研究任务入口 | 直接写 `trade_events` |
| Sell Put 工作台 | 候选分析、交易草稿、确认入口 | 真实下单、绕过资金/规则门 |
| 确认中心 | 提交确认决策 | 风险计算、直接改 broker 数据 |

## 7. Domain Tools 契约

### 7.1 工具族与边界

| 工具族 | 职责 | 典型输入 | 输出上限 | 高风险门 |
| --- | --- | --- | --- | --- |
| `PortfolioTools` | 聚合资产、持仓概览、现金/保证金汇总、组合风险摘要 | `tenant_id`、`portfolio_view_id` | `info_only / analysis_only` | 组合风险进入建议前需 `RiskReviewTools` |
| `EquityTools` | 股票 / ETF 分析、收益路径、止盈止损建议、纪律上下文 | `position_id`、price/history、rules | `analysis_only / suggested_action` | 如形成策略草稿，需走 `RiskReviewTools` + `ConfirmationTools` |
| `OptionsTools` | Sell Put 候选、short put 监控、DTE/IV/流动性分析、roll/assignment 分析 | option positions、chain、underlying、cash context | `analysis_only / suggested_action / trade_draft` | `BrokerTools.read`、`DisciplineRuleTools`、`RiskReviewTools` 必经 |
| `DisciplineRuleTools` | 规则检查、override 条件、纪律评分 | action payload、tenant rules | `pass / warn / override_required / hard_block` | `hard_block` 直接阻断；`override_required` 进入确认 |
| `ConfirmationTools` | 创建 `pending_action`、会话管理、提交幂等、状态同步 | object ref、risk level、ttl | confirmed / rejected / expired | 不负责自动下单 |
| `BrokerTools.read` | 只读券商持仓、现金、保证金、期权仓位、sync 状态 | broker connection、scope | `info_only` 原始事实 | 不允许升级成交易能力 |
| `DegradationPolicyTools` | 统一判定 L1-L4 降级、模板、动作上限 | freshness、source tier、reconcile、runtime health | `actionability_cap` | 高风险任务可直接降到 `blocked` |
| `AuditObservabilityTools` | 审计、trace、lineage、指标、回放 | run context、tool result、decision | 审计事件 | 所有 controlled write 必须落审计 |

### 7.2 动作等级与统一门控

系统统一使用以下 `actionability_level`：

| 等级 | 含义 |
| --- | --- |
| `info_only` | 事实展示 |
| `analysis_only` | 可分析但不可行动 |
| `suggested_action` | 可作为人工判断参考 |
| `trade_draft` | 已通过主要 gate、可进入确认的待确认草稿 |
| `blocked` | 当前不允许继续给行动结论 |

统一规则：

1. 高风险输出不能由 agent 自己升级到 `trade_draft`。
2. `trade_draft` 只允许在 `L1` 正常状态下出现，并要求 freshness、对账、现金/保证金、规则检查和确认流可用。
3. `BrokerTools.read` 永远只读；读取 broker 数据不代表具备交易权限。
4. `ConfirmationTools` 的确认对象可以是事实写入、草稿、执行清单、OCR 修正或 override，但都不等于自动下单授权。

### 7.3 Sell Put 特有强门

Sell Put 进入 `trade_draft` 前必须同时满足：

1. `BrokerTools.read` 返回现金 / 保证金 `verified_sufficient`。
2. 期权链关键字段完整：`bid/ask`、IV、OI、DTE、underlying price。
3. `DisciplineRuleTools` 对愿接股、财报窗口、现金上限、DTE 范围返回 `pass` 或最多 `warn`。
4. `DegradationPolicyTools` 不高于 `L1`。
5. `RiskReviewTools` 通过，并且 `ConfirmationTools` 可承接。

## 8. 状态机

### 8.1 `portfolio_view` 切换状态机

| 状态 | 进入条件 | 转移 |
| --- | --- | --- |
| `idle` | 当前视图稳定 | 用户点击切换 -> `loading` |
| `loading` | BFF 请求新视图 read model | 成功 -> `resolved`；失败 -> `failed` |
| `resolved` | 新视图 read model 返回 | UI 更新并回到 `idle` |
| `failed` | 接口失败或参数非法 | 保留旧视图，提示重试 -> `idle` |

约束：

1. 切换只影响展示口径，不改变资产事实。
2. 切换失败时保留当前视图，不允许空白态覆盖已知数据。

### 8.2 持仓 freshness / reconcile 状态机

| 状态 | 含义 | 转移 |
| --- | --- | --- |
| `fresh_matched` | 数据新鲜且对账通过 | 过期 -> `stale`；冲突 -> `disputed` |
| `stale` | 数据过期但仍可查看 | 同步成功且对账通过 -> `fresh_matched`；主源异常 -> `degraded` |
| `degraded` | 使用 fallback 或主源不完整 | 主源恢复并通过校验 -> `fresh_matched`；发现冲突 -> `disputed` |
| `disputed` | 存在数量/现金/合约冲突 | 用户确认或修复 -> `fresh_matched` 或 `stale` |
| `unavailable` | 当前无可用读数据 | 数据恢复 -> `stale` 或 `fresh_matched` |

约束：

1. `disputed` 时不能形成高置信持仓建议。
2. cash mismatch 或 option contract mismatch 时，Sell Put 直接阻断。

### 8.3 Sell Put 候选 / 草稿状态机

| 状态 | 含义 | 转移 |
| --- | --- | --- |
| `candidate_observed` | 仅完成观察分析 | 通过规则和数据门 -> `candidate_scored`；关键字段缺失 -> `blocked` |
| `candidate_scored` | 已有结构化候选评分 | 用户请求生成草稿 -> `draft_pending_review` |
| `draft_pending_review` | 等待 `RiskReviewTools` / 确认流承接 | 通过 -> `draft_ready_for_confirmation`；失败 -> `blocked` |
| `draft_ready_for_confirmation` | 已形成待确认草稿 | 创建会话 -> `confirmation_open` |
| `confirmation_open` | 确认中心处理中 | confirmed -> `acknowledged_draft`；rejected/expired -> `closed` |
| `acknowledged_draft` | 用户确认的执行草稿 / 清单 | 后续人工执行，不自动下单 |
| `blocked` | 关键条件不满足 | 条件恢复后重新计算 |
| `closed` | 用户拒绝或过期 | 重新生成新草稿才可继续 |

### 8.4 confirmation session 状态机

| 状态 | 含义 | 转移 |
| --- | --- | --- |
| `created` | 已创建待确认对象 | 用户打开 -> `presented` |
| `presented` | 用户已看到结构化明细 | confirm -> `user_confirmed`；reject -> `rejected`；return -> `returned` |
| `user_confirmed` | 用户决策已提交 | commit success -> `committed`；commit fail -> `commit_failed` |
| `commit_failed` | 用户已确认但写入未成功 | retry success -> `committed`；TTL 失效 -> `expired` |
| `rejected` | 用户拒绝 | 终态 |
| `returned` | 退回补字段或重算 | 重新生成会话 |
| `expired` | TTL 过期或源上下文已变化 | 终态，需重新开会话 |
| `committed` | 审计完成、状态回写 | 终态 |

## 9. 错误 / 降级

### 9.1 L1-L4 降级定义

| 等级 | 含义 | 动作上限 | 页面表现 |
| --- | --- | --- | --- |
| `L1` | 正常 | 可到 `trade_draft` | 正常显示 |
| `L2` | 受控降级 | 通常不高于 `suggested_action` | 显示降级 badge，缩小范围 |
| `L3` | fallback 观察级 | 只到 `analysis_only` | 明确“仅观察分析” |
| `L4` | 阻断级 | `blocked` 或最小 `info_only` | 阻断高风险动作，给恢复条件 |

### 9.2 典型错误与处理

| 错误场景 | 默认级别 | 处理原则 |
| --- | --- | --- |
| Dashboard overview 依赖的聚合接口超时 | `L2` | 保留最近成功摘要，标注时间戳 |
| `portfolio_view` 切换失败 | `L2` | 保留旧视图，允许重试 |
| 持仓数据过期 | `L2` 或 `L3` | 允许查看，但不生成高风险草稿 |
| 富途主源不可用，腾讯财经 fallback 生效 | `L3` | 只做观察分析，不给交易级建议 |
| 对账失败 | `L4`（高风险任务） | 持仓建议和 Sell Put 阻断，进入确认中心 |
| 规则服务不可用 | `L2` 或 `L4` | 低风险查询可继续，高风险建议暂停 |
| 确认提交失败 | `L2` | 保持待处理状态，不假设已生效 |

### 9.3 Sell Put 阻断规则

以下任一条件成立，Sell Put 必须进入 `L4 / blocked`：

1. 现金 / 保证金缺失、过期、对账失败或明确不足。
2. 期权链关键字段缺失：`bid/ask`、IV、OI、DTE、underlying price 任一关键字段不可用。
3. 纪律规则返回 `hard_block`。
4. 期权合约与底层标的映射不确定。
5. 确认流不可用，无法承接 `trade_draft`。

### 9.4 用户可见文案原则

1. 明确告诉用户当前还能看、不能做什么。
2. 不用模糊措辞暗示“也许可以执行”。
3. 恢复条件要具体，例如“等待数据页完成同步”或“先处理现金对账冲突”。

## 10. 权限与审计

### 10.1 权限模型

| 边界 | 规则 |
| --- | --- |
| 身份 | 以 Supabase Auth 身份进入 WebApp |
| 隔离 | 所有读写都按 `tenant_id` 隔离 |
| 页面权限 | 用户只能查看和处理自己账号下的持仓、视图、确认项 |
| broker 读取 | 通过 `BrokerTools.read` 按 entitlement 控制，只读不扩权 |
| controlled write | 交易录入、草稿确认、OCR 修正、规则 override 必须进确认流 |

### 10.2 审计要求

以下动作必须写审计：

1. `portfolio_view` 创建、编辑、设为默认。
2. 确认会话创建、查看、确认、拒绝、过期、重试。
3. Sell Put 草稿生成与风险降级决策。
4. 股票 / ETF 详情页产生的策略草稿与 override。
5. read model 命中 `degraded / disputed / blocked` 的关键页面访问。

建议审计字段：

| 字段 | 说明 |
| --- | --- |
| `tenant_id` | 数据隔离主体 |
| `actor_user_id` | 当前确认人 / 操作者 |
| `channel` | webapp / wechat |
| `object_type` | portfolio view / trade draft / correction / override |
| `source_snapshot_hash` | 来源快照 |
| `risk_level` | low / medium / high |
| `actionability_level` | 本次输出的动作等级 |
| `decision` | confirm / reject / return |
| `idempotency_key` | 防重复提交 |
| `created_at` / `committed_at` | 时序审计 |

## 11. 性能指标

### 11.1 页面读性能

| 查询 | 目标 |
| --- | --- |
| Dashboard overview | p95 < 500ms |
| 持仓工作台首屏 | p95 < 800ms |
| 股票 / ETF 列表分页 | p95 < 700ms |
| 期权持仓 / Sell Put 首屏 | p95 < 900ms |
| 股票 / ETF 详情 | p95 < 900ms |
| confirmation inbox 列表 | p95 < 500ms |

### 11.2 写与状态同步性能

| 动作 | 目标 |
| --- | --- |
| `portfolio_view` 切换后首屏刷新 | p95 < 800ms |
| `portfolio_view` 配置保存 | p95 < 700ms |
| confirmation submit | p95 < 800ms，幂等重试可恢复 |
| 确认状态跨端同步 | 5s 内反映到 WebApp / 微信摘要 |

### 11.3 数据质量目标

| 指标 | 目标 |
| --- | --- |
| freshness 状态可见率 | 100% 核心持仓页面展示 |
| 对账状态可见率 | 100% 核心持仓页面展示 |
| 降级时误放行 `trade_draft` | 0 容忍 |
| Sell Put 关键字段缺失下草稿生成率 | 0 容忍 |

## 12. 测试策略

### 12.1 Contract 测试

验证对象：

1. BFF 读接口返回字段与状态字段完整。
2. `portfolio_view` 写接口只影响配置，不影响事实层。
3. confirmation submit 幂等、过期、拒绝、重试语义正确。
4. Domain Tools 输出包含 `data_quality`、`lineage_refs`、`actionability_level`。

### 12.2 Read Model 测试

验证对象：

1. `dashboard overview` 聚合正确区分 equity、options、cash。
2. `portfolio overview` 与 `portfolio_view` 过滤口径一致。
3. `equity positions` 与 `option positions` 不混字段、不串模型。
4. `portfolio risk` 在 freshness / reconcile 变化时正确降级。
5. `position timeline` 能正确串联交易、确认和分析事件。
6. `confirmation inbox` 能反映状态变化与 TTL 失效。

### 12.3 Integration 测试

验证链路：

1. broker snapshot -> read model -> 持仓页面渲染。
2. 规则检查 -> 风险审查 -> confirmation session 创建。
3. cash mismatch / option mismatch -> `DegradationPolicyTools` -> Sell Put 阻断。
4. `portfolio_view` 变更 -> BFF 失效缓存 -> 页面重新读取。
5. WebApp 确认后 -> 审计事件 -> Dashboard / inbox 状态更新。

### 12.4 E2E 测试

覆盖场景：

1. 登录后进入 Dashboard，看到当前视图、摘要、freshness、待确认数。
2. 从持仓工作台切换两个 `portfolio_view`，验证只变展示口径。
3. 从股票行进入详情，看到时间线与纪律状态，生成草稿但不写事实。
4. 从期权卡进入 Sell Put 工作台，在数据齐全时生成草稿并进入确认中心。
5. 在现金 / 保证金缺失或期权链关键字段缺失时，Sell Put 被阻断。
6. 在确认中心确认 / 拒绝后，状态同步回 Dashboard 和对应页面。

## 13. 实施顺序

### Phase 1：数据与读模型基础

1. 固化 `portfolio_views`、`portfolio_view_sources`、`portfolio_positions`、`equity_positions`、`option_positions`、cash / margin 实体。
2. 建立 `dashboard overview`、`portfolio overview`、`equity positions`、`option positions`、`portfolio risk` read model。
3. 为所有 read model 注入 freshness / reconcile / source_tier 字段。

### Phase 2：BFF 与页面读取闭环

1. 实现 Dashboard 与持仓工作台读接口。
2. 实现股票 / ETF 详情与 `position timeline`。
3. 实现 Sell Put 工作台读接口和阻断态返回。

### Phase 3：控制面接入

1. 接入 `DisciplineRuleTools`、`RiskReviewTools`、`DegradationPolicyTools`。
2. 定义股票 / ETF 策略草稿、Sell Put 草稿、OCR 修正、冲突处理的 `pending_action` 模型。
3. 打通 `confirmation inbox` 与确认中心详情 / 提交接口。

### Phase 4：写路径与审计闭环

1. 实现 `portfolio_view` 配置写接口与审计。
2. 实现 confirmation submit 幂等与跨端状态同步。
3. 对接 Data / Account 页的 freshness 展示和深链，不把同步入口放回 Dashboard。

### Phase 5：验收与加固

1. 跑通 E2E 核心场景。
2. 验证所有高注意动作都进入确认中心。
3. 验证 Sell Put 在关键字段缺失时严格阻断。

## 14. 开发前已确认

1. 普通 `portfolio_view` 展示变更只审计；影响资产口径/资金口径/source inclusion 的变更走轻量确认。
2. `position timeline` 中事实事件、分析事件、系统事件分组展示，视觉上区分，避免用户把分析结论误读为交易事实。
3. Sell Put 候选排序与展示字段已明确；具体阈值如 DTE、delta、spread、IV 区间全部配置化，不在页面层硬编码。
4. Sell Put 行情/期权链 freshness 要求 30-60 秒内；现金/保证金以最近成功 broker snapshot 为准；超时降级为观察分析。
5. WebApp 消息中心与微信推送共用 `delivery/outbox/message_events` 事实源；微信与 WebApp 是不同 channel view，需要实现双端状态同步。
6. 多币种折算与默认货币展示由 `portfolio_view.base_currency` 控制；汇率源走 data-service，记录更新时间和来源。
7. Dashboard “今日行动”卡片优先级：待确认/冲突 > 高风险到期 > Sell Put 到期 > 异动提醒 > 普通摘要。
8. 股票/ETF 止盈止损草稿与 Sell Put 交易草稿分开定义：`equity_exit_plan_draft` 与 `sell_put_trade_draft`。
