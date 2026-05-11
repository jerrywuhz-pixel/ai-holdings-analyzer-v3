# AI 持仓系统 3.0 阿里云配置与费用建议

> 说明：这里把“蝶泳”按“费用”理解。价格会随地域、购买方式、活动、用量变化，本文给出架构选型和月度预算区间；正式下单前以阿里云控制台价格计算器为准。

## 1. 推荐结论

P0 推荐采用 **阿里云 SAE + RDS PostgreSQL + OSS + Tair/Redis + EventBridge + SLS/ARMS**。

推荐地域：

- 首选：`华东2（上海）`
- 备选：`华北2（北京）`

理由：

- 阿里云 SAE 在北京/上海有明确的中国内地 SAE CU 计费口径。
- 国内用户访问稳定，适合微信渠道和 WebApp。
- RDS、OSS、Tair、SLS、ARMS、EventBridge 等配套完整。

## 2. P0 推荐配置

### 2.1 计算层 SAE

| 服务 | SAE 应用 | 实例配置 | 最小实例 | 最大实例 | 备注 |
| --- | --- | --- | --- | --- | --- |
| WebApp | `ai-holdings-webapp` | 0.5 vCPU / 1 GB | 1 | 3 | Next.js，公网入口，前面可接 CDN/WAF |
| OpenClaw Gateway | `openclaw-gateway` | 0.5 vCPU / 1 GB | 1 | 3 | 微信入口、确认中心、delivery hook |
| Data Service | `data-service` | 1 vCPU / 2 GB | 1 | 3 | 持仓、行情、Sell Put、历史行情查询 |
| Hermes/GBrain Worker | `gbrain-worker` | 1 vCPU / 2 GB | 0 | 2 | 深研和长任务，P0 按需拉起 |
| Outbox Worker | `outbox-worker` | 0.5 vCPU / 1 GB | 0 或合并 Gateway | 2 | P0 可先与 Gateway 同镜像不同启动命令 |

P0 成本控制建议：

1. `webapp`、`gateway`、`data-service` 保持最小 1 实例。
2. `gbrain-worker` 最小 0，只有深研/长任务时运行。
3. `outbox-worker` 第一阶段可合并进 Gateway 或按定时任务启动，等投递量上来再拆。

### 2.2 数据库

| 组件 | 推荐配置 | 说明 |
| --- | --- | --- |
| RDS PostgreSQL | 2 vCPU / 4 GB，ESSD 100 GB | P0 最小生产规格 |
| 系列 | 内测用基础系列；正式生产用高可用系列 | 正式收费用户建议高可用 |
| 备份 | 自动备份 + PITR | 交易/持仓系统必须保留恢复能力 |
| 网络 | VPC 内网，不开放公网 | SAE 通过 VPC 访问 |

### 2.3 缓存 / 锁 / 限流

| 组件 | 推荐配置 | 说明 |
| --- | --- | --- |
| Tair / Redis | 1 GB 标准版 | outbox rate limit、job lock、短缓存、idempotency |
| 扩容点 | 2-4 GB | 用户数上来后再扩 |

### 2.4 对象存储 OSS

| Bucket | 存储类型 | 初始容量预算 | 用途 |
| --- | --- | --- | --- |
| `ai-holdings-market-data` | 标准存储 | 100-500 GB | 历史行情、期权链快照 |
| `ai-holdings-artifacts` | 标准存储，后续转低频 | 50-100 GB | Hermes 报告、策略 artifact |
| `ai-holdings-replay` | 低频/归档 | 50-100 GB | replay/eval 证据 |
| `ai-holdings-media` | 标准 + 生命周期 | 20-50 GB | 微信图片、OCR/ASR 临时文件 |

生命周期建议：

- media 原始文件：30-90 天转低频或删除。
- replay/eval：90 天后转归档。
- historical market data：热数据保留标准存储，旧数据可转低频。

### 2.5 网络入口

| 组件 | P0 配置 | 说明 |
| --- | --- | --- |
| ALB | 共享一个公网入口 | 路由 WebApp / Gateway |
| WAF | 建议开启基础防护 | 保护微信入口和登录入口 |
| CDN | Web 静态资源和报告下载 | 初期可后置，流量上来后接入 |
| DNS | 阿里云 DNS | `app.example.cn`、`api.example.cn` |

