# 轻量级服务器第一阶段部署手册

## 关键运行时约束（请先确认）

本阶段目标是基于 **Hermes-only** 落地 3.0 P0。轻量化服务器不启动 OpenClaw 服务；微信入口、消息路由、domain tools 与上线验收都必须在 Hermes 系统内完成。

验收前请先确认：

- WebApp、data-service、reference-capture、gbrain、postgres、redis、minio 均可达。
- `verify-foundation-runtime.sh` 通过，且 compose 服务列表中不存在 `openclaw` 服务。
- `data-service /health` 返回 `runtime=hermes`，`/api/hermes/domain-tools` 返回 Hermes 工具清单，且包含 `reference.web.read` 与 `reference.web.search`。
- 微信系统消息与确认体系已按业务要求进行过滤/重路由（`HERMES_SKIP_SYSTEM_DELIVERIES=true` 或 `HERMES_WECHAT_SUPPRESSED_DELIVERY_CONTENT_TYPES` 已配置）。

目标：先让 3.0 P0 单机版在轻量级服务器跑起来：WebApp 公网可访问，data-service、reference-capture、Postgres/pgvector、Redis、MinIO、GBrain/Hermes 在服务器内网运行并健康。

第一阶段仍然不接真实交易、不自动下单；Futu OpenD、真实微信推送可以按账户逐步接入。MiniMax M2.7 已支持在第一阶段以 live route 运行；GPT-5.5 / OpenAI 深研 route 需要 OpenAI API key 或系统级 `openai-codex` bridge 后再启用。

当前轻量服务器使用本地 Postgres 保存 P0 schema、GBrain 记忆表和账户业务表；历史行情对象与 manifest 直接走 Supabase Storage / Supabase manifest 表，避免本机磁盘成为后续迁移负担。
WebApp 已切到 Supabase Auth；本地管理员登录只保留为开发兜底。正式对外使用前应启用域名与 HTTPS。

## 当前已验证状态（2026-06-10）

- 阿里云轻量服务器已能运行 Docker Compose 单机栈，WebApp 公网页面可访问。
- `verify-foundation-runtime.sh` 已切到 Hermes-only 验收：compose 服务列表不得包含 `openclaw`，`data-service /health` 必须返回 `runtime=hermes`。
- MiniMax M2.7 已通过 Anthropic-compatible endpoint 进入 live route。
- OpenAI/GPT-5.5 深研 route 与 `openai-codex` bridge 契约已写入代码和配置模板，但服务器尚未启用真实 deep auth。
- 历史行情对象存储与 manifest 已按 Supabase 后端配置，不再把 P0 历史行情默认写入本机 file backend。

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

阿里云对外部署建议直接使用 Supabase Auth：

```text
AUTH_MODE=supabase
LOCAL_AUTH_ENABLED=false
```

如需本地联调，可临时将登录切到本地模式（仅用于本地开发，不得作为轻量化线上入口）：

```text
AUTH_MODE=local
LOCAL_AUTH_ENABLED=true
LOCAL_AUTH_EMAIL=admin@ai-holdings.local
LOCAL_AUTH_PASSWORD=一串强密码
AUTH_SESSION_SECRET=另一串足够长的随机字符串
LOCAL_AUTH_REGISTRATION_ENABLED=true
```

线上轻量化部署的 readiness 目标默认不应依赖本地验证码链路；请在 `AUTH_MODE=supabase` 场景下用真实邮箱完成注册验证。

要让本地注册真正发送验证码邮件，还需要配置 SMTP。未配置 SMTP 时，验证码只会写入 WebApp 容器日志，适合测试但不适合真实用户：

```text
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_SECURE=false
SMTP_USER=你的 SMTP 用户名
SMTP_PASSWORD=你的 SMTP 密码
SMTP_FROM=AI 持仓分析系统 <no-reply@example.com>
```

微信 ClawBot 绑定由 Hermes 微信入口托管，轻量服务器阶段不需要配置微信小程序 `WECHAT_APP_ID/WECHAT_APP_SECRET`。需要启用 ClawBot API、凭证加密和 Hermes 内部授权：

