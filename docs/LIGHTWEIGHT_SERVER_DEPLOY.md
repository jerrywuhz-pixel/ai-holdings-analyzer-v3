# 轻量级服务器第一阶段部署手册

目标：先让 3.0 P0 单机版在轻量级服务器跑起来：WebApp 公网可访问，data-service、Postgres/pgvector、Redis、MinIO、GBrain/Hermes、OpenClaw 在服务器内网运行并健康。

第一阶段仍然不接真实交易、不自动下单；Supabase Cloud、Futu OpenD、真实微信推送、域名和 HTTPS 可以后续再接入。MiniMax M2.7 已支持在第一阶段以 live route 运行；GPT-5.5 / OpenAI 深研 route 需要 OpenAI API key 或系统级 `openai-codex` bridge 后再启用。

当前单机版会先使用本地 Postgres 和 MinIO 保存 P0 schema、GBrain 记忆表、历史行情对象和 Hermes/OpenClaw artifact 占位对象。
如果暂未配置 Supabase Auth，WebApp 会使用本地管理员登录兜底；正式对外使用前应改成 Supabase Auth，并启用域名与 HTTPS。

## 当前已验证状态（2026-05-20）

- 阿里云轻量服务器已能运行 Docker Compose 单机栈，WebApp 公网登录页可访问。
- `verify-foundation-runtime.sh` 与 `verify-openclaw-foundation.sh` 已用于验证 OpenClaw/GBrain 基座。
- MiniMax M2.7 已通过 Anthropic-compatible endpoint 进入 live route。
- OpenAI/GPT-5.5 深研 route 与 `openai-codex` bridge 契约已写入代码和配置模板，但服务器尚未启用真实 deep auth。
- SSH 运维链路仍需单独加固；当前第一阶段可通过宝塔面板完成必要操作。

## 你只需要准备

1. 服务器公网 IP。
2. SSH 登录方式：用户名、端口、密钥或密码。
3. 阿里云安全组放行 TCP `3000`。

推荐服务器规格：`2 核 4G` 起步。`1 核 2G` 可能能跑，但构建镜像时容易慢或内存紧张；如果要长期保留历史行情和 GBrain 内容，建议至少准备 40GB 以上磁盘。

## 我可以替你做的部分

如果你把下面信息给我，我可以直接登录服务器执行：

```text
服务器 IP：
SSH 用户名：
SSH 端口：
登录方式：密钥路径或临时密码
系统：Ubuntu / Debian / CentOS / 其他
是否已有域名：
```

不要在公开聊天里长期暴露密码；可以使用临时密码，部署完成后立即改掉。

## 自己执行的最短路径

以下以 Ubuntu / Debian 为例。

### 1. 登录服务器

```bash
ssh -p 22222 root@YOUR_SERVER_IP
```

### 2. 安装 Docker

```bash
curl -fsSL https://get.docker.com | sh
docker version
docker compose version
```

如果不是 root 用户：

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

### 3. 在服务器创建目录

```bash
mkdir -p /opt/ai-holdings-analyzer-v3
```

### 4. 从本机复制项目到服务器

在你的 Mac 上执行：

```bash
rsync -avh --progress \
  --exclude ".env" \
  --exclude ".env.local" \
  --exclude ".env.server" \
  --exclude ".DS_Store" \
  --exclude "._*" \
  --exclude "node_modules/" \
  --exclude ".next/" \
  --exclude "__pycache__/" \
  --exclude ".pytest_cache/" \
  --exclude ".vercel/" \
  --exclude "*.log" \
  /Users/jerry.wu/Documents/vibecodingapp/ai-holdings-analyzer-v2/ \
  root@YOUR_SERVER_IP:/opt/ai-holdings-analyzer-v3/
```

### 5. 创建服务器环境文件

在服务器上执行：

```bash
cd /opt/ai-holdings-analyzer-v3
cp .env.server.example .env.server
sed -i "s/YOUR_SERVER_IP/你的服务器公网IP/g" .env.server
```

如果 `sed -i` 不可用，就手工编辑：

```bash
nano .env.server
```

至少确认这两项不是 `YOUR_SERVER_IP`：

```text
WEBAPP_BASE_URL=http://你的服务器公网IP:3000
CORS_ALLOWED_ORIGINS=http://你的服务器公网IP:3000,http://localhost:3000
```

如果暂时不用 Supabase Auth，也要配置本地登录：

```text
AUTH_MODE=local
LOCAL_AUTH_ENABLED=true
LOCAL_AUTH_EMAIL=admin@ai-holdings.local
LOCAL_AUTH_PASSWORD=一串强密码
AUTH_SESSION_SECRET=另一串足够长的随机字符串
LOCAL_AUTH_REGISTRATION_ENABLED=true
```

