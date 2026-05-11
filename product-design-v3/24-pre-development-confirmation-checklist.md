# AI 持仓投资分析系统 3.0 开发前确认 Checklist

> 状态：开发前 gate 已完成  
> 范围：除 `07-open-questions.md` 之外，对 `product-design-v3/`、`prd/`、`system-analysis/`、`control-plane/` 已产出文档中的“待确认/风险与待确认/开放问题”做归并去重。  
> 结论：A 类阻塞项已全部确认；B 类已确认，B-03 采用调整后的超时；C 类已确认全部延后，不阻塞 P0。

---

## 0. 已确认，不再放入阻塞清单

| 编号 | 已确认事项 | 确认值 |
| --- | --- | --- |
| D-01 | 系统账号定义 | `tenant_id` 是 3.0 账号/数据隔离根；微信 bot 是渠道绑定，不是系统账号 |
| D-02 | 新用户注册与 `tenant_id` | 注册后即生成 `tenant_id`，绑定微信 claw bot 后生成/关联渠道绑定 |
| D-03 | WebApp 认证 | 沿用 Supabase |
| D-04 | WebApp 全局聊天入口 | 不需要全局聊天入口，只做页面级 AI/任务入口 |
| D-05 | P0 付费/配额 UI | 不进 P0，只保留内部成本/配额字段 |
| D-06 | 首期多个 `portfolio_view` | 支持 |
| D-07 | 用户手动触发富途实时同步 | 允许 |
| D-08 | Futu OpenD 部署方式 | 本地安装连接 |
| D-09 | Futu 权限范围 | `read_only` |
| D-10 | MiniMax M2.7 接入 | 通过统一 `model adapter`；MiniMax CLI 可作为接入实现 |
| D-11 | confirmation TTL | 高风险 30 分钟，低风险 24 小时 |
| D-12 | Sell Put 草稿 | 允许生成草稿，不自动下单 |
| D-13 | 微信绑定/券商授权/账号切换 | 在 WebApp 和管理后台完成，不通过微信渠道交互 |
| D-14 | 股票和期权产品边界 | 股票/ETF 与期权作为不同交易品种分开建模和分析 |
| D-15 | 美港股主源 | 富途优先；腾讯财经作为稳定行情补充/校验源 |

---

## 0.1 A 类确认记录