```text
WECHAT_CLAWBOT_API_BASE_URL=https://ilinkai.weixin.qq.com
ONBOARDING_CREDENTIAL_ENCRYPTION_KEY=32位以上随机字符串
HERMES_DELIVERY_MODE=log
HERMES_DOMAIN_TOOLS_KEY=一串随机字符串
HERMES_INTERNAL_TOKEN=同上或另一串随机字符串
```

`HERMES_DELIVERY_MODE=log` 可以完成绑定和路由写入验证；正式让系统通过微信回复消息前，再切到 `webhook` 并补齐 `HERMES_DELIVERY_WEBHOOK_URL`、`HERMES_DELIVERY_WEBHOOK_SECRET` 和 `HERMES_CRON_SECRET`。

微信公开网页引用资料由独立 `reference-capture` sidecar 承担。它只处理公开 URL，生成 `reference_only` 快照、正文净化结果、来源、审计字段和失败原因；data-service 通过 Hermes domain tool 调用它。第一阶段对微信公众号文章和小红书公开分享页做轻量启发式抽取：优先读取 `mp.weixin.qq.com` 的 `#js_content` / `.rich_media_content`，以及小红书页面的 `.note-content` / `#detail-desc`，再退回通用 `article` / `main` / `body`：

```text
HERMES_REFERENCE_CAPTURE_URL=http://reference-capture:8010
```

`reference-capture` 主路径使用 Scrapling；如果轻量运行环境缺少 Scrapling，`get` 模式会退回到 Python 标准库读取基础公开 HTML，但动态页面、反爬页面和复杂正文抽取仍依赖 Scrapling/Playwright 容器依赖。

微信消息中的小红书分享短链可以直接转交给 `reference.web.read`，例如 `https://xhslink.com/...`；路由层会剔除中文标点后的“复制本条信息”等分享后缀。实际能否读取正文仍取决于目标页面是否公开、是否需要登录、是否允许服务端抓取。

搜索意图默认不把 Scrapling/reference-capture 当搜索引擎。第二阶段的 `reference.web.search` 是 provider 链：先查 IMA / GBrain 这类已授权知识源，再查配置的公开搜索 API；只有拿到候选 URL 后，才把首条公开 `http(s)` URL 交给 `reference.web.read` 读取。

- `ima`：调用 IMA OpenAPI 搜索知识库或笔记；命中项作为 `reference_only`，没有公开 URL 时不会触发网页读取。
- `gbrain`：查询本机 Postgres 的 `gbrain_pages`，命中项可以是 `gbrain://...` 引用；没有公开 URL 时不会触发网页读取。
- `searxng`：配置 SearXNG 兼容 JSON endpoint；未配置 endpoint 时，直接 URL 读取仍可用，搜索会返回 `search_source_not_configured` 并保留失败原因。
- `bing_html`：可作为临时兜底，不需要账号和 endpoint，data-service 直接读取 Bing HTML 搜索结果，再把首条公开 URL 交给 `reference-capture` 读取。

```text
HERMES_REFERENCE_SEARCH_PROVIDERS=ima,gbrain,searxng
# 兼容旧单 provider 配置；若设置 HERMES_REFERENCE_SEARCH_PROVIDERS，则优先使用 provider 链。
HERMES_REFERENCE_SEARCH_PROVIDER=
HERMES_REFERENCE_SEARCH_URL=
HERMES_REFERENCE_SEARCH_LANGUAGE=zh-CN
```

如果要先用无账号兜底验证搜索链路，可以临时设置：

```text
HERMES_REFERENCE_SEARCH_PROVIDERS=bing_html
HERMES_REFERENCE_SEARCH_URL=
```

Stealthy 读取和代理默认关闭，只对明确需要的站点启用。建议先用普通 `auto/get/dynamic` 验证公开页面，确实需要时再按 host allowlist 打开：

```text
HERMES_REFERENCE_STEALTHY_ENABLED=false
HERMES_REFERENCE_STEALTHY_HOSTS=mp.weixin.qq.com,www.xiaohongshu.com,xhslink.com
HERMES_REFERENCE_STEALTHY_REQUIRED_HOSTS=
HERMES_REFERENCE_PROXY_ENABLED=false
HERMES_REFERENCE_PROXY_HOSTS=
HERMES_REFERENCE_PROXY_URL=
```

