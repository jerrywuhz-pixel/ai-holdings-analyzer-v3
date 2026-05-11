# AI 持仓投资分析系统 3.0 P0 研发计划表

> 状态：P0 主竖切、第一轮生产化补齐、真实 hook / 生产存储 / 云端监控配置均已完成本地代码收口；下一步是目标云环境实际部署与线上观测。  
> 前置条件：`24-pre-development-confirmation-checklist.md` 已完成开发前 gate。  
> 执行方式：已连续按 6 条并行线推进；每条线拥有清晰写入边界，避免互相覆盖。

---

## 1. P0 研发目标

第一轮研发不追求一次性做完整 3.0，而是跑通最小但完整的竖切：

1. `tenant_id` 账号隔离、portfolio view、资产来源、股票/期权持仓分离。
2. Futu 本地 OpenD/read-only 同步链路的 mock/connector 基础能力。
3. 行情/期权链 freshness gate 和 Sell Put 候选草稿。
4. Confirmation Center：交易录入、OCR/ASR 修正、规则变更、Sell Put 草稿、broker 冲突。
5. OpenClaw 微信文本/语音口令 + WebApp 深链，不依赖按钮/卡片。
6. Hermes job、artifact registry、context pack、GBrain memory gate 的最小闭环。
7. WebApp P0 页面：Dashboard、持仓、Sell Put、确认中心、数据/账户、规则/纪律。
8. 内部 Ops 最小页面：任务、推送失败、broker sync、人工 replay。

---

## 2. 6 个子 agent 并行分工

| Agent | 角色 | 写入边界 | 主要任务 | 交付物 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| Agent 1 | Data Foundation | `supabase/migrations/`、`supabase/seed/`、DB type/helper 文件 | 设计并实现 3.0 P0 schema：tenant/account/channel binding、asset sources、portfolio views、stock/options positions、confirmation、artifact registry、tool contract、run contract、outbox、job/checkpoint | migrations、seed、RLS、索引、schema README | 第 24 号确认清单 |
| Agent 2 | Data Service & Broker | `data-service/src/`、`data-service/tests/` | Futu local connector adapter/mock、腾讯财经 L3 adapter 占位、historical manifest/object storage adapter、freshness gate、Sell Put 数据查询接口、内置保证金估算器 | API endpoints、adapter、tests、freshness contract | Agent 1 schema |
| Agent 3 | OpenClaw Gateway & Delivery | `openclaw/gateway/`、`openclaw/skills/` | 微信文本口令、语音口令/ASR 接入边界、WebApp 深链确认、delivery/outbox、失败补偿、quiet hours、OpenClaw routing 与 `tenant_id` 继承 | gateway handlers、delivery templates、skill updates、tests | Agent 1 outbox/confirmation schema |
| Agent 4 | Hermes / Model / Memory | `gbrain/src/`、新增 `hermes/` 或 runtime 模块、model adapter 文件 | model adapter、Hermes job worker、context pack builder、memory write gate、artifact registry 写入、weekly optimization confirmation list | worker、adapter、memory gate、artifact tools、tests | Agent 1 artifact/job schema |
| Agent 5 | WebApp P0 | `webapp/src/`、`webapp/public/` | 红色暗色风格 WebApp：Dashboard、持仓、Sell Put、确认中心、数据/账户、规则/纪律、Ops 最小页；移动端适配 | 页面、组件、API client、loading/error/empty states | Agent 1 schema/API contract，Agent 2/3 endpoints |
| Agent 6 | QA / Integration / DevOps | `docker-compose.yml`、`.env.example`、`scripts/`、CI/test docs | MinIO/Supabase Storage env、worker 启动脚本、集成测试、E2E 场景、lint/typecheck/test、文档收口、风险回归 | compose/env/scripts、test matrix、verification report | 所有 agent 输出 |

---

## 3. 阶段计划

| 阶段 | 当前状态 | 并行方式 | 目标 | 验收标准 |
| --- | --- | --- | --- | --- |
| Phase 0 | 已完成 | 6 agent 并行只读审计 | 各 agent 读取现有代码，产出写入计划和接口依赖 | 每个 agent 给出文件清单、风险点、测试入口 |
| Phase 1 | 已完成 | Agent 1 主线；Agent 2/3/4 准备 adapter；Agent 5 准备页面骨架；Agent 6 准备环境 | DB schema、RLS、基础 contract 先落地 | migrations/seed 已在本地 Supabase release gate 中验证通过 |
| Phase 2 | 已完成 | 6 agent 全并行 | 数据链路、确认链路、Hermes/memory、WebApp 页面同时推进 | Futu mock snapshot -> portfolio read model -> WebApp 展示已跑通 |
| Phase 3 | 已完成 | 集成优先，减少大改 | Sell Put 草稿、确认中心、outbox、artifact、context pack 打通 | Sell Put 候选缺字段会降级/阻断；确认过期/提交/拒绝状态正确 |
| Phase 4 | 已完成 | Agent 6 主导，其他 agent 修复 | 全量验证、回归、文档更新 | `verify-p0.sh --with-futu-real --with-live-e2e` required 7/7、optional 3/3 通过，gate=`READY_FOR_NEXT_STAGE` |
| Phase 5 | 已完成 | 6 条生产化补齐线并行 | 多用户本地连接、历史缓存、模型路由、OpenClaw 优雅退出、WebApp 移动端体验、live E2E 探针 | Futu user-local polling 契约、historical cache、Hermes model/artifact contract、SyncQueue graceful shutdown、核心页移动端与 live smoke 均已落地 |
| Phase 6 | 已完成 | leader + 子 agent 小队并行 | 真实 delivery hook、live model provider、artifact/object storage、可信 FX、历史行情生产对象存储、云端部署监控 | delivery HMAC payload、live confirmation smoke、GBrain live gate、Supabase/file artifact store、trusted FX provider、Supabase historical store、production readiness 和 cloud monitor 均已落地 |

