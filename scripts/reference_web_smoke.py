#!/usr/bin/env python3
"""
Hermes reference.web first-stage smoke probe.

This probe is intentionally read-only except for the same persistence path used
by Hermes itself when `persist=true`. It separates internal Hermes readiness
from real WeChat user-visible readiness so a healthy data-service path is not
mistaken for a working ClawBot account.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
SERVER_ENV_FILE = PROJECT_ROOT / ".env.server"
DEFAULT_DATA_SERVICE_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_WEBAPP_BASE_URL = "http://127.0.0.1:3000"
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
DEFAULT_REFERENCE_URL = "https://example.com"
DEFAULT_BLOCKED_REFERENCE_URL = "http://localhost/private"
DEFAULT_SEARCH_QUERY = "NVIDIA latest news"
DEFAULT_SYMBOL = "NVDA"


@dataclass
class StepResult:
    step: str
    status: str
    detail: str
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "detail": self.detail,
            "payload": self.payload,
        }


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _headers(internal_key: str = "") -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if internal_key:
        headers["X-Hermes-Domain-Tools-Key"] = internal_key
        headers["X-Hermes-Internal-Token"] = internal_key
    return headers


def _get_json(url: str, *, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any] | None, str]:
    request_headers = {"Accept": "application/json", **(headers or {})}
    req = urllib.request.Request(url, headers=request_headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else None, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw), raw
        except json.JSONDecodeError:
            return exc.code, None, raw
    except urllib.error.URLError as exc:
        return 0, None, str(exc.reason)


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any] | None, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers or {"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else None, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw), raw
        except json.JSONDecodeError:
            return exc.code, None, raw
    except urllib.error.URLError as exc:
        return 0, None, str(exc.reason)


def _invoke_tool(
    *,
    base_url: str,
    tenant_id: str,
    tool: str,
    arguments: dict[str, Any],
    internal_key: str = "",
) -> tuple[int, dict[str, Any] | None, str]:
    payload = {"tool": tool, "tenant_id": tenant_id, "arguments": {"tenant_id": tenant_id, **arguments}}
    return _post_json(
        f"{base_url.rstrip('/')}/api/hermes/domain-tools/invoke",
        payload,
        headers=_headers(internal_key),
    )


def _unwrap_result(response_json: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response_json, dict):
        return {}
    result = response_json.get("result")
    return result if isinstance(result, dict) else response_json


def _compact(value: Any, *, max_chars: int = 4000) -> dict[str, Any]:
    raw = json.dumps(value, ensure_ascii=False, default=str)
    if len(raw) <= max_chars:
        return value if isinstance(value, dict) else {"value": value}
    return {"truncated": True, "chars": len(raw), "preview": raw[:max_chars]}


def probe_health(base_url: str) -> StepResult:
    status_code, response_json, raw = _get_json(f"{base_url.rstrip('/')}/health")
    if not 200 <= status_code < 300:
        return StepResult("data_service_health", "failed", f"{status_code or 'network'}: {raw}", response_json)
    runtime = response_json.get("runtime") if isinstance(response_json, dict) else None
    if runtime != "hermes":
        return StepResult("data_service_health", "failed", f"expected runtime=hermes, got {runtime}", response_json)
    return StepResult("data_service_health", "passed", "data-service is healthy", _compact(response_json))


def probe_manifest(base_url: str, internal_key: str) -> StepResult:
    headers: dict[str, str] = {}
    if internal_key:
        headers["X-Hermes-Domain-Tools-Key"] = internal_key
        headers["X-Hermes-Internal-Token"] = internal_key
    status_code, response_json, raw = _get_json(f"{base_url.rstrip('/')}/api/hermes/domain-tools", headers=headers)
    if not 200 <= status_code < 300:
        return StepResult("domain_tools_manifest", "failed", f"{status_code or 'network'}: {raw}", response_json)
    tools = response_json.get("tools") if isinstance(response_json, dict) else []
    names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
    missing = {"reference.web.read", "reference.web.search"} - names
    if missing:
        return StepResult("domain_tools_manifest", "failed", f"missing tool(s): {', '.join(sorted(missing))}", response_json)
    return StepResult("domain_tools_manifest", "passed", "reference.web tools are registered", {"tools": sorted(names)})


def probe_reference_read(base_url: str, tenant_id: str, url: str, internal_key: str) -> StepResult:
    status_code, response_json, raw = _invoke_tool(
        base_url=base_url,
        tenant_id=tenant_id,
        tool="reference.web.read",
        arguments={"url": url, "mode": "get", "persist": True},
        internal_key=internal_key,
    )
    if not 200 <= status_code < 300:
        return StepResult("reference_web_read", "failed", f"{status_code or 'network'}: {raw}", response_json)
    result = _unwrap_result(response_json)
    data = result.get("data") if isinstance(result, dict) else {}
    reference = data.get("reference") if isinstance(data, dict) else {}
    if result.get("ok") is not True or data.get("schema_version") != "web_reference_tool_result_v1":
        return StepResult("reference_web_read", "failed", "reference.web.read did not return ok tool result", _compact(result))
    if reference.get("schema_version") != "web_reference_snapshot_v1" or reference.get("reference_only") is not True:
        return StepResult("reference_web_read", "failed", "missing reference_only snapshot", _compact(result))
    persistence = data.get("persistence") if isinstance(data, dict) else {}
    detail = f"title={reference.get('title') or 'untitled'}; persistence={(persistence or {}).get('status', 'unknown')}"
    return StepResult("reference_web_read", "passed", detail, _compact(result))


def probe_reference_search(base_url: str, tenant_id: str, query: str, internal_key: str) -> StepResult:
    status_code, response_json, raw = _invoke_tool(
        base_url=base_url,
        tenant_id=tenant_id,
        tool="reference.web.search",
        arguments={"query": query, "read_top": True, "persist": True, "limit": 5},
        internal_key=internal_key,
    )
    if not 200 <= status_code < 300:
        return StepResult("reference_web_search", "failed", f"{status_code or 'network'}: {raw}", response_json)
    result = _unwrap_result(response_json)
    data = result.get("data") if isinstance(result, dict) else {}
    if result.get("ok") is not True or data.get("schema_version") != "web_reference_search_result_v1":
        return StepResult("reference_web_search", "failed", "reference.web.search did not return ok search result", _compact(result))
    items = data.get("items") if isinstance(data, dict) else []
    read_result = data.get("read_result") if isinstance(data, dict) else {}
    read_ok = isinstance(read_result, dict) and read_result.get("ok") is True
    if not items:
        return StepResult("reference_web_search", "failed", "search returned no public result items", _compact(result))
    if not read_ok:
        return StepResult("reference_web_search", "failed", "search did not read the top public result", _compact(result))
    first_url = items[0].get("url") if isinstance(items[0], dict) else "unknown"
    return StepResult("reference_web_search", "passed", f"items={len(items)}; first_url={first_url}", _compact(result))


def probe_reference_failure(base_url: str, tenant_id: str, blocked_url: str, internal_key: str) -> StepResult:
    status_code, response_json, raw = _invoke_tool(
        base_url=base_url,
        tenant_id=tenant_id,
        tool="reference.web.read",
        arguments={"url": blocked_url, "mode": "get", "persist": True, "prompt": "blocked-url-smoke"},
        internal_key=internal_key,
    )
    if not 200 <= status_code < 300:
        return StepResult("reference_web_failure_snapshot", "failed", f"{status_code or 'network'}: {raw}", response_json)
    result = _unwrap_result(response_json)
    data = result.get("data") if isinstance(result, dict) else {}
    summary = data.get("summary") if isinstance(data, dict) else {}
    persistence = data.get("persistence") if isinstance(data, dict) else {}
    audit = data.get("audit") if isinstance(data, dict) else {}
    failed = result.get("failed") if isinstance(result, dict) else {}
    if result.get("ok") is not False or data.get("schema_version") != "web_reference_tool_result_v1":
        return StepResult("reference_web_failure_snapshot", "failed", "blocked URL did not return failed tool result", _compact(result))
    if not isinstance(failed, dict) or not failed.get("reason"):
        return StepResult("reference_web_failure_snapshot", "failed", "failed reason missing from tool result", _compact(result))
    if not isinstance(summary, dict) or not isinstance(summary.get("failed"), dict):
        return StepResult("reference_web_failure_snapshot", "failed", "failed reason missing from summary", _compact(result))
    if not isinstance(audit, dict) or not isinstance(audit.get("failed"), dict):
        return StepResult("reference_web_failure_snapshot", "failed", "failed reason missing from audit", _compact(result))
    if persistence.get("status") == "saved" and persistence.get("artifact_status") != "failed":
        return StepResult("reference_web_failure_snapshot", "failed", "failed read persisted without artifact_status=failed", _compact(result))
    if persistence.get("status") not in {"saved", "skipped", "failed"}:
        return StepResult("reference_web_failure_snapshot", "failed", f"unexpected persistence status={persistence.get('status')}", _compact(result))
    detail = f"reason={failed.get('reason')}; persistence={persistence.get('status')}; artifact_status={persistence.get('artifact_status')}"
    return StepResult("reference_web_failure_snapshot", "passed", detail, _compact(result))


def probe_wechat_url(base_url: str, tenant_id: str, url: str, internal_key: str) -> StepResult:
    payload = {
        "routing": {"tenant_id": tenant_id, "channel": "hermes_wechat", "timezone": "Asia/Shanghai"},
        "message": {"type": "text", "text": url},
    }
    status_code, response_json, raw = _post_json(
        f"{base_url.rstrip('/')}/api/hermes/wechat/messages",
        payload,
        headers=_headers(internal_key),
    )
    if not 200 <= status_code < 300:
        return StepResult("wechat_reference_url", "failed", f"{status_code or 'network'}: {raw}", response_json)
    if response_json.get("result_type") != "web_reference":
        return StepResult("wechat_reference_url", "failed", f"expected result_type=web_reference, got {response_json.get('result_type')}", response_json)
    if response_json.get("safety", {}).get("mode") != "reference_only":
        return StepResult("wechat_reference_url", "failed", "missing reference_only safety mode", response_json)
    return StepResult("wechat_reference_url", "passed", "internal WeChat ingress routed URL to reference.web.read", _compact(response_json))


def probe_wechat_search_analysis(base_url: str, tenant_id: str, symbol: str, query: str, internal_key: str) -> StepResult:
    text = f"分析 {symbol} 搜索一下 {query}"
    payload = {
        "routing": {"tenant_id": tenant_id, "channel": "hermes_wechat", "timezone": "Asia/Shanghai"},
        "message": {"type": "text", "text": text},
    }
    status_code, response_json, raw = _post_json(
        f"{base_url.rstrip('/')}/api/hermes/wechat/messages",
        payload,
        headers=_headers(internal_key),
    )
    if not 200 <= status_code < 300:
        return StepResult("wechat_search_analysis", "failed", f"{status_code or 'network'}: {raw}", response_json)
    if response_json.get("result_type") != "stock_analysis":
        return StepResult("wechat_search_analysis", "failed", f"expected stock_analysis, got {response_json.get('result_type')}", response_json)
    analysis = response_json.get("analysis") if isinstance(response_json, dict) else {}
    data = analysis.get("data") if isinstance(analysis, dict) else {}
    reference_summary = response_json.get("reference_summary") if isinstance(response_json, dict) else {}
    news_context = {}
    if isinstance(analysis, dict) and isinstance(analysis.get("news_context"), dict):
        news_context = analysis["news_context"]
    elif isinstance(data, dict) and isinstance(data.get("news_context"), dict):
        news_context = data["news_context"]
    elif isinstance(reference_summary, dict):
        news_context = reference_summary
    source_refs = response_json.get("source_refs") if isinstance(response_json, dict) else []
    has_argument_source = any(
        isinstance(ref, dict)
        and ref.get("source") == "domain_tool_arguments"
        and ref.get("ref") == "stock.analysis.news_context"
        for ref in source_refs
    )
    reply_text = str(response_json.get("reply_text") or "")
    if (
        news_context.get("schema_version") != "web_reference_search_news_context_v1"
        and not has_argument_source
        and "reference_only" not in reply_text
    ):
        return StepResult("wechat_search_analysis", "failed", "stock.analysis missing web_reference_search news_context", _compact(response_json))
    return StepResult("wechat_search_analysis", "passed", "search reference injected into stock.analysis news_context", _compact(response_json))


def probe_bridge_poll(webapp_base_url: str, cron_secret: str) -> StepResult:
    if not cron_secret:
        return StepResult("wechat_bridge_poll", "skipped", "cron/bridge secret not configured")
    status_code, response_json, raw = _post_json(
        f"{webapp_base_url.rstrip('/')}/api/openclaw/wechat/poll",
        {},
        headers={"Authorization": f"Bearer {cron_secret}", "Content-Type": "application/json"},
    )
    if not 200 <= status_code < 300:
        return StepResult("wechat_bridge_poll", "failed", f"{status_code or 'network'}: {raw}", response_json)
    credentials = response_json.get("credentials") if isinstance(response_json, dict) else None
    if not credentials:
        return StepResult("wechat_bridge_poll", "gap", "bridge reachable but no active ClawBot credentials", _compact(response_json))
    return StepResult("wechat_bridge_poll", "passed", f"bridge reachable with credentials={credentials}", _compact(response_json))


def probe_db_readiness(database_url: str) -> StepResult:
    if not database_url:
        return StepResult("db_reference_readiness", "skipped", "DATABASE_URL not configured")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:  # noqa: BLE001
        return StepResult("db_reference_readiness", "skipped", f"psycopg unavailable: {exc}")

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      (SELECT count(*) FROM public.artifact_registry
                       WHERE artifact_type = 'web_reference_snapshot'
                         AND created_at >= %s) AS recent_reference_artifacts,
                      (SELECT count(*) FROM public.wechat_bot_credentials
                       WHERE credential_status = 'active') AS active_wechat_credentials,
                      (SELECT count(*) FROM public.channel_bindings
                       WHERE channel IN ('hermes_wechat', 'openclaw_wechat')
                         AND binding_status = 'active'
                         AND is_primary = true) AS active_primary_wechat_bindings
                    """,
                    (since,),
                )
                row = dict(cur.fetchone() or {})
    except Exception as exc:  # noqa: BLE001
        return StepResult("db_reference_readiness", "failed", f"DB readiness query failed: {exc}")

    status = "passed" if row.get("recent_reference_artifacts", 0) > 0 else "gap"
    detail = (
        f"recent_reference_artifacts={row.get('recent_reference_artifacts', 0)}; "
        f"active_wechat_credentials={row.get('active_wechat_credentials', 0)}; "
        f"active_primary_wechat_bindings={row.get('active_primary_wechat_bindings', 0)}"
    )
    return StepResult("db_reference_readiness", status, detail, row)


