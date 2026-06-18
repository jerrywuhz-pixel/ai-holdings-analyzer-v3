"""Skill and data-source discovery for OpenClaw runtime health."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _truthy_env(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _first_existing_path(env_name: str, fallback: Path, marker: str) -> Path:
    configured = os.getenv(env_name, "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(fallback)
    for candidate in candidates:
        if (candidate / marker).exists():
            return candidate
    return candidates[0] if candidates else fallback


def _openclaw_root() -> Path:
    return Path(__file__).resolve().parents[1]


def skills_root() -> Path:
    configured = os.getenv("OPENCLAW_SKILLS_DIR", "").strip()
    if configured:
        return Path(configured)
    return _openclaw_root() / "skills"


def discover_openclaw_skills(root: Path | None = None) -> list[str]:
    """Return installed top-level OpenClaw skills with a SKILL.md contract."""
    base = root or skills_root()
    if not base.exists():
        return []
    return sorted(
        item.name
        for item in base.iterdir()
        if item.is_dir() and (item / "SKILL.md").exists()
    )


def build_data_source_status(root: Path | None = None) -> list[dict[str, Any]]:
    """Expose configured source/tool dependencies without leaking secrets."""
    base = root or skills_root()
    ftshare_dir = _first_existing_path(
        "FTSHARE_MARKET_DATA_SKILL_DIR",
        base / "ftshare-market-data",
        "run.py",
    )
    ima_dir = _first_existing_path("IMA_SKILL_DIR", base / "ima-skill", "SKILL.md")

    return [
        {
            "id": "data-service",
            "kind": "internal_api",
            "status": "configured" if _truthy_env("DATA_SERVICE_URL") else "missing",
            "capabilities": ["quotes", "portfolio", "sell_put", "historical"],
        },
        {
            "id": "ftshare-market-data",
            "kind": "openclaw_skill",
            "status": "configured" if (ftshare_dir / "run.py").exists() else "missing",
            "skill_dir": str(ftshare_dir),
            "capabilities": ["cn_quotes", "cn_fundamentals", "hk_reference", "macro"],
        },
        {
            "id": "ima-reference",
            "kind": "openclaw_skill",
            "status": (
                "configured"
                if _env_bool("IMA_REFERENCE_SOURCE_ENABLED")
                and _truthy_env("IMA_OPENAPI_CLIENTID")
                and _truthy_env("IMA_OPENAPI_APIKEY")
                else "disabled"
            ),
            "skill_dir": str(ima_dir),
            "reference_only": True,
            "capabilities": ["wechat_article_reference", "knowledge_search", "notes_search"],
        },
        {
            "id": "futu",
            "kind": "broker_local_connector",
            "status": "configured" if os.getenv("FUTU_CONNECTOR_MODE", "local_mock") != "local_mock" else "mock",
            "capabilities": ["hk_us_quotes", "option_chain", "positions_readonly"],
        },
        {
            "id": "tushare",
            "kind": "market_data_api",
            "status": "configured" if _truthy_env("TUSHARE_TOKEN") else "missing",
            "capabilities": ["cn_quotes", "cn_history", "cn_fundamentals"],
        },
        {
            "id": "longbridge",
            "kind": "market_data_api",
            "status": "configured" if _truthy_env("LONGBRIDGE_APP_KEY") else "missing",
            "capabilities": ["hk_us_quotes"],
        },
        {
            "id": "gbrain-mcp",
            "kind": "mcp",
            "status": "configured" if _truthy_env("DATABASE_URL") else "missing",
            "capabilities": ["memory", "hybrid_search", "artifacts_context"],
        },
    ]
