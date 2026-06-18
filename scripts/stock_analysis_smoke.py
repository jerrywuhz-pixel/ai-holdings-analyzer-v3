#!/usr/bin/env python3
"""
Hermes stock.analysis smoke probe.

Checks the two user-facing paths that matter for the P1 stock-analysis slice:
1. /api/hermes/domain-tools/invoke with tool=stock.analysis
2. /api/hermes/wechat/messages with a natural-language stock-analysis prompt

The probe validates routing, response shape, report constraints, and safety
mode. Market-data and persistence failures are reported as payload details
instead of being conflated with ingress failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
SERVER_ENV_FILE = PROJECT_ROOT / ".env.server"
DEFAULT_DATA_SERVICE_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
DEFAULT_SYMBOL = "NVDA"
MODULE_MAX_CHARS = 200


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
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    internal_key: str = "",
) -> tuple[int, dict[str, Any] | None, str]:
    headers = {"Content-Type": "application/json"}
    if internal_key:
        headers["X-Hermes-Domain-Tools-Key"] = internal_key
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw), raw
        except json.JSONDecodeError:
            return exc.code, None, raw
    except urllib.error.URLError as exc:
        return 0, None, str(exc.reason)


def run_domain_tool_probe(
    *,
    base_url: str,
    tenant_id: str,
    symbol: str,
    prompt: str,
    persist: bool,
    internal_key: str = "",
) -> StepResult:
    payload = {
        "tool": "stock.analysis",
        "tenant_id": tenant_id,
        "arguments": {
            "tenant_id": tenant_id,
            "symbol": symbol,
            "prompt": prompt,
            "persist": persist,
            "entry_surface": "system",
        },
    }
    status_code, response_json, raw = _post_json(
        f"{base_url.rstrip('/')}/api/hermes/domain-tools/invoke",
        payload,
        internal_key=internal_key,
    )
    if not 200 <= status_code < 300:
        return StepResult("domain_tool", "failed", f"{status_code or 'network'}: {raw}", response_json)
    result = _unwrap_domain_tool_result(response_json)
    errors = _validate_stock_analysis_result(result)
    if errors:
        return StepResult("domain_tool", "failed", "; ".join(errors), result)
    detail = _analysis_detail(result)
    return StepResult("domain_tool", "passed", detail, _compact_analysis_payload(result))


def run_wechat_probe(
    *,
    base_url: str,
    tenant_id: str,
    symbol: str,
    prompt: str,
    internal_key: str = "",
) -> StepResult:
    payload = {
        "routing": {
            "tenant_id": tenant_id,
            "channel": "hermes_wechat",
            "timezone": "Asia/Shanghai",
        },
        "message": {
            "type": "text",
            "text": prompt or f"{symbol} 怎么看",
        },
    }
    status_code, response_json, raw = _post_json(
        f"{base_url.rstrip('/')}/api/hermes/wechat/messages",
        payload,
        internal_key=internal_key,
    )
    if not 200 <= status_code < 300:
        return StepResult("wechat_message", "failed", f"{status_code or 'network'}: {raw}", response_json)
    errors = _validate_wechat_result(response_json, symbol)
    if errors:
        return StepResult("wechat_message", "failed", "; ".join(errors), response_json)
    analysis = response_json.get("analysis") if isinstance(response_json, dict) else {}
    persistence = analysis.get("persistence") if isinstance(analysis, dict) else {}
    persistence_status = persistence.get("status") if isinstance(persistence, dict) else "unknown"
    actionability = (analysis or {}).get("actionability_cap")
    return StepResult(
        "wechat_message",
        "passed",
        f"routed stock_analysis; actionability={actionability}; persistence={persistence_status}",
        _compact_wechat_payload(response_json),
    )


def summarize(results: list[StepResult], *, strict_persistence: bool = False) -> dict[str, Any]:
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for result in results:
        counts[result.status] += 1

    persistence_failures: list[str] = []
    if strict_persistence:
        for result in results:
            persistence = _extract_persistence(result.payload or {})
            status = persistence.get("status")
            if status and status != "saved":
                persistence_failures.append(f"{result.step}: persistence={status}")

    status = "fail" if counts["failed"] or persistence_failures else "pass"
    return {
        "status": status,
        "strict_persistence": strict_persistence,
        "counts": counts,
        "persistence_failures": persistence_failures,
        "steps": [result.to_dict() for result in results],
    }


def _unwrap_domain_tool_result(response_json: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response_json, dict):
        return {}
    result = response_json.get("result")
    return dict(result) if isinstance(result, dict) else dict(response_json)


def _validate_stock_analysis_result(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if result.get("tool") != "stock.analysis":
        errors.append("expected tool=stock.analysis")
    if result.get("ok") is not True:
        errors.append(f"expected ok=true, got {result.get('ok')}")
    data = result.get("data")
    if not isinstance(data, dict):
        return [*errors, "missing data object"]
    if data.get("schema_version") != "stock_analysis_p1":
        errors.append("expected schema_version=stock_analysis_p1")
    report = data.get("report")
    if not isinstance(report, dict):
        errors.append("missing report object")
    else:
        if "conclusion" not in report:
            errors.append("missing conclusion-first report module")
        oversized = [key for key, value in report.items() if len(str(value)) > MODULE_MAX_CHARS]
        if oversized:
            errors.append(f"report modules exceed {MODULE_MAX_CHARS} chars: {', '.join(oversized)}")
    constraints = data.get("report_constraints")
    if not isinstance(constraints, dict) or constraints.get("module_max_chars") != MODULE_MAX_CHARS:
        errors.append("missing report constraint module_max_chars=200")
    if data.get("actionability_cap") not in {"blocked", "analysis_only", "trade_draft"}:
        errors.append("unexpected actionability_cap")
    return errors


def _validate_wechat_result(response_json: dict[str, Any] | None, symbol: str) -> list[str]:
    if not isinstance(response_json, dict):
        return ["missing JSON response"]
    errors: list[str] = []
    if response_json.get("ok") is not True:
        errors.append("expected ok=true")
    if response_json.get("runtime") != "hermes":
        errors.append("expected runtime=hermes")
    if response_json.get("result_type") != "stock_analysis":
        errors.append(f"expected result_type=stock_analysis, got {response_json.get('result_type')}")
    if not response_json.get("reply_text"):
        errors.append("missing reply_text")
    safety = response_json.get("safety")
    if not isinstance(safety, dict) or safety.get("places_orders") is not False:
        errors.append("missing no-order safety guard")
    analysis = response_json.get("analysis")
    if not isinstance(analysis, dict):
        errors.append("missing analysis object")
    else:
        if str(analysis.get("symbol") or "").upper() != symbol.upper():
            errors.append("analysis symbol mismatch")
        report = analysis.get("report")
        if not isinstance(report, dict) or "conclusion" not in report:
            errors.append("missing conclusion report in WeChat response")
        elif any(len(str(value)) > MODULE_MAX_CHARS for value in report.values()):
            errors.append("WeChat report module exceeds 200 chars")
    return errors


def _analysis_detail(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    persistence = data.get("persistence") if isinstance(data.get("persistence"), dict) else {}
    quality = data.get("data_quality") if isinstance(data.get("data_quality"), dict) else {}
    return (
        f"actionability={data.get('actionability_cap')}; "
        f"action={data.get('action')}; "
        f"quote_source={quality.get('quote_source')}; "
        f"persistence={persistence.get('status')}"
    )


def _extract_persistence(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    persistence = data.get("persistence") if isinstance(data, dict) else None
    if not isinstance(persistence, dict):
        persistence = analysis.get("persistence") if isinstance(analysis, dict) else None
    return persistence if isinstance(persistence, dict) else {}


def _compact_analysis_payload(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "tool": result.get("tool"),
        "ok": result.get("ok"),
        "status": result.get("status"),
        "data": {
            "schema_version": data.get("schema_version"),
            "symbol": data.get("symbol"),
            "action": data.get("action"),
            "action_label": data.get("action_label"),
            "actionability_cap": data.get("actionability_cap"),
            "score": data.get("score"),
            "data_quality": data.get("data_quality"),
            "persistence": data.get("persistence"),
            "report": data.get("report"),
            "report_constraints": data.get("report_constraints"),
        },
    }


def _compact_wechat_payload(response_json: dict[str, Any]) -> dict[str, Any]:
    analysis = response_json.get("analysis") if isinstance(response_json.get("analysis"), dict) else {}
    return {
        "ok": response_json.get("ok"),
        "runtime": response_json.get("runtime"),
        "result_type": response_json.get("result_type"),
        "reply_text": response_json.get("reply_text"),
        "intent": response_json.get("intent"),
        "analysis": analysis,
        "safety": response_json.get("safety"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Hermes stock.analysis smoke probes.")
    parser.add_argument("--mode", choices=["domain", "wechat", "both"], default="both")
    parser.add_argument("--base-url", default="", help="Data-service base URL")
    parser.add_argument("--tenant-id", default="", help="Tenant id for analysis")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--prompt", default="", help="Prompt text; defaults to '<symbol> 怎么看'")
    parser.add_argument("--persist", action="store_true", help="Ask stock.analysis to persist artifacts")
    parser.add_argument("--strict-persistence", action="store_true", help="Fail if persistence is not saved")
    parser.add_argument("--internal-key", default="", help="Hermes internal key; defaults to env if present")
    parser.add_argument("--output", default="", help="Optional JSON output path")
    return parser.parse_args()


def main() -> int:
    load_env_file(ENV_FILE)
    load_env_file(SERVER_ENV_FILE)
    args = parse_args()
    base_url = (
        args.base_url
        or os.getenv("SMOKE_DATA_SERVICE_BASE_URL", "").strip()
        or DEFAULT_DATA_SERVICE_BASE_URL
    ).rstrip("/")
    tenant_id = args.tenant_id or os.getenv("SMOKE_TENANT_ID", "").strip() or DEFAULT_TENANT_ID
    symbol = args.symbol.strip().upper()
    prompt = args.prompt or f"{symbol} 怎么看"
    internal_key = (
        args.internal_key
        or os.getenv("HERMES_DOMAIN_TOOLS_KEY", "").strip()
        or os.getenv("HERMES_INTERNAL_TOKEN", "").strip()
    )

    results: list[StepResult] = []
    if args.mode in {"domain", "both"}:
        results.append(
            run_domain_tool_probe(
                base_url=base_url,
                tenant_id=tenant_id,
                symbol=symbol,
                prompt=prompt,
                persist=args.persist,
                internal_key=internal_key,
            )
        )
    if args.mode in {"wechat", "both"}:
        results.append(
            run_wechat_probe(
                base_url=base_url,
                tenant_id=tenant_id,
                symbol=symbol,
                prompt=prompt,
                internal_key=internal_key,
            )
        )

    summary = summarize(results, strict_persistence=args.strict_persistence)
    rendered = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered)
    return 1 if summary["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
