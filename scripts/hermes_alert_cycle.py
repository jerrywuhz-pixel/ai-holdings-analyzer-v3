#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def post_json(base_url: str, path: str, payload: dict, token: str) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Hermes-Domain-Tools-Key": token,
            "X-Hermes-Internal-Token": token,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Hermes alert evaluation and delivery processing once.")
    parser.add_argument("--base-url", default=os.getenv("HERMES_DOMAIN_TOOLS_URL") or os.getenv("DATA_SERVICE_URL") or "http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.getenv("HERMES_DOMAIN_TOOLS_KEY") or os.getenv("HERMES_INTERNAL_TOKEN") or "")
    parser.add_argument("--limit", type=int, default=int(os.getenv("HERMES_ALERT_CYCLE_LIMIT", "50")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-delivery", action="store_true")
    args = parser.parse_args()

    if not args.token:
        print("missing HERMES_DOMAIN_TOOLS_KEY or HERMES_INTERNAL_TOKEN", file=sys.stderr)
        return 2

    try:
        alert_result = post_json(
            args.base_url,
            "/api/hermes/alerts/evaluate",
            {"limit": args.limit, "dry_run": args.dry_run},
            args.token,
        )
        result = {"alerts": alert_result}
        if not args.skip_delivery:
            result["delivery"] = post_json(
                args.base_url,
                "/api/hermes/delivery/process-ready",
                {"limit": args.limit, "dry_run": args.dry_run},
                args.token,
            )
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
