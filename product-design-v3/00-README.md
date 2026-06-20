# AI 持仓投资分析系统 3.0 产品设计草案

> 目标：在不改动 2.0 原有文件的前提下，先建立一套可讨论的产品和架构设计草案，用 Environment Engineering 的方式升级多账户、多 agent、股票和期权产品能力。

## 本轮产物

| 文件 | 内容 |
| --- | --- |
| `01-environment-engineering.md` | Environment Engineering 方法论如何落到本系统 |
| `02-agent-framework-selection.md` | OpenClaw、Hermes 与主流 agent 框架选型草案 |
| `03-target-architecture.md` | 3.0 目标架构、多账户隔离、多 agent 拆分 |
| `04-product-modules.md` | 持仓前、中、后功能模块，股票和期权双产品 |
| `05-data-and-broker-integration.md` | 数据质量、行情源、券商生产账号接入设计 |
| `06-cron-and-interaction-reliability.md` | 分账号定时任务、推送可靠性、对话补偿机制 |
| `07-open-questions.md` | 需要与你确认后才能拍板的问题 |
| `08-market-data-sources.md` | 市场分析数据源分层、富途主源、腾讯财经校验源、freshness gate |
| `09-historical-market-data-store.md` | 历史行情存储、每日采集、覆盖检查、回测和复盘数据服务 |
| `10-position-data-model.md` | 股票/ETF 与期权分离的持仓数据模型、核心参数和分析表 |
| `11-domain-tools-layer.md` | Domain Tools 层、子 agent 调用关系、外部能力和工具依赖 |
| `12-openclaw-hermes-agent-runtime.md` | OpenClaw + Hermes 双 agent runtime、handoff、复杂任务和自主优化边界 |
| `13-architecture-hardening.md` | 架构风险、健壮性补强、工具网关、数据质量门和运行治理 |
| `14-growth-and-scale-readiness.md` | 10 万级用户增长准备、队列分片、成本配额和容量指标 |
| `15-environment-orchestrator.md` | Environment Orchestrator、tenant-scoped run contract、模型策略、工具权限、memory gate 和审计 |
| `16-wechat-conversation-experience.md` | 微信 claw 对话体验、交互种类、内容类型、确认流、推送和长任务体验 |
| `17-webapp-product-experience.md` | WebApp 产品体验、信息架构、移动端适配、确认中心、绑定授权和页面级 AI 入口 |
| `18-webapp-site-map-and-prototype.md` | WebApp 登录前/登录后 sitemap、B+C 登录前站点原型、红色主色登录后 Dashboard 原型 |
| `19-webapp-core-pages.md` | WebApp P0 核心页面拆解：持仓工作台、股票/ETF 详情、Sell Put 工作台、确认中心 |
| `20-holdings-feature-task-list.md` | 持仓功能 P0 任务清单、Epic 拆解、验收标准、里程碑和最小可验收版本 |
| `21-options-sellput-strategy-rulebook.md` | Sell Put 期权策略规则说明书：标的适合性、期权链排序、评分模型、默认阈值、市场状态参数、持仓管理 |
| `22-options-advanced-ev-greeks-risk-architecture.md` | 高级期权 EV、波动率曲面、高阶 Greeks、dealer flow 与尾部风险风控架构 |
| `23-deployment-resources-and-storage-context-review.md` | 部署资源清单、服务器/数据库/存储准备、GBrain 与 Hermes 四层存储、上下文管理遗漏 review |
| `24-pre-development-confirmation-checklist.md` | 开发前确认 Checklist：从全部待确认项中归并出 P0 阻塞项、默认项和可延后项 |
| `25-p0-development-parallel-plan.md` | P0 研发计划表：6 个子 agent 并行分工、阶段计划、竖切验收和验证策略 |
| `26-p0-dev-integration-tracker.md` | P0 并行研发跟踪表：主竖切、生产化补齐、验证记录和剩余风险 |
| `27-cloud-deployment-runbook.md` | 云端部署 Runbook：生产 env、preflight、Cloud Run 部署、监控探针和切流前确认 |
| `28-aliyun-deployment-plan.md` | 阿里云部署方案：SAE、RDS PostgreSQL、OSS、Tair/Redis、EventBridge/SchedulerX、SLS/ARMS |
| `29-aliyun-config-and-cost.md` | 阿里云配置与费用建议：P0 内测、省钱版、正式生产版、增长版资源规格和月度预算 |
| `30-cloud-cost-comparison.md` | 阿里云、Google Cloud、Vercel + Supabase 三套部署方案的费用、网络、扩展和适配度对比 |
| `31-v2-to-v3-deployment-upgrade-plan.md` | 2.0 到 3.0 部署升级方案：Mac mini P0 双轨升级、历史数据保留、阿里云生产迁移 |
| `32-fresh-v3-deployment-plan.md` | 3.0 全新部署方案：空库部署、首账号初始化、本地 P0、阿里云生产化和新代码目录复制计划 |
| `33-gbrain-runtime-upgrade-plan.md` | GBrain 3.0 可用化方案：当前能力、上游同步、长期记忆边界、本地/阿里云部署与验收标准 |
| `34-ima-reference-source-integration.md` | IMA 参考资料源集成方案：微信公众号/网页/笔记/知识库作为 OpenClaw 与 Hermes 的研究参考源 |
| `35-implementation-review-2026-05-20.md` | 最新实现 review：阿里云轻量服务器、MiniMax live、OpenAI/Codex bridge、readiness gate、代码审查和 GitHub 同步边界 |
| `36-product-feature-readiness-checklist.md` | 3.0 产品功能 readiness：注册/onboarding、微信绑定、Futu 同步、股票/期权分析和阿里云基础依赖 |
| `37-production-dependency-config-package.md` | 生产依赖配置包：本地 secret 文件、仍需外部提供的域名/云资源/API key/授权清单 |
| `38-webapp-growth-onboarding-design-concepts.md` | WebApp 增长型站点与新用户引导三套高保真方案：首页、核心功能页、会员页、onboarding |
| `39-webapp-prelogin-site-bc-design.md` | 登录前站点定稿方向：以长期资产管家为主，融合 AI 投研任务流，覆盖移动端适配 |
| `40-openclaw-hermes-skills-mcp-integration-review.md` | OpenClaw / Hermes skills 与 MCP 集成 review：技能安装、工具暴露、运行时边界和风险补齐 |
| `41-p0-cron-task-list.md` | P0 定时任务清单：收盘摘要、风险提醒、同步、回放与运维任务 |
| `42-analysis-insight-trading-framework.md` | 分析洞察升级交易框架：结合宏观文章、半人马交易者思想和 Hermes 交易纪律的完整分析/风控/输出契约 |
| `prd/00-README.md` | PRD 索引：持仓核心、数据/券商/对账、交互/确认/Agent 体验 |
| `system-analysis/00-README.md` | 系统分析索引：PRD 完成后的编码前架构分析入口 |
| `system-analysis/04-architecture-integration-and-coding-entry.md` | 三份 PRD 与三份系统分析的架构整合、共享契约、编码任务切分和编码前确认结果 |
| `control-plane/00-README.md` | 8 类控制面契约能力索引：工具契约、agent 能力、确认、风险审查、配额、handoff、回放、降级 |