| 编号 | 确认状态 | 确认值 |
| --- | --- | --- |
| A-01 | 已确认 | Hermes 独立 worker；EO 与 Tool Gateway P0 可在 Product API 内部模块化实现，但接口边界按独立服务设计 |
| A-02 | 已确认，覆盖推荐默认 | 工具使用、分析输出允许自主优化自动生效；交易执行动作类需要人工确认；可按每周一次频次推送交易执行相关优化确认清单 |
| A-03 | 已确认 | OpenClaw-side 日常意图/文本使用 MiniMax M2.7；Hermes-side 深研/长任务使用 GPT-5.5；高风险输出走规则/风控复核 |
| A-04 | 已确认 | 统一 model adapter 内置 fallback 模板；业务层不直接依赖 MiniMax SDK/CLI |
| A-05 | 已确认 | P0 使用 Supabase Storage；本地研发用 MinIO；路径和 metadata 按第 23 号文档执行 |
| A-06 | 已确认，补充表述 | 接受用户本地运行 Futu OpenD；生产使用 tenant-scoped local connector 主动领取任务并上报脱敏 snapshot，云端不直接连接用户 OpenD |
| A-07 | 已确认 | P0 不保存生产券商 token；云端只保存连接状态、脱敏快照和 source lineage |
| A-08 | 已确认 | P0 先按已有富途账号实际权限实现；同步频率配置化；期权链字段缺失时阻断 Sell Put 交易级建议 |
| A-09 | 已确认 | P0 维持腾讯财经为 L3 补充/校验源，不作为交易级主事实；商用授权/SLA 未确认前不升级 |
| A-10 | 已确认 | 云端对象存储优先；P0 先保存持仓、关注清单、Sell Put 候选池相关标的，暂不做全市场分钟线 |
| A-11 | 已确认 | P0 保存持仓相关、关注标的、Sell Put 候选池快照；全市场 OPRA 级历史放 P1/P2 付费源 |
| A-12 | 已确认 | P0 做轻量指标/规则回测，不做完整撮合、滑点、手续费、保证金仿真 |
| A-13 | 已确认 | P0 A 股只做正股/ETF，不做 A 股期权 |
| A-14 | 已确认 | P0 只支持 single-leg cash-secured Sell Put；covered call/spread 仅保留数据/导航扩展点，不做完整 UI |
| A-15 | 已确认 | ETF 首期归入 Equity Product，不单独做 ETF 产品模块 |
| A-16 | 已确认，覆盖推荐默认 | 已连接券商时优先使用券商返回的保证金/现金占用；未连接券商系统时以内置估算器为主，估算数据必须提示“仅供参考”，不应伪装为券商确认口径 |
| A-17 | 已确认 | Dashboard/持仓总览中拆开展示：期权市值、现金担保/保证金占用、可用现金；不混成单一“总资产” |
| A-18 | 已确认 | 默认以用户选择的 `portfolio_view.base_currency` 展示；P0 汇率源走 data-service，记录更新时间和来源 |
| A-19 | 已确认，覆盖推荐默认 | 首期基于第一期同步到的投资标的范围创建默认 `portfolio_view`，覆盖 A 股、港股、美股或期权；用户后续可新增多个 view |
| A-20 | 已确认 | P0 支持通过 `portfolio_view_sources` 做组合分组，例如长期账户、期权现金流账户、观察组合 |
| A-21 | 已确认 | P0 使用 domain service/internal API 作为事实写入口；agent 侧通过受控 tool adapter/MCP facade 调用；禁止 agent 直接写核心表 |
| A-22 | 已确认 | 只允许 Domain Service/Confirmation commit 写事实；agent/Hermes 只能写 proposal、artifact、pending confirmation |
| A-23 | 已确认 | P0 所有 broker tools 只读；contract/代码中不暴露 `place_order`、`modify_order`、`cancel_order` |
| A-24 | 已确认，覆盖推荐默认 | P0 支持图片 OCR 和语音输入：图片走 OCR/Vision 候选识别 + 确认中心；语音走 ASR/语音口令识别 + 二次确认；低置信结果不得直接写入 |
| A-25 | 已确认，覆盖推荐默认 | 微信 claw 不支持按钮/卡片；P0 确认流使用文本口令、语音口令和 WebApp 深链 |
| A-26 | 已确认 | 微信只推摘要、关键风险、WebApp 链接；完整报告在 WebApp/artifact 页面查看 |
| A-27 | 已确认 | WebApp 消息中心与微信推送共用 `delivery/outbox/message_events` 事实源；微信与 WebApp 只是不同 channel view |
| A-28 | 已确认 | P0 至少支持：交易录入、OCR 修正、语音识别修正、规则变更、Sell Put 草稿、broker 冲突、portfolio view 高影响变更 |
| A-29 | 已确认 | 普通 `portfolio_view` 展示变更只审计；影响资产口径/资金口径/source inclusion 的变更走轻量确认 |
| A-30 | 已确认 | Sell Put 所有默认阈值配置化，不在页面硬编码；P0 使用第 21 号文档默认值作为系统初始规则 |
| A-31 | 已确认 | Sell Put 行情/期权链 freshness 要求 30-60 秒内；现金/保证金以最近成功 broker snapshot 为准；超时降级为观察分析 |
| A-32 | 已确认 | P0 默认保守：L2 及以下不输出交易草稿，只输出 `analysis_only`；用户保守模式放 P1 配置 |
| A-33 | 已确认 | WebApp 展示降级 badge，并与微信模板一致展示数据源、新鲜度、降级原因和不能行动的原因 |
| A-34 | 已确认 | P0 支持账户级 quiet hours 和基础频控；不按付费等级区分 |
| A-35 | 已确认 | Hermes artifact 使用 DB metadata + Object Storage；P0 默认保留 90 天，可按 artifact type 调整 |
| A-36 | 已确认，与 A-24 对齐 | P0 图片和语音原始文件默认保留 30 天；OCR/ASR 结构化结果按业务记录保留 |
| A-37 | 已确认 | GBrain 长期记忆 P0 至少提供后台/内部管理；用户侧管理页可 P1，但 schema 需要支持删除/禁用 |
| A-38 | 已确认 | P0 做内部 Ops 最小页面：任务、推送失败、broker sync、人工 replay；不做完整运营平台 |
| A-39 | 已确认 | Tool Contract Registry P0 使用“工具族 + method”，高风险方法单独拆分，例如 `broker.position.read` 与 `broker.order.*` 永不合并 |
| A-40 | 已确认 | P0 由产品/工程/风控共同确认高风险 contract；低风险 schema/timeout 变更可工程审批 |
| A-41 | 已确认 | deprecated contract 兼容窗口 P0 默认 30 天；Hermes 长任务和 replay 保留旧 contract schema 引用 |
| A-42 | 已确认 | 新 contract 先 registry shadow，再 capability matrix 灰度，最后激活 |

