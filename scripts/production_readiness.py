#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


@dataclass
class CheckResult:
    group: str
    name: str
    status: str
    detail: str
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "group": self.group,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "missing": self.missing,
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


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _missing(names: Iterable[str]) -> list[str]:
    return [name for name in names if not _env(name)]


def _check_required(group: str, name: str, names: list[str], detail: str, *, profile: str) -> CheckResult:
    missing = _missing(names)
    status = "pass" if not missing else ("warn" if profile == "local" else "fail")
    return CheckResult(
        group=group,
        name=name,
        status=status,
        detail=detail if not missing else f"missing required env: {', '.join(missing)}",
        missing=missing,
    )


def run_checks(*, profile: str) -> list[CheckResult]:
    checks: list[CheckResult] = [
        _check_required(
            "database",
            "supabase_core",
            ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"],
            "Supabase REST/Auth/service role configured",
            profile=profile,
        ),
        _check_required(
            "delivery",
            "openclaw_webhook_delivery",
            ["OPENCLAW_DELIVERY_MODE", "OPENCLAW_DELIVERY_WEBHOOK_URL", "OPENCLAW_DELIVERY_WEBHOOK_SECRET"],
            "OpenClaw delivery webhook endpoint and HMAC secret configured",
            profile=profile,
        ),
        _check_required(
            "model",
            "live_model_provider",
            ["GBRAIN_LIVE_MODELS_ENABLED", "OPENAI_API_KEY", "MINIMAX_API_KEY"],
            "Live model routing can use GPT-5.5 and MiniMax through the unified adapter",
            profile=profile,
        ),
        _check_required(
            "storage",
            "artifact_object_storage",
            ["HERMES_ARTIFACT_STORAGE_BACKEND", "HERMES_ARTIFACT_BASE_URI"],
            "Hermes artifacts have an object storage backend and stable URI base",
            profile=profile,
        ),
        _check_required(
            "storage",
            "historical_market_storage",
            ["HISTORICAL_STORAGE_BACKEND"],
            "Historical market data cache has a production storage backend",
            profile=profile,
        ),
        _check_required(
            "fx",
            "trusted_fx_source",
            ["FX_RATES_SOURCE"],
            "Portfolio base-currency conversion has an auditable FX source label",
            profile=profile,
        ),
        _check_required(
            "monitoring",
            "sentry",
            ["SENTRY_DSN"],
            "Sentry DSN configured for runtime error monitoring",
            profile=profile,
        ),
        _check_required(
            "web",
            "public_origins",
            ["CORS_ALLOWED_ORIGINS", "WEBAPP_BASE_URL"],
            "CORS and WebApp base URL configured explicitly",
            profile=profile,
        ),
    ]

    checks.append(_mode_check("delivery", "OPENCLAW_DELIVERY_MODE", expected="webhook", profile=profile))
    checks.append(_enabled_check("model", "GBRAIN_LIVE_MODELS_ENABLED", profile=profile))
    checks.append(_one_of_check("storage", "HERMES_ARTIFACT_STORAGE_BACKEND", {"supabase", "file"}, profile=profile))
    checks.append(_one_of_check("storage", "HISTORICAL_STORAGE_BACKEND", {"supabase_storage", "file"}, profile=profile))
    checks.append(_fx_source_check(profile=profile))
    checks.append(_cors_check(profile=profile))
    return checks


def _mode_check(group: str, env_name: str, *, expected: str, profile: str) -> CheckResult:
    value = _env(env_name).lower()
    if profile == "local" and value != expected:
        return CheckResult(group, env_name, "warn", f"{env_name}={value or '<empty>'}; production expects {expected}")
    return CheckResult(
        group,
        env_name,
        "pass" if value == expected else "fail",
        f"{env_name}={value or '<empty>'}; expected {expected}",
        [] if value == expected else [env_name],
    )


def _enabled_check(group: str, env_name: str, *, profile: str) -> CheckResult:
    value = _env(env_name).lower()
    enabled = value in {"1", "true", "yes"}
    if profile == "local" and not enabled:
        return CheckResult(group, env_name, "warn", "live model calls are disabled in local profile")
    return CheckResult(
        group,
        env_name,
        "pass" if enabled else "fail",
        f"{env_name}={value or '<empty>'}; expected true",
        [] if enabled else [env_name],
    )


def _one_of_check(group: str, env_name: str, allowed: set[str], *, profile: str) -> CheckResult:
    value = _env(env_name).lower()
    if profile == "local" and value not in allowed:
        return CheckResult(group, env_name, "warn", f"{env_name}={value or '<empty>'}; production expects one of {sorted(allowed)}")
    return CheckResult(
        group,
        env_name,
        "pass" if value in allowed else "fail",
        f"{env_name}={value or '<empty>'}; expected one of {sorted(allowed)}",
        [] if value in allowed else [env_name],
    )


def _fx_source_check(*, profile: str) -> CheckResult:
    has_inline_rates = bool(_env("FX_RATES_JSON"))
    has_endpoint = bool(_env("FX_RATE_ENDPOINT"))
    if has_inline_rates or has_endpoint:
        return CheckResult("fx", "fx_rates", "pass", "trusted FX source is configured")
    return CheckResult(
        "fx",
        "fx_rates",
        "warn" if profile == "local" else "fail",
        "set FX_RATES_JSON or FX_RATE_ENDPOINT before production release",
        ["FX_RATES_JSON or FX_RATE_ENDPOINT"],
    )


def _cors_check(*, profile: str) -> CheckResult:
    origins = _env("CORS_ALLOWED_ORIGINS")
    unsafe = "*" in {item.strip() for item in origins.split(",")}
    if unsafe and profile == "production":
        return CheckResult("web", "cors_no_wildcard", "fail", "CORS_ALLOWED_ORIGINS must not use * in production")
    return CheckResult("web", "cors_no_wildcard", "pass", "CORS origins do not use wildcard")


def summarize(checks: list[CheckResult], *, profile: str) -> dict:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for check in checks:
        counts[check.status] += 1
    return {
        "profile": profile,
        "status": "fail" if counts["fail"] else "pass",
        "counts": counts,
        "checks": [check.to_dict() for check in checks],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check AI holdings production readiness config.")
    parser.add_argument("--profile", choices=["local", "production"], default="production")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(ENV_FILE)
    summary = summarize(run_checks(profile=args.profile), profile=args.profile)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
