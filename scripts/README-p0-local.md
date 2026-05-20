# AI Holdings Analyzer 3.0 P0 Local Verification

## Scope

This checklist is the local integration baseline for Agent 6:

1. `docker-compose.yml` starts the shared dev stack: Postgres, Redis, MinIO, data-service, gbrain, OpenClaw, webapp.
2. `.env.example` carries P0 placeholders for MinIO/Supabase Storage, Hermes/model adapter, Futu local connector, quiet hours, and TTL policy.
3. `scripts/verify-p0.sh` runs the repo verification sequence in the required order.
4. `scripts/e2e_smoke.py` provides a mock-first E2E skeleton for:
   `tenant -> broker snapshot -> portfolio -> Sell Put -> confirmation -> delivery`
5. `openclaw.gateway.outbox_worker` provides the delivery worker entrypoint for:
   `delivery_outbox -> channel sender -> delivered / retrying / failed / expired`
6. `openclaw.gateway.post_confirmation_worker` provides the confirmation follow-through worker for:
   `job_runs(PENDING) -> trade/event/artifact handling -> pending_actions committed / retryable -> delivery_outbox receipt`

## Environment Priority

All local verify scripts now treat the current shell environment as the source of truth and only use `.env` for missing defaults.

- Exported variables win over `.env`
- `.env` fills gaps for local convenience

Example:

```bash
SUPABASE_URL=http://127.0.0.1:54321 \
SUPABASE_SERVICE_ROLE_KEY=real-service-role \
./scripts/verify-p0.sh
```

That lets you keep shared `.env` defaults in the repo without masking real local overrides.

## Local Run

```bash
cp .env.example .env
./scripts/init-local.sh
```

If Docker is not available yet, run the non-Docker local services instead:

```bash
./scripts/setup-supabase-env.sh --mode local
./scripts/start-local-services.sh
```

This starts `data-service`, `openclaw`, `webapp`, the post-confirmation worker, and the delivery outbox worker directly on the host. Local delivery defaults to `OPENCLAW_DELIVERY_MODE=log`, so queued WeChat messages are marked delivered without calling a real sender. If Supabase keys are still placeholders, the Python services run in in-memory/stub mode and the workers are skipped until Supabase is available.

MinIO buckets created automatically:

- `market-data`
- `hermes-artifacts`
- `replay-evidence`
- `tenant-media`

## P0 Verification Matrix

```bash
./scripts/verify-p0.sh
```

`verify-p0.sh` now prints a gate-oriented summary with three buckets: `required`, `optional`, `skipped`.

Required checks:

1. DB migration + seed apply against local/cloud Supabase (`supabase db push` preferred, `psql` fallback)
2. `data-service` `pytest`
3. `openclaw` smoke + `openclaw/tests`
4. `gbrain` `npm run typecheck`
5. `webapp` `npm run lint`
6. `webapp` `npm run build`
7. Futu mock smoke via `scripts/verify-futu-local.sh --mode mock`

Optional checks:

1. `gbrain` `bun run test`
2. Real Futu smoke via `--with-futu-real`
3. Live E2E smoke via `--with-live-e2e`
4. Real OpenClaw confirmation/delivery smoke via `--with-live-confirmation`

QA coverage audit for the current local P0 surface uses this 8-block mapping:

1. Bootstrap and local service startup: covered by `scripts/start-local-services.sh` and `scripts/init-local.sh`; this is a runtime prerequisite, not a required gate inside `verify-p0.sh`.
2. Tenant bootstrap contract: covered by `scripts/e2e_smoke.py` in `mock` mode and by the built-in live tenant probe when `--with-live-e2e` is enabled.
3. Broker snapshot and Futu sync: covered by required `scripts/verify-futu-local.sh --mode mock`; the real OpenD path remains optional unless `--with-futu-real` is passed.
4. Portfolio read model: covered by `data-service` tests and the real Futu smoke path; the read model prefers `broker_verified` snapshots over newer estimated/mock snapshots.
5. Sell Put analysis contract: covered by data-service tests and by the built-in live Sell Put probe when `--with-live-e2e` is enabled.
6. Confirmation intake: covered by `scripts/e2e_smoke.py` hook mode and by `scripts/live_confirmation_smoke.py` for the real local WeChat path.
7. Post-confirmation worker execution: covered by `scripts/live_confirmation_smoke.py`; it is not part of the default required gate yet.
8. Delivery and WebApp confirmation handoff: covered by `scripts/e2e_smoke.py` hook mode plus `scripts/live_confirmation_smoke.py`; `webapp` lint/build only prove compileability, not live confirmation UX.