---

## 0.2 B 类确认记录

| 编号 | 确认状态 | 确认值 |
| --- | --- | --- |
| B-01 | 已确认 | 用户可在微信里主动查看 Hermes 长任务简短进度；完整进度在 WebApp |
| B-02 | 已确认 | P0 在报告/详情页展示“数据来源与新鲜度”，不展示完整 run contract |
| B-03 | 已确认，覆盖推荐默认 | Hermes job 默认超时：轻任务 5 分钟，深研 30 分钟；超时进入可恢复排队/失败补偿 |
| B-04 | 已确认 | Dashboard “今日行动”优先级：待确认/冲突 > 高风险到期 > Sell Put 到期 > 异动提醒 > 普通摘要 |
| B-05 | 已确认 | 移动端持仓页保留摘要 + 核心筛选，下钻页提供完整字段 |
| B-06 | 已确认 | Position timeline 中事实事件、分析事件、系统事件分组展示，视觉上区分 |
| B-07 | 已确认 | 止盈/止损草稿与 Sell Put 草稿分开定义：`equity_exit_plan_draft` 与 `sell_put_trade_draft` |
| B-08 | 已确认 | 长任务阶段使用平台级词表：`queued`、`collecting`、`analyzing`、`reviewing`、`ready`、`failed` |
| B-09 | 已确认 | Intent Router P0 规则 + 小分类器优先；模型只做低风险补充分流 |
| B-10 | 已确认 | Registry P0 以配置文件/DB seed 驱动；Ops UI 只读或最小编辑 |
| B-11 | 已确认 | `tenant_override` P0 只允许 rollout/feature flag 级 override，不允许绕过 runtime_scope 和高风险审批 |
| B-12 | 已确认 | `Portfolio Agent` 允许创建待确认交易/调整草稿，但不得绕过 Options/Equity 专属策略检查 |
| B-13 | 已确认 | Broker Sync 不作为用户可见 agent 暴露，只展示同步状态和异常解释 |
| B-14 | 已确认 | Quick Portfolio 单独埋点使用量和误路由率，但不作为独立 role |
| B-15 | 已确认 | Ops Agent 不计入 8 个用户可见 role，归为后台系统角色 |

---

## 0.3 C 类确认记录

