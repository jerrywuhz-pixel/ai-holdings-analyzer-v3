"""Runtime status helpers for the OpenClaw/Hermes foundation layer."""
from __future__ import annotations

import os
import socket
from typing import Any


DEFAULT_OPENCLAW_UPSTREAM_TARGET = "v2026.5.18"
DEFAULT_HERMES_UPSTREAM_TARGET = "v2026.5.16"
DEFAULT_GBRAIN_ADAPTER_VERSION = "0.2.0"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _deployment_mode() -> str:
    return (
        os.getenv("OPENCLAW_DEPLOYMENT_MODE")
        or os.getenv("DEPLOYMENT_MODE")
        or "local"
    )


def _openai_codex_auth_profile() -> str:
    return (
        os.getenv("OPENAI_CODEX_AUTH_PROFILE")
        or os.getenv("HERMES_AUTH_PROFILE_ID")
        or os.getenv("OPENCLAW_AUTH_PROFILE")
        or ""
    )


def _openai_codex_bridge_base_url() -> str:
    return (
        os.getenv("OPENAI_CODEX_BRIDGE_BASE_URL")
        or os.getenv("HERMES_CODEX_GATEWAY_BASE_URL")
        or os.getenv("OPENCLAW_CODEX_GATEWAY_BASE_URL")
        or ""
    )


def _deep_provider() -> str:
    configured = os.getenv("HERMES_DEEP_PROVIDER") or os.getenv("MODEL_ADAPTER_FALLBACK_PROVIDER")
    if configured in {"openai", "openai-codex", "minimax"}:
        return configured
    if os.getenv("MODEL_AUTH_MODE") in {"openai_codex", "hermes_auth_profile"}:
        return "openai-codex"
    return "openai"


def _minimax_api_format() -> str:
    configured = os.getenv("MINIMAX_API_FORMAT")
    if configured in {"openai", "anthropic"}:
        return configured
    base_url = os.getenv("MINIMAX_OPENAI_BASE_URL") or os.getenv("MINIMAX_BASE_URL") or ""
    return "anthropic" if "/anthropic" in base_url else "openai"


def local_gateway_snapshot(reporter: Any | None) -> dict[str, Any]:
    """Return process-local gateway health without relying on external heartbeat storage."""
    active_skills = list(getattr(reporter, "_active_skills", []) or [])
    claw_plugin_status = getattr(reporter, "_claw_plugin_status", "unknown") if reporter else "unknown"

    return {
        "status": "healthy",
        "last_reported_at": None,
        "deployment_mode": _deployment_mode(),
        "instance_id": os.getenv("OPENCLAW_INSTANCE_ID", socket.gethostname()),
        "active_skills": active_skills,
        "claw_plugin_status": claw_plugin_status,
        "source": "local_process",
    }


def prefer_external_or_local_gateway(
    external_status: dict[str, Any] | None,
    local_status: dict[str, Any],
) -> dict[str, Any]:
    """Use persisted heartbeat when available; otherwise keep health useful locally."""
    if not external_status:
        return local_status

    status = str(external_status.get("status") or "unknown")
    has_heartbeat = bool(external_status.get("last_reported_at"))
    if status == "unknown" and not has_heartbeat:
        return local_status

    merged = dict(local_status)
    merged.update({key: value for key, value in external_status.items() if value is not None})
    merged["source"] = "heartbeat_store" if has_heartbeat else local_status.get("source", "local_process")
    if not merged.get("active_skills"):
        merged["active_skills"] = local_status.get("active_skills", [])
    return merged


