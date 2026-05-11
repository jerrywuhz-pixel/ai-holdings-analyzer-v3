# 数据质量与券商接入

## 2.0 当前数据能力

当前 2.0 已具备通用行情数据服务：

- Yahoo、Tushare、AkShare、Longbridge adapters
- `/api/quote/{symbol}`
- `/api/quote/batch`
- `/api/search`
- `/api/resolve/{user_input}`
- `/api/health/sources`
- Redis/health cache 设计
- `symbol_registry` 替代硬编码股票池

这些能力适合行情分析、watchlist、机会捕捉和一部分持仓估值，但不足以单独支撑“真实持仓系统”。

## 账号下的多来源资产模型

3.0 中 `tenant_id` 是系统账号和主隔离边界，继承当前 `routing.json.tenantId`。`routing.json.accountId` 只表示 OpenClaw 微信 bot，在 3.0 内部命名为 `openclaw_account_id`。一个系统账号下可以同时存在多种资产数据来源：

| 来源 | 示例 | 写入要求 |
| --- | --- | --- |
| 手工录入 | WebApp 或微信中录入历史成交 | `source_type=manual`，保留录入人、确认状态 |
| 买入/卖出消息 | 微信里发送“买入 AAPL 10 股 180” | `source_type=message_trade_input`，保留原始消息 hash |
| 券商消息解析 | 转发券商成交提醒 | `source_type=broker_message`，保留券商、消息 fingerprint |
| OCR | 成交截图、持仓截图 | `source_type=ocr`，保留图片 ref、识别置信度 |
| 券商 API | 富途、长桥、PTrade 直连 | `source_type=broker_api`，绑定 `broker_connection_id` 和同步 run；美港股和期权链首选富途 |
| 系统派生 | 持仓快照、策略评分、止盈计划 | `source_type=derived`，保留上游数据 lineage |

统一资产视图可以合并这些来源，但每条底层成交、仓位、现金、期权仓位和分析结果都必须保留来源，方便对账、纠错和审计。

## 数据分层

| 数据层 | 示例 | 可信度要求 | 推荐来源 |
| --- | --- | --- | --- |
| Market Public | 行情、K线、指数、ETF、新闻 | 可 fallback，但必须标注延迟和来源 | Yahoo、Tushare、AkShare、Longbridge |
| Options Public | 期权链、Greeks、IV、成交量、OI | 高 freshness，缺字段必须降级 | broker、Longbridge、OPRA/第三方 |
| Broker Account | 真实持仓、成交、现金、保证金、期权仓位 | 最高优先级，必须审计和只读授权 | 富途优先，长桥/PTrade 补充 |
| Market Analysis | 行情、期权链、新闻、财报、事件 | 分层使用，策略输出需 freshness gate | 富途主源，腾讯财经交叉校验，其他源兜底 |
| Historical Market Store | 日线、分钟线、期权链快照、公司行动、交易日历 | 可回测、可复盘、可审计；必须有覆盖范围和质量报告 | 本地/云端 Parquet + manifest，缺口按主源补拉 |
| User Input | 手工交易、微信转发、截图 OCR | 需要确认、去重、纠错 | 微信 claw、WebApp、OCR |
| Derived Analytics | 成本、盈亏、策略标签、止盈计划 | 可重算，可追溯 | 系统计算 |

## 数据质量评分

每条关键数据都应带质量元数据：

```json
{
  "tenant_id": "uuid",
  "asset_source_id": "uuid",
  "openclaw_account_id": "uuid-or-string-if-from-wechat",
  "source": "longbridge",
  "source_type": "broker | public_market | user_input | derived",
  "as_of": "2026-05-09T09:31:20+08:00",
  "freshness_seconds": 45,
  "confidence_score": 0.97,
  "lineage": ["broker_positions_sync:run_123"],
  "fallback_used": false,
  "missing_fields": [],
  "reconciliation_status": "matched | mismatch | unverified"
}
```

建议评分维度：

| 维度 | 说明 |
| --- | --- |
| Freshness | 行情、期权链、现金保证金的时间戳是否满足策略要求 |
| Completeness | 是否缺少 bid/ask、volume、OI、cash、margin 等关键字段 |
| Provenance | 是否来自券商、公共源、用户输入或推导 |
| Reconciliation | 手工交易与券商真实成交是否能对账 |
| Consistency | provider symbols、market、exchange 是否标准化一致 |
| Stability | 数据源近期失败率和 fallback 次数 |

## 历史行情数据质量

历史行情数据不能只看“能不能查到”，还要能证明“覆盖是否完整、口径是否一致、能不能复现”。写入 Historical Market Store 时，每批数据必须记录：