### 2.6 调度与监控

| 能力 | P0 推荐 | 后续升级 |
| --- | --- | --- |
| 定时任务 | EventBridge 定时规则 | SchedulerX 分片调度 |
| 日志 | SLS | 按 tenant/request_id/run_id 查询 |
| APM | ARMS | 接入 FastAPI/Node tracing |
| 指标告警 | CloudMonitor + SLS Alert | outbox、confirmation、FX fallback、broker freshness |
| 密钥 | KMS Secrets Manager | env fallback 只用于本地 |

## 3. 月度费用估算

估算假设：

- 地域：华东2（上海）
- SAE 标准版，默认服务器
- 月运行时长按 30 天 * 24 小时
- 汇率粗略按 1 USD ≈ 7.2 CNY
- 只估云基础设施，不含 MiniMax/OpenAI token、行情付费 API、域名备案、人工运维

### 3.1 SAE 计算费用

阿里云 SAE 标准版默认服务器计费口径：

- CPU：`1 CU / 核*秒`
- 内存：`0.25 CU / GB*秒`
- 北京/上海：`0.000006859 USD / CU`

按这个口径估算：

| 服务 | 配置 | 运行假设 | 月估算 |
| --- | --- | --- | --- |
| WebApp | 0.5 vCPU / 1 GB | 1 实例 24h | ¥90-110 |
| OpenClaw Gateway | 0.5 vCPU / 1 GB | 1 实例 24h | ¥90-110 |
| Data Service | 1 vCPU / 2 GB | 1 实例 24h | ¥180-220 |
| GBrain Worker | 1 vCPU / 2 GB | 20% 运行 | ¥35-50 |
| Outbox Worker | 合并 Gateway | 0 | ¥0 |

SAE 小计：**约 ¥400-500 / 月**  
如果 GBrain Worker 也 24h 常驻，增加约 **¥180-220 / 月**。

### 3.2 基础设施费用区间

| 项目 | P0 内测省钱版 | P0 正式生产推荐 | 备注 |
| --- | ---: | ---: | --- |
| SAE | ¥400-700 | ¥700-1,500 | 取决于 worker 是否常驻、是否双实例 |
| RDS PostgreSQL | ¥150-350 | ¥350-900 | 基础系列 vs 高可用系列，活动价差异很大 |
| Tair / Redis | ¥50-150 | ¥120-300 | 1-2 GB 起步 |
| OSS | ¥30-150 | ¥100-400 | 历史行情容量和公网下载流量决定上限 |
| SLS / ARMS / CloudMonitor | ¥50-200 | ¥200-800 | 日志量、索引、APM 探针决定成本 |
| ALB / WAF / CDN / DNS | ¥50-300 | ¥300-1,000 | WAF 和公网流量是主要变量 |
| KMS Secrets | ¥0-50 | ¥50-150 | 看密钥/API 调用量 |
| EventBridge / SchedulerX | ¥0-100 | ¥100-500 | P0 用 EventBridge 成本较低 |
| ACR | ¥0-50 | ¥0-300 | P0 用基础镜像仓库即可 |

### 3.3 推荐预算

| 阶段 | 适用场景 | 推荐月预算 |
| --- | --- | ---: |
| 内测省钱版 | 1-3 个自用账号，少量真实持仓，低流量 | **¥800-1,500 / 月** |
| P0 正式生产版 | 小规模付费用户，要求稳定、可监控、可恢复 | **¥1,800-3,500 / 月** |
| 增长版 | 1,000-5,000 活跃用户，多账户定时任务 | **¥5,000-12,000 / 月** |
| 10 万级准备 | 多租户分片、队列、读写分离、对象存储/CDN 放量 | **¥30,000+/月**，需单独容量评估 |

我的建议：**第一期按 P0 正式生产版准备，目标预算 ¥2,500/月上下**。  
这能保留 RDS 高可用、WAF、SLS/ARMS 的空间，不至于为了省几百块牺牲交易系统最重要的可恢复性和可观测性。