def build_runtime_status() -> dict[str, Any]:
    """Non-secret foundation status used by health checks and deployment verification."""
    openai_configured = bool(os.getenv("OPENAI_API_KEY") or os.getenv("GBRAIN_OPENAI_API_KEY"))
    openai_codex_auth_profile_configured = bool(_openai_codex_auth_profile())
    openai_codex_bridge_configured = bool(_openai_codex_bridge_base_url())
    openai_codex_configured = (
        openai_codex_auth_profile_configured and openai_codex_bridge_configured
    )
    minimax_configured = bool(os.getenv("MINIMAX_API_KEY"))
    live_models_enabled = _env_bool("GBRAIN_LIVE_MODELS_ENABLED", False)
    deep_provider = _deep_provider()
    provider_ready = {
        "openai": openai_configured,
        "openai-codex": openai_codex_configured,
        "minimax": minimax_configured,
    }.get(deep_provider, False)
    system_model_auth_ready = live_models_enabled and provider_ready

    return {
        "foundation": {
            "app_version": os.getenv("APP_VERSION", "3.0.0-p0"),
            "openclaw_adapter": "ai-holdings-openclaw-gateway",
            "openclaw_upstream_target": os.getenv(
                "OPENCLAW_UPSTREAM_TARGET_VERSION",
                DEFAULT_OPENCLAW_UPSTREAM_TARGET,
            ),
            "hermes_runtime": "gbrain-hermes-worker",
            "hermes_upstream_target": os.getenv(
                "HERMES_UPSTREAM_TARGET_VERSION",
                DEFAULT_HERMES_UPSTREAM_TARGET,
            ),
            "gbrain_adapter_version": os.getenv(
                "GBRAIN_ADAPTER_VERSION",
                DEFAULT_GBRAIN_ADAPTER_VERSION,
            ),
        },
        "modes": {
            "deployment_mode": _deployment_mode(),
            "delivery_mode": os.getenv("OPENCLAW_DELIVERY_MODE", "log"),
            "hermes_worker_mode": os.getenv("HERMES_WORKER_MODE", "stub"),
            "live_models_enabled": live_models_enabled,
            "model_auth_mode": os.getenv("MODEL_AUTH_MODE", "api_key"),
            "artifact_storage_backend": os.getenv("HERMES_ARTIFACT_STORAGE_BACKEND", "file"),
            "object_storage_provider": os.getenv("OBJECT_STORAGE_PROVIDER", "minio"),
            "futu_connector_mode": os.getenv("FUTU_CONNECTOR_MODE", "local_mock"),
        },
        "authorization": {
            "openclaw_skill_key_configured": bool(os.getenv("OPENCLAW_SKILL_KEY")),
            "openai_configured": openai_configured,
            "openai_codex_auth_profile_configured": openai_codex_auth_profile_configured,
            "openai_codex_bridge_configured": openai_codex_bridge_configured,
            "openai_codex_configured": openai_codex_configured,
            "minimax_configured": minimax_configured,
            "minimax_api_format": _minimax_api_format(),
            "system_model_auth_ready": system_model_auth_ready,
            "live_model_authorization": "ready"
            if system_model_auth_ready
            else "disabled" if not live_models_enabled else f"missing_{deep_provider}_auth",
        },
        "token_plan": {
            "default_plan": os.getenv("OPENCLAW_DEFAULT_PLAN", "basic"),
            "context_pack_max_tokens": int(os.getenv("HERMES_CONTEXT_PACK_MAX_TOKENS", "24000")),
            "light_task_timeout_seconds": int(os.getenv("HERMES_LIGHT_TASK_TIMEOUT_SECONDS", "300")),
            "deep_task_timeout_seconds": int(os.getenv("HERMES_DEEP_TASK_TIMEOUT_SECONDS", "1800")),
        },
        "models": {
            "light_provider": "minimax",
            "light_model": os.getenv("MINIMAX_MODEL") or os.getenv("HERMES_LIGHT_MODEL", "MiniMax-M2.7"),
            "deep_provider": deep_provider,
            "deep_model": os.getenv(
                "HERMES_DEEP_MODEL",
                "gpt-5.4" if deep_provider == "openai-codex" else "gpt-5.5",
            ),
        },
        "safety": {
            "confirmation_high_risk_ttl_minutes": int(
                os.getenv("CONFIRMATION_HIGH_RISK_TTL_MINUTES", "30")
            ),
            "confirmation_low_risk_ttl_minutes": int(
                os.getenv("CONFIRMATION_LOW_RISK_TTL_MINUTES", "1440")
            ),
            "delivery_rate_limit_per_hour": int(
                os.getenv("DELIVERY_RATE_LIMIT_PER_HOUR", "6")
            ),
        },
    }
