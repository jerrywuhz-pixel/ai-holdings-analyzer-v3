# Mac mini 本地部署材料清单

## 1. 必须复制到 Mac mini 的项目文件

- `data-service/`: FastAPI 数据服务、行情源、持仓读模型、Futu/行情适配器。
- `webapp/`: Next.js 前端、登录注册、微信绑定、确认中心、持仓页面。
- `openclaw/`: OpenClaw Gateway、MiniMax 日常对话、图片识别、确认中心、post-confirmation worker、outbox。
- `gbrain/`: Hermes/GBrain runtime、domain tools adapter。
- `supabase/migrations/`: Postgres schema 和迁移 SQL。
- `scripts/`: 本地启动、迁移、验证、OpenClaw/Codex bridge、Futu smoke 脚本。
- `docker-compose.server.yml`: Mac mini Docker 本地化部署主 compose。
- `docker-compose.wechat-bridge.yml`: 微信轮询桥接服务。
- `docker-compose.yml`: 开发 compose，可作本地调试参考。
- `docs/`: 通用部署文档。
- `product-design-v3/`: 产品设计、能力边界、上线检查清单。
- `deploy/macmini-local/`: 本清单、Mac mini env 模板、打包排除规则。

## 2. 不应该复制或不应进入归档的文件

- `.git/`
- `node_modules/`
- `webapp/.next/`
- `.pytest_cache/`
- `__pycache__/`
- `.DS_Store`
- `.env`, `.env.server`, `.env.local`, `.env.production`
- 任何填了真实 API key、数据库密码、微信 token、Codex bridge key 的文件
- Docker volume 数据目录和本地日志目录

## 3. Mac mini 需要单独准备的外部依赖

- Docker Desktop 或兼容 Docker Engine。
- Node.js 20+。
- Python 3.11+。
- `psql` 客户端。
- MiniMax API Key。
- 微信/ClawBot/OpenClaw 账号与通道凭证。
- 如果启用深研：Mac mini 上的 Codex/OpenAI auth profile，以及本机 bridge。
- 如果启用 Futu 管理员侧行情：Futu OpenD、管理员富途账号、只读权限。
- SMTP 凭证，如果注册验证码要发真实邮件。

## 4. 环境变量材料

从 `deploy/macmini-local/env.macmini.example` 复制生成 `.env.server`。

最低可启动：

- `POSTGRES_PASSWORD`
- `AUTH_SESSION_SECRET`
- `LOCAL_AUTH_PASSWORD`
- `MINIMAX_API_KEY`
- `OPENCLAW_SKILL_KEY`

注册链路：

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`

微信链路：

- `WECHAT_CLAWBOT_API_BASE_URL`
- `WECHAT_ILINK_APP_ID`
- `WECHAT_ILINK_CLIENT_VERSION`
- `ONBOARDING_CREDENTIAL_ENCRYPTION_KEY`
- `OPENCLAW_DELIVERY_MODE`
- `OPENCLAW_DELIVERY_WEBHOOK_URL`
- `OPENCLAW_DELIVERY_WEBHOOK_SECRET`

深研链路：

- `MODEL_AUTH_MODE=openai_codex`
- `OPENAI_CODEX_AUTH_PROFILE`
- `OPENAI_CODEX_BRIDGE_BASE_URL`
- `OPENAI_CODEX_BRIDGE_API_KEY`
- `HERMES_WORKER_MODE=live`

Futu 管理员行情：

- `FUTU_CONNECTOR_MODE=local_dev_direct`
- `FUTU_CONNECTOR_BASE_URL=http://host.docker.internal:8765`

## 5. 验收检查

基础服务：

```bash
curl -fsS http://127.0.0.1:3000 >/dev/null
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8080/health
```

核心回归：

```bash
python3 -m pytest openclaw/tests/test_confirmation_center.py \
  openclaw/tests/test_image_vision.py \
  openclaw/tests/test_openclaw_gateway_router.py \
  openclaw/tests/test_post_confirmation_worker.py -q
```

前端构建：

```bash
npm --prefix webapp ci
npm --prefix webapp run build
```

微信持仓截图验收：

1. 微信发送持仓截图。
2. OpenClaw 返回待确认持仓导入。
3. 用户回复确认。
4. post-confirmation worker 写入 `position_snapshots`。
5. WebApp 持仓页可看到更新后的持仓。

## 6. 当前已知边界

- 普通用户不做 Futu 账号同步。
- Futu OpenD 仅作为管理员侧系统行情/本地 read-only 数据源。
- MiniMax vision 偶发 5xx/529 已加入重试；如果仍失败，日志会保留 HTTP 状态和错误体摘要。
- Deep research 依赖 Codex/OpenAI bridge，Mac mini 必须先保证本地 auth bridge 可用。
