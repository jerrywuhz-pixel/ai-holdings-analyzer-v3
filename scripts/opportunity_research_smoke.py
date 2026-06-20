#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def post_json(url: str, payload: dict[str, Any], *, internal_key: str) -> tuple[int, dict[str, Any] | None, str]:
    headers = {"Content-Type": "application/json"}
    if internal_key:
        headers["X-Hermes-Domain-Tools-Key"] = internal_key
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw), raw
        except json.JSONDecodeError:
            return exc.code, None, raw
    except urllib.error.URLError as exc:
        return 0, None, str(exc.reason)


def compact_response(response: dict[str, Any] | None) -> dict[str, Any]:
    response = response if isinstance(response, dict) else {}
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    persistence = data.get("persistence") if isinstance(data.get("persistence"), dict) else {}
    cases = data.get("cases") if isinstance(data.get("cases"), list) else []
    if result.get("tool") == "opportunity.review.run":
        marks = data.get("marks") if isinstance(data.get("marks"), list) else []
        return {
            "ok": response.get("ok"),
            "tool_status": result.get("status"),
            "tool_error": result.get("error"),
            "tool_message": result.get("message"),
            "reviewed_cases": data.get("reviewed_cases"),
            "marks_count": len(marks),
            "summary": summary,
            "first_mark": marks[0] if marks else None,
        }
    return {
        "ok": response.get("ok"),
        "tool_status": result.get("status"),
        "tool_error": result.get("error"),
        "tool_message": result.get("message"),
        "model_policy": data.get("model_policy"),
        "candidate_pool": summary.get("candidate_pool"),
        "cases_count": len(cases),
        "top": [
            {
                "symbol": item.get("symbol"),
                "rank": item.get("leader_rank"),
                "actionability": item.get("actionability"),
                "five_layer": item.get("five_layer"),
            }
            for item in (summary.get("top_opportunities") or [])[:5]
            if isinstance(item, dict)
        ],
        "persistence": {
            "status": persistence.get("status"),
            "reason": persistence.get("reason"),
            "backend": persistence.get("backend"),
            "agent_run_id": persistence.get("agent_run_id"),
            "artifact_id": persistence.get("artifact_id"),
            "case_ids_count": len(persistence.get("opportunity_case_ids") or []),
            "candidate_pool": persistence.get("candidate_pool"),
            "delivery": persistence.get("delivery"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke opportunity.research.run through Hermes domain-tools.")
    parser.add_argument("--mode", choices=["research", "review"], default="research")
    parser.add_argument("--base-url", default=os.getenv("DATA_SERVICE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--market", default="US")
    parser.add_argument("--session-type", default="manual_cloud_smoke")
    parser.add_argument("--report-date", default="")
    parser.add_argument("--universe-policy", default="holdings_watchlist_hard_tech")
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--env-file", default=str(PROJECT_ROOT / ".env.server"))
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    internal_key = os.getenv("HERMES_DOMAIN_TOOLS_KEY") or os.getenv("HERMES_INTERNAL_TOKEN") or ""
    if args.mode == "review":
        payload = {
            "tool": "opportunity.review.run",
            "tenant_id": args.tenant_id,
            "arguments": {
                "tenant_id": args.tenant_id,
                "market": args.market,
                "review_date": args.report_date,
                "persist": args.persist,
            },
        }
    else:
        payload = {
            "tool": "opportunity.research.run",
            "tenant_id": args.tenant_id,
            "arguments": {
                "tenant_id": args.tenant_id,
                "market": args.market,
                "session_type": args.session_type,
                "universe_policy": args.universe_policy,
                "persist": args.persist,
                "max_candidates": args.max_candidates,
            },
        }
        if args.report_date:
            payload["arguments"]["report_date"] = args.report_date
    status_code, response, raw = post_json(
        f"{args.base_url.rstrip('/')}/api/hermes/domain-tools/invoke",
        payload,
        internal_key=internal_key,
    )
    compact = compact_response(response)
    compact["http_status"] = status_code
    if not 200 <= status_code < 300:
        compact["error"] = raw[:1000]
    print(json.dumps(compact, ensure_ascii=False, indent=2, default=str))
    return 0 if 200 <= status_code < 300 and compact.get("ok") is True else 1


if __name__ == "__main__":
    sys.exit(main())
