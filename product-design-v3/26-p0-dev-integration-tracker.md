# AI 持仓系统 3.0 P0 并行研发跟踪表

> 更新时间：2026-05-10  
> 当前目标：打穿“真实 Futu 同步 -> 持仓 read model -> WebApp 展示 -> Sell Put / 确认 / 验证”主竖切。  
> 当前状态：第四轮生产化补齐 6 条并行线已回收；本机 Supabase migration/seed、P0 required gate、真实 Futu read-only smoke 与 live E2E smoke 均已通过，gate=`READY_FOR_NEXT_STAGE`。

## 生产化推进

| 项目 | 进展 | 验证证据 |
| --- | --- | --- |
| OpenClaw delivery webhook | 已完成 | 真实生产 payload 已接入，使用 `X-OpenClaw-Delivery-Signature: v1=<sha256>` HMAC 签名；`openclaw/tests/test_outbox.py` 已覆盖 |
| 真实 confirmation smoke | 已完成 | `scripts/live_confirmation_smoke.py` 已跑通 confirmation -> pending action committed -> outbox delivered 的本地端到端 smoke；最新 job `a529cc68-3deb-498b-a7c8-ff8e90f792b8` 为 `SUCCESS`，trade event 为 `AAPL qty 1 price 180`，outbox `delivered 2` |
| GBrain live model gate | 已完成 | 新增 `GBRAIN_LIVE_MODELS_ENABLED` live provider gate，支持 OpenAI-compatible OpenAI / MiniMax chat completion；默认仍走安全 stub |
| Artifact / storage | 已完成 | GBrain artifact registry 已补 object storage：`memory` / `file` / `supabase`，registry sink 支持 `postgres` |
| 可信 FX provider | 已完成 | data-service 已支持 `FX_RATES_JSON` 或 `FX_RATE_ENDPOINT`；缺省 fallback 需明确标注为参考值 |
| Historical store | 已完成 | historical store 已增加生产对象存储 backend：`file` / `supabase_storage` |
| Production readiness gate | 已完成 | 新增 `scripts/production_readiness.py`，可检查 `db` / `delivery` / `model` / `storage` / `fx` / `monitoring` / `web` |
| Cloud deploy env/secrets | 已准备 | `scripts/deploy-cloud.sh` 已补 delivery / model / storage / fx / monitoring 相关 env/secrets；云端部署监控配置和 readiness gate 已准备，但尚未写成最终云端已部署完成 |
| Cloud deployment monitor | 已完成 | 新增 `scripts/cloud_deployment_monitor.py`，检查 Cloud Run Ready、Gateway `/health` 与 4 个 P0 Scheduler job |
| Cloud preflight | 已完成 | 新增 `scripts/cloud_preflight.py` 与 `.env.production.example`，部署前统一检查 GCP CLI / 登录项目 / 生产 env gate |

### 剩余风险 / 下一步

1. 云端正式切流前，先用 `scripts/production_readiness.py` 在目标环境复跑一遍，确认 `db` / `delivery` / `model` / `storage` / `fx` / `monitoring` / `web` 全部通过。
2. live model 仍应维持 gate 控制，避免未配置真实 provider 时误走生产路径。
3. delivery webhook 上云后需要补齐告警、重试和签名密钥轮换检查，确认线上 outbox 投递可观测。
4. FX 与对象存储虽然已接入生产形态，但正式对账前仍要继续盯 fallback 告警和数据可用性。
5. `scripts/cloud_deployment_monitor.py` 只证明云端服务状态和调度任务存在，不能替代真实交易日行情/投递成功率监控。
6. 当前本机 `gcloud` 与 `supabase` CLI 未安装，production readiness 仍缺 delivery webhook、live model key、生产 storage、可信 FX、Sentry 和 WebApp URL；属于部署配置待办，不是代码阻断。

## 8 大块进度总览