New local preflight behavior:

- `verify-p0.sh` now warns before `webapp` build if it detects a running local dev server from `start-local-services.sh` or something already listening on `WEBAPP_PORT`.
- The warning is intentional: `npm run dev` and `npm run build` both write under `webapp/.next`, so a shared worktree can produce confusing build/dev cross-talk.
- Recommended inner loop: stop the host-started webapp with `./scripts/stop-local-services.sh` before running `./scripts/verify-p0.sh` when you want a clean production build check.

Gate rules:

- `gate: READY_FOR_NEXT_STAGE`: all required checks passed
- `gate: BLOCKED_REQUIRED_FAILURES`: at least one required check failed
- `gate: INCOMPLETE_REQUIRED_CHECKS`: a required check was intentionally skipped, such as `--skip-db-migration`

Missing dependency handling is explicit:

- Bun missing: optional Hermes runtime test is marked skipped with the install command
- Supabase CLI / `psql` missing: DB migration fails with the exact next step
- OpenD missing: real Futu stays optional and the summary explains how to opt in later

Run the full default matrix:

```bash
./scripts/verify-p0.sh
```

Run the same matrix and opt into the real Futu/OpenD check:

```bash
./scripts/verify-p0.sh --with-futu-real
```

Run the live E2E smoke after local services or smoke hooks are configured. Without external hooks, it still probes the local tenant context, Futu dry-run sync, portfolio overview, and Sell Put analysis:

```bash
./scripts/verify-p0.sh --with-live-e2e
```

Run the real local confirmation path after Supabase and OpenClaw are configured:

```bash
./scripts/verify-p0.sh --with-live-confirmation
```

Use strict mode when every E2E step must be backed by a live hook or built-in local probe. This currently requires confirmation and delivery hooks in addition to the built-in probes:

```bash
./scripts/verify-p0.sh --strict-live-e2e
```

If you only want the repo checks and have already applied migrations in the current environment:

```bash
./scripts/verify-p0.sh --skip-db-migration
```

That inner-loop shortcut is useful during development, but it will end with `gate: INCOMPLETE_REQUIRED_CHECKS` because the full release gate was not run end-to-end.

## Supabase Setup

This workspace can prepare Supabase environment variables even before a real Supabase project is connected:

```bash
./scripts/setup-supabase-env.sh --mode local
./scripts/verify-supabase-config.sh
```

If Supabase CLI and Docker are installed, start the local Supabase stack and apply the project migrations:

```bash
supabase start
./scripts/setup-supabase-env.sh --mode local
./scripts/apply-supabase-migrations.sh --via supabase --seed
```

If using Supabase Cloud, export the project URL, anon key, service role key, and database URL, then run:

```bash
./scripts/setup-supabase-env.sh --mode cloud
./scripts/apply-supabase-migrations.sh --via psql --seed
```

Detailed notes live in `supabase/README-local-setup.md`.

## 2.0 to 3.0 Upgrade Helpers

Two helper scripts are available when upgrading an existing 2.0 deployment in place. They generate SQL first, and only mutate the database when `--apply` is passed.

Migrate `routing.json` OpenClaw mappings into 3.0 channel bindings:

```bash
python3 scripts/routing_to_channel_bindings.py /path/to/routing.json \
  --output /tmp/routing-to-channel-bindings.sql

python3 scripts/routing_to_channel_bindings.py /path/to/routing.json --apply
```

Project 2.0 position snapshots into the 3.0 portfolio read model:

```bash
python3 scripts/legacy_v2_projector.py \
  --output /tmp/legacy-v2-to-v3-projector.sql

python3 scripts/legacy_v2_projector.py \
  --tenant-id <tenant_uuid> \
  --apply
```