微信通道的长读取默认有异步保护：超过即时回复窗口时先返回“正在读取”，后台完成后写入 `delivery_outbox`，由现有 Hermes delivery worker 推送给绑定微信用户。默认阈值是 12 秒；如果要在后台完成后立即触发一次 delivery worker，可显式打开立即投递开关：

```text
HERMES_REFERENCE_ASYNC_ENABLED=true
HERMES_REFERENCE_ASYNC_THRESHOLD_SECONDS=12
HERMES_REFERENCE_ASYNC_DELIVER_IMMEDIATELY=false
```

当微信消息同时包含搜索/链接和股票分析意图时，Hermes 会把读取摘要作为 `stock.analysis.news_context` 注入分析；它仍是参考资料，不写持仓事实，不下单。

FTShare 行情源作为 Hermes skill 资产接入，已安装到 `skills/ftshare-market-data`。轻量服务器的 data-service 会通过只读挂载读取该 skill，默认路径如下：

```text
FTSHARE_MARKET_DATA_SKILL_DIR=/app/skills/ftshare-market-data
FTSHARE_MARKET_DATA_TIMEOUT_SECONDS=10
```

验证 A 股兜底行情源：

```bash
curl "http://127.0.0.1:8000/api/quote/SH600519?source=ftshare"
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
./scripts/init-hermes-foundation.sh
```

使用 host-network 覆盖文件时，迁移脚本也要带上覆盖文件：

```bash
COMPOSE_FILES="$PWD/docker-compose.server.yml:$PWD/docker-compose.lightweight-host.yml" \
  ./scripts/apply-server-migrations.sh
```

这个脚本会先创建 Supabase 兼容的 `auth` 函数和角色，再按顺序应用 `supabase/migrations/000001` 到当前最新迁移。当前数据基础层至少应包含 `000030_account_lists_manual_positions_trading_rules.sql`，覆盖 GBrain 表、持仓 3.0 P0 表、delivery outbox、broker connector instances、注册初始化、微信绑定状态、关注清单、清仓回溯、手工持仓和交易纪律基础表。

轻量服务器默认使用 Supabase 保存历史行情对象与 manifest：

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
HISTORICAL_STORAGE_BACKEND=supabase_storage
HISTORICAL_MANIFEST_BACKEND=supabase_storage
WEBAPP_RUNTIME_SCHEMA_REPAIR=false
```

其中 `WEBAPP_RUNTIME_SCHEMA_REPAIR=false` 表示 WebApp 不再依赖运行时建表，部署前必须先完成 migration。Supabase Storage 需要提前创建 `market-data` bucket；manifest 会写入同一 bucket 下的 `.manifests/market_data_manifests.json` 索引对象。

`init-hermes-foundation.sh` 会补齐 Hermes 运行初始化：生成内部 `HERMES_DOMAIN_TOOLS_KEY` / `HERMES_INTERNAL_TOKEN`、写入 P0 默认套餐/额度、为现有账号补 `quota_tracking` 和 active subscription。若需要同时开启 OpenAI live 授权，可在执行时传入：

```bash
OPENAI_API_KEY=sk-... ./scripts/init-hermes-foundation.sh
docker compose --env-file .env.server -f docker-compose.server.yml up -d --force-recreate gbrain data-service webapp
```

如果使用系统级 OpenAI Codex / Hermes auth profile，不在本系统里保存网页登录态。先在 Mac mini 或受控 Hermes 节点启动一个拥有 `openai-codex` auth profile 的 bridge，并让它暴露 OpenAI-compatible `/chat/completions` 接口。

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

当前轻量服务器采用方案 A：Mac mini 持有 Codex/ChatGPT 授权，阿里云只访问服务器本机
`127.0.0.1:8091`，这一路径由 Mac mini 主动建立反向 SSH 隧道：

```bash
ALIYUN_HOST=149.129.240.111 \
ALIYUN_SSH_PORT=22222 \
ALIYUN_SSH_KEY="$HOME/.ssh/ai_holdings_aliyun_deploy_20260521" \
./scripts/install-codex-deep-auth-launchd.sh install
```

安装后会生成两个 macOS LaunchAgents：

- `ai.holdings.codex-bridge`：启动本机 OpenAI-compatible Codex auth bridge。
- `ai.holdings.codex-tunnel`：建立 `阿里云 127.0.0.1:8091 -> Mac mini 127.0.0.1:8091` 的反向隧道。

安装脚本会把 bridge 运行所需的最小源码同步到
`$HOME/.ai-holdings-analyzer-v3/codex-bridge-src`，并把 launchd wrapper 和日志放到
`$HOME/.ai-holdings-analyzer-v3/codex-deep-auth`。这样可以避开 macOS 对 `Documents`
目录的后台进程访问限制。

运行状态和端到端 smoke：

```bash
./scripts/install-codex-deep-auth-launchd.sh status
./scripts/check-codex-deep-auth.sh status
./scripts/check-codex-deep-auth.sh smoke
```

如果需要替代接入，也可以将 `CODEX_BRIDGE_MODE` 切到 `stub` 或 `http`：

- `stub`：只验证云端链路，不调用真实 OpenAI/Codex。
- `http`：通过 `CODEX_BRIDGE_UPSTREAM_BASE_URL` 转发给已经拥有 `openai-codex` auth profile 的上游 Hermes 服务。

然后在阿里云主服务写入：

```bash
OPENAI_CODEX_AUTH_PROFILE=system-pro \
OPENAI_CODEX_BRIDGE_BASE_URL=http://mac-mini-lan-ip:8091/v1 \
./scripts/init-hermes-foundation.sh

