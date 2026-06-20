# P0 定时任务清单

本文定义当前 Hermes 持仓分析系统在 P0 阶段必须启用的云端定时任务。口径以轻量服务器上的 Hermes / data-service / webapp 运行形态为准，不沿用旧 Google Cloud Scheduler 或 OpenClaw 主运行时假设。

## 当前云端基线

2026-06-12 云端只读巡检结论：

1. 系统 `crond` 正常运行，但没有业务 crontab。
2. systemd timer 只有系统维护任务。
3. Docker Compose 未运行独立 scheduler 容器。
4. Hermes gateway cron ticker 正常运行，但 `hermes cron list` 为空。
5. `/root/.hermes/cron` 没有业务 job。

因此 P0 需要先建立最小业务定时任务集，再做更复杂的行情、深研和推送编排。

## 设计原则

1. 所有任务必须带 `tenant_id` 或明确标记为平台共享任务。
2. 所有写入必须幂等，使用 `idempotency_key` 防止重复生成报告或重复推送。
3. 所有用户可见消息先进入 outbox，再由投递链路发送。
4. P0 不创建、修改、撤销券商订单；券商相关任务只读。
5. 关键数据缺失时降级为观察摘要，不生成高置信策略建议。
6. 每个任务都要有手动重跑入口，便于云端事故后补偿。
7. 默认时区使用 `Asia/Shanghai`；涉及美股任务时按美东交易日历判断是否开市。
8. 业务类任务默认对每个已绑定微信账号启用；触发时先枚举 `channel_bindings.binding_status='active'` 的账号，再按 `tenant_id` 检查持仓数据。
9. 单个微信账号对应的 `tenant_id` 没有任何 open 且正数量持仓时，业务类任务跳过该账号，不生成报告、不刷新候选、不推送提醒。

## 账号展开与持仓 gate

平台任务和业务任务的触发边界不同：

| 类型 | 任务 | 展开规则 |
| --- | --- | --- |
| 平台任务 | `p0-health-heartbeat`、`p0-delivery-retry`、`p0-backup-verify` | 全局运行，不要求账号已有持仓 |
| 业务任务 | `p0-broker-sync-planner`、`p0-broker-sync-staleness`、`p0-market-watchlist-refresh`、`p0-price-alert-evaluator`、`p0-cn-close-summary`、`p0-us-close-summary`、`p0-weekly-review`、`p0-opportunity-research-cn-hk-premarket`、`p0-opportunity-research-us-premarket`、`p0-opportunity-research-daily-review` | 按 active 微信绑定账号展开，且该账号必须有非空持仓 |

业务任务每次 tick 的共同 gate：

1. 查询 active 微信绑定账号：`channel_bindings.binding_status = 'active'`，优先面向 `hermes_wechat`，兼容历史 `openclaw_wechat`。
2. 对每个 `tenant_id` 查询持仓：`portfolio_positions.position_status IN ('open', 'closing', 'stale') AND quantity > 0`。
3. 如果当前账号在 `portfolio_positions` 尚未投影，但存在 open 的 `webapp_manual_positions.quantity > 0`，也视为有持仓。
4. 无 active 微信绑定时，本轮业务任务记为 `skipped_no_active_wechat_binding`。
5. 某个 active 微信账号没有持仓时，仅记录 `skipped_empty_holdings`，不进入业务 handler。
6. 同一租户有多个 active 微信绑定时，P0 使用 primary binding；没有 primary 时使用最近绑定的一条，避免重复推送。

## P0 必启任务