## 我读取到的 2.0 基础

本草案参考了 Obsidian 2.0 设计目录和当前工程实现。2.0 已经不只是概念稿，仓库中已经有以下落地能力：

| 层 | 已有能力 |
| --- | --- |
| 数据层 | Supabase migrations，包含 `users`、`trade_events`、`position_snapshots`、`symbol_registry`、`job_runs`、`delivery_runs`、`user_sessions`、`task_definitions`、订阅、用量、GBrain memory、止盈计划等表 |
| 数据服务 | FastAPI `data-service`，已包含行情查询、批量查询、股票搜索、代码解析、数据源健康检查、Yahoo/Tushare/AkShare/Longbridge 适配器、缓存、计费接口；3.0 需要新增历史行情存储和回测数据服务 |
| Agent/Gateway | `openclaw` 目录中已有 Gateway Data Middleware、JobManager、DeliveryManager、Webhook 安全、Heartbeat、微信认证/小程序路由、机会猎手和止盈等 skills |
| WebApp | Next.js 页面包括 Dashboard、持仓、交易、周报、任务、计费、设置、管理、止盈计划等 |
| 质量保障 | 已有 tests 覆盖数据源适配器、delivery、job、quota、webhook、profit-taking、Hermes 等方向 |

## 3.0 先行判断

1. **不要把 agent 框架当作唯一架构答案。** 3.0 的核心应该是“账号级运行环境 + 明确工具边界 + 可观测执行轨迹”，框架只是承载这些环境约束的运行时。
2. **OpenClaw 更适合作为交互 Gateway。** 它天然贴近微信 claw 插件、多渠道、账号绑定和多 agent routing，3.0 中负责渠道入口、轻量会话和推送闭环。
3. **Hermes 作为复杂长任务 runtime。** 深度研究、复杂股票/期权分析、复盘归因、memory curator 和受控自主优化交给 Hermes；但持仓事实、券商数据和交易规则仍由 Domain Tools 与数据库治理。
4. **核心金融工作流建议独立成 typed domain orchestrator。** 用数据库、任务表、审计、数据质量评分、账号隔离来约束 agent，而不是把持仓真相源放进某个 agent workspace。
5. **股票和期权需要产品级拆分。** 用户资产总览可以统一，但持仓明细、分析参数、风控规则和策略输出必须按 Equity Product 与 Options Product 分开建模。股票模块关注机会、持仓、止盈止损、复盘；期权模块先聚焦 sell put，强调现金担保、保证金、流动性、IV、assignment 风险和 post-trade 监控。