| 编号 | 确认状态 | P0 处理 |
| --- | --- | --- |
| C-01 | 已确认延后 | P0 保持可迁移架构和指标，不做重型分片实现 |
| C-02 | 已确认延后 | P0 不实现顾问/机构账号，只预留 tenant/account/profile 字段扩展 |
| C-03 | 已确认延后 | P0 只保留内部 cost/quota 字段，不按付费等级影响 deep research、broker sync 或 SLA |
| C-04 | 已确认延后 | P0 默认一个系统账号绑定一个主 bot；多个 bot/多账号切换放 P1 |
| C-05 | 已确认延后 | 钉钉/飞书仅保留 channel abstraction，不实现 |
| C-06 | 已确认延后 | P0 支持语音输入/语音口令、ASR 识别和二次确认；完整语音输出和多轮语音体验放 P1 |
| C-07 | 已确认延后 | 复杂 CSV/对账单/文件导入放 P2；P0 保留确认中心对象类型 |
| C-08 | 已确认延后 | 全市场 OPRA 级期权历史放 P1/P2，依赖付费数据源 |
| C-09 | 已确认延后 | 完整交易策略仿真、滑点、手续费、保证金回测放 P1/P2 |
| C-10 | 已确认延后 | Covered call / spread 完整产品化放 P1/P2 |
| C-11 | 已确认延后 | 用户侧 GBrain 记忆管理完整页面放 P1；P0 先 schema 支持 + 内部管理 |
| C-12 | 已确认延后 | 按付费等级的推送频率控制放 P1；P0 只做基础频控和 quiet hours |
| C-13 | 已确认延后 | Advisor/多账户降级 override 放 P1/P2 |

---

## 1. A 类：进入开发代码前必须确认

这些事项会影响数据库 schema、服务边界、权限模型、数据写入链路或 P0 核心体验。如果不确认，后续返工成本较高。