| ID | 任务 | Cron | 范围 | 主要作用 | 用户可见 |
| --- | --- | --- | --- | --- | --- |
| `p0-health-heartbeat` | 运行心跳与卡死任务巡检 | `*/5 * * * *` | 平台 | 写入 Hermes / data-service / webapp / broker connector 状态，标记超时任务 | 异常时推送 |
| `p0-delivery-retry` | outbox 投递重试 | `*/5 * * * *` | 平台 | 重试失败微信推送，超过上限标记 abandoned | 是 |
| `p0-broker-sync-planner` | 券商只读同步任务规划 | `0 9,12,16,21 * * 1-5` | tenant | 为已启用连接器的账号创建只读同步 job | 否 |
| `p0-broker-sync-staleness` | 持仓数据新鲜度检查 | `*/15 9-23 * * 1-5` | tenant | 检查持仓、现金、期权链是否过期，必要时降级分析能力 | 异常时推送 |
| `p0-market-watchlist-refresh` | 持仓与关注标的行情刷新 | `*/15 9-23 * * 1-5` | tenant | 刷新持仓、关注清单、Sell Put 候选池相关行情 | 否 |
| `p0-price-alert-evaluator` | 价格与规则提醒评估 | `*/10 9-23 * * 1-5` | tenant | 评估关注价、止盈止损、规则命中、期权风险提醒 | 是 |
| `p0-cn-close-summary` | A 股/港股收盘摘要 | `30 16 * * 1-5` | tenant | 生成日内变化、风险、待处理项摘要 | 是 |
| `p0-us-close-summary` | 美股收盘摘要 | `30 6 * * 2-6` | tenant | 生成美股与美股期权持仓摘要 | 是 |
| `p0-opportunity-research-cn-hk-premarket` | A股/港股盘前机会研究 | `0 9 * * 1-5` | tenant | 基于交易框架扫描持仓、关注和动态候选池，按 3.5 资产路径与五层蛋糕筛选每组 Top 3 龙头，生成机会 case、四道门结论和信号账本 | 是 |
| `p0-opportunity-research-us-premarket` | 美股盘前机会研究 | `0 20 * * 1-5` | tenant | 基于交易框架扫描美股持仓、关注、AI/硬科技动态候选池和 Sell Put 候选，只让主题/层级 Top 3 龙头进入深研 | 是 |
| `p0-opportunity-research-daily-review` | 机会研究每日复盘 | `45 16,7 * * 1-5` | tenant | 对上一轮机会 case 做事实核对、paper PnL、benchmark excess 和纪律复盘 | 摘要/异常时推送 |
| `p0-weekly-review` | 周复盘摘要 | `0 18 * * 5` | tenant | 汇总本周持仓变化、纪律命中、已完成任务和下周关注 | 是 |
| `p0-backup-verify` | 备份与关键数据完整性巡检 | `30 3 * * *` | 平台 | 校验数据库备份、对象存储、artifact 索引和关键表行数 | 异常时推送 |

## 当前推送模板

| 任务 | 正常推送策略 | 消息定位 | 当前模板要点 | 继续优化点 |
| --- | --- | --- | --- | --- |
| `p0-cn-close-summary` | 每个本地 ready 微信绑定直发 | A/H 日终持仓行动简报 | 组合变化、最大风险、市场走向与强势板块、数据质量、规则命中、明天观察项 | 接入昨日市值/盈亏快照后，把“持仓结构变化”升级为真实 PnL/贡献拆解 |
| `p0-us-close-summary` | 每个本地 ready 微信绑定直发 | 美股日终持仓行动简报 | 正股/期权结构、临近到期期权风险、整体市场/强势板块、数据质量、明日观察 | 接入期权链、DTE、delta、IV、保证金后，升级期权风险和 Sell Put 观察项 |
| `p0-broker-sync-planner` | 正常静默 | 无用户消息 | 只记录任务进入同步规划链路 | 仅在 connector 长时间离线或同步任务堆积时推送 |
| `p0-broker-sync-staleness` | 正常静默，异常推送 | 数据质量提醒 | 显示 freshness 降级、影响、建议、`actionability`、`degrade_reason` | 写入具体过期资产、过期时长、最后成功同步时间 |
| `p0-market-watchlist-refresh` | 正常静默，异常推送 | 市场机会提醒 | 显示关注清单/市场刷新异常、机会边界、风险、`actionability`、`degrade_reason` | 真正写入 `sector_daily_snapshots` 后推送强势板块变化和候选池变化 |
| `p0-price-alert-evaluator` | 命中或异常推送 | 价格/纪律提醒 | 显示规则命中待复核、影响、建议、`actionability`、`degrade_reason` | 补充具体条件、触发价、当前价、同日去重和后续口令 |
| `p0-opportunity-research-cn-hk-premarket` | 每日推送摘要，全文归档 | A/H 盘前机会研究 | Top 3 机会、四道门、仓位层、触发/失效条件；完整 artifact 与 `opportunity_cases` 入库 | 接入交易所节假日日历后跳过休市日 |
| `p0-opportunity-research-us-premarket` | 每日推送摘要，强触发机会高优先级 | 美股盘前机会研究 | AI/硬科技机会、Sell Put 候选、利润垫/纪律门；完整 artifact 与信号账本入库 | 接入期权链 freshness 与现金占用后提升 Sell Put actionability |
| `p0-opportunity-research-daily-review` | 摘要/异常推送，全文归档 | 机会研究每日复盘 | 核对昨日建议与次日事实，更新 `opportunity_case_marks`、paper PnL、benchmark excess | 每周聚合胜率、平均 R、最大回撤和 QQQ 2x stretch 偏离 |
| `p0-backup-verify` | 正常静默，异常推送 | 数据可恢复性告警 | 显示 Postgres/对象存储探针状态、`actionability`、`degrade_reason` | 增加最近备份时间、备份大小、恢复演练结果 |
| `p0-weekly-review` | 每周推送 | 周复盘摘要 | 尚未单独升级，本轮仍沿用复盘口径 | 下轮应从日报模板中抽取周贡献、规则偏离和下周计划 |