## 已确认的关键定义

**账号 = 持仓 3.0 系统账号。** 用户通过邮箱、账号 ID 或手机号登录系统；账号绑定微信 clawbot 插件后获得微信消息交互和推送能力。一个账号下可以通过手工录入、买入/卖出消息、券商 skill 直连 API 等多种方式获得资产与交易数据，并支持整合多个券商账户形成统一资产视图。后台写入任何持仓、成交、现金、期权或分析数据时，必须记录数据来源。

为继承当前 `routing.json`，3.0 的技术字段约定为：`tenant_id` 表示持仓系统账号和数据隔离根，继承 `routing.json.tenantId`；`openclaw_account_id` 表示 OpenClaw 微信机器人账号 ID，继承 `routing.json.accountId`。后续文档不再用裸 `account_id` 指代系统账号，避免和现有字段冲突。

## 开发前已确认边界

开发前 gate 已在 `24-pre-development-confirmation-checklist.md` 中完成。核心边界如下：

- OpenClaw 作为微信/渠道入口；Hermes 作为独立 worker 承接深研和长任务；Environment Orchestrator 与 Tool Gateway 在 P0 可先作为 Product API 内部模块实现，但接口边界按独立服务设计。
- 券商数据 P0 只读；富途 OpenD 采用用户本地运行方式；云端不保存生产券商 token，只保存连接状态、脱敏快照和 source lineage。
- Deep Research / Hermes-side 使用 GPT-5.5；OpenClaw-side 日常意图和文本回复使用 MiniMax M2.7；统一经 `model adapter` 接入，失败时使用 fallback 模板。
- Hermes 工具使用和分析输出允许自主优化自动生效；交易执行动作类优化需要人工确认，可按每周一次推送确认清单。
- P0 支持图片 OCR、语音输入/语音口令、ASR 识别和二次确认；完整语音输出和多轮语音体验延后。
- P0 不自动下单，Sell Put 允许生成草稿和待确认对象，但所有 broker tools 均为 read-only。

完整确认记录以 `24-pre-development-confirmation-checklist.md` 的 `0.1 / 0.2 / 0.3` 确认记录为准。

## 当前实现快照（2026-05-20）

3.0 已完成 P0 主竖切和阿里云轻量服务器第一阶段部署验证。当前运行形态是：

- 阿里云轻量服务器 / 宝塔面板 / Docker Compose 单机部署，WebApp、data-service、Postgres/pgvector、Redis、MinIO、GBrain/Hermes、OpenClaw 均在服务器内运行。
- WebApp 已可通过公网 `http://149.129.240.111:3000/login` 进入登录页；域名、HTTPS、真实 SMTP 仍属于下一阶段生产化事项。
- 本阶段使用本地 Postgres、MinIO 和本地登录兜底；正式生产仍推荐迁移到阿里云 RDS PostgreSQL、OSS、Tair/Redis、SLS/ARMS 或等价托管服务。
- MiniMax M2.7 已通过统一 `model adapter` 走 Anthropic-compatible endpoint 进入 live 模式，负责日常文本/意图和轻量解释。
- GPT-5.5 / OpenAI 深研路径已支持 API key 或系统级 `openai-codex` bridge 契约，但当前服务器尚未启用深研 live 授权，因此深研任务仍需要在正式验收前补齐。
- `production_readiness.py` 已区分 `local`、`lightweight`、`production` 三类 profile；当前服务器以 `lightweight` profile 表达第一阶段可验收边界，不能等同于完整生产切流。
- GitHub 同步目标以 `ai-holdings-analyzer-v3-fresh-deploy` 目录为准；当前工作目录不是 Git 仓库。

## 主要外部参考

- Aymen Furter, [Environment Engineering: Platform Engineering for AI Agents](https://aymenfurter.ch/articles/environment-engineering-platform-engineering-for-ai-agents/)
- [OpenClaw GitHub](https://github.com/openclaw/openclaw)
- [OpenClaw agents routing docs](https://github.com/openclaw/openclaw/blob/main/docs/cli/agents.md)
- [Hermes Agent GitHub](https://github.com/NousResearch/hermes-agent)
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Model Context Protocol architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [A2A Protocol GitHub](https://github.com/a2aproject/A2A)
- [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [Google Agent Development Kit](https://adk.dev/)