要让本地注册真正发送验证码邮件，还需要配置 SMTP。未配置 SMTP 时，验证码只会写入 WebApp 容器日志，适合测试但不适合真实用户：

```text
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_SECURE=false
SMTP_USER=你的 SMTP 用户名
SMTP_PASSWORD=你的 SMTP 密码
SMTP_FROM=AI 持仓分析系统 <no-reply@example.com>
```

### 6. 预检

```bash
chmod +x scripts/server-preflight.sh
./scripts/server-preflight.sh
```

### 7. 启动

```bash
docker compose --env-file .env.server -f docker-compose.server.yml up -d --build
```

如果服务器镜像或面板防火墙完全阻断 Docker bridge（典型表现是容器内访问
`postgres:5432`、`host.docker.internal:5432`、外部 DNS 都报 `No route to host`），
改用 host-network 覆盖文件：

```bash
POSTGRES_HOST=127.0.0.1
REDIS_HOST=127.0.0.1
MINIO_HOST=127.0.0.1
DATA_SERVICE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_DATA_SERVICE_URL=http://127.0.0.1:8000

docker compose --env-file .env.server \
  -f docker-compose.server.yml \
  -f docker-compose.lightweight-host.yml \
  up -d --build
```

host-network 模式会让 WebApp 只监听 `127.0.0.1:3000`，建议用服务器自带
Nginx/宝塔站点把公网 `80/443` 反向代理到 `http://127.0.0.1:3000`。这时
`.env.server` 里的 `WEBAPP_BASE_URL` 应写公网地址，例如 `http://你的服务器公网IP`
或后续的正式域名，而不是内部的 `127.0.0.1`。

### 8. 初始化本地数据库 schema

如果第一阶段先不配置 Supabase Cloud，就在本机 Postgres 上初始化兼容 schema：

```bash
./scripts/apply-server-migrations.sh
./scripts/init-openclaw-foundation.sh
```

使用 host-network 覆盖文件时，迁移脚本也要带上覆盖文件：

```bash
COMPOSE_FILES="$PWD/docker-compose.server.yml:$PWD/docker-compose.lightweight-host.yml" \
  ./scripts/apply-server-migrations.sh
```

这个脚本会先创建 Supabase 兼容的 `auth` 函数和角色，再按顺序应用 `supabase/migrations/000001` 到 `000028`，包括 GBrain 表、持仓 3.0 P0 表、delivery outbox、broker connector instances、注册初始化和微信绑定状态等。

`init-openclaw-foundation.sh` 会补齐 OpenClaw 运行初始化：生成内部 `OPENCLAW_SKILL_KEY`、写入 P0 默认套餐/额度、为现有账号补 `quota_tracking` 和 active subscription。若需要同时开启 OpenAI live 授权，可在执行时传入：

```bash
OPENAI_API_KEY=sk-... ./scripts/init-openclaw-foundation.sh
docker compose --env-file .env.server -f docker-compose.server.yml up -d --force-recreate gbrain openclaw
```

如果使用系统级 OpenAI Codex / Hermes auth profile，不在本系统里保存网页登录态。先在 Mac mini 或受控 OpenClaw/Hermes 节点启动一个拥有 `openai-codex` auth profile 的 bridge，并让它暴露 OpenAI-compatible `/chat/completions` 接口。

本仓库提供了 bridge sidecar 的最小契约实现。先在本机确认 Codex CLI 版本与登录态；如需重新授权，`login` 会生成 OpenAI device-auth 地址和一次性授权码：

```bash
./scripts/openai-codex-auth-bridge.sh status
./scripts/openai-codex-auth-bridge.sh login
```

本地正式接入推荐用 `command` 模式，它会通过 `local_connectors.openai_codex_bridge.codex_cli_adapter` 调用本机 Codex CLI，并把最终消息包装成 OpenAI-compatible JSON：

```bash
CODEX_BRIDGE_HOST=0.0.0.0 \
CODEX_BRIDGE_PORT=8091 \
OPENAI_CODEX_AUTH_PROFILE=system-pro \
./scripts/openai-codex-auth-bridge.sh start
```

启动后运行：

```bash
CODEX_BRIDGE_HOST=127.0.0.1 \
CODEX_BRIDGE_PORT=8091 \
./scripts/openai-codex-auth-bridge.sh smoke
```

如果需要替代接入，也可以将 `CODEX_BRIDGE_MODE` 切到 `stub` 或 `http`：

- `stub`：只验证云端链路，不调用真实 OpenAI/Codex。
- `http`：通过 `CODEX_BRIDGE_UPSTREAM_BASE_URL` 转发给已经拥有 `openai-codex` auth profile 的上游 Hermes/OpenClaw 服务。