机会研究的候选池自动化写入 `opportunity_candidate_pool`：每日从持仓、已有候选池和 3.5 资产路径种子池出发，映射到黄仁勋五层蛋糕分组，按行情强度/相对强弱打分；每个主题路径与层级允许当前 Top 3 进入 `stock.analysis` 深研和 `opportunity_cases`，失去 Top 3 或强度不足的标的写入 `remove`，非 Top 3 但仍值得跟踪的标的写入 `watch`。该机制用于“半人马座交易”的动态筛选：AI 负责解释和批判，强弱排名、移入/移除和入账由确定性规则计算。

日终持仓行动简报在市场/板块快照缺失时必须显式降级：展示 `source / as_of / freshness / actionability / degrade_reason`，并把“整体市场数据缺口”列为明日观察项，避免用户把持仓清单误读为市场判断。一旦 `sector_daily_snapshots` 有最新数据，模板自动展示市场走向、强势板块和弱势风险板块。

日终简报生成前必须先刷新市场快照：按市场拉取大盘和行业 ETF 代理标的，优先使用 Longbridge，只读失败时回退系统默认行情路由；将涨跌幅、相对大盘强弱、代表标的和 freshness 写入 `sector_daily_snapshots`，再由简报读取聚合后的市场走向与强势板块。该链路只用于日终机会/风险观察，不把行情代理结论升级为交易建议。

日终简报正文必须先以本地持仓库为事实源：读取 `positions`、`trades`、`option_positions`、`option_trades` 后，再对当前持仓标的一次性批量查行情，计算市值、浮盈亏、盈亏比例、集中度和当日强弱。没有当日交易时明确写“今日无操作/未读取到交易记录”；数据质量正常时不单独占用版面，只在行情缺失、市场快照失败、可行动性降级等异常情况下提示。

## 任务定义

### p0-health-heartbeat

目标：证明系统不是“容器还活着但业务链路已停”。

检查项：

1. Hermes gateway cron ticker 状态。
2. data-service `/health` 和关键内部健康项。
3. webapp `/` 或健康页。
4. Postgres / Redis / MinIO 容器状态。
5. broker connector 最近心跳。
6. 运行中任务是否超过 SLA。

写入：

- `hermes_heartbeat`
- `job_runs` 或后续 Hermes job 表
- 运维告警 outbox

验收：

- 15 分钟内至少 2 条新 heartbeat。
- 人为停止一个服务后，下一轮能标记异常。

### p0-delivery-retry

目标：确保日报、提醒、深研完成消息不会因为一次微信投递失败而丢失。

规则：

1. 只处理 `delivery_outbox.status in ('pending', 'retry_wait')`。
2. 每条消息最多重试 3 次。
3. 重试必须保持原 `content_snapshot_hash`，不能重新生成内容。
4. 超过上限标记 `abandoned`，等待用户主动消息或人工修复。

验收：

- 模拟一次投递失败后，5 分钟内进入重试。
- 重复执行不会重复创建 outbox 记录。

### p0-broker-sync-planner

目标：创建券商只读同步任务，而不是在云端直接访问用户本地券商服务。

规则：

1. 只为 `enabled=true` 且 connector 最近在线的账号创建 sync job。
2. 云端不保存生产券商 token。
3. job 由用户本地 connector 领取，读取本地 OpenD / broker source 后上传脱敏 snapshot。
4. 同一账号、同一 market window 只能有一个待执行同步任务。

验收：

- 每个启用账号在指定窗口有且仅有一个待执行 sync job。
- connector 离线时只记录 freshness 风险，不创建不可执行任务堆积。

### p0-broker-sync-staleness

目标：让分析和推送知道真实持仓数据是否过期。

规则：

1. 持仓、现金、保证金超过 freshness SLA 时标记 stale。
2. 期权相关字段缺失时，Sell Put 输出降级为 `analysis_only` 或 `blocked`。
3. stale 状态持续超过阈值后进入 outbox 告警。