Use `--exclude-closed` only when you intentionally want to omit zero-quantity historical positions from the initial projection. The default keeps closed positions so the 3.0 cleared-position view can support review and replay.

## GBrain Runtime Verification

GBrain is the long-term memory layer, not the portfolio fact source. Before enabling memory-backed OpenClaw/Hermes flows, verify the adapter and Hermes runtime:

```bash
./scripts/verify-gbrain-runtime.sh
```

This runs:

1. `gbrain` TypeScript typecheck
2. `gbrain` unit tests
3. Hermes runtime smoke with stub/fallback model routing
4. MCP adapter database health-check when `DATABASE_URL` or `GBRAIN_DATABASE_URL` points at a migrated Postgres database

For local P0, OpenClaw should invoke the adapter as a stdio child process via:

```bash
GBRAIN_MCP_RUNTIME=bun
GBRAIN_MCP_ADAPTER_PATH=./gbrain/src/mcp-adapter.ts
GBRAIN_DATABASE_URL=$DATABASE_URL
```

Do not treat the stdio adapter as a public network service. If a future deployment needs remote MCP, add an authenticated HTTP/SSE transport with tenant-scoped run-contract checks first.

## IMA Reference Source

IMA skills are installed under:

```bash
openclaw/skills/ima-skill
```

Configure credentials from https://ima.qq.com/agent-interface:

```bash
IMA_OPENAPI_CLIENTID=...
IMA_OPENAPI_APIKEY=...
IMA_REFERENCE_SOURCE_ENABLED=true
IMA_DEFAULT_KNOWLEDGE_BASE_ID=...
```

Verify the local install:

```bash
./scripts/verify-ima-skill.sh
```

IMA content is a reference source for research and strategy context. It must be cited through `source_refs`; it must not be treated as portfolio, broker, quote, or trade fact data.

## Outbox Worker

The confirmation path remains WeChat-first. The WebApp confirmation link is a review page; actual decisions are submitted by WeChat text or voice commands.

Run one worker batch locally:

```bash
OPENCLAW_DELIVERY_MODE=log python3 -m openclaw.gateway.outbox_worker --once
```

For real delivery, configure:

```bash
OPENCLAW_DELIVERY_MODE=webhook
OPENCLAW_DELIVERY_WEBHOOK_URL=https://example.com/openclaw/send
OPENCLAW_DELIVERY_WEBHOOK_SECRET=...
```

Webhook delivery now sends a channel-ready payload instead of the raw outbox row. The receiver should verify:

- `X-OpenClaw-Delivery-Id`
- `X-OpenClaw-Delivery-Timestamp`
- `X-OpenClaw-Delivery-Signature` (`v1=<sha256 hmac>`)

The JSON body contains `delivery_id`, `tenant_id`, `recipient`, `message`, `dedupe_key`, `content_snapshot_hash`, optional `confirmation_session_id`, and optional `source_run_id`.

## Post-Confirmation Worker

WeChat remains the main confirmation path. After a user confirms a high-attention action, the gateway creates a `job_runs` record. Run this worker to consume those jobs:

```bash
python3 -m openclaw.gateway.post_confirmation_worker --once
```

Handled P0 job types:

- `confirmed_trade_recalculate_holdings`: write a confirmed trade event, then refresh the legacy position snapshot.
- `confirmed_sell_put_draft_finalize`: store a Sell Put draft artifact; it never places an order automatically.
- `confirmed_discipline_rule_save`: store a discipline-rule artifact for downstream rule tooling.
- `confirmation_rebuild_request`: preserve the revision request without committing business facts.

Successful and retryable-failed processing both enqueue a user-readable `task_update` receipt into `delivery_outbox`. Run the outbox worker afterwards to push the receipt back to WeChat:

```bash
OPENCLAW_DELIVERY_MODE=log python3 -m openclaw.gateway.outbox_worker --once
```

## Futu Local Connector

P0 defaults to deterministic mock data so local tests are stable:

```bash
FUTU_CONNECTOR_MODE=local_mock
```

For real read-only integration, run a local sidecar that talks to Futu OpenD and exposes the data-service contract:

```bash
python3 -m local_connectors.futu_opend.server
```

Sidecar settings:

```bash
FUTU_SIDECAR_MODE=real
FUTU_SIDECAR_HOST=127.0.0.1
FUTU_SIDECAR_PORT=8765
FUTU_OPEND_HOST=127.0.0.1
FUTU_OPEND_PORT=11111
FUTU_TRD_MARKET=US
FUTU_SECURITY_FIRM=FUTUSECURITIES
FUTU_TRD_ENV=REAL
FUTU_CURRENCY=USD
FUTU_ACC_ID=0
FUTU_ACC_INDEX=0
FUTU_SDK_MODULE=futu
```

`FUTU_SECURITY_FIRM` must match the account entity exposed by OpenD. For example, `FUTUSECURITIES` is Futu Securities, while `FUTUINC` is Moomoo US; choosing the wrong entity can return cash or an empty position list from a different account boundary.

Data-service settings:

```bash
FUTU_CONNECTOR_MODE=local_connector
FUTU_CONNECTOR_BASE_URL=http://localhost:8765
FUTU_CONNECTOR_SNAPSHOT_PATH=/api/v1/snapshots
FUTU_CONNECTOR_OPTION_CHAIN_PATH=/api/v1/option-chain
FUTU_CONNECTOR_READ_ONLY=true
```

This direct HTTP mode is only the local-development path (`connector_runtime_mode=local_dev_direct`). In production, each tenant gets a `broker_connector_instances` row for their own local connector; the connector polls tenant-scoped sync jobs and uploads sanitized snapshots, so the cloud service never tries to connect to a user's `localhost` or store a Futu trading token.

The tenant-scoped polling skeleton lives in `local_connectors/futu_opend/polling.py`. It reads only connector control-plane metadata from environment variables:

```bash
FUTU_CONNECTOR_RUNTIME_MODE=user_local_polling
FUTU_CONNECTOR_TENANT_ID=<tenant-id>
FUTU_CONNECTOR_INSTANCE_ID=<connector-instance-id>
FUTU_CONNECTOR_POLL_ENDPOINT=https://control-plane.example/connectors/poll
FUTU_CONNECTOR_UPLOAD_ENDPOINT=https://control-plane.example/connectors/upload
FUTU_CONNECTOR_PAIRING_TOKEN=<pairing-token>
FUTU_CONNECTOR_CLOUD_ENABLED=false
```

`FUTU_CONNECTOR_CLOUD_ENABLED=false` is the default and keeps the connector fully offline unless you explicitly opt in. P0 still does not persist any broker trade token, does not expose order APIs, and forces `permission_scope=read_only` for both poll and upload payloads. `local_dev_direct` remains the separate localhost sidecar path and does not require `tenant_id` or `connector_instance_id` in the direct snapshot HTTP contract.

Use the smoke wrapper directly when you only want to validate the local Futu path:

```bash
./scripts/verify-futu-local.sh --mode mock
```

When `DATA_SERVICE_BASE_URL` points at localhost and no healthy data-service is running, the script will start a temporary local `data-service`, wait for `/health`, and clean it up after the smoke finishes.

You can also let the host-start script launch the sidecar:

```bash
START_FUTU_SIDECAR=true FUTU_SIDECAR_MODE=mock ./scripts/start-local-services.sh
```

The sidecar exposes only:

- `GET /health`
- `GET /api/v1/account-diagnostics`
- `POST /api/v1/snapshots`
- `POST /api/v1/option-chain`

It does not expose order placement, order modification, order cancellation, or trade unlock endpoints. The data-service will reject any Futu response that is not marked `permission_scope=read_only`. If mock fallback is explicitly enabled per request, the returned data is marked `connector_mode=local_mock`, `status=partial`, and includes `local_connector_unavailable` in `missing_fields`.

## Historical Cache Contract

P0 historical 行情查询现在明确区分三种结果，不再在缓存未命中时静默伪造完整历史数据：

- `hit`: 命中已保存 manifest 和对象内容，返回 `bars`
- `cache_miss`: 没有 manifest，或 manifest coverage 不覆盖请求区间
- `degraded`: manifest 已存在，但对象缺失、payload 无效，或 manifest freshness/status 已降级