## 4. 成本不包含项

以下不计入上面的阿里云基础设施预算：

| 项目 | 说明 |
| --- | --- |
| MiniMax / OpenAI | 按 token 或调用量计费，深研任务可能成为最大变量 |
| 富途 OpenD | 用户本地运行，不产生云端资源费 |
| 可信 FX API | 如果使用商业汇率源，需要单独订阅 |
| 行情数据 API | Tushare、Longbridge、腾讯财经代理服务等可能另计 |
| 域名与备案 | 域名年费较低，ICP备案是时间成本 |
| 短信/邮件 | 登录验证、告警、运营通知若使用会单独计费 |

## 5. 三套推荐配置

### 5.1 内测省钱版

适合：只有自己和少量测试用户。

- SAE：WebApp/Gateway/Data Service 各 1 实例；Worker 按需。
- RDS：PostgreSQL 基础系列 2c4g / 100GB。
- Redis：1GB。
- OSS：100GB 标准存储。
- WAF：可先不用，至少开启基础安全组和签名校验。
- 监控：SLS 基础日志 + CloudMonitor。

预算：**¥800-1,500 / 月**。

### 5.2 P0 正式生产推荐版

适合：准备给外部用户使用，且系统会管理真实持仓。

- SAE：Gateway 和 Data Service 支持 max 3，WebApp max 3，Worker max 2。
- RDS：PostgreSQL 高可用 2c4g / 100GB ESSD。
- Redis/Tair：1-2GB。
- OSS：500GB 标准存储包起步，历史行情单独 bucket。
- WAF：开启。
- ALB：统一公网入口。
- SLS/ARMS：开启应用监控、错误告警、业务日志索引。
- EventBridge：cron trigger。
- KMS Secrets：管理所有 API key 和 webhook secret。

预算：**¥1,800-3,500 / 月**。

### 5.3 增长版

适合：账号开始增长，需要提升并发和任务稳定性。

- SAE：Gateway/Data Service 最小 2 实例，Worker 独立扩容。
- RDS：4c8g 或更高，高可用；增加只读实例或数据库代理。
- Redis/Tair：4GB 起步。
- OSS：1TB+，历史行情冷热分层。
- SchedulerX：分 tenant 分片调度。
- SLS/ARMS：完整链路追踪、告警和值班仪表盘。
- CDN：Web 静态资源和 artifact 下载。

预算：**¥5,000-12,000 / 月**。

## 6. 我建议先下单的最小生产清单

| 顺序 | 资源 | 配置 |
| --- | --- | --- |
| 1 | VPC / vSwitch / 安全组 | 同地域双可用区 |
| 2 | RDS PostgreSQL | 高可用 2c4g / ESSD 100GB |
| 3 | OSS | 4 个 bucket，先买 500GB 标准存储包 |
| 4 | Tair/Redis | 1GB |
| 5 | ACR | 基础镜像仓库 |
| 6 | SAE | 4 个应用：webapp / gateway / data-service / worker |
| 7 | KMS Secrets | 模型 key、微信 secret、delivery secret、FX key |
| 8 | SLS/ARMS | 应用日志、错误、核心业务指标 |
| 9 | ALB/WAF/CDN/DNS | 绑定正式域名后开启 |
| 10 | EventBridge | 5 个 P0 cron 规则 |

## 7. 后续工程任务

1. `.env.aliyun.example`
2. `scripts/aliyun_preflight.py`
3. `scripts/deploy-aliyun.sh`
4. `scripts/aliyun_deployment_monitor.py`
5. `oss` artifact/historical backend
6. `production_readiness.py --cloud aliyun`
7. SLS/ARMS 日志字段规范和告警模板

## 8. 参考依据

- SAE 按 CPU/内存/磁盘使用量转 CU 计费，上海/北京 SAE 标准版默认服务器按官方 CU 单价估算。
- OSS 费用由存储、流量、请求、数据处理等组成，可用资源包降低稳定用量成本。
- RDS 支持 PostgreSQL，并提供备份、恢复、监控、读写分离等数据库能力。
- Tair/Redis 支持按量和包年包月，按开通规格计费。