验收：

- 修改一条旧 snapshot 时间后，下一轮能标记 stale。
- stale 状态下不会生成高置信 Sell Put 候选。

### p0-market-watchlist-refresh

目标：刷新 P0 真正会被使用的标的集合，而不是全市场扫。

范围：

1. 当前持仓。
2. 关注清单。
3. 未完成 Sell Put 候选池。
4. 最近 7 天有深研、提醒或复盘任务的标的。

规则：

1. 优先使用主行情源，失败时可 fallback，但必须记录 source 和 freshness。
2. 不因行情刷新失败阻塞入站微信问答；问答侧必须显示数据过期。

验收：

- 刷新后每个标的有 `source_key`、`as_of`、`freshness_seconds`。
- 主源失败时记录 fallback，而不是静默替换。

### p0-price-alert-evaluator

目标：触发用户明确设置过的价格、关注和纪律提醒。

规则：

1. 只评估用户已创建的关注项、提醒条件和规则。
2. 同一条件同一交易日只推送一次，除非用户重新激活。
3. 提醒只能给观察和后续口令，不能变成下单建议。
4. quiet hours 内只记录，不立即推送，除非是用户显式设置的高优先级提醒。

验收：

- 命中关注价时生成一条 outbox。
- 重跑同一轮不会重复推送。

### p0-cn-close-summary

目标：在 A 股/港股交易日收盘后生成微信可读的日终摘要。

内容：

1. 组合变化。
2. 主要风险和仓位变化。
3. 关注清单触发项。
4. 期权风险摘要。
5. 数据源和时点。

规则：

1. 数据 stale 时必须醒目标注。
2. 每个 tenant 每个市场日最多生成一份收盘摘要。
3. 长文保存为 artifact，微信只推摘要。

验收：

- 同一 tenant / market_date 重跑只更新同一份 artifact 或跳过。
- 微信 outbox 包含摘要、来源、后续口令。

### p0-us-close-summary

目标：覆盖美股和美股期权组合的日终风险摘要。

规则：

1. 按美股交易日历判断，不按北京时间工作日粗暴执行。
2. Sell Put 必须展示 DTE、delta、IV、strike 距离和现金/保证金状态。
3. 现金/保证金不可验证时，只输出风险观察，不输出可执行候选。

验收：

- 非美股交易日不生成新摘要。
- 缺少期权链或保证金字段时明确降级。

### p0-weekly-review

目标：维持“投资复盘循环”，把一周内的交易、提醒、规则命中和研究任务压缩成可复盘摘要。

内容：

1. 本周组合变化和主要贡献。
2. 规则命中、override 和纪律偏离。
3. 清仓 / assignment / Sell Put 复盘候选。
4. 未完成任务和下周关注。
5. 可沉淀为 memory candidate 的经验，但不直接写成金融事实。

验收：

- 每周每 tenant 最多一份周报 artifact。
- 微信推送只含摘要和后续口令。

### p0-backup-verify

目标：避免“服务可用但数据不可恢复”。

检查项：

1. Postgres 最近备份时间和大小。
2. artifact registry 与对象存储引用一致性。
3. 关键表行数异常变化。
4. 最近 24 小时失败任务和 abandoned delivery 数量。

验收：

- 备份缺失时生成运维告警。
- 正常情况下记录成功巡检结果，不打扰用户。

## 暂不进入 P0 自动定时的任务

| 任务 | 暂缓原因 |
| --- | --- |
| 全市场机会扫描 | 成本和噪音高，P0 先限定持仓/关注/候选池 |
| 自动深研批量生成 | 高模型成本，先由用户显式触发或周报中建议 |
| gbrain dream / memory 自动沉淀 | 当前阶段外部记忆存储尚未作为生产依赖 |
| 自动交易草稿生成 | 容易越过 P0 非执行边界，先保留用户显式触发 |
| 全量历史分钟线补拉 | 成本高，先按持仓、关注、回测需要补拉 |

## 部署验收清单

启用定时任务后，至少验证：

1. `hermes cron list` 能看到 P0 任务。
2. `hermes cron status` 显示 gateway 正在托管 cron。
3. `/root/.hermes/cron/output` 有最近执行输出或任务状态。
4. heartbeat 表 15 分钟内更新。
5. outbox 重试任务可人工造数验证。
6. 每日摘要任务在测试 tenant 上可手动 run，生成 artifact 和 outbox。
7. 任一任务重复 run 不产生重复用户推送。
8. 所有用户可见推送都带来源、时间和后续口令。
