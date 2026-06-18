# 3.0 产品功能可运行性清单

更新时间：2026-05-12

检查口径：

- 云端部署前提：阿里云大陆 Region + ICP 备案，GCP 仅作为海外/备用路径。
- 产品依赖检查命令：`TMPDIR=$PWD/.tmp PYTHONPATH=. .venv/bin/python scripts/product_feature_readiness.py --profile production --env-file .env`
- 本轮检查结果：`status=fail`，`pass=1`，`fail=7`；失败项已主要收敛为生产 secret、第三方授权、云资源和端到端烟测。
- 阿里云预检命令：`python3 scripts/aliyun_preflight.py --profile production --env-file .env`
- 最新阿里云预检日志：`.logs/aliyun-preflight-20260512-044550.json`

## 总体结论

当前按生产 profile 检查：8 项产品能力中，1 项通过、7 项未达到生产可运行。注册初始化、微信 ClawBot 绑定和 Futu 配对的 WebApp 代码入口已经补齐；未通过项主要是生产环境变量、第三方授权、云资源和真实端到端烟测。

已补齐的代码侧能力：

1. WebApp 支持邮箱注册和登录。
2. 登录/注册后进入 `/onboarding`，按 profile / wechat / broker / review 推进。
3. Onboarding schema 已覆盖 `tenant_settings`、`onboarding_sessions`、`wechat_clawbot_auth_sessions`、`wechat_bot_credentials`、`onboarding_audit_events`。
4. WebApp 注册流程可通过 ClawBot QR/status/getupdates 完成微信二维码授权与绑定码验证。
5. WebApp 可创建用户级 Futu 本地 connector 配对记录。
6. WebApp 持仓、数据、Sell Put、确认中心等核心页面已按当前登录用户 `tenant_id` 读取数据。
7. Data Service 已提供用户本地 Futu connector 的 `/api/v3/connectors/poll` 与 `/api/v3/connectors/upload` 控制面，并补上 Futu sync tenant mismatch 拦截。
8. 阿里云生产 env 模板已补齐 Data Service、ClawBot、onboarding 加密密钥与 Futu connector poll/upload endpoint。
9. 产品功能 readiness 脚本已落地，可反复检查 API key、授权、设置和代码入口。

## 功能清单

| 产品功能 | 代码依赖 | 当前 `.env` / 授权状态 | 当前可运行性 | 下一步行动 |
| --- | --- | --- | --- | --- |
| WebApp 注册 / 登录 / tenant 初始化 | 已可用：`signUp`、`signInWithPassword`、auth sync / tenant bootstrap migration；onboarding 服务会兜底创建 public user 与 tenant account | 当前 `.env` 中 Supabase/Auth 相关 key 已配置 | 可进入烟测 | 在生产 Auth 控制台启用邮箱注册策略、配置回调域名，用真实邮箱验证注册、登录和 onboarding tenant bootstrap |
| 注册后的持仓系统初始化向导 | 已可用：`/onboarding/profile`、`/onboarding/wechat`、`/onboarding/review`、ClawBot QR/status/getupdates 封装、token 加密存储；`/onboarding/broker` 仅保留为系统行情源说明页 | 当前 `.env` 缺 `WECHAT_CLAWBOT_API_BASE_URL`、`ONBOARDING_CREDENTIAL_ENCRYPTION_KEY`、`DATA_SERVICE_INTERNAL_TOKEN` | 代码已可构建，生产不可完整承诺 | 在阿里云 KMS/SAE Secret 配置 ClawBot API base、token 加密 key、Data Service internal token；真实微信扫码和绑定码烟测 |
| WebApp 持仓 / 数据 / Sell Put 实时视图 | 已可用：核心页面登录后用 `user.id` 作为 `tenant_id`，Data Service portfolio endpoint 存在 | 缺 `NEXT_PUBLIC_DATA_SERVICE_URL` 或 `DATA_SERVICE_URL` | 未达到生产可运行 | 在 SAE WebApp/DataService 配置生产 API 域名，并用两个账号验证 tenant 隔离 |
| 绑定微信 Claw 插件 / 消息路由 | 已可用：注册初始化 QR 授权与绑定码验证、`channel_bindings` schema、OpenClaw ingress、设置页手工兜底入口 | 缺 `WECHAT_APP_ID`、`WECHAT_APP_SECRET`、`OPENCLAW_DELIVERY_WEBHOOK_URL`、`OPENCLAW_DELIVERY_WEBHOOK_SECRET`；当前 `OPENCLAW_DELIVERY_MODE=disabled` | 未达到生产可运行 | 配置微信与 OpenClaw webhook secret，走 `/onboarding/wechat` 完成真实 ClawBot 绑定，再跑微信消息到 tenant 解析的端到端烟测 |
| 管理员侧 Futu 系统行情源 | 已可用：Futu quote/option-chain adapter、freshness gate、Sell Put 实时行情策略；历史 user-local connector 控制面仅兼容保留 | 当前 `FUTU_CONNECTOR_MODE=local_mock`；管理员 OpenD 与云端之间的安全连通方式仍需运维配置 | 生产行情源未完整承诺；普通用户个人 Futu 同步已取消 | 配置管理员侧 OpenD/sidecar 作为系统行情源；普通用户持仓通过手工、微信消息、OCR 和确认写入建立 |
| 股票 / 期权查询与 Sell Put 分析 | 已可用：quote/search、Futu option chain、Sell Put analyze endpoints | 缺 `TUSHARE_TOKEN`，缺 `FX_RATES_JSON` 或 `FX_RATE_ENDPOINT` | 部分代码可跑，生产不可完整承诺 | 配置 A/H/US 行情源策略和可信汇率源；Sell Put 必须依赖新鲜期权链与 broker snapshot |
| AI 深度研究 / 分析输出 | 代码入口存在 | 当前 `GBRAIN_LIVE_MODELS_ENABLED=false`；缺 `OPENAI_API_KEY`、`MINIMAX_API_KEY` | 未达到生产可运行 | 在阿里云 KMS/SAE Secret 配置模型 key，启用 live models，跑 Hermes artifact 烟测 |
| 阿里云生产基础设施 / ICP | 预检脚本与模板已可用，CLI 已安装 | 未登录阿里云 CLI；缺 ACR、SAE、RDS、Redis/Tair、OSS、EventBridge、ICP env | 未达到生产可运行 | `aliyun configure` 或 AK/SK；补齐 `.env.aliyun`；完成 ICP 备案和域名解析后再切大陆生产流量 |