| 编号 | 确认项 | 推荐默认 | 影响范围 | 来源 |
| --- | --- | --- | --- | --- |
| A-01 | Hermes、Environment Orchestrator、Tool Gateway 的部署边界 | Hermes 独立 worker；EO 与 Tool Gateway P0 可在 Product API 内部模块化实现，但接口边界按独立服务设计 | 服务拓扑、任务队列、run contract、工具审计 | `02`、`12`、`13`、`15` |
| A-02 | Hermes 自主优化是否允许自动生效 | P0 只生成 proposal；低风险 prompt/report template 也先人工确认，不自动改金融规则/数据源/策略 | Hermes governance、proposal 表、审批流 | `02`、`12`、`13` |
| A-03 | GPT-5.5 与 MiniMax M2.7 的严格分工 | OpenClaw-side 日常意图/文本使用 MiniMax M2.7；Hermes-side 深研/长任务使用 GPT-5.5；高风险输出走规则/风控复核 | model adapter、run policy、成本控制 | `00`、`12`、`16`、`system-analysis/03` |
| A-04 | MiniMax 失败降级方式 | 统一 model adapter 内置 fallback 模板；业务层不直接依赖 MiniMax SDK/CLI | 对话可靠性、错误补偿 | `02`、`system-analysis/03` |
| A-05 | Object Storage 首选方案 | P0 使用 Supabase Storage；本地研发用 MinIO；路径和 metadata 按第 23 号文档执行 | 历史行情、图片/语音、Hermes artifact、replay evidence | `09`、`23` |
| A-06 | Futu local connector 的产品形态 | 接受用户电脑运行本地 connector/OpenD；生产使用 tenant-scoped local connector 主动领取任务并上报脱敏 snapshot，云端不直接连用户 OpenD；本地开发保留 `local_dev_direct` | 券商同步、安全模型、部署说明 | `05`、`13`、`14`、`23`、`system-analysis/02` |
| A-07 | 券商 token 是否允许云端保存 | P0 不保存生产券商 token；云端只保存连接状态、脱敏快照和 source lineage | Secret 管理、合规、安全边界 | `05`、`13`、`23`、`system-analysis/02` |
| A-08 | Futu 行情/期权链 entitlement 与同步频率 | P0 先按已有富途账号实际权限实现；同步频率配置化；期权链字段缺失时阻断 Sell Put 交易级建议 | data-service、freshness gate、Sell Put | `05`、`08`、`system-analysis/02` |
| A-09 | 腾讯财经的定位与商用边界 | P0 维持 L3 补充/校验源，不作为交易级主事实；商用授权/SLA 未确认前不升级 | market data routing、降级策略 | `08`、`system-analysis/02` |
| A-10 | 历史行情存储优先级 | 云端对象存储优先；P0 先保存持仓、关注清单、Sell Put 候选池相关标的，暂不做全市场分钟线 | storage、historical jobs、回测 | `09` |
| A-11 | 期权链历史保存范围 | P0 保存持仓相关、关注标的、Sell Put 候选池快照；全市场 OPRA 级历史放 P1/P2 付费源 | 期权回测、容量成本 | `09`、`21` |
| A-12 | 回测引擎 P0 深度 | P0 做轻量指标/规则回测，不做完整撮合、滑点、手续费、保证金仿真 | backtest API、UI 范围 | `09`、`22` |
| A-13 | A 股首期交易品种 | P0 A 股只做正股/ETF，不做 A 股期权 | 产品范围、数据适配器 | `05`、`prd/02` |
| A-14 | 期权产品首期范围 | P0 只支持 single-leg cash-secured Sell Put；covered call/spread 仅保留数据/导航扩展点，不做完整 UI | Options module、确认对象、策略规则 | `10`、`prd/01` |
| A-15 | ETF 归属 | ETF 首期归入 Equity Product，不单独做 ETF 产品模块 | schema、页面导航、规则 scope | `10` |
| A-16 | 期权保证金/现金占用口径 | P0 以券商返回为准；内置估算器只做缺失时的观察级辅助，不生成交易级建议 | Sell Put 阻断、资金展示 | `10`、`system-analysis/01` |
| A-17 | 期权空头市值与现金担保展示 | Dashboard/持仓总览中拆开展示：期权市值、现金担保/保证金占用、可用现金；不混成单一“总资产” | WebApp Dashboard、用户理解 | `10`、`prd/01` |
| A-18 | 多币种折算默认货币与汇率源 | 默认以用户选择的 `portfolio_view.base_currency` 展示；P0 汇率源走 data-service，记录更新时间和来源 | 资产总览、对账、收益率 | `system-analysis/01`、`system-analysis/02` |
| A-19 | `portfolio_view` 首期创建方式 | 系统创建默认视图；用户可新增多个 view；view 变更审计，涉及资金口径变更时走轻量确认 | schema、WebApp 首次体验、确认中心 | `prd/01`、`system-analysis/01` |
| A-20 | 多券商账户 + 手工组合的策略分组 | P0 支持通过 `portfolio_view_sources` 做组合分组，例如长期账户、期权现金流账户、观察组合 | portfolio model、source lineage | `05` |
| A-21 | Domain Tools 暴露形式 | P0 使用 domain service/internal API 作为事实写入口；agent 侧通过受控 tool adapter/MCP facade 调用；禁止 agent 直接写核心表 | 工具安全、测试、审计 | `11` |
| A-22 | 哪些工具可写数据库 | 只允许 Domain Service/Confirmation commit 写事实；agent/Hermes 只能写 proposal、artifact、pending confirmation | 权限、RLS、审计 | `11`、`13` |
| A-23 | Broker tools 是否显式禁止 `place_order` | P0 所有 broker tools 只读；contract/代码中不暴露 `place_order`、`modify_order`、`cancel_order` | 安全边界、工具契约 | `11` |
| A-24 | OCR/Vision P0 范围 | P0 支持图片 OCR 的“候选识别 + 确认中心”，不允许低置信结果直接写入；语音放 P1 | 微信输入、Media Tools、确认中心 | `11`、`16`、`prd/03` |
| A-25 | 微信 claw 是否支持按钮/卡片 | 若支持则使用结构化确认卡片；若不支持，P0 使用文本口令 + WebApp 深链兜底 | OpenClaw gateway、Delivery templates | `16`、`system-analysis/03` |
| A-26 | 微信报告展示方式 | 微信只推摘要、关键风险、WebApp 链接；完整报告在 WebApp/artifact 页面查看 | 消息长度、artifact、用户体验 | `16` |
| A-27 | WebApp 消息中心与微信推送是否共用事实源 | 共用 `delivery/outbox/message_events` 事实源；微信与 WebApp 只是不同 channel view | delivery、补偿、跨端一致性 | `prd/03` |
| A-28 | 确认中心对象类型与写入边界 | P0 至少支持：交易录入、OCR 修正、规则变更、Sell Put 草稿、broker 冲突、portfolio view 高影响变更 | ConfirmationTools、状态机、审计 | `prd/03`、`system-analysis/01`、`system-analysis/03` |
| A-29 | `portfolio_view` 变更是否都需要确认 | 普通展示变更只审计；影响资产口径/资金口径/source inclusion 的变更走轻量确认 | portfolio settings、确认中心 | `system-analysis/01` |
| A-30 | Sell Put 默认阈值是否全部配置化 | 所有阈值配置化，不在页面硬编码；P0 使用第 21 号文档默认值作为系统初始规则 | Options scoring、RiskReview | `21`、`system-analysis/01` |
| A-31 | Sell Put freshness SLA | 行情/期权链 30-60 秒内，现金/保证金以最近成功 broker snapshot 为准；超时降级为观察分析 | Sell Put gate、数据页状态 | `system-analysis/01`、`system-analysis/02` |
| A-32 | 降级后的 actionability 策略 | P0 默认保守：L2 及以下不输出交易草稿，只输出 `analysis_only`；用户保守模式放 P1 配置 | DegradationPolicy、RiskReview | `13`、`15`、`control-plane/08` |
| A-33 | WebApp 是否展示降级 badge | 展示，且与微信模板一致：数据源、新鲜度、降级原因、不能行动的原因 | WebApp、微信一致性 | `control-plane/08`、`prd/02` |
| A-34 | 推送 quiet hours 与频率 | P0 支持账户级 quiet hours 和基础频控；不按付费等级区分 | Delivery、Cron、设置页 | `15`、`16` |
| A-35 | Hermes artifact 存储格式与保留周期 | DB metadata + Object Storage；P0 默认 90 天，可按 artifact type 调整 | artifact registry、存储成本 | `23`、`system-analysis/03` |
| A-36 | 微信图片/语音原始文件保留周期 | P0 图片和语音原始文件默认保留 30 天；OCR/ASR 结构化结果按业务记录保留 | media storage、隐私、成本 | `23` |
| A-37 | GBrain 长期记忆是否用户可见/可删除 | P0 至少提供后台/内部管理；用户侧管理页可 P1，但需要 schema 支持删除/禁用 | memory governance、隐私 | `23` |
| A-38 | Replay/Ops 页面是否进入 P0 | P0 做内部 Ops 最小页面：任务、推送失败、broker sync、人工 replay；不做完整运营平台 | 运维、事故恢复 | `14`、`23` |
| A-39 | Tool Contract Registry 粒度 | P0 使用“工具族 + method”，高风险方法单独拆分，例如 `broker.position.read` 与 `broker.order.*` 永不合并 | Tool policy、审计、版本管理 | `control-plane/01` |
| A-40 | Tool contract 评审责任人 | P0 由产品/工程/风控共同确认高风险 contract；低风险 schema/timeout 变更可工程审批 | governance、发布流程 | `control-plane/01` |
| A-41 | deprecated contract 兼容窗口 | P0 默认 30 天；Hermes 长任务和 replay 需要保留旧 contract schema 引用 | replay、长任务恢复 | `control-plane/01` |
| A-42 | Capability Matrix 与 Tool Contract 发布顺序 | 新 contract 先 registry shadow，再 capability matrix 灰度，最后激活 | 控制面发布流程 | `control-plane/02` |

