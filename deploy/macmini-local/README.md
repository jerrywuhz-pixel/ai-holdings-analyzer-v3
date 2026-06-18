# Mac mini 本地化部署包

本目录是 AI Holdings Analyzer 3.0 迁移到 Mac mini 做最终本地化部署的交接入口。项目主包仍然是仓库根目录，Mac mini 专属材料集中放在这里，避免和阿里云轻量服务器材料混在一起。

## 目标拓扑

- WebApp: `http://127.0.0.1:3000`
- Data Service: `http://127.0.0.1:8000`
- OpenClaw Gateway: `http://127.0.0.1:8080`
- Postgres: Docker volume，本地端口 `5432`
- Redis: Docker volume，本地端口 `6379`
- MinIO: Docker volume，本地端口 `9000` / console `9001`
- GBrain/Hermes: Docker service，连接同一 Postgres
- WeChat bridge: 默认可启用轮询桥接，真实微信通道需要已配置 ClawBot/OpenClaw 凭证
- Futu OpenD: Mac mini 本机服务，管理员侧行情/只读数据源；普通用户不连接个人 Futu 账号
- Deep research auth bridge: Mac mini 可持有 Codex/OpenAI 授权，通过本机或反向隧道暴露给 OpenClaw

## 首次部署步骤

1. 安装基础依赖：

```bash
xcode-select --install
brew install git docker node python@3.11 postgresql@15 redis
```

2. 启动 Docker Desktop，并确认：

```bash
docker version
docker compose version
```

3. 复制项目包到 Mac mini，例如：

```bash
mkdir -p ~/Projects
tar -xzf ai-holdings-analyzer-v3-macmini-*.tar.gz -C ~/Projects
cd ~/Projects/ai-holdings-analyzer-v3-fresh-deploy
```

4. 准备环境变量：

```bash
cp deploy/macmini-local/env.macmini.example .env.server
```

填入至少这些值：

- `AUTH_SESSION_SECRET`
- `LOCAL_AUTH_PASSWORD`
- `MINIMAX_API_KEY`
- `OPENCLAW_SKILL_KEY`
- 微信/ClawBot 相关凭证，如要测试真实微信上行和下行
- `OPENAI_CODEX_BRIDGE_BASE_URL` / `OPENAI_CODEX_AUTH_PROFILE`，如要启用 Hermes 深研

5. 构建并启动本地全栈：

```bash
docker compose --env-file .env.server \
  -f docker-compose.server.yml \
  -f docker-compose.wechat-bridge.yml \
  up -d --build
```

6. 应用数据库迁移：

```bash
./scripts/apply-server-migrations.sh
```

7. 验证基础服务：

```bash
curl -fsS http://127.0.0.1:3000 >/dev/null
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8080/health
docker compose --env-file .env.server -f docker-compose.server.yml ps
```

8. 运行回归验证：

```bash
python3 -m pytest openclaw/tests/test_image_vision.py openclaw/tests/test_openclaw_gateway_router.py -q
npm --prefix webapp run build
```

## Futu OpenD 本地数据源

Mac mini 上可以运行 Futu OpenD。当前产品策略是：

- 管理员侧系统行情源可以使用 Mac mini 上的 Futu OpenD。
- 普通用户不连接个人 Futu 账号。
- 普通用户持仓通过微信截图识别、确认中心二次确认后写入持仓系统。

本机联调：

```bash
export FUTU_CONNECTOR_MODE=local_dev_direct
export FUTU_CONNECTOR_BASE_URL=http://host.docker.internal:8765
./scripts/verify-futu-local.sh --mode mock
```

如要测真实 OpenD：

```bash
./scripts/verify-futu-local.sh --mode real
```

## Deep Research / Codex Bridge

如果 Mac mini 持有 Codex/OpenAI 登录态，优先在 Mac mini 本地启动桥：

```bash
./scripts/openai-codex-auth-bridge.sh
```

然后在 `.env.server` 中配置：

```bash
MODEL_AUTH_MODE=openai_codex
OPENAI_CODEX_AUTH_PROFILE=<profile-id>
OPENAI_CODEX_BRIDGE_BASE_URL=http://host.docker.internal:8091
OPENAI_CODEX_BRIDGE_API_KEY=<local-secret>
HERMES_WORKER_MODE=live
```

## 关闭和清理

```bash
docker compose --env-file .env.server -f docker-compose.server.yml -f docker-compose.wechat-bridge.yml down
```

保留数据卷不要加 `-v`。只有确认要清空本地数据时才执行：

```bash
docker compose --env-file .env.server -f docker-compose.server.yml -f docker-compose.wechat-bridge.yml down -v
```