当前最小验证面：

- 注册 manifest: `POST /api/v3/market/history/manifests`
- 查询 coverage: `GET /api/v3/market/history/coverage`
- 查询缓存历史 bars: `GET /api/quote/{symbol}/history?market=US&interval=1d&start_date=2026-05-01&end_date=2026-05-09&tenant_id=tenant-1`

`historical_store` 在 P0 内建三种 storage：

- `memory`: 默认测试路径，完全不依赖对象存储
- `file`: 本地文件系统 stub，适合临时集成验证
- `supabase_storage`: 生产对象存储路径，使用 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY` 写入 Supabase Storage

manifest 记录的标准字段至少包括：

- `tenant_id`
- `symbol`
- `market`
- `bar_interval`
- `range`
- `source`
- `storage_uri`
- `freshness`
- `status`

When debugging account-entity mismatches such as `FUTUINC` vs `FUTUSECURITIES`, first inspect the configured read context:

```bash
curl -s http://127.0.0.1:8765/health | python3 -m json.tool
curl -s http://127.0.0.1:8765/api/v1/account-diagnostics | python3 -m json.tool
```

The diagnostic payload is read-only and masks `acc_id`; it reports the current `security_firm / trd_market / trd_env / acc_id / acc_index` plus candidate entity summaries.

For a terminal-friendly matrix of common `SecurityFirm x TrdMarket` combinations, run:

```bash
python3 scripts/live_futu_account_diagnostic.py --base-url http://127.0.0.1:8765
```

The script only prints account counts, masked account identifiers, and position counts. It never prints full holdings or raw account numbers.

To validate the local Futu smoke contract without touching persisted portfolio data, run:

```bash
./scripts/verify-futu-local.sh --mode mock
```

By default this uses `SMOKE_FUTU_CONNECTOR_MODE=local_mock` with `SMOKE_FUTU_PERSIST=false`. It validates the mock contract without writing fixture data into Supabase, so a local test cannot accidentally replace a real broker-verified portfolio view.

If you intentionally want mock fixture data persisted, use a dedicated smoke tenant or opt in explicitly:

```bash
SMOKE_FUTU_MOCK_TENANT_ID=<uuid> \
SMOKE_FUTU_MOCK_PERSIST=true \
./scripts/verify-futu-local.sh --mode mock
```

Persisted broker sync writes into:

- `broker_connections`
- `asset_sources`
- `broker_sync_snapshots`
- `broker_position_snapshots`
- `cash_balance_snapshots`
- `margin_balance_snapshots`

For a real local OpenD read, start the sidecar and run:

```bash
START_FUTU_SIDECAR=true \
FUTU_SIDECAR_MODE=real \
FUTU_CONNECTOR_MODE=local_connector \
FUTU_CONNECTOR_BASE_URL=http://127.0.0.1:8765 \
./scripts/start-local-services.sh
./scripts/verify-futu-local.sh --mode real
```

Real smoke stays opt-in. The default P0 matrix does not require OpenD. If `./scripts/verify-p0.sh` notices OpenD listening on `FUTU_OPEND_HOST:FUTU_OPEND_PORT` (default `127.0.0.1:11111`), it prints a clear reminder that you can re-run with `--with-futu-real`.

When real and mock snapshots coexist in the same tenant, the portfolio read model ranks source quality first. `broker_verified` snapshots win over newer `estimated` or `public_fallback` snapshots; recency is only used inside the same quality tier.

If you are exercising a pre-created connector instance row, pass it explicitly:

```bash
SMOKE_FUTU_CONNECTOR_INSTANCE_ID=<uuid> \
SMOKE_FUTU_CONNECTOR_RUNTIME_MODE=local_dev_direct \
SMOKE_FUTU_CONNECTOR_MODE=local_connector \
python3 scripts/live_futu_sync_smoke.py
```

## Live Smoke Hook-In

The E2E smoke does not assume all P0 APIs already exist. In `live` mode it now has built-in local probes for tenant context, Futu read-only dry run, portfolio overview, and Sell Put analysis through `SMOKE_DATA_SERVICE_BASE_URL` or `DATA_SERVICE_BASE_URL`. Confirmation and delivery remain hook-driven because the main user path is WeChat confirmation.

When other agents expose hooks, wire them through `.env`:

```bash
SMOKE_TENANT_ENDPOINT=http://localhost:8000/api/p0/smoke/tenant
SMOKE_BROKER_SNAPSHOT_ENDPOINT=http://localhost:8000/api/p0/smoke/broker-snapshot
SMOKE_PORTFOLIO_ENDPOINT=http://localhost:8000/api/p0/smoke/portfolio
SMOKE_SELL_PUT_ENDPOINT=http://localhost:8000/api/p0/smoke/sell-put
SMOKE_CONFIRMATION_ENDPOINT=http://localhost:8080/api/p0/smoke/confirmation
SMOKE_DELIVERY_ENDPOINT=http://localhost:8080/api/p0/smoke/delivery
python3 scripts/e2e_smoke.py --mode live
```

Unset hooks are reported as `skipped`, not failed, so parallel delivery can continue while interfaces are landing.
Add `--strict-live` when skipped steps should fail the smoke.

For the real local WeChat confirmation path, run:

```bash
python3 scripts/live_confirmation_smoke.py
```

This creates or updates a local `openclaw_wechat` channel binding, sends a real text trade input to OpenClaw, confirms it with the returned token, runs the post-confirmation worker once, runs the outbox worker once in log mode, then verifies:

- `pending_actions` is committed
- `confirmation_sessions` is consumed
- `job_runs` succeeded
- `trade_events` has the confirmed AAPL buy
- `position_snapshots` has an AAPL snapshot
- `delivery_outbox` has both the confirmation card and the post-confirmation receipt

## Productionization Switches

The production path uses the same code contracts with stricter env gates:

```bash
cp .env.production.example .env.production