---

## 2. B 类：建议确认，但可接受推荐默认后先编码

这些事项会影响体验、文案、运营或二期扩展。若你同意推荐默认，不需要逐个展开讨论。

| 编号 | 确认项 | 推荐默认 | 来源 |
| --- | --- | --- | --- |
| B-01 | 用户是否可在微信里主动查看 Hermes 长任务进度 | 支持简短查询：“任务到哪了”；完整进度在 WebApp | `12` |
| B-02 | Run Contract 是否对用户展示摘要 | P0 在报告/详情页展示“数据来源与新鲜度”，不展示完整 run contract | `15` |
| B-03 | Hermes job 默认超时和最大预算 | P0：轻任务 5 分钟，深研 30 分钟；超时进入可恢复排队/失败补偿 | `15` |
| B-04 | Dashboard “今日行动”卡片优先级 | 待确认/冲突 > 高风险到期 > Sell Put 到期 > 异动提醒 > 普通摘要 | `system-analysis/01` |
| B-05 | 移动端持仓页筛选能力 | 移动端保留摘要 + 核心筛选，下钻页提供完整字段 | `prd/01` |
| B-06 | Position timeline 展示层级 | 事实事件、分析事件、系统事件分组展示，视觉上区分 | `system-analysis/01` |
| B-07 | 止盈/止损草稿与 Sell Put 草稿的对象类型 | 分开定义：`equity_exit_plan_draft` 与 `sell_put_trade_draft` | `system-analysis/01` |
| B-08 | 长任务阶段名称 | 使用平台级词表：queued、collecting、analyzing、reviewing、ready、failed | `prd/03` |
| B-09 | Intent Router 首期是否允许模型参与 | P0 规则 + 小分类器优先；模型只做低风险补充分流 | `15` |
| B-10 | Registry 与管理界面实现顺序 | P0 配置文件/DB seed 驱动；Ops UI 只读或最小编辑 | `control-plane/01` |
| B-11 | `tenant_override` 粒度 | P0 只允许 rollout/feature flag 级 override，不允许绕过 runtime_scope 和高风险审批 | `control-plane/01`、`control-plane/02` |
| B-12 | `Portfolio Agent` 是否允许到 `trade_draft` | 允许创建待确认交易/调整草稿，但不允许绕过 Options/Equity 专属策略检查 | `control-plane/02` |
| B-13 | Broker Sync 是否作为用户可见 agent | 不作为 agent 暴露，只展示同步状态和异常解释 | `control-plane/02` |
| B-14 | Quick Portfolio 是否单独埋点 | 单独埋点使用量和误路由率，但不作为独立 role | `control-plane/02` |
| B-15 | Ops Agent 是否计入 8 个用户可见 role | 不计入用户可见 role，归为后台系统角色 | `control-plane/02` |