| 块 | 当前状态 | 本轮结果 | 下一步 |
| --- | --- | --- | --- |
| 账号 / tenant / 数据基础 | P0 可用，release gate 已通过 | schema/seed 覆盖 tenant、asset source、portfolio view、stock/options、confirmation、artifact、tool contract、run/outbox/job/checkpoint；tool binding 补齐到 13/13；本地 Supabase migration/seed 已纳入 full gate | 云端 Supabase 上线前复跑同一套 migration/seed 与 RLS smoke |
| Futu / 券商同步 | P0 可用 | 本机 OpenD + sidecar real/read-only 已同步真实持仓 8 条、现金 1 条、保证金 1 条，`source_quality=broker_verified`；mock smoke 默认不落库；新增 tenant-scoped `user_local_polling` 契约，默认离线、只读 | 多用户生产形态继续走用户本地 connector 主动轮询/上传，不把 OpenD 暴露给云端 |
| 行情 / 历史 / 期权链数据 | P0 可用 | Futu option chain 接口增加空链降级；期权链缺失会返回 partial；历史行情缓存契约已落地 `hit/cache_miss/degraded`，支持 manifest + object stub | 历史 manifest 后续接真实对象存储，优先覆盖持仓/关注/Sell Put 候选池 |
| Portfolio read model / 持仓展示 | P0 可用 | 股票/期权分离，多币种 base currency 估算提示、现金/保证金/期权占用拆分展示；股票/ETF 展示已调整为名称主显示、代码副显示；read model 优先展示 `broker_verified` 快照；兼容 Supabase/Postgres 不固定小数位时间戳 | 正式对账前接入可信实时/日终汇率源 |
| Sell Put 策略 | P0 可用 | freshness、现金担保、已有短 Put、同标的集中度、stressed market 降级约束已接入；Futu/OCC 期权行权价缩放修复 | 继续补高阶 EV/Greeks 的实盘数据校验，不进入自动下单 |
| 微信交互 / 确认 / 投递 | P0 可用 | 文本/语音/OCR 候选进入确认中心；低置信 OCR 强制人工确认；确认后仍受 draft-only / read-only guard 约束；memory SyncQueue 已补 flush/shutdown 生命周期 | confirmation/delivery 真实 hook 接入后，把 live E2E 从可选非严格升级为强制严格 |
| Hermes / GBrain / Memory | P0 可用，生产存储待接入 | `npm test` 标准入口补齐；Minimax M2.7 / GPT-5.5 model adapter 路由、stub 降级、artifact 元数据与 memory write gate 回归通过 | live model provider、artifact registry DB/object storage 持久化仍需生产接入 |
| WebApp / QA / Ops | P0 可用，release gate 已通过 | 用户可见文案继续去工程化；核心页补移动端 card 视图；WebApp build/typecheck 通过；`verify-p0.sh --with-futu-real --with-live-e2e` 全量通过 | `/jobs`、`/positions` 继续做完整用户文案 sweep；接入真实 confirmation/delivery hook 后开启 strict live E2E |

## 最近并行工作线（已回收）

| 线 | Agent | 范围 | 写入边界 | 集成依赖 |
| --- | --- | --- | --- | --- |
| Futu local connector | Jason | tenant-scoped 本地轮询与云端上传契约 | `local_connectors/futu_opend/*`、connector tests、README | Futu OpenD / data-service upload endpoint |
| Historical market cache | Helmholtz | 历史行情 manifest/object store 与 quote history 读取 | `data-service/src/services/historical_store.py`、`data-service/src/routers/quotes.py`、相关测试 | 行情 adapter / object storage |
| Hermes / model / artifact | Erdos | 模型路由、Hermes artifact 元数据、source lineage | `gbrain/src/*`、gbrain tests | model provider env / artifact registry |
| OpenClaw memory lifecycle | Einstein | SyncQueue flush/shutdown 与 gateway lifespan 优雅退出 | `openclaw/gateway/memory/*`、`openclaw/gateway_app.py`、memory tests | OpenClaw app lifecycle |
| WebApp UX / mobile | Nash | 核心页用户文案、移动端 card 视图、API 文案映射 | `webapp/src/*` | Read Model / P0 API |
| QA / live E2E | Codex leader | live E2E 本地探针、verify 脚本、验证文档 | `scripts/e2e_smoke.py`、`scripts/verify-p0.sh`、README | data-service / Futu / WebApp |

## 本轮完成状态

| 线 | 状态 | 验证 |
| --- | --- | --- |
| Futu local connector | 已完成 | user-local polling payload 包含 `tenant_id/connector_instance_id/read_only`；默认离线；local_dev_direct 兼容原本本地 sidecar contract |
| Historical market cache | 已完成 | data-service 全量测试通过；quote history 能明确返回 `hit/cache_miss/degraded`，不伪造完整历史数据 |
| Hermes / model / artifact | 已完成 | `gbrain` typecheck 与 9 个测试通过；轻任务路由 Minimax M2.7，深研/长任务路由 GPT-5.5，provider 缺失时显式 stub 降级 |
| OpenClaw memory lifecycle | 已完成 | memory/openclaw 组合测试 78 passed；SyncQueue 退出时 flush/drain/close，不再留下既有 pending task warning |
| WebApp UX / mobile | 已完成 | WebApp lint/build 通过；核心页移动端卡片化；用户界面未再暴露 P0、broker sync、artifact、run contract 等内部术语 |
| QA / 验证矩阵 | 已完成 | `verify-p0.sh --with-futu-real --with-live-e2e` required 7/7、optional 3/3 通过，gate=`READY_FOR_NEXT_STAGE`；mock smoke 默认 `persisted=false` |

## 第四轮生产化补齐成果