docker compose --env-file .env.server -f docker-compose.server.yml up -d --force-recreate gbrain data-service webapp
```

对应的 `.env.server` 关键项：

```dotenv
GBRAIN_LIVE_MODELS_ENABLED=true
MODEL_AUTH_MODE=openai_codex
HERMES_DEEP_PROVIDER=openai-codex
HERMES_DEEP_MODEL=gpt-5.5
OPENAI_CODEX_AUTH_PROFILE=system-pro
OPENAI_CODEX_BRIDGE_BASE_URL=http://127.0.0.1:8091/v1
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

MiniMax Token Plan 文档中的 Anthropic-style 环境变量也支持直接透传：

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
curl http://127.0.0.1:8010/health
curl http://127.0.0.1:8000/api/hermes/domain-tools
python3 scripts/production_readiness.py --profile lightweight --env-file .env.server
python3 scripts/product_feature_readiness.py --profile lightweight --env-file .env.server
chmod +x scripts/verify-foundation-runtime.sh
./scripts/verify-foundation-runtime.sh
docker exec ai-holdings-server-postgres-1 psql -U postgres -d ai_holdings -Atc "select count(*) from public.schema_migrations;"
```

浏览器打开：

```text
http://你的服务器公网IP:3000
```

首次打开 `/` 会展示登录前功能介绍页，登录和注册按钮进入 `/login`。阿里云对外部署主路径使用 Supabase Auth，`AUTH_MODE=supabase` 且 `LOCAL_AUTH_ENABLED=false`；本地登录只作为开发兜底，使用 `.env.server` 中的 `LOCAL_AUTH_EMAIL` 和 `LOCAL_AUTH_PASSWORD`。注册和登录需依赖 Supabase 的邮件发送与回执链路：未配置 `SMTP_HOST/SMTP_FROM` 时仅能看到测试日志，不可直接当作用户自助可用状态。注册初始化的微信绑定会弹出二维码；扫码确认后，WebApp 写入 `channel_bindings` 并进入最终检查。Futu OpenD 只作为管理员侧系统行情源，不进入普通用户注册流程。当前未启用 HTTPS 时，登录信息只适合测试部署使用。

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

# 验证 Hermes/GBrain 基座
./scripts/verify-foundation-runtime.sh

# 外部域名透传检查（用于确认 webapp 与 data-service 的 /api/hermes 兼容路径）
# curl https://www.11office.top/api/hermes/domain-tools
# curl http://127.0.0.1:3000/api/hermes/domain-tools

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
  build --network host webapp data-service reference-capture gbrain
docker compose --env-file .env.server \
  -f docker-compose.server.yml \
  -f docker-compose.lightweight-host.yml \
  up -d --no-build --force-recreate

# 停止
docker compose --env-file .env.server -f docker-compose.server.yml down
```