然后在阿里云主服务写入：

```bash
OPENAI_CODEX_AUTH_PROFILE=system-pro \
OPENAI_CODEX_BRIDGE_BASE_URL=http://mac-mini-lan-ip:8091/v1 \
./scripts/init-openclaw-foundation.sh

docker compose --env-file .env.server -f docker-compose.server.yml up -d --force-recreate gbrain openclaw
```

对应的 `.env.server` 关键项：

```dotenv
GBRAIN_LIVE_MODELS_ENABLED=true
MODEL_AUTH_MODE=openai_codex
HERMES_DEEP_PROVIDER=openai-codex
HERMES_DEEP_MODEL=gpt-5.5
OPENAI_CODEX_AUTH_PROFILE=system-pro
OPENAI_CODEX_BRIDGE_BASE_URL=http://mac-mini-lan-ip:8091/v1
OPENAI_CODEX_BRIDGE_API_KEY=
```

这条路径仍然是系统级共享模型能力；业务账号隔离继续由 `tenant_id`、run contract、memory scope、artifact/audit scope 负责。

MiniMax M2.7 推荐使用 Anthropic-compatible endpoint。当前 `gbrain` MiniMax provider 会在 `MINIMAX_API_FORMAT=anthropic` 或 base URL 包含 `/anthropic` 时，自动用 `/v1/messages`、`X-Api-Key` 和 Anthropic message schema 调用：

```dotenv
MINIMAX_API_KEY=...
MINIMAX_OPENAI_BASE_URL=https://api.minimaxi.com/anthropic
MINIMAX_API_FORMAT=anthropic
MINIMAX_MODEL=MiniMax-M2.7
HERMES_LIGHT_MODEL=MiniMax-M2.7
```

MiniMax Token Plan / OpenClaw 文档中的 Anthropic-style 环境变量也支持直接透传：

```dotenv
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
ANTHROPIC_AUTH_TOKEN=...
API_TIMEOUT_MS=3000000
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
ANTHROPIC_MODEL=MiniMax-M2.7
ANTHROPIC_DEFAULT_SONNET_MODEL=MiniMax-M2.7
ANTHROPIC_DEFAULT_OPUS_MODEL=MiniMax-M2.7
ANTHROPIC_DEFAULT_HAIKU_MODEL=MiniMax-M2.7
```

### 9. 查看状态

```bash
docker compose --env-file .env.server -f docker-compose.server.yml ps
docker compose --env-file .env.server -f docker-compose.server.yml logs -f webapp
```

### 10. 验证

服务器上执行：

```bash
curl -I http://127.0.0.1:3000
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8080/health
python3 scripts/production_readiness.py --profile lightweight --env-file .env.server
chmod +x scripts/verify-foundation-runtime.sh
./scripts/verify-foundation-runtime.sh
chmod +x scripts/verify-openclaw-foundation.sh
./scripts/verify-openclaw-foundation.sh
docker exec ai-holdings-server-postgres-1 psql -U postgres -d ai_holdings -Atc "select count(*) from public.schema_migrations;"
```

浏览器打开：

```text
http://你的服务器公网IP:3000
```

首次打开会进入登录页。第一阶段本地登录使用 `.env.server` 中的 `LOCAL_AUTH_EMAIL` 和 `LOCAL_AUTH_PASSWORD`。如果开启本地注册，用户注册后需要输入邮箱验证码；未配置 SMTP 时验证码可从 WebApp 容器日志查看。当前未启用 HTTPS 时，登录信息只适合测试部署使用。

核心页面：

```text
http://你的服务器公网IP:3000/
http://你的服务器公网IP:3000/holdings
http://你的服务器公网IP:3000/sell-put
http://你的服务器公网IP:3000/data
http://你的服务器公网IP:3000/settings
```

如果页面提示“当前显示参考视图”或“暂时还没拿到最新账户数据”，这是第一阶段未接真实券商/真实账户数据时的正常状态。

### 账号工作区与手工持仓验证

登录成功后，WebApp 会为当前用户自动初始化：

- `account_id`
- `tenant_id`
- 默认 `portfolio_views`
- 默认 `follow_views`
- 默认 `list_views`
- 手工录入、买卖消息、OCR、语音、富途只读连接等 `asset_sources`

可通过接口确认：

```bash
curl -b cookies.txt http://你的服务器公网IP:3000/api/account/context
```

在 `/data` 页面可手工录入股票或 ETF 持仓。录入后系统会：

