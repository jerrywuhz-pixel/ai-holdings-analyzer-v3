# 3.0 生产依赖配置包

更新时间：2026-05-12

## 已生成的本地文件

- `.env.aliyun.local`
- 权限：`0600`
- Git 状态：被 `.gitignore` 的 `.env.*.local` 覆盖，不应提交
- 来源：基于 `.env.aliyun.example` 生成

该文件已经写入本系统可以自行生成的内部 secret：

- `DATA_SERVICE_INTERNAL_TOKEN`
- `ONBOARDING_CREDENTIAL_ENCRYPTION_KEY`
- `OPENCLAW_DELIVERY_WEBHOOK_SECRET`
- `OPENCLAW_CRON_SECRET`
- `OPENCLAW_SKILL_KEY`
- `FUTU_CONNECTOR_PAIRING_TOKEN`

这些值后续应同步写入阿里云 KMS Secrets Manager / SAE 环境变量。不要把 `.env.aliyun.local` 提交到版本库，也不要把 secret 明文放入产品文档。

## 当前门禁结果

命令：

```bash
TMPDIR="$PWD/.tmp" PYTHONPATH=. .venv/bin/python scripts/product_feature_readiness.py --profile production --env-file .env.aliyun.local
TMPDIR="$PWD/.tmp" PYTHONPATH=. .venv/bin/python scripts/aliyun_preflight.py --profile production --env-file .env.aliyun.local
```

结论：

- Onboarding 初始化依赖已通过。
- Futu connector 内部 pairing token 已通过。
- Data Service internal token 已通过。
- 仍未通过的项目都来自真实域名、云资源、第三方授权或生产观测配置。

## 仍需提供的值

### 域名与备案

- `WEBAPP_BASE_URL`
- `CORS_ALLOWED_ORIGINS`
- `NEXT_PUBLIC_DATA_SERVICE_URL`
- `DATA_SERVICE_URL`
- `OPENCLAW_DELIVERY_WEBHOOK_URL`
- `FUTU_CONNECTOR_POLL_ENDPOINT`
- `FUTU_CONNECTOR_UPLOAD_ENDPOINT`
- `ICP_BEIAN_NUMBER`

当前 `.env.aliyun.local` 里的 `app.example.cn`、`api.example.cn`、`fx.example.cn` 已被 readiness 识别为占位符，不能作为生产通过条件。

### 阿里云控制台

- 本机 `aliyun configure` 或 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET`
- `ALIYUN_ACCOUNT_ID`
- `ALIYUN_SAE_NAMESPACE_ID`
- `ALIYUN_SAE_WEBAPP_APP_ID`
- `ALIYUN_SAE_GATEWAY_APP_ID`
- `ALIYUN_SAE_DATA_SERVICE_APP_ID`
- `ALIYUN_RDS_INSTANCE_ID`
- `ALIYUN_REDIS_INSTANCE_ID`

已具备默认值或已填模板值：

- `ALIYUN_REGION=cn-shanghai`
- `ALIYUN_ACR_REGISTRY=registry.cn-shanghai.aliyuncs.com`
- `ALIYUN_ACR_NAMESPACE=ai-holdings`
- `ALIYUN_OSS_BUCKET_ARTIFACTS`
- `ALIYUN_OSS_BUCKET_MARKET_DATA`
- `ALIYUN_EVENTBRIDGE_BUS`

### Supabase/Auth 边界

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_JWT_SECRET`
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

说明：当前代码仍使用 Supabase-compatible Auth/REST 作为认证边界。若生产最终迁到阿里云 RDS，也需要保留等价的 Auth/REST 配置，直到这些调用点完成替换。

### 微信 / ClawBot

- `WECHAT_APP_ID`
- `WECHAT_APP_SECRET`

已具备：

- `WECHAT_CLAWBOT_API_BASE_URL=https://ilinkai.weixin.qq.com`
- `OPENCLAW_DELIVERY_MODE=webhook`
- `OPENCLAW_DELIVERY_WEBHOOK_SECRET`

### 行情、汇率、模型、监控

- `TUSHARE_TOKEN`
- `FX_RATES_JSON` 或真实 `FX_RATE_ENDPOINT`
- `OPENAI_API_KEY`
- `MINIMAX_API_KEY`
- `SENTRY_DSN`

## 建议处理顺序

1. 先确定生产域名：`app.<domain>` 与 `api.<domain>`，同步完成 ICP 备案。
2. 登录阿里云 CLI：`aliyun configure`，创建或确认 SAE/RDS/Tair/Redis/OSS/EventBridge 资源。
3. 填入 Supabase/Auth 生产边界，跑注册和 tenant bootstrap 烟测。
4. 填入微信 App ID/Secret，跑 `/onboarding/wechat` 真实扫码与绑定码烟测。
5. 填入 Futu poll/upload 真实 API 域名，跑本地 connector poll/upload 到 WebApp 持仓页的端到端烟测。
6. 填入行情、汇率、模型、Sentry，跑 Sell Put、AI artifact 和错误监控烟测。
7. 两个门禁命令都返回 `status=pass` 后，再进入正式切换。
