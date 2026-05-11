#!/usr/bin/env python3
"""
AI Holdings Analyzer 3.0 P0 smoke skeleton.

Flow:
tenant -> broker snapshot -> portfolio -> Sell Put -> confirmation -> delivery

`mock` mode always produces a contract-level happy path.
`live` mode uses hook endpoints supplied by env vars or CLI flags. Missing hooks are
reported as skipped so parallel agents can wire them in later without changing this file.
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

STEP_ENV_KEYS = {
    "tenant": "SMOKE_TENANT_ENDPOINT",
    "broker_snapshot": "SMOKE_BROKER_SNAPSHOT_ENDPOINT",
    "portfolio": "SMOKE_PORTFOLIO_ENDPOINT",
    "sell_put": "SMOKE_SELL_PUT_ENDPOINT",
    "confirmation": "SMOKE_CONFIRMATION_ENDPOINT",
    "delivery": "SMOKE_DELIVERY_ENDPOINT",
}

DEFAULT_DATA_SERVICE_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


MOCK_PAYLOADS = {
    "tenant": {
        "tenant_id": "tenant-smoke-001",
        "account_id": "acct-smoke-001",
        "default_portfolio_view_id": "pv-default-001",
    },
    "broker_snapshot": {
        "snapshot_id": "broker-snapshot-001",
        "connector_mode": "local_stub",
        "source": "futu_local_connector",
        "positions": [{"symbol": "AAPL", "asset_type": "equity"}],
    },
    "portfolio": {
        "portfolio_view_id": "pv-default-001",
        "base_currency": "USD",
        "positions_summary": {"equities": 1, "options": 0},
    },
    "sell_put": {
        "candidate_id": "sell-put-001",
        "actionability": "draft_only",
        "freshness_seconds": 45,
    },
    "confirmation": {
        "confirmation_id": "confirm-001",
        "status": "pending",
        "ttl_minutes": 30,
    },
    "delivery": {
        "delivery_id": "delivery-001",
        "channel": "webapp_deeplink",
        "status": "queued",
    },
}


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


def _post_json(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, None, raw
    except urllib.error.URLError as exc:
        return 0, None, str(exc.reason)


def _get_json(url: str) -> tuple[int, dict[str, Any] | None, str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, None, raw
    except urllib.error.URLError as exc:
        return 0, None, str(exc.reason)


def run_mock_flow() -> list[StepResult]:
    return [
        StepResult(step=step, status="passed", detail="mock contract satisfied", payload=payload)
        for step, payload in MOCK_PAYLOADS.items()
    ]


def run_live_flow(
    endpoint_overrides: dict[str, str],
    *,
    tenant_id: str | None = None,
    data_service_base_url: str | None = None,
    allow_builtin_probes: bool = True,
) -> list[StepResult]:
    results: list[StepResult] = []
    smoke_tenant_id = tenant_id or os.getenv("SMOKE_TENANT_ID", DEFAULT_TENANT_ID).strip()
    current_payload = {
        **MOCK_PAYLOADS["tenant"],
        "tenant_id": smoke_tenant_id,
    }
    base_url = (
        data_service_base_url
        or os.getenv("SMOKE_DATA_SERVICE_BASE_URL", "").strip()
        or os.getenv("DATA_SERVICE_BASE_URL", "").strip()
        or DEFAULT_DATA_SERVICE_BASE_URL
    ).rstrip("/")

    for step, env_key in STEP_ENV_KEYS.items():
        endpoint = endpoint_overrides.get(step) or os.getenv(env_key, "").strip()
        if not endpoint:
            if allow_builtin_probes:
                result, current_payload = _run_builtin_live_step(
                    step=step,
                    current_payload=current_payload,
                    tenant_id=smoke_tenant_id,
                    data_service_base_url=base_url,
                )
                results.append(result)
                continue
            results.append(
                StepResult(
                    step=step,
                    status="skipped",
                    detail=f"missing hook: set {env_key}",
                    payload=current_payload if step != "tenant" else MOCK_PAYLOADS["tenant"],
                )
            )
            current_payload = MOCK_PAYLOADS.get(step, current_payload)
            continue

        payload = current_payload
        status_code, response_json, raw = _post_json(endpoint, payload)
        if 200 <= status_code < 300:
            current_payload = _unwrap_response_data(response_json)
            validation_errors = _validate_step_payload(step, current_payload)
            if validation_errors:
                results.append(
                    StepResult(
                        step=step,
                        status="failed",
                        detail=f"{status_code} from {endpoint}; invalid payload: {', '.join(validation_errors)}",
                        payload=current_payload,
                    )
                )
                break
            results.append(
                StepResult(
                    step=step,
                    status="passed",
                    detail=f"{status_code} from {endpoint}",
                    payload=current_payload,
                )
            )
        else:
            results.append(
                StepResult(
                    step=step,
                    status="failed",
                    detail=f"{status_code or 'network'} from {endpoint}: {raw}",
                    payload=None,
                )
            )
            break

    return results


def _run_builtin_live_step(
    *,
    step: str,
    current_payload: dict[str, Any],
    tenant_id: str,
    data_service_base_url: str,
) -> tuple[StepResult, dict[str, Any]]:
    if step == "tenant":
        payload = {
            **MOCK_PAYLOADS["tenant"],
            "tenant_id": tenant_id,
            "source": "local_env",
        }
        return (
            StepResult(step=step, status="passed", detail="local tenant context resolved", payload=payload),
            payload,
        )

    if step == "broker_snapshot":
        payload = {
            "tenant_id": tenant_id,
            "connection_label": os.getenv("SMOKE_FUTU_CONNECTION_LABEL", "Futu E2E read-only dry run"),
            "snapshot_label": os.getenv("SMOKE_FUTU_SNAPSHOT_LABEL", "e2e"),
            "connector_mode": os.getenv("SMOKE_FUTU_CONNECTOR_MODE", "local_mock"),
            "persist": os.getenv("SMOKE_FUTU_PERSIST", "false").lower() in {"1", "true", "yes"},
        }
        status_code, response_json, raw = _post_json(f"{data_service_base_url}/api/v3/broker/futu/sync", payload)
        return _live_http_result(
            step=step,
            status_code=status_code,
            response_json=response_json,
            raw=raw,
            detail=f"data-service futu sync dry run at {data_service_base_url}",
            fallback_payload=current_payload,
        )

    if step == "portfolio":
        status_code, response_json, raw = _get_json(
            f"{data_service_base_url}/api/v3/portfolio/overview?tenant_id={tenant_id}"
        )
        return _live_http_result(
            step=step,
            status_code=status_code,
            response_json=response_json,
            raw=raw,
            detail=f"data-service portfolio overview at {data_service_base_url}",
            fallback_payload=current_payload,
        )

    if step == "sell_put":
        status_code, response_json, raw = _post_json(
            f"{data_service_base_url}/api/v3/options/sell-put/analyze",
            _sample_sell_put_payload(tenant_id),
        )
        return _live_http_result(
            step=step,
            status_code=status_code,
            response_json=response_json,
            raw=raw,
            detail=f"data-service Sell Put analysis at {data_service_base_url}",
            fallback_payload=current_payload,
        )

    env_key = STEP_ENV_KEYS[step]
    return (
        StepResult(
            step=step,
            status="skipped",
            detail=f"missing hook: set {env_key}",
            payload=current_payload,
        ),
        current_payload,
    )


def _live_http_result(
    *,
    step: str,
    status_code: int,
    response_json: dict[str, Any] | None,
    raw: str,
    detail: str,
    fallback_payload: dict[str, Any],
) -> tuple[StepResult, dict[str, Any]]:
    if 200 <= status_code < 300:
        payload = _unwrap_response_data(response_json)
        validation_errors = _validate_step_payload(step, payload)
        if validation_errors:
            return (
                StepResult(
                    step=step,
                    status="failed",
                    detail=f"{detail}; invalid payload: {', '.join(validation_errors)}",
                    payload=payload,
                ),
                payload,
            )
        return (
            StepResult(step=step, status="passed", detail=detail, payload=payload),
            payload,
        )

    if status_code in {0, 404, 503}:
        return (
            StepResult(
                step=step,
                status="skipped",
                detail=f"{detail}; unavailable ({status_code or 'network'}): {raw}",
                payload=fallback_payload,
            ),
            fallback_payload,
        )

    return (
        StepResult(
            step=step,
            status="failed",
            detail=f"{detail}; {status_code}: {raw}",
            payload=None,
        ),
        fallback_payload,
    )


def _unwrap_response_data(response_json: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response_json, dict):
        return {}
    if response_json.get("ok") is True and isinstance(response_json.get("data"), dict):
        return dict(response_json["data"])
    return dict(response_json)


def _validate_step_payload(step: str, payload: dict[str, Any]) -> list[str]:
    validators = {
        "tenant": ("tenant_id",),
        "broker_snapshot": ("broker_sync_snapshot_id", "snapshot_id", "account_snapshot", "snapshot_summary"),
        "portfolio": ("positions_count", "positions_summary", "freshness"),
        "sell_put": ("candidate_id", "candidate_ranking", "candidates", "overall_actionability"),
        "confirmation": ("confirmation_id", "session_id", "status"),
        "delivery": ("delivery_id", "status"),
    }
    accepted_fields = validators[step]
    if any(payload.get(field) is not None for field in accepted_fields):
        return []
    return [f"expected one of {accepted_fields}"]


def _sample_sell_put_payload(tenant_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    as_of = (now - timedelta(seconds=10)).isoformat()
    return {
        "tenant_id": tenant_id,
        "underlying_symbol": os.getenv("SMOKE_SELL_PUT_SYMBOL", "AAPL"),
        "quote": {
            "symbol": os.getenv("SMOKE_SELL_PUT_SYMBOL", "AAPL"),
            "as_of": as_of,
            "price": float(os.getenv("SMOKE_SELL_PUT_UNDERLYING_PRICE", "190.0")),
            "currency": "USD",
            "cross_check_status": "matched",
        },
        "option_candidates": [
            {
                "contract_symbol": os.getenv("SMOKE_SELL_PUT_CONTRACT", "AAPL260619P175"),
                "strike": float(os.getenv("SMOKE_SELL_PUT_STRIKE", "175.0")),
                "expiry": os.getenv("SMOKE_SELL_PUT_EXPIRY", "2026-06-19"),
                "days_to_expiry": int(os.getenv("SMOKE_SELL_PUT_DTE", "40")),
                "bid": 2.4,
                "ask": 2.7,
                "delta": 0.21,
                "implied_volatility": 0.34,
                "open_interest": 1200,
                "volume": 180,
                "as_of": as_of,
            }
        ],
    }


def summarize(results: list[StepResult], mode: str, *, strict_skips: bool = False) -> dict[str, Any]:
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for result in results:
        counts[result.status] += 1

    overall_status = "fail" if counts["failed"] or (strict_skips and counts["skipped"]) else "pass"
    return {
        "mode": mode,
        "status": overall_status,
        "strict_skips": strict_skips,
        "counts": counts,
        "steps": [result.to_dict() for result in results],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the P0 smoke skeleton.")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--strict-live", action="store_true", help="Fail live mode when any step is skipped")
    parser.add_argument("--no-builtins", action="store_true", help="Disable built-in local data-service probes")
    parser.add_argument("--tenant-id", default="", help="Tenant id for built-in live probes")
    parser.add_argument("--data-service-base-url", default="", help="Base URL for built-in data-service probes")
    for step in STEP_ENV_KEYS:
        parser.add_argument(f"--{step.replace('_', '-')}-endpoint", default="")
    return parser.parse_args()


def main() -> int:
    load_env_file(ENV_FILE)
    args = parse_args()
    overrides = {
        "tenant": args.tenant_endpoint,
        "broker_snapshot": args.broker_snapshot_endpoint,
        "portfolio": args.portfolio_endpoint,
        "sell_put": args.sell_put_endpoint,
        "confirmation": args.confirmation_endpoint,
        "delivery": args.delivery_endpoint,
    }

    results = (
        run_mock_flow()
        if args.mode == "mock"
        else run_live_flow(
            overrides,
            tenant_id=args.tenant_id or None,
            data_service_base_url=args.data_service_base_url or None,
            allow_builtin_probes=not args.no_builtins,
        )
    )
    summary = summarize(results, args.mode, strict_skips=args.strict_live and args.mode == "live")
    rendered = json.dumps(summary, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)

    print(rendered)
    return 1 if summary["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
