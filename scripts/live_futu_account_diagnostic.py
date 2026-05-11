#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Futu OpenD account diagnostic. Lists candidate entity/account combinations without dumping holdings."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("FUTU_CONNECTOR_BASE_URL", "http://127.0.0.1:8765"),
        help="Futu sidecar base URL. Default: %(default)s",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("FUTU_CONNECTOR_TIMEOUT_SECONDS", "8")),
        help="HTTP timeout in seconds. Default: %(default)s",
    )
    return parser.parse_args()


def _get_json(url: str, timeout: float) -> dict[str, Any]:
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{url} returned a non-object payload")
    return payload


def _unwrap_data(payload: dict[str, Any]) -> dict[str, Any]:
    detail = payload.get("detail")
    if isinstance(detail, dict) and detail.get("ok") is False:
        raise RuntimeError(str(detail.get("message") or "request failed"))
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise RuntimeError("diagnostic payload must be an object")
    if payload.get("ok") is False:
        raise RuntimeError(str(payload.get("message") or payload.get("error") or "request failed"))
    return data


def _render_requested(requested: dict[str, Any]) -> str:
    return (
        f"security_firm={requested.get('security_firm', '-')}"
        f" trd_market={requested.get('trd_market', '-')}"
        f" acc_id={requested.get('acc_id', '-')}"
    )


def _render_candidate(candidate: dict[str, Any]) -> str:
    position_count = candidate.get("position_count")
    return (
        f"{'*' if candidate.get('matches_requested') else ' '} "
        f"firm={candidate.get('security_firm', '-'):<16} "
        f"market={candidate.get('trd_market', '-'):<4} "
        f"acc_id={candidate.get('acc_id', '-'):<12} "
        f"accounts={candidate.get('account_count', 0):<2} "
        f"positions={position_count if position_count is not None else '-':<4} "
        f"status={candidate.get('status', '-')}"
    )


def main() -> int:
    args = _parse_args()
    base_url = args.base_url.rstrip("/")
    try:
        health_payload = _get_json(f"{base_url}/health", args.timeout)
        diagnostics_path = (
            health_payload.get("diagnostics", {}).get("account_context_path")
            if isinstance(health_payload.get("diagnostics"), dict)
            else None
        ) or "/api/v1/account-diagnostics"
        diagnostic_payload = _get_json(f"{base_url}{diagnostics_path}", args.timeout)
        data = _unwrap_data(diagnostic_payload)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    requested = data.get("requested") or {}
    summary = data.get("summary") or {}
    candidates = data.get("candidate_entities") or []

    print("Futu account diagnostic")
    print(f"Sidecar: {base_url}")
    print(f"Requested: {_render_requested(requested)}")
    print(
        "Summary:"
        f" candidates={summary.get('candidate_count', len(candidates))}"
        f" non_zero_position_candidates={summary.get('non_zero_position_candidates', 0)}"
    )
    print("Candidates:")
    for candidate in candidates:
        print(_render_candidate(candidate))
    recommendations = data.get("recommendations") or []
    if recommendations:
        print("Suggestions:")
        for item in recommendations:
            print(f"- {item}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
