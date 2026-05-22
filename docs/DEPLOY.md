# AI Holdings Analyzer 2.0 - 部署文档

## 目录

- [本地开发环境](#本地开发环境)
- [生产环境部署](#生产环境部署)
- [环境变量配置](#环境变量配置)
- [Supabase 配置](#supabase-配置)
- [常见问题](#常见问题)

---

## 本地开发环境

### 前置要求

- Docker >= 24.0
- Docker Compose >= 2.20
- Python 3.11（如不使用 Docker 运行 data-service）
- Node.js 20（webapp 前端开发）

### 快速启动

1. **克隆仓库并进入目录**

   ```bash
   cd ai-holdings-analyzer-v2
   ```

2. **复制环境变量模板**

   ```bash
   cp .env.example .env
   # 按需编辑 .env 填入你的 API Key
   ```

3. **一键启动**

   ```bash
   chmod +x scripts/init-local.sh
   ./scripts/init-local.sh
   ```

   该脚本会：
   - 检查 Docker 和 docker-compose 是否安装
   - 启动 PostgreSQL、Redis、data-service 和 WebApp
   - 等待数据库就绪并输出连接信息

4. **手动管理**

   ```bash
   # 查看日志
   docker-compose logs -f data-service

   # 进入数据库
   docker-compose exec postgres psql -U postgres -d ai_holdings

   # 停止所有服务
   docker-compose down

   # 完全清理（含数据卷）
   docker-compose down -v
   ```

### 服务地址

| 服务         | 地址                            |
| ------------ | ------------------------------- |
| Data Service | http://localhost:8000           |
| WebApp       | http://localhost:3000           |
| PostgreSQL   | postgres://localhost:5432       |
| Redis        | redis://localhost:6379          |
| API Docs     | http://localhost:8000/docs      |

---

## 生产环境部署

### 架构概览

```
┌─────────────┐      ┌─────────────────┐      ┌─────────────┐
│   Webapp    │─────▶│  Data Service   │─────▶│  Supabase   │
│  (Vercel)   │      │ (Cloud/Server)  │      │(PostgreSQL) │
└─────────────┘      └─────────────────┘      └─────────────┘
                            │
                            ▼
                     ┌─────────────┐
                     │    Redis    │
                     │  (Upstash)  │
                     └─────────────┘
```

### Webapp - Vercel 部署

1. 将代码推送到 GitHub
2. 在 [Vercel Dashboard](https://vercel.com) 导入项目
3. 配置环境变量（项目设置 → Environment Variables）：
   - `NEXT_PUBLIC_DATA_SERVICE_URL` — data-service 的生产地址
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
4. 部署

### Data Service - 服务器/容器部署

#### 选项 A: Docker Compose（自有服务器）

```bash
# 服务器上
scp .env user@server:/opt/ai-holdings/
ssh user@server "cd /opt/ai-holdings && docker-compose -f docker-compose.yml up -d"
```

> 生产环境建议移除 `docker-compose.yml` 中的 `--reload` 和开发挂载卷。

#### 选项 B: 云容器平台

- **Render**: 使用 Web Service 类型，构建命令留空，启动命令 `uvicorn src.main:app --host 0.0.0.0 --port 8000`
- **Railway**: 自动识别 Dockerfile，配置环境变量即可
- **Fly.io**: `fly launch` 后修改 `fly.toml`

#### 生产 Dockerfile 注意事项

已提供的 `data-service/Dockerfile` 可直接用于生产构建。确保：

- 使用多阶段构建进一步减小镜像体积（可选优化）
- 不挂载本地源码卷
- 不启用 `--reload`

---

## 环境变量配置

### 必需变量

| 变量名                    | 说明                     | 示例值                                          |
| ------------------------- | ------------------------ | ----------------------------------------------- |
| `DATABASE_URL`            | PostgreSQL 连接字符串    | `postgresql://user:pass@host:5432/db`           |
| `REDIS_URL`               | Redis 连接字符串         | `redis://host:6379/0`                           |
| `SUPABASE_URL`            | Supabase 项目 URL        | `https://xxxx.supabase.co`                      |
| `SUPABASE_SERVICE_ROLE_KEY`| Supabase 服务角色密钥   | `eyJ...`                                        |

### 可选变量

| 变量名                    | 说明                     | 默认值       |
| ------------------------- | ------------------------ | ------------ |
| `OPENAI_API_KEY`          | OpenAI API 密钥          | —            |
| `YAHOO_FINANCE_ENABLED`   | 启用 Yahoo Finance 数据源 | `true`       |
| `TUSHARE_TOKEN`           | Tushare Pro API Token    | —            |
| `FTSHARE_MARKET_DATA_SKILL_DIR` | ClawHub `ftshare-market-data` skill 路径 | `/app/skills/ftshare-market-data` |
| `AKSHARE_ENABLED`         | 启用 AkShare 备用数据源   | `false`      |
| `DATA_SERVICE_PORT`       | 本地服务端口             | `8000`       |
| `WEBAPP_PORT`             | WebApp 本地端口          | `3000`       |

### 环境区分建议

| 环境 | DATABASE_URL 主机 | REDIS_URL 主机 |
|------|-------------------|----------------|
| 本地 Docker | `postgres` (服务名) | `redis` (服务名) |
| 本地原生 | `localhost` | `localhost` |
| 生产 | Supabase 连接串 | Upstash 连接串 |

---

## 数据源配置

系统支持多数据源获取股票和基金数据，按以下方式配置：

### Tushare（A 股数据）

1. 访问 [Tushare Pro](https://tushare.pro) 注册账号
2. 进入「个人主页」→「接口 TOKEN」
3. 复制 Token 并填入 `.env` 的 `TUSHARE_TOKEN`

FTShare 市场数据作为 ClawHub/OpenClaw skill 安装在 `openclaw/skills/ftshare-market-data`。Docker Compose 会把它只读挂载到 data-service 的 `/app/skills/ftshare-market-data`，用于 A 股 `source=ftshare` 查询和 Tushare 失败后的 CN 行情兜底。

### Yahoo Finance（美股/港股/基金）

- 无需额外配置，默认启用
- 通过 `YAHOO_FINANCE_ENABLED=true` 控制开关（默认已开启）

### AkShare（备用数据源）

- 可选配置，作为 Tushare / Yahoo Finance 的 fallback
- 无需 Token，安装依赖后即可使用
- 在 `.env` 中设置 `AKSHARE_ENABLED=true` 开启

---

## 多数据源切换

data-service 会根据股票代码自动路由和切换数据源：

1. **A 股数据**：优先使用 Tushare，失败时自动回退到 AkShare
2. **美股/港股**：优先使用 Yahoo Finance
3. **基金数据**：支持 Tushare 和 Yahoo Finance 双源校验

**自动路由规则**：

| 代码前缀/格式 | 首选数据源 | 回退数据源 |
|-------------|-----------|-----------|
| `6xxxxxx`、`0xxxxxx`、`3xxxxxx`（A 股） | Tushare | AkShare |
| `.SS`、`.SZ`、`.BJ` 后缀 | Tushare | AkShare |
| 其他（美股、港股等） | Yahoo Finance | — |

无需手动切换，系统根据股票代码前缀自动选择最佳数据源。

---

## Supabase 配置

### 1. 创建项目

1. 访问 [Supabase Dashboard](https://supabase.com/dashboard)
2. 点击 "New Project"
3. 设置项目名称、数据库密码、区域（建议选择离用户最近的区域）
4. 等待项目创建完成（约 1-2 分钟）

### 2. 获取连接信息

进入项目 → Project Settings → API：
- `SUPABASE_URL` → `Project URL`
- `SUPABASE_SERVICE_ROLE_KEY` → `service_role` key（注意：此密钥拥有最高权限，勿泄露到前端）

### 3. 执行数据库迁移

```bash
# 安装 Supabase CLI（如未安装）
npm install -g supabase

# 登录
supabase login

# 链接项目
supabase link --project-ref <your-project-ref>

# 执行迁移（如项目已有 migrations 目录）
supabase db push
```

或手动在 Supabase SQL Editor 中执行初始化脚本：

```sql
-- 示例：创建核心表（根据实际 schema 调整）
CREATE TABLE IF NOT EXISTS portfolios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS holdings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 0,
    avg_cost NUMERIC,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 启用 Row Level Security
ALTER TABLE portfolios ENABLE ROW LEVEL SECURITY;
ALTER TABLE holdings ENABLE ROW LEVEL SECURITY;
```

### 4. 配置 Row Level Security (RLS)

在 Supabase Dashboard → Database → Tables → 选择表 → Policies 中创建：

```sql
-- portfolios 表：用户只能访问自己的数据
CREATE POLICY "Users can only access their own portfolios"
ON portfolios FOR ALL
TO authenticated
USING (auth.uid() = user_id);

-- holdings 表：通过 portfolio 关联控制访问
CREATE POLICY "Users can access holdings in their portfolios"
ON holdings FOR ALL
TO authenticated
USING (
    portfolio_id IN (
        SELECT id FROM portfolios WHERE user_id = auth.uid()
    )
);
```

---

## 常见问题

### Q: 本地启动时 PostgreSQL 连接失败？

确保 `.env` 中的 `DATABASE_URL` 使用正确的主机名：
- Docker 方式启动 → 使用 `postgres` 作为主机名（docker-compose 内部网络）
- 本地原生 Python 启动 → 使用 `localhost`

### Q: data-service 热重载不生效？

`docker-compose.yml` 中的 data-service 已配置 `--reload` 和源码挂载卷，仅用于开发。生产构建请移除这两个配置。

### Q: 如何更新生产环境的数据库 schema？

推荐使用 Supabase CLI 管理迁移：

```bash
# 本地修改 schema 后生成迁移
supabase db diff -f add_new_column

# 审查后推送到生产
supabase db push
```

---

## Phase 1: OpenClaw Gateway 与微信集成部署

### 1. OpenClaw Gateway 配置

#### 安装方式

**选项 A: Docker 运行（推荐）**

```bash
# 在 docker-compose.yml 中追加 gateway 服务（参考下方配置）
docker-compose up -d openclaw-gateway
```

**选项 B: 本地 Python 运行**

```bash
cd openclaw/gateway
pip install -r requirements.txt
python -m gateway.main --config config.yaml
```

#### 配置文件字段

复制模板并编辑：

```bash
cp openclaw/gateway/config.example.yaml openclaw/gateway/config.yaml
# 按需填入环境变量或硬编码值
```

关键字段说明：

| 字段 | 说明 | 必填 |
|------|------|------|
| `gateway.port` | Gateway 监听端口 | 是（默认 8080） |
| `supabase.url` | Supabase 项目 URL | 是 |
| `supabase.service_role_key` | Supabase service_role 密钥 | 是 |
| `skills.*.api_key` | 各 Skill 独立 API Key | 是 |
| `channels.wechat_claw.webhook_url` | 微信 claw 插件 Webhook 地址 | 是（微信接入） |

#### Skill 注册方式

Gateway 启动时会自动读取 `config.yaml` 中的 `skills` 段落注册 Skill。每个 Skill 需配置：

1. `enabled`: 是否启用
2. `api_key`: 用于验证调用方身份的独立密钥
3. 各 Skill 特有的配置（如 `daily-analysis` 的 `openai_api_key` 和 `cron`）

注册后，Gateway 会：
- 为每个 Skill 生成调用端点：`POST /skills/{skill-name}/invoke`
- 在请求头中校验 `X-Skill-API-Key`
- 将调用记录写入 `audit_logs`

---

### 2. Skill-level API Key 管理

#### 在 Supabase 中创建多个 API Key

```sql
-- 方法 1: 使用 Supabase Dashboard
-- Database → Tables → api_keys → Insert Row

-- 方法 2: 通过 SQL 插入
INSERT INTO api_keys (name, key_hash, scope, skill_name, tenant_id)
VALUES (
    'trade-input-prod',
    crypt('sk-trade-input-xxxx', gen_salt('bf')),
    'skill',
    'trade-input',
    '00000000-0000-0000-0000-000000000000'  -- 全局 Skill Key
);
```

#### 每个 Skill 使用独立 Key 的原因

| 原因 | 说明 |
|------|------|
| **追踪溯源** | 通过 `audit_logs.skill_name` 精准定位哪个 Skill 产生调用 |
| **隔离风险** | 某个 Key 泄露只需轮换该 Skill 的 Key，不影响其他 Skill |
| **独立配额** | 未来可为不同 Skill 配置独立的速率限制和配额 |
| **调试排障** | 按 Skill 维度查看错误率和延迟，快速定位问题 |

---

### 3. 微信 claw 插件配置

#### 获取 Webhook URL

1. 部署 OpenClaw Gateway 后，微信 claw 插件的 Webhook 地址为：
   ```
   {OPENCLAW_GATEWAY_URL}/channels/wechat_claw/webhook
   ```
2. 如需公网访问，使用内网穿透工具（如 ngrok、Cloudflare Tunnel）：
   ```bash
   ngrok http 8080
   # 将生成的 https URL 填入 WECHAT_CLAW_WEBHOOK_URL
   ```

#### 配置消息路由到 Gateway

在微信 claw 插件管理后台：

1. 进入「插件设置」→「Webhook 配置」
2. 填写 Webhook URL：`https://your-ngrok-url/channels/wechat_claw/webhook`
3. 配置消息类型：勾选「文本消息」「图片消息」（用于接收持仓截图）
4. 设置 Context Token（用于会话隔离）

#### 测试 Pairing 流程

```bash
# 1. 启动 Gateway
docker-compose up -d openclaw-gateway

# 2. 检查 Gateway 健康状态
curl http://localhost:8080/health

# 3. 向微信发送测试消息
# 在微信中发送 "绑定账户 test-user-123"

# 4. 查看 Gateway 日志
docker-compose logs -f openclaw-gateway

# 5. 验证数据库记录
# 在 Supabase SQL Editor 中执行：
SELECT * FROM audit_logs WHERE channel = 'wechat_claw' ORDER BY created_at DESC LIMIT 5;
```

---

### 4. Quota 配置

#### 在 Supabase 中配置不同套餐的配额

```sql
-- 为单个用户设置 Pro 套餐配额
UPDATE quota_tracking
SET tier = 'pro'
WHERE tenant_id = '<user-uuid>';

-- 批量为新用户设置默认 Free 套餐
INSERT INTO quota_tracking (tenant_id, tier)
SELECT id, 'free' FROM users
ON CONFLICT (tenant_id) DO NOTHING;
```

#### 查看配额使用情况的 SQL

```sql
-- 查看所有用户当前配额状态
SELECT * FROM quota_status;

-- 查看即将超限的用户（使用比例 > 80%）
SELECT
    tenant_id,
    tier,
    daily_writes_used,
    daily_writes_limit,
    ROUND(daily_writes_used::numeric / NULLIF(daily_writes_limit, 0) * 100, 2) AS write_usage_pct
FROM quota_status
WHERE daily_writes_used::numeric / NULLIF(daily_writes_limit, 0) > 0.8;

-- 查看今日审计日志统计
SELECT
    skill_name,
    COUNT(*) AS call_count,
    COUNT(CASE WHEN status = 'error' THEN 1 END) AS error_count
FROM audit_logs
WHERE created_at >= CURRENT_DATE
GROUP BY skill_name;
```

#### 配额超限处理

当用户触发配额限制时：
1. Gateway 返回 `429 Too Many Requests` 并附带 `X-Quota-Remaining: 0`
2. 微信 claw 插件向用户推送升级提示消息
3. 管理员可在 Supabase Dashboard 手动调整 `quota_tracking.tier`

---

## 部署检查清单

- [ ] `.env` 中所有必需变量已配置
- [ ] Supabase 项目已创建且 RLS 策略已启用
- [ ] 数据库迁移已执行
- [ ] `docker-compose.yml` 中未使用 `--reload`（生产）
- [ ] Webapp 环境变量指向正确的 data-service 地址
- [ ] **Phase 1**: OpenClaw Gateway 配置文件 `config.yaml` 已创建并填写
- [ ] **Phase 1**: 各 Skill 独立 API Key 已生成并填入配置
- [ ] **Phase 1**: 微信 claw 插件 Webhook URL 已配置并测试 pairing
- [ ] **Phase 1**: Supabase 配额初始化脚本 `setup-supabase.sql` 已执行
- [ ] 敏感密钥（OpenAI、Supabase service_role）未提交到 Git