## 需要你提供或完成授权的依赖

阿里云与备案：

- `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` 或本机 `aliyun configure`
- `ALIYUN_REGION`
- `ALIYUN_ACCOUNT_ID`
- `ALIYUN_ACR_REGISTRY`
- `ALIYUN_ACR_NAMESPACE`
- `ALIYUN_SAE_NAMESPACE_ID`
- `ALIYUN_SAE_WEBAPP_APP_ID`
- `ALIYUN_SAE_GATEWAY_APP_ID`
- `ALIYUN_SAE_DATA_SERVICE_APP_ID`
- `ALIYUN_RDS_INSTANCE_ID`
- `ALIYUN_REDIS_INSTANCE_ID`
- `ALIYUN_OSS_BUCKET_ARTIFACTS`
- `ALIYUN_OSS_BUCKET_MARKET_DATA`
- `ALIYUN_EVENTBRIDGE_BUS`
- `ICP_BEIAN_NUMBER`

WebApp / API 域名：

- `NEXT_PUBLIC_DATA_SERVICE_URL`
- `DATA_SERVICE_URL`
- `DATA_SERVICE_INTERNAL_TOKEN`
- 生产 `WEBAPP_BASE_URL`
- 生产 `CORS_ALLOWED_ORIGINS`

微信 / Claw / OpenClaw：

- `WECHAT_CLAWBOT_API_BASE_URL=https://ilinkai.weixin.qq.com`
- `ONBOARDING_CREDENTIAL_ENCRYPTION_KEY`
- `WECHAT_APP_ID`
- `WECHAT_APP_SECRET`
- `OPENCLAW_DELIVERY_MODE=webhook`
- `OPENCLAW_DELIVERY_WEBHOOK_URL`
- `OPENCLAW_DELIVERY_WEBHOOK_SECRET`

Futu 用户本地连接器：

- `FUTU_CONNECTOR_MODE=user_local_polling`
- `FUTU_CONNECTOR_POLL_ENDPOINT=https://<api-domain>/api/v3/connectors/poll`
- `FUTU_CONNECTOR_UPLOAD_ENDPOINT=https://<api-domain>/api/v3/connectors/upload`
- `FUTU_CONNECTOR_PAIRING_TOKEN`

行情、汇率和 AI：

- `TUSHARE_TOKEN`
- `FX_RATES_JSON` 或 `FX_RATE_ENDPOINT`
- `OPENAI_API_KEY`
- `MINIMAX_API_KEY`
- `GBRAIN_LIVE_MODELS_ENABLED=true`
- `SENTRY_DSN`

## 升级切换前的验收门槛

1. `scripts/product_feature_readiness.py --profile production --env-file .env.aliyun` 返回 `status=pass`。
2. `scripts/aliyun_preflight.py --profile production --env-file .env.aliyun` 返回 `status=pass`。
3. WebApp 真实注册账号成功，并进入 `/onboarding`。
4. Profile 初始化后生成 `tenant_settings`；onboarding 服务确保 `users` 与 `tenant_accounts` 存在。
5. `/onboarding/wechat` 真实扫码授权 ClawBot，发送绑定码后 `channel_bindings` 写入当前用户 tenant，真实微信消息能解析回该 tenant。
6. `/onboarding/review` 不再要求普通用户创建 Futu connector instance；系统行情源状态由管理员侧运维验证。
7. 股票/期权查询、Sell Put 分析在新鲜系统行情和用户确认持仓下返回可解释结果；过期数据只允许 observation，不允许 actionable 建议。
8. Hermes/gbrain live model 与 artifact 存储烟测通过。
