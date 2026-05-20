# AI 持仓系统 3.0 最新实现 Review（2026-05-20）

> 目的：把原始产品方案、PRD、系统分析和最新代码实现对齐，明确“已实现”“第一阶段可验收”“仍需生产化补齐”的边界。

## 1. 当前结论

3.0 已具备 **阿里云轻量服务器第一阶段运行条件**：WebApp 可公网访问，核心服务通过 Docker Compose 启动，OpenClaw/GBrain 基座验证通过，MiniMax M2.7 已进入 live model 路由。

它还 **不等于完整生产切流**：域名/HTTPS、真实 SMTP、真实微信投递、OpenAI/GPT-5.5 深研授权、可信 FX、生产级对象存储、SLS/ARMS 监控和 SSH 安全治理仍需补齐。

## 2. 最新部署形态

| 层 | 当前实现 | 验收状态 | 说明 |
| --- | --- | --- | --- |
| WebApp | Next.js 容器 | 已跑通 | 公网可打开登录页；用户文案已做去工程化调整 |
| data-service | FastAPI 容器 | 已跑通 | 持仓、行情、历史缓存、Sell Put、对账相关接口保留 P0 能力 |
| Postgres/pgvector | 单机容器 | 已跑通 | 承载 Supabase 兼容 schema、持仓 3.0 P0 表、GBrain 表 |
| Redis | 单机容器 | 已跑通 | P0 用于缓存、锁、队列协调 |
| MinIO | 单机容器 | 已跑通 | P0 承载 market-data、hermes-artifacts、replay-evidence、tenant-media |
| GBrain/Hermes | 容器 + model adapter | 已跑通 | MiniMax live 已接入；OpenAI/Codex deep route 具备契约但未启用 |
| OpenClaw | 容器 | 已跑通 | foundation、套餐/token plan、quota/subscription 初始化通过 |
| Futu OpenD | 用户本地 connector | 设计支持 | 不部署到云端；用户本地 read-only 同步后上传脱敏快照 |

## 3. 模型与 Agent 边界

| 能力 | 当前状态 | 产品边界 |
| --- | --- | --- |
| MiniMax M2.7 | 已 live | 日常文本、意图识别、轻量解释；图片/语音仍通过专用 Media Tools |
| GPT-5.5 / OpenAI API key | 代码已支持，服务器未启用 | 深研、长任务、复杂策略解释 |
| openai-codex bridge | 已有最小契约与测试 | 用系统级共享模型能力，不把网页登录态保存到业务系统 |
| Hermes runtime | 已承接深研/长任务边界 | 写 artifact、memory candidate 和待确认对象，不直接写持仓事实 |
| OpenClaw gateway | 已承接渠道入口 | 微信/后续钉钉飞书入口、确认主路径、投递和失败补偿 |

`system_model_auth_ready=false` 只表示 OpenAI/Codex 深研授权尚未启用，不表示 MiniMax 轻模型不可用。当前健康检查需要同时展示 light route 和 deep route，避免运维误读。

## 4. Readiness Gate 调整

新增 `scripts/production_readiness.py --profile lightweight`：

| Profile | 使用场景 | 允许项 | 必须项 |
| --- | --- | --- | --- |
| `local` | 本机开发 | 多数生产配置缺失只告警 | 基础脚本可运行 |
| `lightweight` | 阿里云单机第一阶段 | 本地登录、log delivery、fallback FX、无 Sentry 可告警 | Web origin、存储、历史缓存、MiniMax live light route |
| `production` | 正式切流 | 不允许关键项缺失 | Supabase/RDS、webhook delivery、OpenAI/Codex deep、MiniMax、可信 FX、监控、正式 URL |

这避免了两个常见误判：

1. 用完整生产 gate 否定第一阶段服务器部署成果。
2. 用第一阶段服务器可用误判为已经可以对外收费生产。

## 5. PRD / 系分对齐结果

| 原始设计要求 | 最新实现状态 | 仍需注意 |
| --- | --- | --- |
| 多账户 / tenant 隔离 | schema、routing、read model 已按 tenant/account 设计 | 大规模用户前需补 RLS/应用层隔离专项审计 |
| 多来源资产 | 手工、消息、OCR、券商快照、Futu connector 契约已落地 | 真实微信消息写入还需接 OpenClaw delivery/confirmation hook |
| 股票和期权分产品 | WebApp 和 read model 已区分股票/ETF 与期权 | 期权高阶 EV/Greeks 仍以规则和架构为主，需实盘数据校验 |
| Sell Put 策略 | 适合性、候选排序、freshness、现金担保、风险阻断已进入 P0 | 允许草稿，不自动下单 |
| 历史行情 | P0 historical store、manifest、file/supabase_storage backend 已实现 | 生产建议迁移到 OSS 或等价对象存储 |
| GBrain 四层存储 | schema、adapter、artifact registry、memory gate 已具备 | 真实长期记忆运营和冷启动导入仍是下一阶段 |
| 微信交互 | 文本/语音/OCR/URL 设计已完成，确认流已收敛 | 当前服务器还未接真实微信 claw bot 投递 |
| 云端部署 | 阿里云轻量服务器第一阶段已跑通 | SAE/RDS/OSS/Tair/SLS/ARMS 是正式生产迁移路径 |

## 6. 代码 Review 摘要

### 阻断级问题

未发现需要立即阻断同步的代码问题。

### 已修复问题

| 问题 | 风险 | 修复 |
| --- | --- | --- |
| `production_readiness.py` 只有 `local/production` 两档，无法表达当前阿里云单机第一阶段 | 文档和验收容易把“生产配置缺失”误判为“服务器部署失败” | 增加 `lightweight` profile，并补单测 |

### 剩余风险

1. OpenAI/Codex deep route 只是契约可用，尚未在阿里云服务器启用真实授权。
2. SSH 连接链路仍需独立排查和加固；当前可用操作路径依赖宝塔面板。
3. SMTP 未完成真实域名邮箱配置，验证码邮件仍不应作为生产用户链路宣称。
4. `production_readiness.py --profile production` 预计仍会失败，这是正确结果，表示正式生产切流前的配置项尚未补齐。

## 7. GitHub 同步边界

当前源码工作目录不是 Git 仓库。GitHub 同步应使用旁边的：

```text
/Users/jerry.wu/Documents/vibecodingapp/ai-holdings-analyzer-v3-fresh-deploy
```

同步前必须排除：

- `.env`
- `.env.server`
- `.env.production`
- `.env.aliyun`
- `node_modules/`
- `.next/`
- `.pytest_cache/`
- `__pycache__/`
- 日志、运行缓存和临时上传文件

## 8. 下一阶段建议

1. 先把 fresh-deploy 仓库同步到 GitHub，作为 3.0 当前代码基线。
2. 补 SSH 安全组/防火墙/密钥登录排查，减少对宝塔终端依赖。
3. 补真实 SMTP 或改为明确的测试验证码链路。
4. 启用 OpenAI API key 或系统级 `openai-codex` bridge，让 GPT-5.5 深研路径通过 smoke。
5. 接真实微信 OpenClaw delivery/confirmation hook。
6. 把 MinIO/file backend 迁移到 OSS/RDS/Tair/SLS 生产托管资源。