---

## 3. C 类：可延后，不阻塞 P0 编码

| 编号 | 延后项 | P0 处理 |
| --- | --- | --- |
| C-01 | 10 万级是注册账号还是付费活跃账号 | P0 保持可迁移架构和指标，不做重型分片实现 |
| C-02 | 顾问/机构账号，一个 tenant 管多个最终客户 | P0 不实现，只预留 tenant/account/profile 字段扩展 |
| C-03 | 付费等级影响 deep research 次数、broker sync 频率、推送 SLA | P0 只保留内部 cost/quota 字段 |
| C-04 | OpenClaw 一个用户多个 bot、一个 bot 多账号切换 | P0 默认一个系统账号绑定一个主 bot；扩展放 P1 |
| C-05 | 钉钉/飞书绑定 | Channel abstraction 预留，不实现 |
| C-06 | 完整语音输出和多轮语音体验 | P1；P0 支持语音输入/语音口令、ASR 识别和二次确认 |
| C-07 | 复杂 CSV/对账单/文件导入 | P2；P0 保留确认中心对象类型 |
| C-08 | 全市场 OPRA 级期权历史 | P1/P2，依赖付费数据源 |
| C-09 | 完整交易策略仿真、滑点、手续费、保证金回测 | P1/P2 |
| C-10 | Covered call / spread 完整产品化 | P1/P2 |
| C-11 | 用户侧 GBrain 记忆管理完整页面 | P1；P0 先 schema 支持 + 内部管理 |
| C-12 | 按付费等级的推送频率控制 | P1；P0 只做基础频控和 quiet hours |
| C-13 | Advisor/多账户降级 override | P1/P2 |

---

## 4. 开发前 Gate 结论

开发前确认 gate 已完成：

1. A 类 42 项全部确认，其中 A-02、A-16、A-19、A-24、A-25、A-36 按用户确认值覆盖推荐默认。
2. B 类 15 项全部确认，其中 B-03 调整为轻任务 5 分钟、深研 30 分钟。
3. C 类 13 项全部确认延后，不阻塞 P0 编码。

后续进入研发时，以本文件的 `0.1 A 类确认记录`、`0.2 B 类确认记录`、`0.3 C 类确认记录` 为准；原始 A/B/C 清单保留用于追溯。
