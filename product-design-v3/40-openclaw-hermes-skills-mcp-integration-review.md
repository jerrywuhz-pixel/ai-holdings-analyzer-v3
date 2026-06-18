# OpenClaw / Hermes Skills 与 MCP 集成复核

更新日期：2026-05-27

## 结论

3.0 版本不是缺少 OpenClaw skill 文件，而是运行态此前没有把数据源与参考源 skills 纳入统一注册、健康检查和验收清单，导致看起来像是没有集成。已补齐 OpenClaw 运行态的 skill 自动发现和 `data_sources` 状态输出；同时已补齐 Hermes Domain Tools 首版 HTTP facade 与 gbrain/Hermes 调用 client。

## 当前运行态

| 能力 | 当前状态 | 说明 |
| --- | --- | --- |
| OpenClaw skill 自动发现 | 已补齐 | 启动时扫描 `OPENCLAW_SKILLS_DIR` 下带 `SKILL.md` 的目录并注册到 heartbeat |
| OpenClaw `data_sources` health | 已补齐 | `/health` 暴露 data-service、FTShare、IMA、Futu、Tushare、Longbridge、gbrain MCP 的非敏感状态 |
| FTShare market data skill | 已安装并可识别 | OpenClaw 路径为 `/app/openclaw/skills/ftshare-market-data`，data-service 路径为 `/app/skills/ftshare-market-data` |
| IMA skill | 已安装，待凭证启用 | 本地 preflight 通过；线上未配置 `IMA_OPENAPI_CLIENTID` / `IMA_OPENAPI_APIKEY`，状态应显示 `disabled` |
| Futu 本地连接器 | 已按本地轮询模式配置 | 云端只作为控制面；真实 OpenD 仍在 Mac mini/用户本地侧 |
| Tushare | 已配置 | 用于 A 股与部分基础行情补充 |
| Longbridge | 未配置 | 现阶段不作为 P0 必需源 |
| gbrain MCP | 已运行，但仅覆盖记忆/上下文 | 当前工具集中没有 market/broker/IMA 领域工具 |
| Hermes Domain Tools | 已完成首版 | OpenClaw 暴露 `/api/hermes/domain-tools` 与 `/invoke`，gbrain/Hermes 侧通过 `HermesDomainToolsClient` 调用 |
| Hermes live worker | 已运行 | 日常轻任务走 MiniMax M2.7，深研/长任务走 OpenAI Codex auth 下的 `gpt-5.5` |

## 已补齐的代码契约

1. `openclaw/gateway/skill_registry.py`
   - `discover_openclaw_skills()`：统一扫描 OpenClaw skill 目录。
   - `build_data_source_status()`：生成数据源/参考源/本地连接器/MCP 的状态清单。

2. `openclaw/gateway_app.py`
   - heartbeat 不再硬编码 5 个 skill，而是注册所有已安装 skill。
   - `/health` 增加 `data_sources`，并在缓存为空时回退到本地运行态。

3. `docker-compose.server.yml`
   - OpenClaw 容器显式配置 `OPENCLAW_SKILLS_DIR`、`FTSHARE_MARKET_DATA_SKILL_DIR`、`IMA_SKILL_DIR`、IMA 凭证占位。

4. `scripts/verify-openclaw-foundation.sh`
   - 增加关键 OpenClaw skills 与 `data_sources` 的验收断言。

5. `openclaw/gateway/domain_tools.py`
   - 提供 Hermes 可调用的领域工具 facade：行情、Sell Put、持仓只读、IMA 参考源。

6. `gbrain/src/domain-tools-client.ts`
   - 提供 Hermes/gbrain 侧调用 OpenClaw Domain Tools 的标准 client。

## P0 补齐清单