---

## 4. 第一轮竖切验收场景

| 场景 | 预期结果 | 牵头 Agent |
| --- | --- | --- |
| 新 tenant 登录并生成默认 portfolio view | 按第一期同步到的投资标的范围创建默认 view | Agent 1 + Agent 5 |
| Futu mock/read-only snapshot 同步 | 生成 broker snapshot、asset source、stock/options positions、source lineage | Agent 2 |
| Dashboard 展示资产与期权占用 | 期权市值、现金担保/保证金占用、可用现金拆开展示 | Agent 5 |
| Sell Put 候选查询 | 阈值配置化；行情/期权链 30-60 秒 freshness；缺现金/字段时降级观察 | Agent 2 + Agent 5 |
| 未连接券商时保证金估算 | 使用内置估算器，并明确提示“仅供参考” | Agent 2 + Agent 5 |
| 微信文本/语音口令确认 | 不依赖按钮/卡片；生成确认对象和 WebApp 深链 | Agent 3 |
| 图片 OCR / 语音 ASR 修正 | 低置信结果进入确认中心，不直接写入事实 | Agent 3 + Agent 5 |
| Hermes 深研任务 | 轻任务 5 分钟、深研 30 分钟；可查进度；artifact 写对象存储 | Agent 4 |
| Memory write gate | 研究结论不能直接污染长期记忆；规则类写入走确认 | Agent 4 |
| Ops 最小页面 | 可看任务、推送失败、broker sync、人工 replay | Agent 5 + Agent 6 |

---

## 5. 子 agent 启动顺序

确认开工后，建议一次性启动 6 个子 agent，但任务分层：

1. Agent 1 先开 schema，作为其他 agent 的事实源。
2. Agent 2、3、4 同时准备 adapter/worker，但不得直接改 schema。
3. Agent 5 先做页面骨架和 mock client，等 Agent 1/2 contract 稳定后接真实接口。
4. Agent 6 从第一天开始维护 compose/env/test matrix，不等最后才补。

---

## 6. 冲突控制

| 风险 | 控制方式 |
| --- | --- |
| 多 agent 同时改 DB schema | 只有 Agent 1 拥有 migration 写入权；其他 agent 通过 issue/comment 提依赖 |
| WebApp 和 API contract 不一致 | Agent 1 输出 `contract.md` 或 types；Agent 5 只消费该 contract |
| OpenClaw 和 WebApp 确认状态不一致 | Agent 3 与 Agent 5 共用 ConfirmationTools 状态机，不各自实现状态 |
| Hermes 绕过确认中心 | Agent 4 只能写 proposal/artifact/pending confirmation，不能写业务事实 |
| 语音/OCR 低置信误写 | Media 输入默认候选态，必须确认后 commit |
| fallback 数据输出交易级建议 | DegradationPolicy gate 默认保守，L2 及以下只允许 `analysis_only` |

---

## 7. 验证计划

| 验证类型 | 命令/方式 | 负责 |
| --- | --- | --- |
| DB migration smoke | Supabase/Postgres migration + RLS smoke | Agent 1 + Agent 6 |
| data-service tests | `pytest` | Agent 2 + Agent 6 |
| OpenClaw gateway tests | `pytest` / webhook handler tests | Agent 3 + Agent 6 |
| GBrain/Hermes typecheck | `bun run typecheck` / worker smoke | Agent 4 + Agent 6 |
| WebApp lint/build | `npm run lint` / `npm run build` | Agent 5 + Agent 6 |
| E2E smoke | tenant -> broker snapshot -> portfolio -> Sell Put -> confirmation -> delivery | Agent 6 |
| Visual check | desktop/mobile screenshots for Dashboard/Sell Put/Confirmation | Agent 5 + Agent 6 |

---

## 8. 当前研发状态

用户已确认开工，6 条并行研发线已完成多轮收口。当前主线不再是“是否开工”，而是从 P0 可运行竖切转入生产部署准备。

当前状态：

1. Futu 本地 OpenD/read-only 真实同步已跑通，能读取真实持仓、现金和保证金快照。
2. Portfolio read model、WebApp 展示、Sell Put 约束、微信确认、Hermes/GBrain memory gate、QA 脚本均已形成可运行代码。
3. 本机 full gate 已通过 data-service、OpenClaw、GBrain、WebApp、scripts、Supabase migration/seed、Futu mock smoke、真实 Futu read-only smoke 与 live E2E smoke。
4. Mock Futu smoke 默认只验证契约、不落库；Portfolio read model 会优先采用 `broker_verified` 快照，避免较新的估算 fixture 覆盖真实账户视图。
5. tenant-scoped local connector skeleton、historical cache contract、Hermes model/artifact routing、OpenClaw memory graceful shutdown、WebApp 移动端核心页和 live E2E 本地探针已经落地。
6. 真实 confirmation/delivery hook、live model provider、artifact/object storage、可信汇率、历史行情生产对象存储、云端部署监控配置已经落地；后续重点是目标云环境部署、真实 provider 配额/告警、以及交易日长稳观测。