## 第一阶段完成标准

- `docker compose ps` 中 `webapp`、`data-service`、`reference-capture`、`postgres`、`redis`、`minio`、`gbrain` 为 running/healthy，且不存在 `openclaw` 服务。
- `curl http://127.0.0.1:8000/health` 返回 `status: ok` 和 `runtime: hermes`。
- `curl http://127.0.0.1:8010/health` 返回 `runtime: hermes-reference-capture`。
- `curl http://127.0.0.1:8000/api/hermes/domain-tools` 返回 `runtime: hermes`，且包含 `market.quote`、`reference.web.read`、`reference.web.search`。
- `curl https://www.11office.top/api/hermes/domain-tools`（或当前公网域名）返回同一份 Hermes 工具清单（如返回 401，请确认 `HERMES_DOMAIN_TOOLS_KEY` 或 `HERMES_INTERNAL_TOKEN` 已下发）。
- `python3 scripts/production_readiness.py --profile lightweight --env-file .env.server` 无 fail；允许对完整生产项给出 warn。
- `./scripts/verify-foundation-runtime.sh` 通过，证明 Hermes、GBrain adapter、WebApp、data-service 都在当前服务器上可达。
- `python3 scripts/reference_web_smoke.py` 至少返回 `status: partial`，并且 core steps 全部 passed：`reference.web.read` 生成 `reference_only` 快照，blocked URL 生成带 `failed.reason` / audit / `artifact_status=failed` 的失败快照，`reference.web.search` 返回候选公开网页并读取首条网页，`/api/hermes/wechat/messages` 能把 URL 和搜索意图路由到引用资料链路，搜索+股票分析意图能注入 `stock.analysis.news_context`。
- 当 `DATABASE_URL` 可用且 `tenant_id` 为真实 UUID 时，`scripts/reference_web_smoke.py` 的 `db_reference_readiness` 应显示最近 24 小时存在 `web_reference_snapshot` artifact。
- `HERMES_REFERENCE_SEARCH_PROVIDERS=ima,gbrain,searxng` 是推荐链路；IMA/GBrain 未配置时会继续尝试后续 provider。`bing_html` 不需要配置 `HERMES_REFERENCE_SEARCH_URL`；`searxng` 模式必须配置兼容 JSON endpoint，否则搜索返回 `search_source_not_configured`。
- 真实微信用户可见回复不能只看 `/api/hermes/wechat/messages`。`scripts/reference_web_smoke.py --strict-user-visible` 必须通过，或者等价证明 `wechat_bridge_poll` 有 active ClawBot credentials、bridge 收到真实消息、Hermes 回复已通过 ClawBot 发回微信。
- 如果 `reference_web_smoke.py` 只剩 `wechat_bridge_poll` gap，运行 `python3 scripts/wechat_clawbot_readiness.py`。它会区分环境变量缺失、DB 中没有 active `wechat_bot_credentials`、只有 active `channel_bindings`、授权会话 pending/expired、以及 bridge poll 的 `credentials=0`。
- `public.schema_migrations` 记录数至少覆盖当前最新迁移。
- MinIO 中存在 `market-data`、`hermes-artifacts`、`replay-evidence`、`tenant-media` 四个 bucket。
- 公网能打开 WebApp 首页。
- `/holdings`、`/sell-put`、`/data`、`/settings` 不崩溃。
- 邮箱注册、验证码确认、本地登录和 `/api/account/context` 可完成端到端验证。
- 手工录入一条持仓后，当前账号的 `/holdings` 能看到该标的名称、代码、来源和更新时间。

## 下一阶段

1. 配置真实 SMTP，使验证码邮件不再依赖容器日志。
2. 完成 Hermes 微信入口的真实消息回写 smoke，把确认主路径放到微信口令和 WebApp 深链。
3. 接 Futu 本地 connector：服务器保持 read-only API，用户本地 Mac/connector 负责连接 OpenD。
4. MiniMax M2.7 已可作为第一阶段 live light route；下一步接 OpenAI API key 或系统级 `openai-codex` bridge，让 Hermes/GBrain 的 GPT-5.5 深研 route 通过 smoke。
5. 绑定域名、HTTPS、监控、备份和告警。
