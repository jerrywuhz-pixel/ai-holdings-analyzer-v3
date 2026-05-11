# Supabase Local / Cloud Setup

本项目把 Supabase 拆成两类配置：

- **Supabase Auth / REST / RLS**：WebApp 登录、租户级读取、service role 写入。
- **Postgres 迁移**：`supabase/migrations/*.sql` 和 `supabase/seed/*.sql`。

## 1. 当前环境状态

如果本机没有安装 `supabase` CLI、Docker 或 `psql`，仍然可以先生成项目环境变量，但不能在本机直接启动完整 Supabase。

```bash
./scripts/setup-supabase-env.sh --mode local
./scripts/verify-supabase-config.sh
```

首次运行会写入：

- `.env`
- `webapp/.env.local`

若没有本地 Supabase CLI 输出，key 会保留为 `replace-with-*` 占位符。

## 2. 本地 Supabase

安装 Supabase CLI 和 Docker Desktop 后：

```bash
supabase start
./scripts/setup-supabase-env.sh --mode local
./scripts/apply-supabase-migrations.sh --via supabase --seed
./scripts/verify-supabase-config.sh
```

本地默认地址：

- API: `http://127.0.0.1:54321`
- DB: `postgresql://postgres:postgres@127.0.0.1:54322/postgres`
- Studio: `http://127.0.0.1:54323`

## 3. Supabase Cloud

在 Supabase Dashboard 创建项目后，导出真实值再写入本地环境：

```bash
export SUPABASE_URL="https://<project-ref>.supabase.co"
export SUPABASE_ANON_KEY="<anon-key>"
export SUPABASE_SERVICE_ROLE_KEY="<service-role-key>"
export SUPABASE_DB_URL="postgresql://postgres.<project-ref>:<password>@aws-0-xxx.pooler.supabase.com:6543/postgres"

./scripts/setup-supabase-env.sh --mode cloud
./scripts/apply-supabase-migrations.sh --via psql --seed
./scripts/verify-supabase-config.sh
```

`SUPABASE_SERVICE_ROLE_KEY` 只允许服务端使用，不要暴露到浏览器端。前端只使用：

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

## 4. P0 Data Foundation 审计

应用完 migration/seed 后，至少应能覆盖下面 10 个 P0 数据块：

- tenant/account/channel binding:
  `users`, `tenant_accounts`, `channel_bindings`, `broker_connector_instances`, `broker_connections`
- asset sources:
  `asset_sources`
- portfolio views:
  `portfolio_views`, `portfolio_view_sources`
- stock/options 持仓分离:
  `portfolio_positions`, `equity_positions`, `option_positions`
- confirmation:
  `pending_actions`, `confirmation_sessions`, `confirmation_events`
- artifact registry:
  `artifact_registry`
- tool/run contract:
  `agent_runs`, `run_contracts`, `tool_contract_families`, `tool_contract_versions`, `tool_contract_bindings`
- outbox:
  `delivery_outbox`, `message_events`
- job/checkpoint:
  `hermes_jobs`, `handoff_tasks`, `handoff_progress_events`, `handoff_checkpoints`
- storage manifest:
  `market_data_manifests`

如果本机有 `psql`，可以直接跑一轮存在性检查：

```bash
psql "$SUPABASE_DB_URL" -c "
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in (
    'tenant_accounts',
    'channel_bindings',
    'broker_connector_instances',
    'broker_connections',
    'asset_sources',
    'portfolio_views',
    'portfolio_view_sources',
    'portfolio_positions',
    'equity_positions',
    'option_positions',
    'pending_actions',
    'confirmation_sessions',
    'confirmation_events',
    'artifact_registry',
    'agent_runs',
    'run_contracts',
    'tool_contract_families',
    'tool_contract_versions',
    'tool_contract_bindings',
    'delivery_outbox',
    'message_events',
    'hermes_jobs',
    'handoff_tasks',
    'handoff_progress_events',
    'handoff_checkpoints',
    'market_data_manifests'
  )
order by table_name;
"
```

如果本机还没有 `psql`/Supabase CLI，至少先做文件级检查：

```bash
test -f supabase/migrations/000024_holdings_v3_p0_schema.sql
test -f supabase/migrations/000027_broker_connector_instances.sql
test -f supabase/seed/000024_holdings_v3_p0_seed.sql
```

其中：

- `000024_holdings_v3_p0_schema.sql` 提供主要 holdings/control-plane 骨架
- `000027_broker_connector_instances.sql` 补充 user-local connector 边界
- `000024_holdings_v3_p0_seed.sql` 提供 P0 tool-contract registry 的最小 seed