| 优先级 | 项目 | 状态 | 验收标准 |
| --- | --- | --- | --- |
| P0 | OpenClaw skill 注册与数据源状态 | 已完成 | `/health.gateway.active_skills` 包含 FTShare、IMA、gbrain、持仓、交易输入、期权策略等核心 skills |
| P0 | OpenClaw 数据源 health | 已完成 | `/health.data_sources` 不为空，且能区分 `configured`、`disabled`、`missing` |
| P0 | IMA 凭证启用 | 待配置 | 配置 `IMA_REFERENCE_SOURCE_ENABLED=true`、`IMA_OPENAPI_CLIENTID`、`IMA_OPENAPI_APIKEY` 后，`ima-reference` 状态变为 `configured` |
| P0 | IMAReferenceClient | 待开发 | 支持微信公众号 URL/文章引用的 search、read、source_refs 输出 |
| P0 | 微信 URL 输入接入 IMA | 待开发 | 微信转发 weburl 后能识别、读取、归档并在报告中引用来源 |
| P0 | Hermes 领域工具 facade | 已完成首版 | Hermes 可调用 market quote、batch quote、sell put rank、broker positions read、IMA search/read |
| P0 | gbrain MCP 领域扩展 | 暂不扩展 | 领域数据通过 OpenClaw Domain Tools 暴露，gbrain MCP 继续专注记忆/上下文，避免把交易数据混入长期记忆层 |
| P0 | Futu Mac mini 连接器联调 | 待本地环境 | 云端 `FUTU_CONNECTOR_MODE=user_local_polling`，本地 OpenD/connector 能按用户授权返回只读持仓和期权链 |
| P1 | Longbridge 数据源 | 延后 | 有正式凭证后再启用 |

## 建议的 MCP / Tool 分层

3.0 不建议把所有能力都塞进 gbrain MCP。更清晰的分层如下：

| 层 | 工具能力 | 建议承载 |
| --- | --- | --- |
| 记忆与上下文 | `ensure_source`、`upsert_page`、`search`、`get_page_context` | gbrain MCP |
| 行情与历史数据 | `market.quote`、`market.batch_quote`、`market.history`、`market.freshness_check` | domain-tools MCP 或 data-service HTTP tool facade |
| 期权策略 | `options.chain`、`options.sell_put_rank`、`options.roll_close_assignment` | domain-tools MCP / OpenClaw skill |
| 持仓与券商只读 | `broker.positions_read`、`broker.cash_read`、`portfolio.snapshot` | broker connector + data-service |
| 参考源 | `reference.ima.import_url`、`reference.ima.search`、`reference.ima.read` | OpenClaw IMA skill + Hermes reference tool |
| 交易纪律 | `discipline.evaluate`、`discipline.explain_violation` | application/domain tool |

## Hermes Domain Tools 首版契约

| Tool | 能力 | 底层依赖 | 状态 |
| --- | --- | --- | --- |
| `market.quote` | 单标的行情读取，支持 `source`、`require_fresh`、`max_age_seconds` | data-service `/api/quote/{symbol}` | 已接入 |
| `market.batch_quote` | 多标的行情批量读取 | data-service `/api/quote/batch` | 已接入 |
| `options.sell_put_rank` | Sell Put 标的/期权候选排序；有券商连接时优先走 Futu 分析 | data-service `/api/v3/options/sell-put/analyze-from-futu` 或 `/analyze` | 已接入 |
| `broker.positions_read` | 持仓只读；默认读已落库 portfolio read model，也可读 Futu snapshot | data-service `/api/v3/portfolio/positions` 或 `/api/v3/broker/futu/snapshot` | 已接入 |
| `reference.ima.search` | IMA 知识库/笔记搜索，作为研究参考源 | IMA skill `ima_api.cjs` | 已接入，待凭证启用 |
| `reference.ima.read` | IMA note/media 内容读取，作为研究参考源 | IMA skill `ima_api.cjs` | 已接入，待凭证启用 |

当前刻意没有把交易下单或持仓写入暴露给 Hermes domain tools。Sell Put 只允许输出分析和交易草稿建议，仍走人工确认链路。

## 风险与边界

- IMA 未配置凭证时只能确认 skill 文件和本地 preflight，不能声称线上参考源已可用。
- Futu OpenD 是本地能力，云端只能验证 connector 模式和入口，不能直接读取用户本地 OpenD。
- gbrain 当前 MCP 工具是记忆/上下文工具，不等价于数据源 MCP。
- 完整 foundation 验收脚本目前还会检查用户配额/订阅行，线上已有历史用户数据不完整时会阻断一键验收；这是部署数据修复项，不属于 OpenClaw skill 注册问题。