| 字段 | 说明 |
| --- | --- |
| `source_key` | 富途、Tushare、腾讯财经、Databento 等来源 |
| `coverage_start/coverage_end` | 覆盖日期范围 |
| `trading_days_expected/trading_days_available` | 应有交易日和实际可用交易日 |
| `missing_trading_days` | 缺失交易日列表 |
| `adjustment` | raw、前复权、后复权、split adjusted 等口径 |
| `schema_version` | 标准化 schema 版本 |
| `checksum` | 文件内容校验，防止静默损坏 |
| `quality_status` | validated、partial、stale、failed |

回测和复盘默认只使用 `quality_status=validated` 的历史数据；如果使用 partial 数据，报告必须明确标注缺失区间和可能影响。

## 券商接入优先级

| 阶段 | 能力 | 目标 |
| --- | --- | --- |
| Phase A | 只读同步持仓和成交 | 真实持仓优先于手工和微信解析 |
| Phase B | 同步现金、保证金、期权仓位 | 支撑 sell put 风险和资金约束 |
| Phase C | 对账和差异修复 | 手工记录、微信提醒、券商流水三方 reconcile |
| Phase D | 交易草稿和确认流 | 只生成订单草稿，用户确认后跳转或手动执行 |
| Phase E | 自动交易评估 | 高风险，暂不默认纳入 3.0 |

## 候选券商连接器

| 券商/系统 | 用途 | 关键评估点 |
| --- | --- | --- |
| 富途 Futu | **首选**：港美股、ETF、期权链、账户持仓、成交、现金、保证金 | OpenAPI 登录形态、OpenD 部署、行情权限、期权链字段完整度、风控限制 |
| 长桥 Longbridge | 备选：港美股行情、账户、期权链和交易能力候选 | API 稳定性、账户授权方式、期权字段完整度、地域和合规限制 |
| PTrade | A 股券商生产/仿真交易环境候选 | 券商支持范围、网络白名单、读写权限、运维复杂度 |
| 腾讯财经 Tencent Finance | 公共行情交叉校验和 fallback，2.0 分析经验显示稳定性高 | 接口授权/SLA、延迟、新鲜度、是否可商用；暂不作为交易级主源 |
| 微信券商提醒解析 | 低成本 fallback | 格式变化、延迟、去重、无法获取现金保证金 |
| 手工录入/OCR | 兜底 | 用户负担、错误率、确认流程 |

## 持仓真相源策略

建议引入 `position_sources` 或 `broker_sync_snapshots`：

| 优先级 | 来源 | 使用方式 |
| --- | --- | --- |
| 1 | 券商 production read-only | 作为真实持仓和现金保证金的最高优先级 |
| 2 | 已确认交易事件 `trade_events` | 券商不可用时重建持仓 |
| 3 | 微信券商成交提醒 | 自动生成待确认交易事件 |
| 4 | OCR/手工 | 需要用户确认 |
| 5 | derived snapshots | 展示和分析，不作为不可追溯真相源 |

## 对账机制

每个账号每日需要一条 reconcile 记录：

```json
{
  "tenant_id": "uuid",
  "broker_connection_id": "uuid",
  "date": "2026-05-09",
  "positions_match": true,
  "cash_match": true,
  "unmatched_trade_events": [],
  "broker_only_trades": [],
  "system_only_trades": [],
  "resolution_status": "resolved | needs_user_review"
}
```

对账失败时，agent 不应给出高置信度策略，只能说：

- 哪些数据不一致
- 哪个来源更新
- 当前分析是否降级
- 用户需要确认什么

## 期权数据特别要求

Sell put 不能只看标的价格。必须要求：

1. option chain 的 bid、ask、last、volume、open interest。
2. DTE、delta、theta、IV、IV Rank 或可替代波动率分位。
3. 标的财报日、除息日、重大事件。
4. 现金担保或保证金要求。
5. 用户是否愿意按 strike 接股。
6. 美股、港股、A 股市场差异和可交易范围。

如果缺少现金/保证金或期权链关键字段，输出只能是“观察分析”，不能升级为“可执行 sell put 候选”。

## 开发前已确认

1. 第一优先生产券商为富途；P0 接受用户本地运行 Futu OpenD，系统通过 tenant-scoped local connector 主动领取同步任务并上报脱敏 snapshot，云端不直接连接用户 OpenD。
2. 券商权限边界为 `read_only`；P0 所有 broker tools 只读，contract/代码中不暴露 `place_order`、`modify_order`、`cancel_order`。
3. P0 不保存生产券商 token；云端只保存连接状态、脱敏快照和 source lineage。
4. P0 A 股只做正股/ETF，不做 A 股期权；美股期权首期聚焦 single-leg cash-secured Sell Put。
5. 统一资产视图支持“多个券商账户 + 手工组合”之间的策略分组，通过 `portfolio_view_sources` 表达长期账户、期权现金流账户、观察组合等视图。
6. `broker_connector_instances` 表示用户本地连接器设备与心跳；`broker_connections` 表示富途等券商账户 / 资产来源，两者通过 `connector_instance_id` 关联，避免多用户共享本地 OpenD 连接的误判。
