#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlencode
import uuid
from datetime import datetime, timezone

TASK = os.getenv("P0_TASK") or os.path.basename(sys.argv[0]).replace(".sh", "")
LOG = os.getenv("P0_CRON_LOG", "/root/.hermes/cron/p0-task-runs.jsonl")
DATA_SERVICE = os.getenv("P0_DATA_SERVICE_URL") or os.getenv("DATA_SERVICE_URL") or "http://127.0.0.1:8000"
WEBAPP = os.getenv("P0_WEBAPP_URL", "http://127.0.0.1:3000")
HERMES = os.getenv("P0_HERMES_BIN", "/usr/local/lib/hermes-agent/venv/bin/hermes")
DEPLOY_DIR = os.getenv("P0_DEPLOY_DIR", "/opt/ai-holdings-analyzer-v3")
POSTGRES_CONTAINER = os.getenv("P0_POSTGRES_CONTAINER", "ai-holdings-server-postgres-1")
POSTGRES_DB = os.getenv("P0_POSTGRES_DB", "ai_holdings")
POSTGRES_USER = os.getenv("P0_POSTGRES_USER", "postgres")
WEBAPP_CONTAINER = os.getenv("P0_WEBAPP_CONTAINER", "ai-holdings-server-webapp-1")
DELIVERY_WEBHOOK = os.getenv("P0_DELIVERY_WEBHOOK", WEBAPP.rstrip("/") + "/api/hermes/delivery/wechat")
DRY_RUN = os.getenv("P0_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}
LOCAL_SYNC_NS = uuid.uuid5(uuid.NAMESPACE_URL, "ai-holdings-v3-local-holdings-sync")

# These tasks are account/holding-facing.  They must expand to every active
# WeChat binding whose tenant has holding data and enqueue a delivery_outbox row.
HOLDING_PUSH_TASKS = set([
    "p0-broker-sync-planner",
    "p0-broker-sync-staleness",
    "p0-market-watchlist-refresh",
    "p0-price-alert-evaluator",
    "p0-cn-close-summary",
    "p0-us-close-summary",
    "p0-weekly-review",
    "p0-backup-verify",
    "p0-opportunity-research-cn-hk-premarket",
    "p0-opportunity-research-us-premarket",
    "p0-opportunity-research-daily-review",
])

PLATFORM_NO_PUSH_TASKS = set([
    "p0-health-heartbeat",
    "p0-delivery-retry",
])

# High-frequency routine checks should stay silent when the result is normal.
# They only notify WeChat on a real alert/degradation/signal. Otherwise they are
# system progress noise, not a user-facing investment update.
ROUTINE_OK_SILENT_TASKS = set([
    "p0-broker-sync-planner",
    "p0-broker-sync-staleness",
    "p0-market-watchlist-refresh",
    "p0-price-alert-evaluator",
    "p0-backup-verify",
])

# Close-summary jobs are user-facing digests. They must be visible in every
# ready local WeChat binding, not just whichever product channel_binding was
# populated, and not silently dependent on the product WebApp bridge.
SUMMARY_DIRECT_FANOUT_TASKS = set([
    "p0-cn-close-summary",
    "p0-us-close-summary",
])

TASK_LABELS = {
    "p0-broker-sync-planner": "券商同步计划检查",
    "p0-broker-sync-staleness": "持仓数据新鲜度检查",
    "p0-market-watchlist-refresh": "市场关注清单刷新",
    "p0-price-alert-evaluator": "价格提醒评估",
    "p0-cn-close-summary": "A股/港股收盘摘要",
    "p0-us-close-summary": "美股收盘摘要",
    "p0-weekly-review": "每周持仓复盘",
    "p0-backup-verify": "持仓系统备份校验",
    "p0-opportunity-research-cn-hk-premarket": "A股/港股盘前机会研究",
    "p0-opportunity-research-us-premarket": "美股盘前机会研究",
    "p0-opportunity-research-daily-review": "机会研究每日复盘",
}

SUPPRESSED_STALE_BACKLOG_PREFIX = "suppressed stale backlog"
BLOCKED_DELIVERY_CONTENT_TYPES = set([
    "confirmation_card",
    "task_update",
    "system_message",
    "system",
])

MARKET_PROXY_UNIVERSE = {
    "US": [
        {"sector": "美股大盘", "symbol": "SPY", "name": "S&P 500 ETF", "role": "benchmark"},
        {"sector": "纳指科技", "symbol": "QQQ", "name": "Nasdaq 100 ETF", "role": "sector"},
        {"sector": "半导体", "symbol": "SMH", "name": "Semiconductor ETF", "role": "sector"},
        {"sector": "小盘股", "symbol": "IWM", "name": "Russell 2000 ETF", "role": "sector"},
        {"sector": "金融", "symbol": "XLF", "name": "Financials ETF", "role": "sector"},
        {"sector": "能源", "symbol": "XLE", "name": "Energy ETF", "role": "sector"},
        {"sector": "医疗", "symbol": "XLV", "name": "Healthcare ETF", "role": "sector"},
        {"sector": "可选消费", "symbol": "XLY", "name": "Consumer Discretionary ETF", "role": "sector"},
        {"sector": "公用事业", "symbol": "XLU", "name": "Utilities ETF", "role": "sector"},
    ],
    "HK": [
        {"sector": "港股大盘", "symbol": "HK02800", "name": "盈富基金", "role": "benchmark"},
        {"sector": "恒生科技", "symbol": "HK03033", "name": "南方恒生科技", "role": "sector"},
        {"sector": "国企指数", "symbol": "HK02828", "name": "恒生中国企业", "role": "sector"},
        {"sector": "港股高股息", "symbol": "HK03110", "name": "高股息代理", "role": "sector"},
    ],
    "CN": [
        {"sector": "A股大盘", "symbol": "SH510300", "name": "沪深300ETF", "role": "benchmark"},
        {"sector": "创业板", "symbol": "SZ159915", "name": "创业板ETF", "role": "sector"},
        {"sector": "科创50", "symbol": "SH588000", "name": "科创50ETF", "role": "sector"},
        {"sector": "半导体", "symbol": "SH512480", "name": "半导体ETF", "role": "sector"},
        {"sector": "证券", "symbol": "SH512880", "name": "证券ETF", "role": "sector"},
        {"sector": "医药", "symbol": "SH512010", "name": "医药ETF", "role": "sector"},
        {"sector": "新能源车", "symbol": "SH515030", "name": "新能源车ETF", "role": "sector"},
        {"sector": "消费", "symbol": "SH510150", "name": "消费ETF", "role": "sector"},
    ],
}

SYMBOL_NAME_FALLBACK = {
    "SH688521": "芯原股份",
    "SZ300442": "润泽科技",
    "SH688008": "澜起科技",
    "SZ002384": "东山精密",
    "SZ002240": "盛新锂能",
    "SZ300757": "罗博特科",
}

_MARKET_REFRESH_CACHE = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def run(cmd, timeout=10, input_text=None):
    try:
        p = subprocess.run(
            cmd,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
        )
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as exc:
        return 999, str(exc)


def get(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(500).decode("utf-8", "replace")
            return 200 <= resp.status < 500, "http=%s %s" % (resp.status, body[:160])
    except Exception as exc:
        return False, str(exc)


def post_json(url, payload, headers=None, timeout=45):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(8000).decode("utf-8", "replace")
        parsed = json.loads(raw) if raw else {}
        return 200 <= resp.status < 300, parsed, None
    except Exception as exc:
        return False, None, str(exc)


def internal_key():
    env_file = os.path.join(DEPLOY_DIR, ".env.server")
    for key in ("HERMES_DOMAIN_TOOLS_KEY", "HERMES_INTERNAL_TOKEN"):
        value = os.getenv(key)
        if value:
            return value
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                key, value = line.rstrip("\n").split("=", 1)
                if key in {"HERMES_DOMAIN_TOOLS_KEY", "HERMES_INTERNAL_TOKEN"} and value:
                    return value
    except Exception:
        return ""
    return ""


def record(status, details):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    entry = {"ts": now(), "task": TASK, "status": status, "details": details}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def archive_cron_output(status, details):
    label = TASK_LABELS.get(TASK, TASK)
    message = task_message(details) if TASK in TASK_LABELS or TASK.startswith("p0-") else json.dumps(details, ensure_ascii=False, indent=2)
    payload = {
        "source": "scheduled_task",
        "title": "Hermes 定时任务 - %s" % label,
        "content_markdown": (
            "## %s\n\n"
            "- task: `%s`\n"
            "- status: `%s`\n"
            "- generated_at: `%s`\n\n"
            "### 输出\n\n%s\n\n"
            "### details\n\n```json\n%s\n```"
        ) % (label, TASK, status, now(), message, json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True)),
        "payload": {"task": TASK, "status": status, "details": details},
        "result_type": TASK,
        "metadata": {"dry_run": DRY_RUN, "archive_caller": "p0_cron_dispatcher"},
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    key = internal_key()
    if key:
        headers["X-Hermes-Internal-Token"] = key
    req = urllib.request.Request(
        DATA_SERVICE.rstrip("/") + "/api/hermes/ima/archive",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read(4000).decode("utf-8", "replace")
        parsed = json.loads(raw) if raw else {}
        archive = parsed.get("archive") if isinstance(parsed, dict) else {}
        return {
            "status": archive.get("status") or ("ok" if 200 <= resp.status < 300 else "failed"),
            "path": archive.get("path"),
            "ima": archive.get("ima"),
        }
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)[:500]}


def psql(sql, timeout=20):
    cmd = [
        "docker", "exec", "-i", POSTGRES_CONTAINER,
        "psql", "-U", POSTGRES_USER, "-d", POSTGRES_DB,
        "-v", "ON_ERROR_STOP=1", "-At",
    ]
    return run(cmd, timeout=timeout, input_text=sql)


def psql_json(sql, timeout=20):
    code, out = psql(sql, timeout=timeout)
    if code != 0:
        return False, out, None
    text = out.strip()
    if not text:
        return True, text, []
    try:
        return True, text, json.loads(text)
    except Exception as exc:
        return False, "failed to parse psql json: %s; output=%s" % (exc, text[:400]), None


def eligible_accounts():
    sql = r"""
WITH active_bindings AS (
  SELECT DISTINCT ON (tenant_id)
    tenant_id::text AS tenant_id,
    id::text AS channel_binding_id,
    channel::text AS channel,
    COALESCE(channel_account_id, openclaw_account_id, '') AS channel_account_id,
    COALESCE(openclaw_account_id, '') AS openclaw_account_id,
    COALESCE(channel_user_ref, '') AS target_conversation,
    COALESCE(binding_metadata->>'context_token', '') AS context_token,
    is_primary,
    COALESCE(bound_at, updated_at, created_at) AS binding_time
  FROM public.channel_bindings
  WHERE binding_status = 'active'
    AND channel::text IN ('hermes_wechat', 'openclaw_wechat')
  ORDER BY tenant_id, is_primary DESC, COALESCE(bound_at, updated_at, created_at) DESC
), portfolio_counts AS (
  SELECT tenant_id::text AS tenant_id, COUNT(*)::int AS count
  FROM public.portfolio_positions
  WHERE position_status::text IN ('open', 'closing', 'stale')
    AND quantity > 0
  GROUP BY tenant_id
), manual_counts AS (
  SELECT tenant_id::text AS tenant_id, COUNT(*)::int AS count
  FROM public.webapp_manual_positions
  WHERE position_status::text = 'open'
    AND quantity > 0
  GROUP BY tenant_id
), merged AS (
  SELECT
    b.tenant_id,
    b.channel_binding_id,
    b.channel,
    b.channel_account_id,
    b.openclaw_account_id,
    b.target_conversation,
    b.context_token,
    COALESCE(p.count, 0) AS portfolio_positions_count,
    COALESCE(m.count, 0) AS manual_positions_count,
    COALESCE(p.count, 0) + COALESCE(m.count, 0) AS holdings_count
  FROM active_bindings b
  LEFT JOIN portfolio_counts p ON p.tenant_id = b.tenant_id
  LEFT JOIN manual_counts m ON m.tenant_id = b.tenant_id
)
SELECT COALESCE(json_agg(row_to_json(merged)), '[]'::json) FROM merged;
"""
    ok, raw, rows = psql_json(sql)
    if not ok:
        return "alert", {"gate_error": raw}, []
    active = rows or []
    eligible = [row for row in active if int(row.get("holdings_count") or 0) > 0]
    skipped_empty = [row for row in active if int(row.get("holdings_count") or 0) <= 0]
    return "ok", {
        "active_wechat_bindings": len(active),
        "eligible_accounts": len(eligible),
        "skipped_empty_holdings": len(skipped_empty),
        "eligible_tenants": [row.get("tenant_id") for row in eligible],
        "skipped_empty_tenants": [row.get("tenant_id") for row in skipped_empty],
    }, eligible


def health():
    ok_data, data_msg = get(DATA_SERVICE + "/health")
    ok_web, web_msg = get(WEBAPP)
    code, cron_msg = run([HERMES, "cron", "status"], timeout=12)
    docker_code, docker_msg = run(["docker", "ps", "--format", "{{.Names}} {{.Status}}"], timeout=8)
    required = ["ai-holdings-server-webapp-1", "ai-holdings-server-data-service-1", "ai-holdings-server-postgres-1", "ai-holdings-server-redis-1"]
    missing = [name for name in required if name not in docker_msg]
    status = "ok" if ok_data and ok_web and code == 0 and docker_code == 0 and not missing else "alert"
    return status, {"data_service": data_msg, "webapp": web_msg, "cron_status_ok": code == 0, "missing_containers": missing}


def backup_verify():
    code, pg = run(["docker", "exec", POSTGRES_CONTAINER, "pg_isready", "-U", POSTGRES_USER], timeout=8)
    code2, minio = run(["docker", "exec", "ai-holdings-server-minio-1", "mc", "ready", "local"], timeout=8)
    status = "ok" if code == 0 else "alert"
    return status, {"postgres_ready": code == 0, "postgres_msg": pg[:200], "minio_probe_code": code2, "minio_msg": minio[:200]}


def task_probe_details():
    if TASK == "p0-backup-verify":
        return backup_verify()
    ok_data, data_msg = get(DATA_SERVICE + "/health")
    if not ok_data:
        return "alert", {"data_service": data_msg, "reason": "data-service unavailable before account expansion"}
    return "ok", {"data_service": data_msg}


def task_message(details):
    label = TASK_LABELS.get(TASK, TASK)
    sh_time = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    if TASK == "p0-broker-sync-staleness":
        reason = details.get("reason") or details.get("data_service") or "同步链路或持仓更新时间需要复核"
        return (
            "【抓钱小螃蟹】数据质量提醒｜持仓同步\n"
            f"时间：{sh_time}\n"
            f"问题：{str(reason)[:120]}\n"
            "影响：持仓、盈亏或规则命中可能不是最新状态。\n"
            "建议：先观察，不按本轮数据做加仓/减仓决定；优先触发一次实时持仓分析。\n"
            "actionability：只能观察\n"
            "degrade_reason：holding_freshness_degraded\n"
            "行动等级：info_only。不会改动持仓，也不会下单。"
        )
    if TASK == "p0-price-alert-evaluator":
        reason = details.get("reason") or details.get("data_service") or "价格提醒评估链路返回异常或命中待复核信号"
        return (
            "【抓钱小螃蟹】价格/纪律提醒｜待复核\n"
            f"时间：{sh_time}\n"
            f"触发：{str(reason)[:120]}\n"
            "影响：可能存在止盈、止损、波动放大或纪律规则命中。\n"
            "建议：先看标的实时分析，再决定是否处理；不建议只凭本条消息交易。\n"
            "actionability：只能观察\n"
            "degrade_reason：rule_signal_requires_detail\n"
            "行动等级：info_only。不会改动持仓，也不会下单。"
        )
    if TASK == "p0-market-watchlist-refresh":
        reason = details.get("reason") or details.get("data_service") or "市场/关注清单刷新链路需要复核"
        return (
            "【抓钱小螃蟹】市场机会提醒｜关注清单\n"
            f"时间：{sh_time}\n"
            f"状态：{str(reason)[:120]}\n"
            "机会：刷新强势板块、异动标的和风险板块后，再进入个股分析。\n"
            "风险：若市场数据缺失，本轮只作为观察线索。\n"
            "actionability：只能观察\n"
            "degrade_reason：market_watchlist_requires_detail\n"
            "行动等级：info_only。不会改动持仓，也不会下单。"
        )
    if TASK == "p0-backup-verify":
        if details.get("postgres_ready"):
            status_line = "Postgres 可用，备份/对象存储探针已完成。"
            actionability = "只能观察"
            reason = "none"
        else:
            status_line = "Postgres 探针异常，需要人工查看；恢复能力不应被视为可用。"
            actionability = "数据过期"
            reason = "postgres_backup_probe_failed"
        return (
            "【抓钱小螃蟹】数据可恢复性告警\n"
            f"时间：{sh_time}\n"
            f"状态：{status_line}\n"
            f"actionability：{actionability}\n"
            f"degrade_reason：{reason}\n"
            "行动等级：info_only。不会改动持仓，也不会下单。"
        )
    if TASK.startswith("p0-opportunity-research"):
        summary = details.get("summary") if isinstance(details.get("summary"), dict) else {}
        counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
        reason = details.get("reason") or summary.get("title") or "机会研究 workflow 已完成或需要复核"
        return (
            "【抓钱小螃蟹】机会研究工作流\n"
            f"时间：{sh_time}\n"
            f"状态：{str(reason)[:160]}\n"
            f"产出：cases={counts.get('cases', details.get('cases_created', '未知'))}；trade_drafts={counts.get('trade_drafts', '未知')}\n"
            "收益口径：信号账本 paper P&L，不代表真实成交，不自动下单。\n"
            "行动等级：analysis_only/suggested_action/trade_draft 由四道门决定。"
        )
    status_line = "本轮检查已进入持仓运营链路。"
    return (
        f"【抓钱小螃蟹】{label}\n"
        f"时间：{sh_time}\n"
        f"状态：{status_line}\n"
        "行动等级：info_only。不会改动持仓，也不会下单。"
    )


def enqueue_for_accounts(accounts, probe_status, probe_details, message_builder=None):
    if DRY_RUN:
        return {"dry_run": True, "enqueued": 0, "target_accounts": len(accounts)}
    dedupe_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    rows = []
    label = TASK_LABELS.get(TASK, TASK)
    for account in accounts:
        tenant_id = account["tenant_id"]
        content = {
            "title": label,
            "text": message_builder(account) if message_builder else task_message(probe_details),
            "task": TASK,
            "probe_status": probe_status,
            "holdings_count": account.get("holdings_count"),
            "portfolio_positions_count": account.get("portfolio_positions_count"),
            "manual_positions_count": account.get("manual_positions_count"),
            "generated_at": now(),
        }
        content_bytes = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        rows.append({
            "tenant_id": tenant_id,
            "channel_binding_id": account["channel_binding_id"],
            "openclaw_account_id": account.get("openclaw_account_id") or account.get("channel_account_id"),
            "target_conversation": account.get("target_conversation") or None,
            "context_token": account.get("context_token") or None,
            "content_type": "portfolio_cron_update",
            "content": content,
            "content_snapshot_hash": hashlib.sha256(content_bytes).hexdigest(),
            "content_summary": {"title": label, "task": TASK, "probe_status": probe_status},
            "dedupe_key": f"{TASK}:{tenant_id}:{dedupe_bucket}",
            "priority": "normal" if probe_status in {"ok", "guarded"} else "high",
            "source_run_id": None,
            "asset_source_refs": [{"kind": "holding_push_task", "task": TASK}],
            "data_snapshot_refs": [{"kind": "probe", "status": probe_status, "details": probe_details}],
        })
    payload = json.dumps(rows, ensure_ascii=False)
    sql = r"""
WITH payload AS (
  SELECT jsonb_array_elements($json$%s$json$::jsonb) AS item
), inserted AS (
  INSERT INTO public.delivery_outbox (
    id, tenant_id, channel_binding_id, source_run_id, openclaw_account_id,
    content_type, content, content_snapshot_hash, content_summary, priority,
    dedupe_key, status, attempt_count, next_retry_at, target_conversation,
    context_token, asset_source_refs, data_snapshot_refs, created_at, updated_at
  )
  SELECT
    gen_random_uuid(),
    (item->>'tenant_id')::uuid,
    (item->>'channel_binding_id')::uuid,
    NULL,
    NULLIF(item->>'openclaw_account_id', ''),
    item->>'content_type',
    item->'content',
    item->>'content_snapshot_hash',
    item->'content_summary',
    item->>'priority',
    item->>'dedupe_key',
    'pending'::public.outbox_status,
    0,
    now(),
    NULLIF(item->>'target_conversation', ''),
    NULLIF(item->>'context_token', ''),
    COALESCE(item->'asset_source_refs', '[]'::jsonb),
    COALESCE(item->'data_snapshot_refs', '[]'::jsonb),
    now(),
    now()
  FROM payload
  ON CONFLICT (tenant_id, dedupe_key) DO NOTHING
  RETURNING id::text
)
SELECT json_build_object('inserted', (SELECT count(*) FROM inserted), 'target_accounts', (SELECT count(*) FROM payload));
""" % payload.replace("$json$", "$ json $")
    ok, raw, result = psql_json(sql, timeout=20)
    if not ok:
        return {"enqueue_error": raw}
    return result or {}


def opportunity_task_spec():
    if TASK == "p0-opportunity-research-cn-hk-premarket":
        return "opportunity.research.run", {
            "market": "CN_HK",
            "session_type": "premarket",
            "universe_policy": "holdings_watchlist_hard_tech",
        }
    if TASK == "p0-opportunity-research-us-premarket":
        return "opportunity.research.run", {
            "market": "US",
            "session_type": "premarket",
            "universe_policy": "holdings_watchlist_hard_tech",
        }
    if TASK == "p0-opportunity-research-daily-review":
        return "opportunity.review.run", {"market": None}
    return "", {}


def invoke_domain_tool(tool, arguments, tenant_id):
    headers = {}
    key = internal_key()
    if key:
        headers["X-Hermes-Internal-Token"] = key
    ok, parsed, error = post_json(
        DATA_SERVICE.rstrip("/") + "/api/hermes/domain-tools/invoke",
        {"tool": tool, "tenant_id": tenant_id, "arguments": arguments},
        headers=headers,
        timeout=90,
    )
    if not ok:
        return {"ok": False, "error": error or "domain tool request failed", "response": parsed}
    return parsed or {}


def opportunity_research_task(accounts):
    tool, base_args = opportunity_task_spec()
    if not tool:
        return "alert", {"reason": "unknown_opportunity_task"}
    if DRY_RUN:
        return "ok", {"mode": "opportunity_research_workflow", "dry_run": True, "tool": tool, "target_accounts": len(accounts)}
    results = []
    failed = 0
    cases_created = 0
    for account in accounts:
        tenant_id = account.get("tenant_id")
        args = dict(base_args)
        args["tenant_id"] = tenant_id
        args["report_date"] = datetime.now().date().isoformat()
        args["delivery_context"] = {
            "channel_binding_id": account.get("channel_binding_id"),
            "openclaw_account_id": account.get("openclaw_account_id") or account.get("channel_account_id"),
            "target_conversation": account.get("target_conversation") or None,
            "context_token": account.get("context_token") or None,
        }
        result = invoke_domain_tool(tool, args, tenant_id)
        result_payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        data = result_payload.get("data") if isinstance(result_payload.get("data"), dict) else {}
        cases_created += len(data.get("cases") or []) if isinstance(data.get("cases"), list) else 0
        if not result.get("ok"):
            failed += 1
        results.append(
            {
                "tenant_id": tenant_id,
                "ok": bool(result.get("ok")),
                "status": result_payload.get("status") or result_payload.get("error"),
                "summary": data.get("summary") if isinstance(data.get("summary"), dict) else None,
                "persistence": data.get("persistence") if isinstance(data.get("persistence"), dict) else None,
            }
        )
    retry_status, retry_details = delivery_retry()
    status = "ok" if failed == 0 and retry_status == "ok" else "alert"
    return status, {
        "mode": "opportunity_research_workflow",
        "tool": tool,
        "target_accounts": len(accounts),
        "failed": failed,
        "cases_created": cases_created,
        "results": results[:10],
        "delivery_retry": retry_details,
    }


def local_eligible_bindings(include_without_holdings=False):
    db_path = os.getenv("P0_LOCAL_HOLDINGS_DB", "/root/.hermes/holdings/holdings.db")
    if not os.path.exists(db_path):
        return []
    try:
        import sqlite3
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        try:
            join_kind = "LEFT JOIN" if include_without_holdings else "JOIN"
            where_extra = "" if include_without_holdings else "AND p.symbol IS NOT NULL"
            rows = con.execute(
                f"""
                SELECT
                  b.owner_id,
                  b.wechat_bot_id,
                  b.wechat_user_id,
                  b.weixin_token,
                  b.weixin_base_url,
                  b.context_token,
                  b.hermes_profile,
                  COUNT(p.symbol) AS holdings_count
                FROM wechat_bindings b
                {join_kind} positions p
                  ON p.owner_id = b.wechat_user_id
                 AND p.quantity > 0
                WHERE COALESCE(b.channel_status, 'ready') = 'ready'
                  {where_extra}
                GROUP BY b.owner_id, b.wechat_bot_id, b.wechat_user_id,
                         b.weixin_token, b.weixin_base_url, b.context_token, b.hermes_profile
                ORDER BY b.created_at ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()
    except Exception as exc:
        return [{"error": str(exc)}]


def local_binding_for_tenant(tenant_id):
    """Find local holdings.db WeChat credential for a product tenant UUID.

    Product tenants created from local holdings use uuid5(NS, f"tenant:{wechat_user_id}").
    This fallback keeps scheduled user-facing reminders deliverable when the product
    WebApp credential bridge is degraded.
    """
    wanted = str(tenant_id or "")
    for row in local_eligible_bindings():
        if row.get("error"):
            continue
        wechat_user_id = row.get("wechat_user_id") or ""
        if str(uuid.uuid5(LOCAL_SYNC_NS, f"tenant:{wechat_user_id}")) == wanted:
            return row
    return None


def delivery_row_text(row):
    content = row.get("content") or {}
    if isinstance(content, dict):
        text = content.get("text") or content.get("message") or content.get("summary")
        title = content.get("title") or TASK_LABELS.get(content.get("task"), content.get("task"))
        if text:
            return str(text)
        if title:
            return "【抓钱小螃蟹】%s\n行动等级：info_only。不会改动持仓，也不会下单。" % title
    return "【抓钱小螃蟹】定时任务提醒\n行动等级：info_only。不会改动持仓，也不会下单。"


def local_fallback_for_delivery_row(row):
    binding = local_binding_for_tenant(row.get("tenant_id"))
    if not binding:
        return {"error": "no_local_binding_for_tenant", "tenant_id": row.get("tenant_id")}
    return send_local_binding_message(binding, delivery_row_text(row))


def local_holdings_count():
    bindings = [row for row in local_eligible_bindings() if not row.get("error")]
    return sum(int(row.get("holdings_count") or 0) for row in bindings)


def local_fallback_stdout(probe_status, probe_details, holdings_count):
    label = TASK_LABELS.get(TASK, TASK)
    sh_time = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    if probe_status == "alert":
        status_line = "本轮检查发现依赖异常，请查看系统日志。"
    else:
        status_line = "本轮检查已完成。"
    return (
        f"【抓钱小螃蟹】{label}\n"
        f"时间：{sh_time}\n"
        f"本地持仓库：已检测到 {holdings_count} 条持仓记录\n"
        f"状态：{status_line}\n"
        "行动等级：info_only。不会改动持仓，也不会下单。"
    )


def send_local_binding_message(binding, message):
    if DRY_RUN:
        return {"dry_run": True, "wechat_user_id": binding.get("wechat_user_id"), "holdings_count": binding.get("holdings_count")}
    token = binding.get("weixin_token") or ""
    chat_id = binding.get("wechat_user_id") or ""
    account_id = binding.get("wechat_bot_id") or ""
    base_url = (binding.get("weixin_base_url") or "https://ilinkai.weixin.qq.com").rstrip("/")
    if not token or not chat_id or not account_id:
        return {"error": "missing_local_wechat_credential", "wechat_user_id": chat_id}
    try:
        import asyncio
        sys.path.insert(0, "/usr/local/lib/hermes-agent")
        from gateway.platforms.weixin import send_weixin_direct

        async def _send():
            return await send_weixin_direct(
                extra={
                    "account_id": account_id,
                    "base_url": base_url,
                    "token": token,
                },
                token=token,
                chat_id=chat_id,
                message=message,
                media_files=None,
            )

        result = asyncio.run(_send())
        if isinstance(result, dict) and not result.get("error"):
            return result
        helper_error = result.get("error") if isinstance(result, dict) else str(result)
    except Exception as exc:
        helper_error = str(exc)[:300]

    # Minimal urllib fallback for cron environments where Hermes' optional aiohttp
    # dependency is not importable. This mirrors gateway.platforms.weixin._send_message.
    try:
        import base64
        import secrets
        endpoint = "ilink/bot/sendmessage"
        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": chat_id,
                "client_id": "p0-cron-" + uuid.uuid4().hex,
                "message_type": 2,
                "message_state": 2,
                "item_list": [{"type": 1, "text_item": {"text": message}}],
            },
            "base_info": {"channel_version": "2.2.0"},
        }
        if binding.get("context_token"):
            payload["msg"]["context_token"] = binding.get("context_token")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        uin = base64.b64encode(str(int.from_bytes(secrets.token_bytes(4), "big")).encode("utf-8")).decode("ascii")
        req = urllib.request.Request(
            f"{base_url}/{endpoint}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "AuthorizationType": "ilink_bot_token",
                "Content-Length": str(len(body)),
                "X-WECHAT-UIN": uin,
                "iLink-App-Id": "bot",
                "iLink-App-ClientVersion": os.getenv("WECHAT_ILINK_CLIENT_VERSION", "2.0.0"),
                "Authorization": "Bearer " + token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(1000).decode("utf-8", "replace")
        parsed = json.loads(raw) if raw else {}
        errcode = parsed.get("errcode", parsed.get("code", 0)) if isinstance(parsed, dict) else 0
        if errcode not in (0, None, "0"):
            return {"error": "Weixin direct fallback failed", "helper_error": helper_error, "api_response": parsed}
        return {"success": True, "platform": "weixin", "chat_id": chat_id, "fallback": "urllib", "helper_error": helper_error}
    except Exception as exc:
        return {"error": str(exc)[:500], "helper_error": helper_error, "wechat_user_id": chat_id}


def send_local_fallback_to_all(bindings, probe_status, probe_details):
    sent = 0
    failed = 0
    results = []
    for binding in bindings:
        msg = local_fallback_stdout(probe_status, probe_details, int(binding.get("holdings_count") or 0))
        result = send_local_binding_message(binding, msg)
        ok = bool(result.get("success") or result.get("dry_run")) and not result.get("error")
        if ok:
            sent += 1
        else:
            failed += 1
        safe = dict(result)
        if safe.get("token"):
            safe["token"] = "***"
        results.append(safe)
    return {"sent": sent, "failed": failed, "results": results[:5]}


def _safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _fmt_qty(value):
    number = _safe_float(value)
    if number is None:
        return str(value or "-")
    if abs(number - int(number)) < 0.000001:
        return str(int(number))
    return ("%.3f" % number).rstrip("0").rstrip(".")


def _fmt_pct(value):
    number = _safe_float(value)
    if number is None:
        return "n/a"
    return "%+.2f%%" % number


def _fmt_price(value):
    number = _safe_float(value)
    if number is None:
        return "n/a"
    return ("%.3f" % number).rstrip("0").rstrip(".")


def _parse_date(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text[:10])
    except Exception:
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None


def _markets_for_summary_task():
    return ["US"] if TASK == "p0-us-close-summary" else ["CN", "HK"]


def market_context_for_summary(markets):
    quoted = ", ".join("'%s'" % str(market).replace("'", "''") for market in markets)
    sql = r"""
SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
FROM (
  SELECT
    market::text,
    COALESCE(sector::text, '') AS sector,
    COALESCE(industry::text, '') AS industry,
    snapshot_date::text AS snapshot_date,
    change_pct,
    relative_strength,
    breadth,
    leaders,
    laggards,
    COALESCE(source_key::text, '') AS source_key,
    COALESCE(quality_status::text, '') AS quality_status,
    created_at::text AS created_at
  FROM public.sector_daily_snapshots
  WHERE market::text IN (%s)
  ORDER BY snapshot_date DESC, created_at DESC
  LIMIT 100
) t;
""" % quoted
    ok, raw, rows = psql_json(sql, timeout=15)
    if not ok:
        return {
            "status": "missing",
            "as_of": None,
            "freshness": "unknown",
            "summary": "整体市场/板块数据暂不可用",
            "strong": [],
            "weak": [],
            "degrade_reason": "sector_snapshot_read_failed: %s" % str(raw)[:120],
        }
    rows = rows or []
    if not rows:
        return {
            "status": "missing",
            "as_of": None,
            "freshness": "unknown",
            "summary": "整体市场/板块数据暂不可用",
            "strong": [],
            "weak": [],
            "degrade_reason": "no_sector_snapshots",
        }

    latest_by_market = {}
    for row in rows:
        market = row.get("market")
        if market and market not in latest_by_market:
            latest_by_market[market] = row.get("snapshot_date")
    current_rows = [
        row for row in rows
        if row.get("market") in latest_by_market and row.get("snapshot_date") == latest_by_market.get(row.get("market"))
    ]
    if not current_rows:
        current_rows = rows[:20]

    changes = [_safe_float(row.get("change_pct")) for row in current_rows]
    changes = [value for value in changes if value is not None]
    average_change = round(sum(changes) / len(changes), 2) if changes else None
    positive_ratio = round(len([value for value in changes if value > 0]) / len(changes), 2) if changes else None
    regime = "neutral"
    if average_change is not None and positive_ratio is not None:
        if average_change <= -1.5 or positive_ratio <= 0.35:
            regime = "risk_off"
        elif average_change >= 1.0 and positive_ratio >= 0.6:
            regime = "risk_on"
    if average_change is None or positive_ratio is None:
        summary = "市场状态数据不足"
    elif regime == "risk_off":
        summary = "市场偏防守，板块平均 %+.2f%%，上涨占比 %.0f%%" % (average_change, positive_ratio * 100)
    elif regime == "risk_on":
        summary = "市场风险偏好较强，板块平均 %+.2f%%，上涨占比 %.0f%%" % (average_change, positive_ratio * 100)
    else:
        summary = "市场中性震荡，板块平均 %+.2f%%，上涨占比 %.0f%%" % (average_change, positive_ratio * 100)

    def sector_score(row):
        change = _safe_float(row.get("change_pct"))
        strength = _safe_float(row.get("relative_strength"))
        if change is None and strength is None:
            return -9999
        return (change if change is not None else 0) + 0.25 * (strength if strength is not None else 0)

    def sector_name(row):
        return row.get("sector") or row.get("industry") or row.get("market") or "未知板块"

    deduped = []
    seen = set()
    for row in current_rows:
        key = (row.get("market"), sector_name(row))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    strong = sorted(deduped, key=sector_score, reverse=True)[:3]
    weak = sorted(deduped, key=sector_score)[:2]
    latest_dates = [date for date in latest_by_market.values() if date]
    as_of = max(latest_dates) if latest_dates else None
    parsed_as_of = _parse_date(as_of)
    age_days = None
    if parsed_as_of:
        age_days = (datetime.now().astimezone().date() - parsed_as_of.date()).days
    freshness = "fresh" if age_days is not None and age_days <= 2 else "stale" if age_days is not None else "unknown"
    return {
        "status": "available",
        "as_of": as_of,
        "freshness": freshness,
        "regime": regime,
        "summary": summary,
        "strong": strong,
        "weak": weak,
        "degrade_reason": "none",
    }


def _sector_bits(rows):
    bits = []
    for row in rows:
        name = row.get("sector") or row.get("industry") or row.get("market") or "未知板块"
        bits.append("%s %s" % (name, _fmt_pct(row.get("change_pct"))))
    return "；".join(bits) if bits else "暂无可用板块快照"


def _portfolio_quality(positions, options, market_context):
    if not positions and not options:
        return "无持仓上下文", "no_holding_context"
    if market_context.get("freshness") == "stale":
        return "数据过期", "market_sector_snapshot_stale"
    if market_context.get("status") != "available":
        return "只能观察", market_context.get("degrade_reason") or "market_context_missing"
    return "可行动", "none"


def _near_expiry_options(options, days=14):
    today = datetime.now().astimezone().date()
    hits = []
    for option in options:
        expiry = _parse_date(option.get("expiry"))
        if not expiry:
            continue
        remaining = (expiry.date() - today).days
        if 0 <= remaining <= days:
            hits.append((option, remaining))
    return hits


def _holding_symbol_bits(positions, limit):
    bits = []
    for pos in positions[:limit]:
        symbol = pos.get("symbol") or "-"
        market = pos.get("market")
        prefix = f"{market}:" if market else ""
        bits.append("%s%s %s股@%s%s" % (
            prefix,
            symbol,
            _fmt_qty(pos.get("quantity")),
            _fmt_price(pos.get("avg_cost")),
            pos.get("currency") or "",
        ))
    return "；".join(bits)


def _today_local_date():
    return datetime.now().astimezone().date()


def _is_today_text(value):
    parsed = _parse_date(value)
    return bool(parsed and parsed.date() == _today_local_date())


def _currency_amount(value, currency):
    number = _safe_float(value)
    if number is None:
        return "n/a"
    return "%s%s" % (currency or "", f"{number:,.0f}" if abs(number) >= 100 else f"{number:,.2f}")


def _signed_currency_amount(value, currency):
    number = _safe_float(value)
    if number is None:
        return "n/a"
    sign = "+" if number >= 0 else "-"
    return "%s%s%s" % (sign, currency or "", f"{abs(number):,.0f}" if abs(number) >= 100 else f"{abs(number):,.2f}")


def _signed_pct(value):
    number = _safe_float(value)
    if number is None:
        return "n/a"
    return "%+.2f%%" % number


def _quote_name(quote):
    if not isinstance(quote, dict):
        return ""
    for key in ("name", "stock_name", "name_zh", "name_cn", "short_name", "long_name"):
        value = str(quote.get(key) or "").strip()
        if value:
            return value
    return ""


def _symbol_variants(symbol):
    text = str(symbol or "").strip().upper()
    variants = [text] if text else []
    if text.startswith(("SH", "SZ")) and len(text) > 2:
        variants.append(text[2:])
    if text.startswith("HK") and len(text) > 2:
        variants.append(text[2:])
        variants.append("HK" + text[2:].zfill(5))
    return list(dict.fromkeys([item for item in variants if item]))


def lookup_symbol_names(symbols):
    variants = []
    for symbol in symbols:
        variants.extend(_symbol_variants(symbol))
    variants = sorted(set(variants))
    if not variants:
        return {}
    payload = json.dumps(variants, ensure_ascii=False, separators=(",", ":"))
    sql = r"""
WITH wanted AS (
  SELECT upper(value::text) AS symbol
  FROM jsonb_array_elements_text($json$%s$json$::jsonb) AS value
), registry_rows AS (
  SELECT upper(symbol::text) AS symbol,
         COALESCE(NULLIF(name_zh, ''), NULLIF(name_en, '')) AS name
  FROM public.symbol_registry
  WHERE upper(symbol::text) IN (SELECT symbol FROM wanted)
), instrument_rows AS (
  SELECT upper(symbol::text) AS symbol,
         NULLIF(name, '') AS name
  FROM public.instruments
  WHERE upper(symbol::text) IN (SELECT symbol FROM wanted)
), merged AS (
  SELECT symbol, name FROM registry_rows WHERE name IS NOT NULL
  UNION ALL
  SELECT symbol, name FROM instrument_rows WHERE name IS NOT NULL
)
SELECT COALESCE(json_object_agg(symbol, name), '{}'::json) FROM (
  SELECT DISTINCT ON (symbol) symbol, name
  FROM merged
  ORDER BY symbol, name
) t;
""" % payload.replace("$json$", "$ json $")
    ok, _raw, result = psql_json(sql, timeout=12)
    if not ok or not isinstance(result, dict):
        return {}
    return {str(key).upper(): str(value) for key, value in result.items() if value}


def display_name_for_symbol(symbol, quote=None, name_lookup=None):
    text = str(symbol or "").strip().upper()
    name = _quote_name(quote)
    if name:
        return name
    lookup = name_lookup or {}
    for variant in _symbol_variants(text):
        if lookup.get(variant):
            return lookup[variant]
    if SYMBOL_NAME_FALLBACK.get(text):
        return SYMBOL_NAME_FALLBACK[text]
    return text


def _side_text(side):
    text = str(side or "").strip().lower()
    if text in {"buy", "b", "买", "买入"}:
        return "买入"
    if text in {"sell", "s", "卖", "卖出"}:
        return "卖出"
    return str(side or "交易")


def read_local_summary_book(owner, markets):
    db_path = os.getenv("P0_LOCAL_HOLDINGS_DB", "/root/.hermes/holdings/holdings.db")
    positions = []
    options = []
    trades = []
    option_trades = []
    import sqlite3
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in markets)
        positions = [dict(r) for r in con.execute(
            f"SELECT symbol, market, quantity, avg_cost, currency, updated_at FROM positions WHERE owner_id=? AND market IN ({placeholders}) AND quantity>0 ORDER BY market, symbol",
            (owner, *markets),
        ).fetchall()]
        options = [dict(r) for r in con.execute(
            f"SELECT underlying, market, option_type, position_side, strike, expiry, contracts, avg_premium, currency, updated_at FROM option_positions WHERE owner_id=? AND market IN ({placeholders}) AND contracts<>0 ORDER BY market, underlying, expiry, strike",
            (owner, *markets),
        ).fetchall()]
        all_trades = [dict(r) for r in con.execute(
            f"SELECT symbol, market, side, quantity, price, currency, trade_time, raw_input FROM trades WHERE owner_id=? AND market IN ({placeholders}) ORDER BY trade_time DESC LIMIT 80",
            (owner, *markets),
        ).fetchall()]
        trades = [row for row in all_trades if _is_today_text(row.get("trade_time"))]
        all_option_trades = [dict(r) for r in con.execute(
            f"SELECT underlying, market, option_type, position_side, action, contracts, strike, expiry, premium, currency, trade_time, raw_input FROM option_trades WHERE owner_id=? AND market IN ({placeholders}) ORDER BY trade_time DESC LIMIT 80",
            (owner, *markets),
        ).fetchall()]
        option_trades = [row for row in all_option_trades if _is_today_text(row.get("trade_time"))]
    finally:
        con.close()
    return {"positions": positions, "options": options, "trades": trades, "option_trades": option_trades}


def enrich_positions_with_quotes(positions):
    symbols = [row.get("symbol") for row in positions]
    quotes, quote_meta = fetch_quotes_for_symbols(symbols)
    name_lookup = lookup_symbol_names(symbols)
    enriched = []
    for row in positions:
        item = dict(row)
        symbol = str(row.get("symbol") or "").upper()
        quote = quotes.get(symbol) or {}
        qty = _safe_float(row.get("quantity")) or 0.0
        avg_cost = _safe_float(row.get("avg_cost"))
        price = _safe_float(quote.get("price") or quote.get("last_price") or quote.get("last_done"))
        market_value = qty * price if price is not None else None
        cost_value = qty * avg_cost if avg_cost is not None else None
        pnl = market_value - cost_value if market_value is not None and cost_value is not None else None
        pnl_pct = (price - avg_cost) / avg_cost * 100 if price is not None and avg_cost else None
        item.update({
            "quote": quote,
            "current_price": price,
            "market_value": market_value,
            "unrealized_pnl": pnl,
            "unrealized_pnl_pct": pnl_pct,
            "day_change_pct": _quote_change_pct(quote) if quote else None,
            "quote_source": quote.get("source") or quote.get("provider") or "unknown" if quote else None,
            "quote_freshness": quote.get("freshness_status") if quote else "missing",
            "quote_as_of": _quote_as_of(quote) if quote else None,
            "display_name": display_name_for_symbol(symbol, quote=quote, name_lookup=name_lookup),
        })
        enriched.append(item)
    total_by_currency = {}
    for item in enriched:
        value = _safe_float(item.get("market_value"))
        if value is not None:
            total_by_currency[item.get("currency") or ""] = total_by_currency.get(item.get("currency") or "", 0.0) + abs(value)
    for item in enriched:
        total = total_by_currency.get(item.get("currency") or "")
        value = _safe_float(item.get("market_value"))
        item["concentration_pct"] = round(abs(value) / total * 100, 2) if total and value is not None else None
    return enriched, quote_meta


def trade_lines(trades, option_trades, name_lookup=None):
    lines = []
    for row in trades[:6]:
        lines.append("%s %s %s股 @ %s%s" % (
            _side_text(row.get("side")),
            display_name_for_symbol(row.get("symbol"), name_lookup=name_lookup),
            _fmt_qty(row.get("quantity")),
            _fmt_price(row.get("price")),
            row.get("currency") or "",
        ))
    for row in option_trades[:4]:
        lines.append("%s %s %s %s %s %s张 @ %s%s" % (
            _side_text(row.get("action")),
            display_name_for_symbol(row.get("underlying"), name_lookup=name_lookup),
            row.get("expiry") or "-",
            row.get("position_side") or "-",
            row.get("option_type") or "-",
            _fmt_qty(row.get("contracts")),
            _fmt_price(row.get("premium")),
            row.get("currency") or "",
        ))
    return lines


def position_lines(enriched_positions, limit=8):
    rows = sorted(
        enriched_positions,
        key=lambda item: abs(_safe_float(item.get("market_value")) or 0.0),
        reverse=True,
    )
    lines = []
    for item in rows[:limit]:
        currency = item.get("currency") or ""
        lines.append(
            "%s：市值%s，浮盈亏%s（%s），成本%s，现价%s，持股%s" % (
                item.get("display_name") or item.get("symbol") or "-",
                _currency_amount(item.get("market_value"), currency),
                _signed_currency_amount(item.get("unrealized_pnl"), currency),
                _signed_pct(item.get("unrealized_pnl_pct")),
                _fmt_price(item.get("avg_cost")),
                _fmt_price(item.get("current_price")),
                _fmt_qty(item.get("quantity")),
            )
        )
    if len(rows) > limit:
        lines.append("其余 %d 个标的已省略，可继续展开看完整持仓。" % (len(rows) - limit))
    return lines


def strongest_position_lines(enriched_positions, limit=3):
    rows = [
        item for item in enriched_positions
        if _safe_float(item.get("day_change_pct")) is not None
    ]
    rows = sorted(rows, key=lambda item: _safe_float(item.get("day_change_pct")) or -9999, reverse=True)
    lines = []
    for item in rows[:limit]:
        lines.append("%s 当日%s，现价%s，浮盈亏%s（%s）" % (
            item.get("display_name") or item.get("symbol") or "-",
            _signed_pct(item.get("day_change_pct")),
            _fmt_price(item.get("current_price")),
            _signed_currency_amount(item.get("unrealized_pnl"), item.get("currency") or ""),
            _signed_pct(item.get("unrealized_pnl_pct")),
        ))
    return lines


def risk_summary(enriched_positions, options, market_context):
    if not enriched_positions and not options:
        return "当前没有可用于判断账户风险的持仓上下文；这条简报只看市场机会和风险。"
    missing_quotes = [item for item in enriched_positions if not item.get("quote")]
    if missing_quotes:
        return "%d 个持仓标的缺少行情，先不要依据本轮市值和盈亏做判断：%s。" % (
            len(missing_quotes),
            "、".join([str(item.get("display_name") or item.get("symbol") or "-") for item in missing_quotes[:5]]),
        )
    by_loss = [item for item in enriched_positions if _safe_float(item.get("unrealized_pnl_pct")) is not None]
    if by_loss:
        worst = min(by_loss, key=lambda item: _safe_float(item.get("unrealized_pnl_pct")) or 0)
        if (_safe_float(worst.get("unrealized_pnl_pct")) or 0) <= -5:
            return "%s是当前最大浮亏标的，浮盈亏%s（%s），现价%s；明天先看是否跌破自己的纪律线。" % (
                worst.get("display_name") or worst.get("symbol"),
                _signed_currency_amount(worst.get("unrealized_pnl"), worst.get("currency") or ""),
                _signed_pct(worst.get("unrealized_pnl_pct")),
                _fmt_price(worst.get("current_price")),
            )
    by_concentration = [item for item in enriched_positions if _safe_float(item.get("concentration_pct")) is not None]
    if by_concentration:
        top = max(by_concentration, key=lambda item: _safe_float(item.get("concentration_pct")) or 0)
        if (_safe_float(top.get("concentration_pct")) or 0) >= 30:
            return "%s是当前最大单票暴露，约占同币种持仓 %.1f%%，浮盈亏%s（%s）；明天先复核是否需要控制加仓或分批止盈/止损。" % (
                top.get("display_name") or top.get("symbol"),
                _safe_float(top.get("concentration_pct")) or 0,
                _signed_currency_amount(top.get("unrealized_pnl"), top.get("currency") or ""),
                _signed_pct(top.get("unrealized_pnl_pct")),
            )
    if market_context.get("regime") == "risk_off":
        return "市场环境偏防守，组合里即使没有单一异常，也不适合直接扩大高波动仓位。"
    return "没有看到特别突出的单票集中或大幅浮亏，主要风险是行情波动下的持仓纪律执行。"


def data_quality_issues(actionability, degrade_reason, market_refresh, enriched_positions):
    issues = []
    if actionability != "可行动":
        issues.append("组合可行动性：%s（%s）" % (actionability, degrade_reason))
    if market_refresh.get("status") != "ok":
        issues.append("市场快照刷新异常：%s" % (market_refresh.get("error") or market_refresh.get("persist", {}).get("error") or "unknown"))
    missing = [item for item in enriched_positions if not item.get("quote")]
    if missing:
        issues.append("持仓行情缺失：%s" % "、".join([str(item.get("display_name") or item.get("symbol") or "-") for item in missing[:8]]))
    stale = [item for item in enriched_positions if item.get("quote_freshness") in {"stale", "expired", "missing_timestamp"}]
    if stale:
        issues.append("行情新鲜度异常：%s" % "、".join([str(item.get("display_name") or item.get("symbol") or "-") for item in stale[:8]]))
    return issues


def _json_post(url, payload, timeout=25):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(200000).decode("utf-8", "replace")
    return json.loads(raw) if raw else {}


def _quote_batch(symbols, source=None, max_age_seconds=None):
    params = {}
    if source:
        params["source"] = source
    if max_age_seconds:
        params["max_age_seconds"] = str(max_age_seconds)
    query = ("?" + urlencode(params)) if params else ""
    url = DATA_SERVICE.rstrip("/") + "/api/quote/batch" + query
    payload = _json_post(url, {"symbols": symbols}, timeout=35)
    if not payload.get("ok"):
        raise RuntimeError(str(payload)[:300])
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return data, payload.get("failed") or []


def fetch_quotes_for_symbols(symbols):
    symbols = sorted({str(symbol or "").strip().upper() for symbol in symbols if str(symbol or "").strip()})
    if not symbols:
        return {}, {"attempts": [], "failed": []}
    attempts = []
    merged = {}
    remaining = list(symbols)
    for source in ("longbridge", None):
        if not remaining:
            break
        try:
            data, failed = _quote_batch(remaining, source=source, max_age_seconds=24 * 60 * 60)
            normalized = _normalize_quote_map(data)
            for symbol in list(remaining):
                quote = normalized.get(symbol.upper())
                if quote:
                    merged[symbol] = quote
            remaining = [symbol for symbol in remaining if symbol not in merged]
            attempts.append({"source": source or "default", "returned": len(data), "failed": failed[:12]})
        except Exception as exc:
            attempts.append({"source": source or "default", "error": str(exc)[:180]})
    return merged, {"attempts": attempts, "failed": remaining}


def _quote_change_pct(quote):
    for key in ("change_rate", "change_pct", "pct_chg", "regularMarketChangePercent"):
        number = _safe_float(quote.get(key))
        if number is not None:
            return number
    price = _safe_float(quote.get("price") or quote.get("last_price") or quote.get("last_done"))
    prev_close = _safe_float(quote.get("prev_close") or quote.get("previous_close") or quote.get("previousClose"))
    if price is not None and prev_close:
        return (price - prev_close) / prev_close * 100
    return None


def _quote_as_of(quote):
    for key in ("as_of", "updated_at", "timestamp", "quote_time", "last_trade_time"):
        value = quote.get(key)
        if value:
            if isinstance(value, (int, float)):
                try:
                    return datetime.fromtimestamp(int(value if value < 1e11 else value / 1000), timezone.utc).isoformat()
                except Exception:
                    continue
            return str(value)
    return now()


def _quote_timestamp_date(quote):
    parsed = _parse_date(_quote_as_of(quote))
    return parsed.date().isoformat() if parsed else datetime.now().astimezone().date().isoformat()


def _normalize_quote_map(raw_quotes):
    normalized = {}
    for key, quote in (raw_quotes or {}).items():
        if not isinstance(quote, dict):
            continue
        normalized[str(key).upper()] = quote
        symbol = str(quote.get("symbol") or "").upper()
        if symbol:
            normalized[symbol] = quote
    return normalized


def _market_proxy_symbols(markets):
    proxies = []
    for market in markets:
        proxies.extend(MARKET_PROXY_UNIVERSE.get(market, []))
    return proxies


def _fetch_market_proxy_quotes(proxies):
    symbols = sorted({proxy["symbol"] for proxy in proxies})
    if not symbols:
        return {}, {"attempts": [], "failed": []}
    attempts = []
    merged = {}
    remaining = symbols
    for source in ("longbridge", None):
        if not remaining:
            break
        try:
            data, failed = _quote_batch(remaining, source=source, max_age_seconds=24 * 60 * 60)
            normalized = _normalize_quote_map(data)
            for symbol in list(remaining):
                quote = normalized.get(symbol.upper())
                if quote:
                    merged[symbol] = quote
            remaining = [symbol for symbol in remaining if symbol not in merged]
            attempts.append({"source": source or "default", "returned": len(data), "failed": failed[:12]})
        except Exception as exc:
            attempts.append({"source": source or "default", "error": str(exc)[:180]})
    return merged, {"attempts": attempts, "failed": remaining}


def build_market_snapshot_rows(markets):
    proxies = _market_proxy_symbols(markets)
    quotes, fetch_meta = _fetch_market_proxy_quotes(proxies)
    rows = []
    benchmark_change_by_market = {}
    snapshot_date_by_market = {}
    for proxy in proxies:
        quote = quotes.get(proxy["symbol"])
        if not quote:
            continue
        change_pct = _quote_change_pct(quote)
        if change_pct is None:
            continue
        market = next((m for m in markets if proxy in MARKET_PROXY_UNIVERSE.get(m, [])), str(quote.get("market") or ""))
        snapshot_date = _quote_timestamp_date(quote)
        snapshot_date_by_market[market] = max(snapshot_date, snapshot_date_by_market.get(market, snapshot_date))
        if proxy.get("role") == "benchmark":
            benchmark_change_by_market[market] = change_pct
        source = str(quote.get("source") or quote.get("provider") or quote.get("source_key") or "hermes_quote")
        source_tier = str(quote.get("source_tier") or quote.get("quote_actionability") or "")
        quality = "validated" if quote.get("freshness_status") in {"fresh", "stale"} or quote.get("quote_actionability") else "partial"
        rows.append({
            "market": market,
            "sector": proxy["sector"],
            "industry": proxy["name"],
            "snapshot_date": snapshot_date,
            "change_pct": round(change_pct, 4),
            "relative_strength": None,
            "breadth": {
                "proxy_symbol": proxy["symbol"],
                "proxy_name": proxy["name"],
                "role": proxy.get("role"),
                "price": quote.get("price"),
                "freshness_status": quote.get("freshness_status"),
                "freshness_seconds": quote.get("freshness_seconds"),
                "actionability": quote.get("quote_actionability"),
            },
            "leaders": [{
                "symbol": proxy["symbol"],
                "name": quote.get("name") or proxy["name"],
                "change_pct": round(change_pct, 4),
                "source": source,
            }],
            "laggards": [],
            "source_key": "cron_market_refresh:%s%s" % (source, (":" + source_tier) if source_tier else ""),
            "quality_status": quality,
        })
    for row in rows:
        benchmark = benchmark_change_by_market.get(row["market"])
        if benchmark is not None:
            row["relative_strength"] = round(float(row["change_pct"]) - float(benchmark), 4)
    return rows, {**fetch_meta, "row_count": len(rows), "markets": markets, "snapshot_dates": snapshot_date_by_market}


def persist_market_snapshot_rows(rows):
    if not rows:
        return {"inserted": 0, "reason": "no_rows"}
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    sql = r"""
WITH payload AS (
  SELECT jsonb_array_elements($json$%s$json$::jsonb) AS item
), upserted AS (
  INSERT INTO public.sector_daily_snapshots (
    id, tenant_id, market, sector, industry, snapshot_date, change_pct,
    relative_strength, breadth, leaders, laggards, source_key,
    quality_status, created_at, updated_at
  )
  SELECT
    gen_random_uuid(),
    NULL,
    item->>'market',
    item->>'sector',
    NULLIF(item->>'industry', ''),
    (item->>'snapshot_date')::date,
    NULLIF(item->>'change_pct', '')::numeric,
    NULLIF(item->>'relative_strength', '')::numeric,
    COALESCE(item->'breadth', '{}'::jsonb),
    COALESCE(item->'leaders', '[]'::jsonb),
    COALESCE(item->'laggards', '[]'::jsonb),
    COALESCE(NULLIF(item->>'source_key', ''), 'cron_market_refresh'),
    COALESCE(NULLIF(item->>'quality_status', ''), 'partial'),
    now(),
    now()
  FROM payload
  ON CONFLICT (
    COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid),
    market,
    sector,
    snapshot_date
  )
  DO UPDATE SET
    industry = EXCLUDED.industry,
    change_pct = EXCLUDED.change_pct,
    relative_strength = EXCLUDED.relative_strength,
    breadth = EXCLUDED.breadth,
    leaders = EXCLUDED.leaders,
    laggards = EXCLUDED.laggards,
    source_key = EXCLUDED.source_key,
    quality_status = EXCLUDED.quality_status,
    updated_at = now()
  RETURNING id::text
)
SELECT json_build_object(
  'upserted', (SELECT count(*) FROM upserted)
);
""" % payload.replace("$json$", "$ json $")
    ok, raw, result = psql_json(sql, timeout=25)
    if not ok:
        return {"error": raw}
    return result or {}


def refresh_market_snapshots_for_summary(markets):
    key = ",".join(sorted(markets))
    if key in _MARKET_REFRESH_CACHE:
        return _MARKET_REFRESH_CACHE[key]
    try:
        rows, meta = build_market_snapshot_rows(markets)
        persist = persist_market_snapshot_rows(rows)
        result = {"status": "ok" if rows and not persist.get("error") else "degraded", "rows": len(rows), "fetch": meta, "persist": persist}
    except Exception as exc:
        result = {"status": "degraded", "error": str(exc)[:300], "rows": 0}
    _MARKET_REFRESH_CACHE[key] = result
    return result


def summary_direct_message(binding, probe_status, probe_details):
    title = "美股日终持仓行动简报" if TASK == "p0-us-close-summary" else "A股/港股日终持仓行动简报"
    sh_time = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    owner = binding.get("wechat_user_id") or ""
    markets = _markets_for_summary_task()
    try:
        book = read_local_summary_book(owner, markets)
    except Exception as exc:
        return (
            f"【抓钱小螃蟹】{title}\n"
            f"时间：{sh_time}\n"
            f"状态：摘要生成时读取本地持仓库异常：{str(exc)[:120]}\n"
            "数据质量：source=local_holdings_db；as_of=n/a；freshness=unknown；actionability=只能观察；degrade_reason=local_holdings_read_failed\n"
            "行动等级：info_only。不会改动持仓，也不会下单。"
        )

    positions = book["positions"]
    options = book["options"]
    trades = book["trades"]
    option_trades = book["option_trades"]
    enriched_positions, quote_meta = enrich_positions_with_quotes(positions)
    name_lookup = {}
    for item in enriched_positions:
        symbol = str(item.get("symbol") or "").upper()
        if symbol and item.get("display_name"):
            name_lookup[symbol] = item.get("display_name")
            for variant in _symbol_variants(symbol):
                name_lookup.setdefault(variant, item.get("display_name"))
    market_refresh = refresh_market_snapshots_for_summary(markets)
    market_context = market_context_for_summary(markets)
    actionability, degrade_reason = _portfolio_quality(positions, options, market_context)
    position_count = len(positions)
    option_count = len(options)

    trade_bits = trade_lines(trades, option_trades, name_lookup=name_lookup)
    if trade_bits:
        trade_text = "今日记录到交易：" + "；".join(trade_bits)
    else:
        trade_text = "今日无操作（本地交易记录未读取到当日买卖），本轮按现有持仓和最新行情做复核。"
    holding_lines = position_lines(enriched_positions, limit=8)
    if not holding_lines:
        holding_lines = ["暂无正股持仓。"]
    if options:
        option_bits = [
            "%s %s %s %s %s x%s" % (
                opt.get("underlying") or "-",
                opt.get("expiry") or "-",
                opt.get("position_side") or "-",
                opt.get("option_type") or "-",
                _fmt_price(opt.get("strike")),
                _fmt_qty(opt.get("contracts")),
            )
            for opt in options[:4]
        ]
        option_line = "期权：" + "；".join(option_bits)
    else:
        option_line = "期权：暂无"

    near_expiry = _near_expiry_options(options)
    top_risk = risk_summary(enriched_positions, options, market_context)
    if near_expiry:
        top_risk += " 另外有 %d 条期权 14 天内到期，也需要单独复核。" % len(near_expiry)

    rules = []
    if market_context.get("regime") == "risk_off":
        rules.append("市场防守：控制新开仓，优先减小高波动暴露")
    if near_expiry:
        rules.append("期权临近到期：优先处理时间价值和保证金风险")
    if actionability in {"数据过期", "只能观察", "无持仓上下文"} or quote_meta.get("failed"):
        rules.append("数据质量降级：本轮不直接给交易动作")
    if not rules:
        rules.append("无硬性风险规则命中；进入明日观察清单")

    observations = []
    if positions:
        observations.append("先从最大风险里点到的标的看起，确认它有没有触发自己的止损、减仓或继续观察条件。")
    strong_positions = strongest_position_lines(enriched_positions, limit=3)
    if strong_positions:
        observations.append("持仓内强势标的可以继续跟踪，但只在回踩或计划内条件出现时再考虑动作。")
    if market_context.get("strong"):
        observations.append("从强势板块中找机会：%s；只关注回踩确认或已有计划内标的。" % _sector_bits(market_context.get("strong")[:2]))
    if market_context.get("weak"):
        observations.append("弱势板块风险：%s；避免逆势扩大暴露。" % _sector_bits(market_context.get("weak")[:2]))
    elif market_context.get("status") != "available":
        observations.append("先补齐大盘指数与板块快照；缺口补齐前，只做持仓风险复核，不扩大高波动暴露。")
    if not observations:
        observations.append("先补齐持仓和市场快照，再生成可行动观察项。")

    data_sources = ["local_holdings_db"]
    if enriched_positions:
        data_sources.append("position_quote_batch")
    if market_refresh.get("rows"):
        data_sources.append("market_quote_refresh")
    if market_context.get("status") == "available":
        data_sources.append("sector_daily_snapshots")
    if probe_status:
        data_sources.append("cron_probe:%s" % probe_status)
    as_of_candidates = [pos.get("updated_at") for pos in positions if pos.get("updated_at")]
    as_of_candidates += [pos.get("quote_as_of") for pos in enriched_positions if pos.get("quote_as_of")]
    as_of_candidates += [opt.get("updated_at") for opt in options if opt.get("updated_at")]
    if market_context.get("as_of"):
        as_of_candidates.append(market_context.get("as_of"))
    as_of = max([str(item) for item in as_of_candidates]) if as_of_candidates else "n/a"

    conclusion = market_context.get("summary") or "市场状态数据不足"
    strong_text = _sector_bits(market_context.get("strong") or [])
    weak_text = _sector_bits(market_context.get("weak") or [])
    if market_context.get("status") != "available":
        strong_text = "数据缺口：尚未写入整体市场/板块快照；明天优先补齐后再筛选强势板块机会。"
        weak_text = "数据缺口：无法确认弱势板块；缺口补齐前避免把持仓清单误当市场判断。"
    strong_position_text = "暂无持仓内强势标的数据"
    if strong_positions:
        strong_position_text = "；".join(strong_positions[:3])
    data_issues = data_quality_issues(actionability, degrade_reason, market_refresh, enriched_positions)
    data_quality_section = ""
    if data_issues:
        data_quality_section = (
            "4. 数据异常提醒\n"
            f"- {'；'.join(data_issues[:4])}\n"
            f"- source：{'+'.join(data_sources)}；as_of：{as_of}\n"
        )
    return (
        f"【抓钱小螃蟹】{title}\n"
        f"时间：{sh_time}\n"
        f"结论：{conclusion}；组合 {position_count} 个正股 / {option_count} 条期权。\n"
        "1. 组合变化\n"
        f"- {trade_text}\n"
        f"- 持仓明细：\n- " + "\n- ".join(holding_lines) + "\n"
        f"- {option_line}\n"
        "2. 最大风险\n"
        f"- {top_risk}\n"
        "3. 市场走向与强势板块\n"
        f"- 走向：{market_context.get('summary') or '市场状态数据不足'}\n"
        f"- 强势：{strong_text}\n"
        f"- 持仓强势：{strong_position_text}\n"
        f"- 风险：{weak_text}\n"
        f"{data_quality_section}"
        "5. 规则命中\n"
        f"- {'；'.join(rules)}\n"
        "6. 明天观察项\n"
        f"- {'；'.join(observations[:3])}\n"
        "如果你愿意，我可以继续帮你展开：先看最大风险那只标的，还是看今天强势板块里的机会？\n"
        "行动等级：info_only。不会改动持仓，也不会下单。"
    )


def holding_push_task():
    probe_status, probe_details = task_probe_details()
    gate_status, gate_details, accounts = eligible_accounts()
    if gate_status != "ok":
        return "alert", gate_details
    if gate_details["active_wechat_bindings"] == 0:
        # P0 本机当前仍可能只有 Hermes 微信 profile + 本地持仓库，尚未写入
        # product DB channel_bindings。此时直接读取本地 wechat_bindings，逐个微信账号发送；
        # 不依赖 Hermes cron 的单一 home channel，避免只推送到当前会话。
        local_bindings = [row for row in local_eligible_bindings() if not row.get("error")]
        local_errors = [row for row in local_eligible_bindings() if row.get("error")]
        count = sum(int(row.get("holdings_count") or 0) for row in local_bindings)
        if count > 0:
            local_delivery = send_local_fallback_to_all(local_bindings, probe_status, probe_details)
            status = "ok" if local_delivery.get("failed", 0) == 0 else "alert"
            return status, {
                "mode": "holding_push_local_binding_fanout",
                "reason": "no_product_channel_binding_use_local_wechat_bindings",
                **gate_details,
                "local_bindings": len(local_bindings),
                "local_holdings_count": count,
                "local_errors": local_errors[:3],
                "probe": probe_details,
                "local_delivery": local_delivery,
            }
        return "skipped", {"mode": "holding_push_expansion", "reason": "skipped_no_active_wechat_binding", **gate_details, "probe": probe_details}
    if gate_details["eligible_accounts"] == 0:
        return "skipped", {"mode": "holding_push_expansion", "reason": "skipped_empty_holdings", **gate_details, "probe": probe_details}
    if TASK.startswith("p0-opportunity-research"):
        status, details = opportunity_research_task(accounts)
        return status, {**gate_details, "probe": probe_details, **details}
    if TASK in SUMMARY_DIRECT_FANOUT_TASKS:
        def summary_message_for_account(account):
            binding = local_binding_for_tenant(account.get("tenant_id"))
            return summary_direct_message(binding or {}, probe_status, probe_details)

        enqueue_result = enqueue_for_accounts(accounts, probe_status, probe_details, message_builder=summary_message_for_account)
        if enqueue_result.get("enqueue_error"):
            return "alert", {"mode": "summary_outbox_fanout", **gate_details, "probe": probe_details, "enqueue": enqueue_result}
        retry_status, retry_details = delivery_retry()
        if retry_status != "ok":
            return "alert", {"mode": "summary_outbox_fanout", **gate_details, "probe": probe_details, "enqueue": enqueue_result, "delivery_retry": retry_details}
        return "ok", {"mode": "summary_outbox_fanout", **gate_details, "probe": probe_details, "enqueue": enqueue_result, "delivery_retry": retry_details}
    if TASK in ROUTINE_OK_SILENT_TASKS and probe_status == "ok":
        return "ok", {
            "mode": "holding_push_expansion",
            "reason": "routine_ok_suppressed_no_wechat_push",
            **gate_details,
            "probe": probe_details,
        }
    if probe_status == "alert":
        # Still enqueue an alert to accounts with holdings: this is holding-facing degradation.
        enqueue_result = enqueue_for_accounts(accounts, probe_status, probe_details)
        retry_status, retry_details = delivery_retry()
        return "alert", {"mode": "holding_push_expansion", **gate_details, "probe": probe_details, "enqueue": enqueue_result, "delivery_retry": retry_details}
    enqueue_result = enqueue_for_accounts(accounts, probe_status, probe_details)
    if enqueue_result.get("enqueue_error"):
        return "alert", {"mode": "holding_push_expansion", **gate_details, "probe": probe_details, "enqueue": enqueue_result}
    retry_status, retry_details = delivery_retry()
    if retry_status != "ok":
        return "alert", {"mode": "holding_push_expansion", **gate_details, "probe": probe_details, "enqueue": enqueue_result, "delivery_retry": retry_details}
    return "ok", {"mode": "holding_push_expansion", **gate_details, "probe": probe_details, "enqueue": enqueue_result, "delivery_retry": retry_details}


def _read_env_file_secret(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            values = {}
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"').strip("'")
        return values.get("HERMES_DELIVERY_WEBHOOK_SECRET") or values.get("OPENCLAW_DELIVERY_WEBHOOK_SECRET") or ""
    except Exception:
        return ""


def delivery_secret():
    # Sender and receiver both accept HERMES_* and legacy OPENCLAW_* names.
    # Prefer explicit task env, then deployed .env.server, then live container env.
    for name in ("P0_DELIVERY_WEBHOOK_SECRET", "HERMES_DELIVERY_WEBHOOK_SECRET", "OPENCLAW_DELIVERY_WEBHOOK_SECRET"):
        env_secret = os.getenv(name)
        if env_secret:
            return env_secret
    file_secret = _read_env_file_secret(os.path.join(DEPLOY_DIR, ".env.server"))
    if file_secret:
        return file_secret
    for name in ("HERMES_DELIVERY_WEBHOOK_SECRET", "OPENCLAW_DELIVERY_WEBHOOK_SECRET"):
        code, out = run(["docker", "exec", WEBAPP_CONTAINER, "printenv", name], timeout=8)
        if code == 0 and out.strip():
            return out.strip()
    return ""


def ready_deliveries(limit=25):
    blocked_content_types = ", ".join("'%s'" % item.replace("'", "''") for item in sorted(BLOCKED_DELIVERY_CONTENT_TYPES))
    sql = r"""
WITH candidates AS (
  SELECT id
  FROM public.delivery_outbox
  WHERE status IN ('pending'::public.outbox_status, 'retrying'::public.outbox_status)
    AND (next_retry_at IS NULL OR next_retry_at <= now())
    AND content_type NOT IN (%s)
  ORDER BY priority DESC, created_at ASC
  LIMIT %d
  FOR UPDATE SKIP LOCKED
), claimed AS (
  UPDATE public.delivery_outbox AS d
  SET status='sending'::public.outbox_status,
      last_attempt_at=now(),
      updated_at=now()
  FROM candidates
  WHERE d.id = candidates.id
  RETURNING d.*
)
SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
FROM (
  SELECT
    id::text,
    tenant_id::text,
    channel_binding_id::text,
    openclaw_account_id,
    content_type,
    content,
    content_snapshot_hash,
    priority,
    dedupe_key,
    target_conversation,
    context_token,
    confirmation_session_id::text,
    source_run_id::text
  FROM claimed
) t;
""" % (blocked_content_types, int(limit))
    ok, raw, rows = psql_json(sql, timeout=20)
    if not ok:
        return False, raw, []
    return True, raw, rows or []


def delivery_backlog_audit():
    sql = r"""
SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
FROM (
  SELECT
    status::text AS status,
    content_type,
    COUNT(*)::int AS count,
    SUM(CASE WHEN COALESCE(last_error, '') ILIKE '%s%%' THEN 1 ELSE 0 END)::int AS suppressed_stale_count,
    MIN(created_at) AS oldest_created_at,
    MAX(created_at) AS newest_created_at
  FROM public.delivery_outbox
  WHERE status::text IN ('pending', 'retrying', 'failed', 'sending')
  GROUP BY status::text, content_type
  ORDER BY status::text, content_type
) t;
""" % SUPPRESSED_STALE_BACKLOG_PREFIX.replace("'", "''")
    ok, raw, rows = psql_json(sql, timeout=20)
    if not ok:
        return {"ok": False, "error": raw, "active_failed": 0}
    rows = rows or []
    active_failed = 0
    retrying = 0
    pending = 0
    for row in rows:
        count = int(row.get("count") or 0)
        if row.get("status") == "failed":
            active_failed += max(0, count - int(row.get("suppressed_stale_count") or 0))
        elif row.get("status") == "retrying":
            retrying += count
        elif row.get("status") == "pending":
            pending += count
    return {
        "ok": True,
        "active_failed": active_failed,
        "retrying": retrying,
        "pending": pending,
        "rows": rows,
    }


def delivery_payload(row):
    return {
        "delivery_id": row.get("id"),
        "tenant_id": row.get("tenant_id"),
        "channel": "openclaw-weixin",
        "recipient": {
            "openclaw_account_id": row.get("openclaw_account_id"),
            "target_conversation": row.get("target_conversation"),
            "context_token": row.get("context_token"),
            "channel_binding_id": row.get("channel_binding_id"),
        },
        "message": {
            "content_type": row.get("content_type"),
            "content": row.get("content") or {},
        },
        "dedupe_key": row.get("dedupe_key"),
        "content_snapshot_hash": row.get("content_snapshot_hash"),
        "priority": row.get("priority") or "normal",
        "confirmation_session_id": row.get("confirmation_session_id"),
        "source_run_id": row.get("source_run_id"),
    }


def mark_delivery(delivery_id, status, error=None):
    if status == "delivered":
        sql = """
	UPDATE public.delivery_outbox
	SET status='delivered'::public.outbox_status,
	    delivered_at=now(), last_attempt_at=now(), updated_at=now(), last_error=NULL
	WHERE id='%s'::uuid
	  AND status='sending'::public.outbox_status;
	""" % delivery_id
    else:
        safe_error = json.dumps(str(error or "delivery failed"), ensure_ascii=False)
        sql = """
UPDATE public.delivery_outbox
SET status=CASE WHEN attempt_count + 1 >= 5 THEN 'failed'::public.outbox_status ELSE 'retrying'::public.outbox_status END,
    attempt_count=attempt_count + 1,
    last_attempt_at=now(),
	    next_retry_at=CASE WHEN attempt_count + 1 >= 5 THEN NULL ELSE now() + interval '5 minutes' END,
	    last_error=%s,
	    updated_at=now()
	WHERE id='%s'::uuid
	  AND status='sending'::public.outbox_status;
	""" % (safe_error, delivery_id)
    return psql(sql, timeout=10)


def post_delivery(payload, secret):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-OpenClaw-Delivery-Id": str(payload.get("delivery_id") or "")}
    if secret:
        ts = str(int(time.time()))
        sig = hmac.new(secret.encode("utf-8"), f"{ts}.".encode("utf-8") + body, hashlib.sha256).hexdigest()
        headers["X-OpenClaw-Delivery-Timestamp"] = ts
        headers["X-OpenClaw-Delivery-Signature"] = "v1=" + sig
        headers["X-OpenClaw-Delivery-Secret"] = secret
    req = urllib.request.Request(DELIVERY_WEBHOOK, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        text = resp.read(1000).decode("utf-8", "replace")
        return resp.status, text


def delivery_retry():
    audit = delivery_backlog_audit()
    ok, raw, rows = ready_deliveries()
    if not ok:
        return "alert", {"mode": "delivery_retry", "query_error": raw, "audit": audit}
    if not rows:
        status = "alert" if audit.get("active_failed", 0) else "ok"
        return status, {"mode": "delivery_retry", "scanned": 0, "delivered": 0, "failed": 0, "audit": audit}
    secret = delivery_secret()
    delivered = 0
    failed = 0
    errors = []
    if DRY_RUN:
        status = "alert" if audit.get("active_failed", 0) else "ok"
        return status, {"mode": "delivery_retry", "dry_run": True, "scanned": len(rows), "delivered": 0, "failed": 0, "audit": audit}
    for row in rows:
        delivery_id = row["id"]
        try:
            status_code, body = post_delivery(delivery_payload(row), secret)
            if 200 <= status_code < 300:
                mark_delivery(delivery_id, "delivered")
                delivered += 1
            else:
                mark_delivery(delivery_id, "retrying", f"http={status_code} {body[:200]}")
                failed += 1
        except Exception as exc:
            # If the product WebApp bridge is degraded (401/500/missing ClawBot creds),
            # do not let user-facing cron reminders silently rot in outbox. Fall back to
            # the local Hermes WeChat binding from holdings.db, then mark delivered only
            # after the direct send succeeds.
            fallback = local_fallback_for_delivery_row(row)
            fallback_ok = bool(fallback.get("success") or fallback.get("dry_run")) and not fallback.get("error")
            if fallback_ok:
                mark_delivery(delivery_id, "delivered")
                delivered += 1
                errors.append({"delivery_id": delivery_id, "webapp_error": str(exc)[:160], "fallback": "local_wechat_binding"})
            else:
                mark_delivery(delivery_id, "retrying", "%s; local_fallback=%s" % (str(exc)[:300], json.dumps(fallback, ensure_ascii=False)[:180]))
                failed += 1
                errors.append({"delivery_id": delivery_id, "error": str(exc)[:180], "fallback_error": fallback.get("error")})
    final_audit = delivery_backlog_audit()
    status = "ok" if failed == 0 and not final_audit.get("active_failed", 0) else "alert"
    return status, {
        "mode": "delivery_retry",
        "scanned": len(rows),
        "delivered": delivered,
        "failed": failed,
        "errors": errors[:5],
        "audit": final_audit,
    }


def main():
    if TASK == "p0-health-heartbeat":
        status, details = health()
    elif TASK == "p0-delivery-retry":
        status, details = delivery_retry()
    elif TASK in HOLDING_PUSH_TASKS:
        status, details = holding_push_task()
    else:
        status, details = "alert", {"reason": "unknown_task"}
    try:
        details = dict(details or {})
        details["ima_archive"] = archive_cron_output(status, details)
    except Exception as exc:
        details = dict(details or {})
        details["ima_archive"] = {"status": "failed", "reason": str(exc)[:500]}
    record(status, details)
    if status == "alert":
        print("[%s] ALERT %s" % (TASK, json.dumps(details, ensure_ascii=False)))
    elif details.get("stdout_message"):
        print(details["stdout_message"])
    return 0 if status in ("ok", "guarded", "skipped") else 1

if __name__ == "__main__":
    sys.exit(main())
