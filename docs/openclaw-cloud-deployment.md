# ============================================================
# OpenClaw 云端部署方案
# ============================================================
#
# 架构概览:
#   Vercel (WebApp) ← Supabase (DB/Auth) → OpenClaw Gateway (Cloud Run)
#                                                  ├── Data Service (Cloud Run)
#                                                  └── gbrain MCP (Cloud Run sidecar)
#
# 推荐方案: Google Cloud Run
# 备选方案: Railway / Fly.io

# ─── 1. 部署架构 ───────────────────────────────────────────────

## 1.1 组件映射

| 组件           | 运行时       | 部署目标           | 端口   |
|---------------|-------------|-------------------|--------|
| OpenClaw Gateway | Python 3.11 | Cloud Run          | 8080   |
| Data Service     | Python 3.11 | Cloud Run          | 8000   |
| gbrain MCP       | Bun         | Cloud Run (sidecar)| 3000   |
| WebApp           | Next.js     | Vercel             | -      |
| PostgreSQL       | Supabase    | Supabase Cloud     | 5432   |
| Redis            | Upstash     | Upstash Cloud      | 6379   |

## 1.2 网络拓扑

```
                    ┌─────────────────┐
                    │   Vercel CDN    │
                    │  (WebApp/SSR)   │
                    └────────┬────────┘
                             │ HTTPS
                    ┌────────▼────────┐
                    │   Supabase      │
                    │  (DB + Auth)    │
                    └──┬──────────┬───┘
                       │          │
          ┌────────────▼──┐  ┌───▼────────────┐
          │ OpenClaw GW   │  │  Data Service   │
          │ (Cloud Run)   │  │  (Cloud Run)    │
          │ :8080         │  │  :8000          │
          │               │  │                 │
          │ ┌───────────┐ │  │  Adapters:      │
          │ │ gbrain MCP│ │  │  - Yahoo        │
          │ │ (sidecar) │ │  │  - Tushare      │
          │ │ :3000     │ │  │  - AKShare      │
          │ └───────────┘ │  │  - Longbridge   │
          └───────┬───────┘  └────────┬────────┘
                  │                    │
                  └──────┬─────────────┘
                         │ HTTPS
                  ┌──────▼──────┐
                  │   Upstash   │
                  │    Redis    │
                  └─────────────┘
```

## 1.3 为什么选 Cloud Run

1. **按请求计费** — OpenClaw 并非持续高并发，Cloud Run 按请求数计费，空闲时不收费
2. **自动缩放** — 0 → N 实例自动伸缩，Cron 低谷缩至 0 节省成本
3. **内网通信** — 同项目内 Cloud Run 服务间走内网，无需公网暴露
4. **Sidecar** — 支持 gbrain MCP 作为 sidecar 容器同 Pod 部署
5. **最小运维** — 无需管理服务器，专注代码

## 1.4 备选方案对比

| 维度         | Cloud Run      | Railway       | Fly.io        |
|-------------|---------------|---------------|---------------|
| 计费模式     | 按请求+时长    | 按资源+时长    | 按资源+时长    |
| 免费额度     | 200万请求/月   | $5/月试用      | 3 共享 VM     |
| Sidecar     | 原生支持       | 不支持         | 支持 (process)|
| 冷启动       | ~2-5s          | ~1-3s          | ~1-3s         |
| 国内访问     | 需 CDN/代理    | 需 CDN/代理    | 需 CDN/代理   |
| 最小实例     | 可设 1 防冷启  | 可设           | 可设           |
| 运维复杂度   | 低             | 极低           | 中             |

# ─── 2. 部署配置 ───────────────────────────────────────────────

## 2.1 Google Cloud 项目设置

```bash
# 创建 GCP 项目
gcloud projects create ai-holdings-prod --name="AI Holdings Prod"

# 启用 API
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com

# 设置默认区域 (新加坡，靠近 Supabase)
gcloud config set run/region asia-southeast1
```

## 2.2 Secret Manager 配置

```bash
# 创建密钥
echo -n "$SUPABASE_URL" | gcloud secrets create supabase-url --data-file=-
echo -n "$SUPABASE_SERVICE_ROLE_KEY" | gcloud secrets create supabase-service-role-key --data-file=-
echo -n "$WECHAT_APP_SECRET" | gcloud secrets create wechat-app-secret --data-file=-
echo -n "$OPENAI_API_KEY" | gcloud secrets create openai-api-key --data-file=-
echo -n "$TUSHARE_TOKEN" | gcloud secrets create tushare-token --data-file=-
echo -n "$STRIPE_SECRET_KEY" | gcloud secrets create stripe-secret-key --data-file=-

# 授权 Cloud Run 访问
gcloud secrets add-iam-policy-binding supabase-service-role-key \
  --member serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com \
  --role roles/secretmanager.secretAccessor
```

## 2.3 OpenClaw Gateway Cloud Run 部署