1. 写入当前 `tenant_id` 下的手工持仓来源；
2. 生成一份 `broker_sync_snapshots` 快照；
3. 写入 `broker_position_snapshots`；
4. `/holdings` 页面按当前登录账号读取并展示，不会混用其他账号的数据。

## 常用运维命令

```bash
cd /opt/ai-holdings-analyzer-v3

# 看运行状态
docker compose --env-file .env.server -f docker-compose.server.yml ps

# 看日志
docker compose --env-file .env.server -f docker-compose.server.yml logs -f

# 重启
docker compose --env-file .env.server -f docker-compose.server.yml restart

# 更新代码后重建
docker compose --env-file .env.server -f docker-compose.server.yml up -d --build

# host-network 模式下更新代码后重建
docker compose --env-file .env.server \
  -f docker-compose.server.yml \
  -f docker-compose.lightweight-host.yml \
  up -d --build

# 验证 OpenClaw + Hermes/GBrain 基座
./scripts/verify-foundation-runtime.sh
./scripts/verify-openclaw-foundation.sh

# 如果 gbrain 处于 restarting，先看数据库连接日志
docker compose --env-file .env.server -f docker-compose.server.yml logs --tail=120 gbrain

# 如果日志是 ECONNREFUSED / No route to host postgres:5432，通常是宿主机
# Docker bridge 禁用了容器互通。确认 .env.server 使用 host-gateway 连接：
# INTERNAL_HOST_BIND=172.17.0.1
# POSTGRES_HOST=host.docker.internal
# POSTGRES_PORT=5432
# POSTGRES_HOST_PORT=5432
# REDIS_HOST=host.docker.internal
# REDIS_PORT=6379
# REDIS_HOST_PORT=6379
# MINIO_HOST=host.docker.internal
# MINIO_PORT=9000
# MINIO_HOST_PORT=9000
# DATA_SERVICE_URL=http://host.docker.internal:8000
#
# 轻量服务器冷启动或 Postgres 短暂不可达时，也可调大启动重试窗口：
# GBRAIN_DATABASE_CONNECT_RETRIES=12
# GBRAIN_DATABASE_CONNECT_RETRY_DELAY_MS=5000

# 如果 Docker build 里能拉镜像但 apt/npm 解析失败，优先用宿主机网络构建：
docker compose --env-file .env.server \
  -f docker-compose.server.yml \
  -f docker-compose.lightweight-host.yml \
  build --network host webapp openclaw
docker compose --env-file .env.server \
  -f docker-compose.server.yml \
  -f docker-compose.lightweight-host.yml \
  up -d --no-build --force-recreate

# 停止
docker compose --env-file .env.server -f docker-compose.server.yml down
```

## 第一阶段完成标准

- `docker compose ps` 中 `webapp`、`data-service`、`postgres`、`redis`、`minio`、`gbrain`、`openclaw` 为 running/healthy。
- `curl http://127.0.0.1:8000/health` 返回 `status: ok`。
- `curl http://127.0.0.1:8080/health` 返回 `status: ok`，并能看到 `runtime.foundation.openclaw_upstream_target` 和 `runtime.foundation.hermes_upstream_target`。
- `python3 scripts/production_readiness.py --profile lightweight --env-file .env.server` 无 fail；允许对完整生产项给出 warn。
- `./scripts/verify-foundation-runtime.sh` 通过，证明 OpenClaw Gateway、Hermes/GBrain adapter、WebApp、data-service 都在当前服务器上可达。
- `./scripts/verify-openclaw-foundation.sh` 通过，证明 OpenClaw 内部 skill key、默认套餐、token budget、quota/subscription 初始化完整。
- `public.schema_migrations` 记录数为 `28`。
- MinIO 中存在 `market-data`、`hermes-artifacts`、`replay-evidence`、`tenant-media` 四个 bucket。
- 公网能打开 WebApp 首页。
- `/holdings`、`/sell-put`、`/data`、`/settings` 不崩溃。
- 邮箱注册、验证码确认、本地登录和 `/api/account/context` 可完成端到端验证。
- 手工录入一条持仓后，当前账号的 `/holdings` 能看到该标的名称、代码、来源和更新时间。

## 下一阶段

1. 配置真实 SMTP，使验证码邮件不再依赖容器日志。
2. 接 OpenClaw 微信入口，把确认主路径放到微信口令和 WebApp 深链。
3. 接 Futu 本地 connector：服务器保持 read-only API，用户本地 Mac/connector 负责连接 OpenD。
4. MiniMax M2.7 已可作为第一阶段 live light route；下一步接 OpenAI API key 或系统级 `openai-codex` bridge，让 Hermes/GBrain 的 GPT-5.5 深研 route 通过 smoke。
5. 绑定域名、HTTPS、监控、备份和告警。