| 线 | 结果 |
| --- | --- |
| Futu 多用户本地连接 | 新增 `user_local_polling` skeleton：每个用户本地 connector 按 `tenant_id + connector_instance_id` 上传，只读、可配 pairing token，默认不连云端。 |
| 历史行情缓存 | 新增 historical store 与 `/api/quote/{symbol}/history`：优先读本地/对象存储缓存，未命中或降级时显式返回状态，供回测和复盘后续接入。 |
| Hermes 运行契约 | 明确 Minimax M2.7 用于日常轻任务，GPT-5.5 用于深研/长任务；artifact 写入携带 model/provider/source_run_id/lineage，不直接写业务事实。 |
| OpenClaw 稳定性 | memory SyncQueue 支持 lazy start、flush、stop consumer、close 后拒写；gateway lifespan 退出时主动关闭 memory middleware。 |
| WebApp 体验 | Dashboard、持仓、Sell Put、数据、确认、设置、处理中心等页面继续去工程化表达，并补齐移动端卡片形态。 |
| QA / E2E | `e2e_smoke.py --mode live` 内建 tenant、Futu dry-run、portfolio、Sell Put 本地探针；confirmation/delivery hook 未接入时可跳过，strict 模式可强制失败。 |

## 第三轮并行补齐成果

| 线 | Agent | 结果 |
| --- | --- | --- |
| Data Foundation | McClintock | tool contract binding 补齐到 13/13；schema 覆盖审计记录写入 `supabase/README-local-setup.md` |
| Data Service / Broker | Singer | Futu option chain local connector 增加默认字段归一化；空链/缺链标记为 `partial`，避免误判为完整数据 |
| OpenClaw Gateway | Boyle | 低置信 OCR 即便像交易指令也进入 `ocr_correction` 确认；route 测试覆盖 tenant/会话继承和用户可懂文案 |
| Hermes / GBrain | Pasteur | 新增标准 `npm test`；context pack ref 去重安全和 memory gate secret/cross-tenant 拒写回归测试通过 |
| WebApp UX | Chandrasekhar | 数据页、确认页、Sell Put、规则、运行状态、设置等页面继续清理内部术语，保持用户能读懂且不丢金融含义 |
| QA / DevOps | Curie | `verify-p0.sh` 增加 WebApp dev/build `.next` 冲突预警；本地 README 增加 8-block QA 覆盖审计 |

## 第二轮并行开发成果

| 线 | Agent | 结果 |
| --- | --- | --- |
| 多币种估值 | Ampere | portfolio read model 新增 `base_currency`、`base_*` 金额、`fx_source`、原币种 cash / position 明细；fallback FX 明确标为估算 |
| WebApp 展示口径 | Bacon | Dashboard / 持仓 / 数据页兼容 `base_*` 与 `fx_source`，用户界面提示“按估算汇率折算，仅供参考” |
| Futu 诊断 | Tesla | `/api/v1/account-diagnostics` 和诊断脚本收敛为脱敏 payload，并提示 security firm / market / acc_id 错配风险 |
| 微信确认闭环 | Pauli | TTL、确认状态机、失败补偿文案、交易 draft-only guard 均补测试 |
| Sell Put 约束 | Galileo | 期权链 freshness、现金担保、已有短 Put、同标的集中度约束已进入评分/阻断逻辑 |
| 验收矩阵 | Cicero | `verify-p0.sh` 区分 required / optional / skipped，并给出最终 gate |

## 集成顺序

1. 先合并 Read Model / API，并验证真实 Futu snapshot 能投影出 overview 和持仓列表。
2. 再合并 WebApp 实数接入，保证 API 不可用时仍能展示缓存/示例视图。
3. 合并 Futu 账户实体诊断，确保用户不会再同步到错误券商实体。
4. 合并 Sell Put 策略增强，接入真实现金、保证金和期权链 freshness。
5. 合并微信媒体/确认增强，确认所有写入仍进入 pending action，不直接改事实。
6. 最后合并 QA 验证矩阵，一次跑完整 required gate，再按需补跑 optional real Futu。

## 当前验收门槛

| 验收项 | 标准 |
| --- | --- |
| Futu real sync | 本地 OpenD read-only，同步返回真实持仓、现金、保证金，且 `source_quality=broker_verified` |
| Portfolio read model | 股票/ETF 与期权分离，现金/保证金独立展示，带来源和更新时间 |
| WebApp | Dashboard、持仓页、数据页能展示真实数据；失败时不崩溃、不暴露内部参数或工程术语 |
| Sell Put | 缺字段、过期、现金不足、市场 stressed 时降级或阻断；不自动下单 |
| 微信确认 | 文本/语音/OCR 候选都需要确认后才写事实；失败文案明确没有改动持仓 |
| QA | 本地一键验证能输出 required / optional / skipped，并给出 `READY_FOR_NEXT_STAGE` / `BLOCKED_REQUIRED_FAILURES` / `INCOMPLETE_REQUIRED_CHECKS` gate |

