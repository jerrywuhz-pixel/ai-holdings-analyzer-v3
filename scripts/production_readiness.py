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


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip('"').strip("'").lower()
    if not normalized:
        return True
    exact_placeholders = {
        "todo",
        "tbd",
        "changeme",
        "change-me",
        "replace-me",
        "placeholder",
        "your-value",
    }
    if normalized in exact_placeholders:
        return True
    placeholder_markers = (
        "your-project",
        "your_",
        "example.",
        "<",
        ">",
        "user:password@",
        "rds-internal-host",
        "redis-internal-host",
    )
    return any(marker in normalized for marker in placeholder_markers)


def _missing(names: Iterable[str]) -> list[str]:
    return [name for name in names if _is_placeholder(_env(name))]


def _soft_missing(profile: str, *, profiles: set[str] | None = None) -> bool:
    return profile in (profiles or {"local"})


def _check_required(
    group: str,
    name: str,
    names: list[str],
    detail: str,
    *,
    profile: str,
    soft_profiles: set[str] | None = None,
) -> CheckResult:
    missing = _missing(names)
    status = "pass" if not missing else ("warn" if _soft_missing(profile, profiles=soft_profiles) else "fail")
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
            soft_profiles={"local", "lightweight"},
        ),
        _check_required(
            "delivery",
            "openclaw_webhook_delivery",
            ["OPENCLAW_DELIVERY_MODE", "OPENCLAW_DELIVERY_WEBHOOK_URL", "OPENCLAW_DELIVERY_WEBHOOK_SECRET"],
            "OpenClaw delivery webhook endpoint and HMAC secret configured",
            profile=profile,
            soft_profiles={"local", "lightweight"},
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
        _observability_check(profile=profile),
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
    checks.append(_live_model_provider_check(profile=profile))
    checks.append(_one_of_check("storage", "HERMES_ARTIFACT_STORAGE_BACKEND", {"supabase", "file"}, profile=profile))
    checks.append(_one_of_check("storage", "HISTORICAL_STORAGE_BACKEND", {"supabase_storage", "file"}, profile=profile))
    checks.append(_portfolio_read_repository_check(profile=profile))
    checks.append(_fx_source_check(profile=profile))
    checks.append(_cors_check(profile=profile))
    return checks


def _live_model_provider_check(*, profile: str) -> CheckResult:
    common_missing = _missing(["GBRAIN_LIVE_MODELS_ENABLED"])
    has_minimax = bool(_env("MINIMAX_API_KEY") or _env("ANTHROPIC_AUTH_TOKEN") or _env("ANTHROPIC_API_KEY"))
    if not has_minimax:
        common_missing.append("MINIMAX_API_KEY or ANTHROPIC_AUTH_TOKEN")
    has_openai_api = bool(_env("OPENAI_API_KEY") or _env("GBRAIN_OPENAI_API_KEY"))
    has_codex_bridge = bool(
        (_env("OPENAI_CODEX_AUTH_PROFILE") or _env("HERMES_AUTH_PROFILE_ID") or _env("OPENCLAW_AUTH_PROFILE"))
        and (_env("OPENAI_CODEX_BRIDGE_BASE_URL") or _env("HERMES_CODEX_GATEWAY_BASE_URL") or _env("OPENCLAW_CODEX_GATEWAY_BASE_URL"))
    )
    deep_missing = []
    if not (has_openai_api or has_codex_bridge):
        deep_missing.append("OPENAI_API_KEY or OPENAI_CODEX_AUTH_PROFILE+OPENAI_CODEX_BRIDGE_BASE_URL")

    missing = [*common_missing, *deep_missing]
    if common_missing:
        status = "warn" if profile == "local" else "fail"
    elif deep_missing:
        status = "warn" if profile in {"local", "lightweight"} else "fail"
    else:
        status = "pass"
    route = "openai_api_key" if has_openai_api else "openai_codex_bridge" if has_codex_bridge else "missing"
    light_ready = not common_missing
    if missing and light_ready and deep_missing and profile == "lightweight":
        detail = (
            "MiniMax light route is configured for first-stage deployment; "
            "deep research still needs OpenAI API key or system-level openai-codex bridge before production"
        )
    elif missing:
        detail = f"missing required env: {', '.join(missing)}"
    else:
        detail = (
            f"Live model routing route={route}; MiniMax configured={has_minimax}; "
            "deep research can use OpenAI API key or a system-level openai-codex bridge"
        )
    return CheckResult(
        group="model",
        name="live_model_provider",
        status=status,
        detail=detail,
        missing=missing,
    )


def _mode_check(group: str, env_name: str, *, expected: str, profile: str) -> CheckResult:
    value = _env(env_name).lower()
    if profile == "lightweight" and value in {"log", expected}:
        return CheckResult(
            group,
            env_name,
            "pass",
            f"{env_name}={value}; lightweight first stage accepts log delivery, production expects {expected}",
        )
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


def _portfolio_read_repository_check(*, profile: str) -> CheckResult:
    broker_repository = _env("BROKER_SYNC_REPOSITORY").lower()
    portfolio_repository = _env("PORTFOLIO_READ_REPOSITORY").lower()
    allowed = {"postgres", "supabase", "supabase_rest", "local_postgres", "database_url"}
    if portfolio_repository:
        if portfolio_repository not in allowed:
            return CheckResult(
                "database",
                "portfolio_read_repository",
                "warn" if profile == "local" else "fail",
                f"PORTFOLIO_READ_REPOSITORY={portfolio_repository}; expected one of {sorted(allowed)}",
                ["PORTFOLIO_READ_REPOSITORY"],
            )
        return CheckResult(
            "database",
            "portfolio_read_repository",
            "pass",
            f"PORTFOLIO_READ_REPOSITORY={portfolio_repository}",
        )
    if broker_repository in {"postgres", "supabase"}:
        return CheckResult(
            "database",
            "portfolio_read_repository",
            "pass",
            f"PORTFOLIO_READ_REPOSITORY omitted; follows BROKER_SYNC_REPOSITORY={broker_repository}",
        )
    return CheckResult(
        "database",
        "portfolio_read_repository",
        "warn" if profile == "local" else "fail",
        "BROKER_SYNC_REPOSITORY or PORTFOLIO_READ_REPOSITORY must select postgres/supabase",
        ["PORTFOLIO_READ_REPOSITORY"],
    )


def _fx_source_check(*, profile: str) -> CheckResult:
    has_inline_rates = not _is_placeholder(_env("FX_RATES_JSON"))
    has_endpoint = not _is_placeholder(_env("FX_RATE_ENDPOINT"))
    if has_inline_rates or has_endpoint:
        return CheckResult("fx", "fx_rates", "pass", "trusted FX source is configured")
    if profile == "lightweight":
        return CheckResult(
            "fx",
            "fx_rates",
            "warn",
            "lightweight profile may use labelled fallback FX for UI testing; production needs FX_RATES_JSON or FX_RATE_ENDPOINT",
            ["FX_RATES_JSON or FX_RATE_ENDPOINT"],
        )
    return CheckResult(
        "fx",
        "fx_rates",
        "warn" if profile == "local" else "fail",
        "set FX_RATES_JSON or FX_RATE_ENDPOINT before production release",
        ["FX_RATES_JSON or FX_RATE_ENDPOINT"],
    )


def _observability_check(*, profile: str) -> CheckResult:
    has_sentry = not _is_placeholder(_env("SENTRY_DSN"))
    sls_missing = _missing(["ALIYUN_SLS_PROJECT", "ALIYUN_SLS_LOGSTORE"])
    has_aliyun_sls = not sls_missing
    backend = _env("OBSERVABILITY_BACKEND").lower()
    log_retention = _env("LOG_RETENTION_DAYS")
    lightweight_log_backend = backend in {"docker_logs", "bt_panel_logs", "local_file"} and not _is_placeholder(log_retention)

    if has_sentry:
        return CheckResult("monitoring", "observability", "pass", "Sentry DSN configured for runtime error monitoring")
    if has_aliyun_sls:
        return CheckResult("monitoring", "observability", "pass", "Alibaba Cloud SLS project/logstore configured")
    if profile == "lightweight" and lightweight_log_backend:
        return CheckResult(
            "monitoring",
            "observability",
            "pass",
            f"lightweight observability uses {backend} with LOG_RETENTION_DAYS={log_retention}",
        )

    missing = ["SENTRY_DSN or ALIYUN_SLS_PROJECT+ALIYUN_SLS_LOGSTORE"]
    if profile == "lightweight":
        missing.append("or OBSERVABILITY_BACKEND+LOG_RETENTION_DAYS")
    return CheckResult(
        "monitoring",
        "observability",
        "warn" if profile in {"local", "lightweight"} else "fail",
        "configure Sentry, Alibaba Cloud SLS, or an explicit lightweight log retention backend",
        missing,
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
    parser.add_argument("--profile", choices=["local", "lightweight", "production"], default="production")
    parser.add_argument("--env-file", default=str(ENV_FILE), help="Environment file to load before running checks.")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    summary = summarize(run_checks(profile=args.profile), profile=args.profile)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