def summarize(results: list[StepResult], *, strict_user_visible: bool) -> dict[str, Any]:
    counts = {"passed": 0, "failed": 0, "gap": 0, "skipped": 0}
    for result in results:
        counts[result.status] += 1

    core_steps = {
        "data_service_health",
        "domain_tools_manifest",
        "reference_web_read",
        "reference_web_failure_snapshot",
        "reference_web_search",
        "wechat_reference_url",
        "wechat_search_analysis",
    }
    failed_core = [result.step for result in results if result.step in core_steps and result.status != "passed"]
    bridge_gaps = [result.step for result in results if result.step == "wechat_bridge_poll" and result.status in {"gap", "skipped"}]

    if failed_core or counts["failed"]:
        status = "fail"
    elif strict_user_visible and bridge_gaps:
        status = "fail"
    elif bridge_gaps or counts["gap"]:
        status = "partial"
    else:
        status = "pass"

    return {
        "status": status,
        "strict_user_visible": strict_user_visible,
        "counts": counts,
        "failed_core_steps": failed_core,
        "user_visible_gaps": bridge_gaps,
        "steps": [result.to_dict() for result in results],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test Hermes reference.web first-stage readiness.")
    parser.add_argument("--base-url", default=os.getenv("HERMES_DATA_SERVICE_URL", DEFAULT_DATA_SERVICE_BASE_URL))
    parser.add_argument("--webapp-base-url", default=os.getenv("HERMES_WEBAPP_URL", DEFAULT_WEBAPP_BASE_URL))
    parser.add_argument("--tenant-id", default=os.getenv("HERMES_SMOKE_TENANT_ID", DEFAULT_TENANT_ID))
    parser.add_argument("--url", default=os.getenv("HERMES_REFERENCE_SMOKE_URL", DEFAULT_REFERENCE_URL))
    parser.add_argument("--blocked-url", default=os.getenv("HERMES_REFERENCE_SMOKE_BLOCKED_URL", DEFAULT_BLOCKED_REFERENCE_URL))
    parser.add_argument("--query", default=os.getenv("HERMES_REFERENCE_SMOKE_QUERY", DEFAULT_SEARCH_QUERY))
    parser.add_argument("--symbol", default=os.getenv("HERMES_REFERENCE_SMOKE_SYMBOL", DEFAULT_SYMBOL))
    parser.add_argument(
        "--internal-key",
        default=os.getenv("HERMES_DOMAIN_TOOLS_KEY") or os.getenv("HERMES_INTERNAL_TOKEN") or "",
    )
    parser.add_argument(
        "--cron-secret",
        default=os.getenv("HERMES_CRON_SECRET") or os.getenv("OPENCLAW_CRON_SECRET") or os.getenv("WECHAT_CLAWBOT_BRIDGE_SECRET") or "",
    )
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL") or os.getenv("WEBAPP_DATABASE_URL") or "")
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--skip-bridge", action="store_true")
    parser.add_argument("--strict-user-visible", action="store_true")
    return parser.parse_args()


def main() -> int:
    load_env_file(SERVER_ENV_FILE)
    load_env_file(ENV_FILE)
    args = parse_args()

    results = [
        probe_health(args.base_url),
        probe_manifest(args.base_url, args.internal_key),
        probe_reference_read(args.base_url, args.tenant_id, args.url, args.internal_key),
        probe_reference_failure(args.base_url, args.tenant_id, args.blocked_url, args.internal_key),
        probe_reference_search(args.base_url, args.tenant_id, args.query, args.internal_key),
        probe_wechat_url(args.base_url, args.tenant_id, args.url, args.internal_key),
        probe_wechat_search_analysis(args.base_url, args.tenant_id, args.symbol, args.query, args.internal_key),
    ]
    if not args.skip_db:
        results.append(probe_db_readiness(args.database_url))
    if not args.skip_bridge:
        results.append(probe_bridge_poll(args.webapp_base_url, args.cron_secret))

    summary = summarize(results, strict_user_visible=args.strict_user_visible)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if summary["status"] in {"pass", "partial"} and not args.strict_user_visible else (0 if summary["status"] == "pass" else 1)


if __name__ == "__main__":
    sys.exit(main())