```bash
# 构建并推送镜像
gcloud builds submit --tag asia-southeast1-docker.pkg.dev/ai-holdings-prod/openclaw/gateway:2.0.0

# 部署 Cloud Run
gcloud run deploy openclaw-gateway \
  --image asia-southeast1-docker.pkg.dev/ai-holdings-prod/openclaw/gateway:2.0.0 \
  --region asia-southeast1 \
  --platform managed \
  --port 8080 \
  --cpu 1 \
  --memory 512Mi \
  --min-instances 1 \
  --max-instances 10 \
  --set-env-vars "DEPLOYMENT_MODE=cloud" \
  --set-env-vars "OPENCLAW_DEPLOYMENT_MODE=cloud" \
  --set-secrets "SUPABASE_URL=supabase-url:latest" \
  --set-secrets "SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest" \
  --set-secrets "WECHAT_APP_SECRET=wechat-app-secret:latest" \
  --set-secrets "OPENAI_API_KEY=openai-api-key:latest" \
  --allow-unauthenticated
```

## 2.4 Data Service Cloud Run 部署

```bash
gcloud builds submit --tag asia-southeast1-docker.pkg.dev/ai-holdings-prod/openclaw/data-service:2.0.0 \
  --config data-service/cloudbuild.yaml

gcloud run deploy data-service \
  --image asia-southeast1-docker.pkg.dev/ai-holdings-prod/openclaw/data-service:2.0.0 \
  --region asia-southeast1 \
  --platform managed \
  --port 8000 \
  --cpu 1 \
  --memory 512Mi \
  --min-instances 0 \
  --max-instances 5 \
  --set-secrets "SUPABASE_URL=supabase-url:latest" \
  --set-secrets "SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest" \
  --set-secrets "TUSHARE_TOKEN=tushare-token:latest" \
  --no-allow-unauthenticated
```

## 2.5 Cron 定时任务 (Cloud Scheduler)

```bash
# 每日市场扫描 (工作日 15:30 CST = 07:30 UTC)
gcloud scheduler jobs create http daily-market-scan \
  --schedule="30 7 * * 1-5" \
  --uri="https://openclaw-gateway-XXXXX.run.app/api/cron/daily-scan" \
  --http-method=POST \
  --oidc-service-account-email=PROJECT_NUMBER-compute@developer.gserviceaccount.com \
  --oidc-token-audience="https://openclaw-gateway-XXXXX.run.app"

# 心跳检测 (每 5 分钟)
gcloud scheduler jobs create http heartbeat-check \
  --schedule="*/5 * * * *" \
  --uri="https://openclaw-gateway-XXXXX.run.app/api/cron/heartbeat" \
  --http-method=POST \
  --oidc-service-account-email=PROJECT_NUMBER-compute@developer.gserviceaccount.com

# 超时任务检查 (每 10 分钟)
gcloud scheduler jobs create http stale-jobs-check \
  --schedule="*/10 * * * *" \
  --uri="https://openclaw-gateway-XXXXX.run/app/api/cron/stale-jobs" \
  --http-method=POST \
  --oidc-service-account-email=PROJECT_NUMBER-compute@developer.gserviceaccount.com
```

# ─── 3. 成本估算 ───────────────────────────────────────────────

## 3.1 Cloud Run 月度成本 (估算)

| 资源             | 配置          | 月请求量    | 月成本(USD) |
|-----------------|--------------|-----------|------------|
| OpenClaw GW     | 1 vCPU, 512Mi| ~50万      | $15-25     |
| Data Service    | 1 vCPU, 512Mi| ~30万      | $5-10      |
| Cloud Scheduler | 3 个任务      | ~13K       | $0 (免费)   |
| Secret Manager  | 6 个密钥      | -         | $0.60      |
| Artifact Registry| 2 个镜像     | 2 GB      | $0.10      |
| **总计**         |              |           | **$20-35** |

## 3.2 基础设施总成本

| 服务         | 月成本(USD) |
|-------------|------------|
| Supabase Pro| $25        |
| Cloud Run   | $20-35     |
| Upstash Redis| $0 (免费)  |
| Vercel Pro  | $20        |
| Sentry Team | $26        |
| **总计**    | **$91-106**|

# ─── 4. 安全设计 ───────────────────────────────────────────────

## 4.1 网络隔离

- Data Service: `--no-allow-unauthenticated` — 仅 OpenClaw Gateway 内网调用
- OpenClaw Gateway: `--allow-unauthenticated` — 微信小程序需公网访问
- 微信回调端点: 通过 Webhook Security 的 HMAC 签名验证
- 管理端点: JWT 验证 + IP 白名单

## 4.2 密钥管理

- 所有敏感配置存入 Google Secret Manager
- Cloud Run 通过 Service Account 自动拉取密钥
- 代码仓库不含任何密钥

## 4.3 数据库 RLS

- Supabase RLS 策略保证租户数据隔离
- Gateway 使用 GatewayDataMiddleware 强制注入 tenant_id
- Data Service 使用 supabaseAdmin 绕过 RLS (需后续改为租户级访问)

# ─── 5. 监控与告警 ───────────────────────────────────────────────

## 5.1 健康检查

- Cloud Run 内置健康检查 (HTTP /health)
- OpenClaw 心跳上报 → Supabase openclaw_heartbeat 表
- 超过 15 分钟未上报 → 标记为 down → 触发告警

## 5.2 日志

- Cloud Run 自动收集 stdout/stderr → Cloud Logging
- Sentry 异常追踪 (可选)
- 审计日志 → audit_logs 表

## 5.3 告警

- Cloud Monitoring: 错误率 > 1% → 告警
- 心跳失联 → Supabase 函数 → 飞书/企微通知
- 配额超限 → 日志告警