## 已知风险 / 下一轮注意

1. 当前不是 git 仓库，集成时需要更依赖文件边界和人工检查。
2. WebApp 已对齐 Read Model API 的 `/api/v3/portfolio/overview` 与 `/api/v3/portfolio/positions`，后续新增字段仍以 data-service contract 为准。
3. Futu 账户实体必须作为用户绑定流程的一等配置，不能只依赖 `.env`。
4. Sell Put 不能因为接入真实持仓而跳过 freshness gate 和 confirmation gate。
5. 多币种资产汇总已避免 HKD / USD 原数值简单相加，但 P0 仍使用 fallback FX；正式对账前需要接入可信实时/日终汇率源。
6. 真实 Futu smoke 已在本机 OpenD + sidecar real mode 通过；后续换账号、换机器或变更 `FUTU_SECURITY_FIRM` 后仍需重跑。
7. `--skip-db-migration` 只适合内循环；最终 release gate 以已通过的 `verify-p0.sh --with-futu-real --with-live-e2e` 为准。
8. Mock Futu smoke 默认不写入 Supabase；若需要持久化 mock fixture，必须显式设置 `SMOKE_FUTU_MOCK_PERSIST=true` 或使用独立 smoke tenant。
9. Hermes/GBrain 目前仍以本地 stub/in-memory 为主；生产需要把 model adapter、artifact registry 和四层 memory 存储接到真实 provider/DB/object storage。
10. Live E2E 当前 confirmation/delivery 仍依赖 hook；真实端点接入后应开启 `--strict-live-e2e`，把“跳过”变成阻断。

## 本轮验证记录

- `bash -n scripts/verify-p0.sh scripts/verify-futu-local.sh`：通过。
- `python3 -m pytest scripts/tests/test_e2e_smoke.py -q`：6 passed。
- `python3 scripts/e2e_smoke.py --mode live`：passed 4 / failed 0 / skipped 2，内建 tenant、Futu dry-run、portfolio、Sell Put 探针通过。
- `cd data-service && PYTHONPATH=src:.. python3 -m pytest -q tests`：193 passed。
- `PYTHONPATH=. python3 -m pytest -q openclaw/gateway/memory/tests openclaw/tests scripts/tests/test_openclaw_smoke.py`：78 passed。
- `cd gbrain && bun run test && bun run typecheck`：生产化补齐后 11 passed，typecheck 通过。
- `cd data-service && PYTHONPATH=src:.. python3 -m pytest -q tests/test_portfolio_read_model.py tests/test_historical_store.py tests/test_quotes_router.py`：25 passed。
- `PYTHONPATH=. python3 -m pytest -q openclaw/tests/test_outbox.py openclaw/tests/test_post_confirmation_worker.py openclaw/tests/test_openclaw_gateway_router.py`：21 passed。
- `python3 -m pytest -q scripts/tests`：14 passed。
- `bash -n scripts/verify-p0.sh scripts/verify-futu-local.sh scripts/deploy-cloud.sh scripts/start-local-services.sh scripts/stop-local-services.sh`：通过。
- `docker compose config`：通过；Docker Compose 提示顶层 `version` 字段 obsolete，为非阻断 warning。
- `./scripts/deploy-cloud.sh --target preflight`：可运行；当前环境失败原因是缺少 `gcloud` 与生产 env 值，已输出下一步清单。
- `python3 scripts/live_confirmation_smoke.py`：通过；pending action committed，confirmation consumed，job `a529cc68-3deb-498b-a7c8-ff8e90f792b8` SUCCESS，outbox delivered 2。
- `cd webapp && npm run lint`：通过。
- `cd webapp && npm run build`：通过。
- Browser 验证核心路由 `/`、`/holdings?view=option-income`、`/sell-put`、`/data`、`/confirmations`、`/settings`、`/ops`、`/rules`：无控制台错误；未出现 `P0`、`mock`、`broker sync`、`artifact`、`run contract`、`worker`、`stub`、`tenant` 等内部术语。
- Browser 验证 `http://127.0.0.1:3001/holdings?view=option-income`：港股标的以名称为主显示，代码作为 `HK · 07709` 等副信息展示。
- `./scripts/verify-futu-local.sh --mode real`：通过；最新写入真实快照 `4d42abd4-f332-479c-bb0a-7b5b028b2690`，8 条持仓，股票 6 / 期权 2，现金 1 条、保证金 1 条，`source_quality=broker_verified`。
- `./scripts/verify-p0.sh --with-futu-real --with-live-e2e`：required 7/7 passed，optional 3/3 passed，gate=`READY_FOR_NEXT_STAGE`；真实 Futu path 读到持仓 8 条、现金 1 条、保证金 1 条，live E2E path passed 4 / skipped 2。