OPENCLAW_DELIVERY_MODE=webhook
GBRAIN_LIVE_MODELS_ENABLED=true
HERMES_ARTIFACT_STORAGE_BACKEND=supabase
HERMES_ARTIFACT_BASE_URI=supabase://artifacts
HISTORICAL_STORAGE_BACKEND=supabase_storage
FX_RATES_SOURCE=trusted_http_fx
FX_RATE_ENDPOINT=https://fx.example/latest
SENTRY_DSN=https://...
WEBAPP_BASE_URL=https://app.example.com
CORS_ALLOWED_ORIGINS=https://app.example.com
```

Filled production env files are intentionally ignored by `.gitignore`.

Before cutting traffic to a cloud environment, run the full preflight:

```bash
./scripts/deploy-cloud.sh --target preflight
```

It checks Google Cloud CLI availability, active project/auth, required runtime tools, and the production env readiness gate. You can run the env-only gate directly:

```bash
python3 scripts/production_readiness.py --profile production
```

This checks database credentials, signed delivery webhook config, live model provider keys, artifact storage, historical storage, trusted FX, Sentry, and public WebApp/CORS origins. Local development can use:

```bash
python3 scripts/production_readiness.py --profile local
```

Local profile downgrades missing production hooks to warnings so local smoke work can continue.

For the single-server Aliyun first stage, use:

```bash
python3 scripts/production_readiness.py --profile lightweight
```

Lightweight profile still requires Web origins, artifact/historical storage, and MiniMax light-model routing, but allows local auth, log delivery, fallback FX, and missing deep OpenAI/Codex auth to remain warnings until production cutover.
On a lightweight server, pass the server env file explicitly:

```bash
python3 scripts/production_readiness.py --profile lightweight --env-file .env.server
```

After Cloud Run deployment, run the deployment monitor:

```bash
python3 scripts/cloud_deployment_monitor.py \
  --project "$GCP_PROJECT_ID" \
  --region "${GCP_REGION:-asia-southeast1}"
```

It verifies Cloud Run Ready status for `openclaw-gateway` and `data-service`, probes Gateway `/health`, and checks the four P0 Cloud Scheduler jobs: `daily-market-scan`, `daily-profit-taking`, `heartbeat-check`, and `stale-jobs-check`.
