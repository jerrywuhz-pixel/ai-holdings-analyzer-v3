# AI 持仓系统 3.0 Google Cloud 备选部署 Runbook

> 状态：保留为 Google Cloud 备选 / 历史 Runbook。  
> 当前默认部署路线已切换到阿里云：轻量服务器第一阶段见 `docs/LIGHTWEIGHT_SERVER_DEPLOY.md`，正式生产架构见 `28-aliyun-deployment-plan.md`。  
> 本文只在后续决定使用 Google Cloud Run 时继续适用。

## 0. 当前路线说明

2026-05-20 后的默认路线：

1. P0 测试和演示：阿里云轻量服务器 + Docker Compose + 本地 Postgres/MinIO/Redis。
2. 生产化迁移：阿里云 SAE + RDS PostgreSQL + OSS + Tair/Redis + EventBridge/SchedulerX + SLS/ARMS。
3. Google Cloud Run：仅作为海外部署或备选方案保留。

因此本文中的 `gcloud`、Cloud Run、Cloud Scheduler 和 Cloud Monitoring 阻断项，不再阻塞当前阿里云第一阶段上线。

## 1. 当前环境检查结论

本机已具备：

- Docker
- Bun
- Node.js
- 本地 Supabase 配置值

当前仍缺：

- `gcloud` CLI
- `supabase` CLI（非强制，但建议安装，方便迁移和本地/云端对齐）
- `GCP_PROJECT_ID` / gcloud active account
- 生产 delivery webhook URL 和 HMAC secret
- live model keys：OpenAI / MiniMax
- 生产 artifact 和 historical storage env
- 可信 FX：`FX_RATE_ENDPOINT` 或 `FX_RATES_JSON`
- Sentry DSN
- WebApp 正式域名和 CORS origin

## 2. 生产环境变量准备

从模板创建生产环境文件：

```bash
cp .env.production.example .env.production
```

填入后，至少要保证以下 gate 通过：

| 类别 | 必填项 |
| --- | --- |
| Database | `SUPABASE_URL`、`SUPABASE_ANON_KEY`、`SUPABASE_SERVICE_ROLE_KEY` |
| Delivery | `OPENCLAW_DELIVERY_MODE=webhook`、`OPENCLAW_DELIVERY_WEBHOOK_URL`、`OPENCLAW_DELIVERY_WEBHOOK_SECRET` |
| Model | `GBRAIN_LIVE_MODELS_ENABLED=true`、`OPENAI_API_KEY`、`MINIMAX_API_KEY` |
| Storage | `HERMES_ARTIFACT_STORAGE_BACKEND=supabase`、`HERMES_ARTIFACT_BASE_URI=supabase://hermes-artifacts`、`HISTORICAL_STORAGE_BACKEND=supabase_storage` |
| FX | `FX_RATES_SOURCE=trusted_http_fx`，并配置 `FX_RATE_ENDPOINT` 或 `FX_RATES_JSON` |
| Monitoring | `SENTRY_DSN` |
| Web | `WEBAPP_BASE_URL`、`CORS_ALLOWED_ORIGINS` |

生产 `.env.production` 和 `.env.cloud` 已加入 `.gitignore`，不要提交真实值。

## 3. 本机工具准备

安装 Google Cloud CLI 后执行：

```bash
gcloud auth login
gcloud config set project <project-id>
```

可选安装 Supabase CLI，用于 migration / seed 对齐：

```bash
supabase --version
```

## 4. 部署前置检查

先跑完整 preflight：

```bash
./scripts/deploy-cloud.sh --target preflight
```

成功标准：

- `status=pass`
- `tool_counts.fail=0`
- `readiness_counts.fail=0`

如果只想检查生产 env：

```bash
python3 scripts/production_readiness.py --profile production
```

## 5. 初始化云资源

```bash
./scripts/deploy-cloud.sh --target setup
```

脚本会启用：

- Cloud Run
- Cloud Build
- Secret Manager
- Artifact Registry
- Cloud Scheduler
- Cloud Monitoring
- Cloud Logging

并创建/更新以下 Secret：

- Supabase URL / anon key / service role key
- WeChat app id / secret
- OpenAI key
- MiniMax key
- Tushare token
- OpenClaw delivery webhook URL / secret
- Sentry DSN
- FX rate API key

## 6. 部署服务

部署全部服务：

```bash
./scripts/deploy-cloud.sh --target all
```

或分步部署：

```bash
./scripts/deploy-cloud.sh --target data-service
./scripts/deploy-cloud.sh --target gateway
./scripts/deploy-cloud.sh --target cron
```

## 7. 部署后监控探针

```bash
./scripts/deploy-cloud.sh --target monitor
```

检查范围：

- `openclaw-gateway` Cloud Run Ready
- `data-service` Cloud Run Ready
- Gateway `/health`
- 4 个 P0 Cloud Scheduler job：
  - `daily-market-scan`
  - `daily-profit-taking`
  - `heartbeat-check`
  - `stale-jobs-check`

## 8. 切流前人工确认

切流前至少确认：

1. `production_readiness.py --profile production` 通过。
2. `cloud_deployment_monitor.py` 通过。
3. Supabase migration / seed 已对目标项目执行。
4. Storage bucket 已创建并能写入 artifact / historical market payload。
5. Delivery webhook 接收方能验证 HMAC 签名并返回 2xx。
6. MiniMax / OpenAI quota、限流、失败 fallback 可观测。
7. FX source 的来源和更新时间能在用户输出里保留。
8. Futu 多用户连接仍走用户本地 polling / upload，不让云端访问用户 `localhost`。

## 9. 当前阻断项

本机当前运行 `./scripts/deploy-cloud.sh --target preflight` 的阻断项是：

- 缺少 `gcloud`
- 未配置 GCP project / active auth
- 缺少生产 delivery webhook
- 缺少 live model key 和 gate
- 缺少生产 storage env
- 缺少可信 FX
- 缺少 Sentry
- 缺少 WebApp 正式 URL

这些是部署配置和外部账号准备事项；代码侧生产化能力和本地验证已完成。
