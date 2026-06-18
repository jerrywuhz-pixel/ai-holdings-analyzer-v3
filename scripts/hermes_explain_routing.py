#!/usr/bin/env python3
"""
Explain Hermes model and market-data routing without calling external services.

This mirrors the key operational rules from gbrain/src/model-adapter.ts and
data-service/src/services/registry.py so operators can see why a request will
prefer GPT-5.5, MiniMax, Longbridge, Tushare, FTShare, Yahoo, or AkShare.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT_MS = 5 * 60 * 1000
INVESTMENT_JOB_TYPES = {"equity_analysis", "options_sell_put", "portfolio_review"}
FINANCIAL_KEYWORDS = (
    "股票",
    "持仓",
    "投资",
    "交易",
    "期权",
    "sell put",
    "分析",
    "行情",
    "风险",
    "纪律",
    "仓位",
    "portfolio",
    "holding",
    "equity",
    "stock",
    "option",
    "trade",
)


@dataclass
class Route:
    provider: str
    model: str
    mode: str
    reason: str


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


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def env(name: str) -> str:
    return os.getenv(name, "").strip()


def infer_market(symbol: str) -> str:
    s = symbol.strip().upper()
    if s.startswith(("SH", "SZ")):
        return "CN"
    if s.startswith("HK"):
        return "HK"
    return "US"


def akshare_enabled() -> bool:
    return truthy(env("AKSHARE_ENABLED"))


def longbridge_configured() -> bool:
    return bool(env("LONGBRIDGE_MCP_ACCESS_TOKEN")) or bool(
        env("LONGBRIDGE_APP_KEY") and env("LONGBRIDGE_APP_SECRET") and env("LONGBRIDGE_ACCESS_TOKEN")
    )


def futu_default_enabled() -> bool:
    return truthy(env("FUTU_QUOTE_DEFAULT_ENABLED"))


def quote_priority(symbol: str, prefer: str = "") -> tuple[str, list[str], list[str]]:
    if prefer:
        return infer_market(symbol), [prefer], [f"explicit source={prefer} overrides automatic priority"]

    market = infer_market(symbol)
    reasons: list[str] = [f"market inferred as {market} from symbol={symbol or '<empty>'}"]
    if market == "CN":
        priority = ["tushare", "ftshare", "yahoo", "akshare"]
        reasons.append("CN default priority is Tushare -> FTShare -> Yahoo; AkShare is optional")
    elif market == "HK":
        priority = ["longbridge", "yahoo", "tushare", "akshare"]
        reasons.append("HK default priority is Longbridge -> Yahoo -> Tushare; AkShare is optional")
    else:
        priority = ["yahoo", "longbridge", "tushare", "akshare"]
        if longbridge_configured():
            priority = ["longbridge", "yahoo", "tushare", "akshare"]
            reasons.append("Longbridge credentials/token detected, so US quotes prefer Longbridge before Yahoo")
        else:
            reasons.append("US default priority is Yahoo -> Longbridge -> Tushare when Longbridge is not configured")

    if not akshare_enabled():
        priority = [source for source in priority if source != "akshare"]
        reasons.append("AKSHARE_ENABLED is not true, so AkShare is excluded from fallback priority")
    else:
        reasons.append("AKSHARE_ENABLED=true, so AkShare remains as the last optional fallback")

    if market in {"HK", "US"} and futu_default_enabled():
        priority = ["futu", *[source for source in priority if source != "futu"]]
        reasons.append("FUTU_QUOTE_DEFAULT_ENABLED=true, so Futu is prepended for HK/US quotes")

    return market, priority, reasons


def live_models_enabled() -> bool:
    return truthy(env("GBRAIN_LIVE_MODELS_ENABLED"))


def resolve_light_model() -> str:
    return env("ANTHROPIC_MODEL") or env("MINIMAX_MODEL") or env("HERMES_LIGHT_MODEL") or "MiniMax-M2.7"


def resolve_deep_model() -> str:
    return env("HERMES_DEEP_MODEL") or "gpt-5.5"


def openai_codex_configured() -> bool:
    auth_profile = env("OPENAI_CODEX_AUTH_PROFILE") or env("HERMES_AUTH_PROFILE_ID") or env("OPENCLAW_AUTH_PROFILE")
    bridge = env("OPENAI_CODEX_BRIDGE_BASE_URL") or env("HERMES_CODEX_GATEWAY_BASE_URL") or env("OPENCLAW_CODEX_GATEWAY_BASE_URL")
    return bool(auth_profile and bridge)


def openai_api_configured() -> bool:
    return bool(env("OPENAI_API_KEY") or env("GBRAIN_OPENAI_API_KEY"))


def minimax_configured() -> bool:
    return bool(env("MINIMAX_API_KEY") or env("ANTHROPIC_AUTH_TOKEN") or env("ANTHROPIC_API_KEY")) or (
        (env("MINIMAX_API_FORMAT").lower() in {"hermes-cli", "openclaw-cli"}) and truthy(env("HERMES_MINIMAX_CLI_ENABLED") or env("OPENCLAW_MINIMAX_CLI_ENABLED"))
    )


def route_mode(provider: str) -> str:
    configured = {
        "openai": openai_api_configured(),
        "openai-codex": openai_codex_configured(),
        "minimax": minimax_configured(),
        "fallback-template": True,
    }.get(provider, False)
    return "live" if configured and live_models_enabled() else "stub"


def deep_provider() -> str:
    configured = env("HERMES_DEEP_PROVIDER") or env("MODEL_ADAPTER_FALLBACK_PROVIDER")
    if configured in {"openai", "openai-codex", "minimax"}:
        return configured
    if env("MODEL_AUTH_MODE") in {"openai_codex", "hermes_auth_profile"}:
        return "openai-codex"
    return "openai"


def looks_financial(query: str) -> bool:
    lowered = query.lower()
    if re.search(r"\b[A-Z]{1,5}(\.(US|HK|CN))?\b", query):
        return True
    return any(keyword in lowered for keyword in FINANCIAL_KEYWORDS)


def should_use_deep_route(*, complexity: str, job_type: str, query: str, timeout_ms: int) -> tuple[bool, str]:
    if complexity in {"deep", "background"}:
        return True, f"complexity={complexity} requires deep route"
    if timeout_ms > 5 * 60 * 1000:
        return True, f"timeout_ms={timeout_ms} exceeds light-route threshold"
    if job_type in INVESTMENT_JOB_TYPES:
        return True, f"job_type={job_type} is investment/finance and must prefer GPT before MiniMax fallback"
    if looks_financial(query):
        return True, "query looks finance/investment-related, so GPT primary route is safer"
    return False, "non-financial light/standard task can use MiniMax primary route"


def model_routes(*, query: str, complexity: str, job_type: str, timeout_ms: int) -> tuple[list[Route], str]:
    use_deep, reason = should_use_deep_route(complexity=complexity, job_type=job_type, query=query, timeout_ms=timeout_ms)
    if use_deep:
        primary_provider = deep_provider()
        routes = [
            Route(primary_provider, resolve_deep_model(), route_mode(primary_provider), reason),
            Route("minimax", resolve_light_model(), route_mode("minimax"), "MiniMax is fallback after GPT/OpenAI route is unavailable or exhausted"),
            Route("fallback-template", "hermes-fallback-v1", "stub", "deterministic last-resort template; never writes business facts"),
        ]
        return routes, reason
    routes = [
        Route("minimax", resolve_light_model(), route_mode("minimax"), reason),
        Route("fallback-template", "hermes-fallback-v1", "stub", "deterministic last-resort template"),
    ]
    return routes, reason


def explain_routing(
    *,
    query: str = "",
    symbol: str = "",
    source: str = "",
    complexity: str = "standard",
    job_type: str = "",
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> dict[str, Any]:
    routes, reason = model_routes(query=query, complexity=complexity, job_type=job_type, timeout_ms=timeout_ms)
    market, quote_sources, quote_reasons = quote_priority(symbol, prefer=source) if symbol else ("unknown", [], ["no symbol supplied"])
    return {
        "schema_version": "hermes_routing_explanation_v1",
        "input": {
            "query": query,
            "symbol": symbol,
            "source": source,
            "complexity": complexity,
            "job_type": job_type,
            "timeout_ms": timeout_ms,
        },
        "model_routing": {
            "decision": reason,
            "live_models_enabled": live_models_enabled(),
            "credentials": {
                "openai_api": "set" if openai_api_configured() else "missing",
                "openai_codex_bridge": "set" if openai_codex_configured() else "missing",
                "minimax": "set" if minimax_configured() else "missing",
            },
            "routes": [asdict(route) for route in routes],
        },
        "quote_routing": {
            "market": market,
            "priority": quote_sources,
            "reasons": quote_reasons,
        },
        "search_routing": {
            "official_gbrain_search_mode": env("GBRAIN_SEARCH_MODE") or env("SEARCH_MODE") or "unknown",
            "note": "Official gbrain search mode is separate from Hermes business gbrain adapter.",
        },
    }


def render_text(summary: dict[str, Any]) -> str:
    model_routes_text = "\n".join(
        f"  {idx + 1}. {route['provider']}/{route['model']} mode={route['mode']} - {route['reason']}"
        for idx, route in enumerate(summary["model_routing"]["routes"])
    )
    quote_priority_text = " -> ".join(summary["quote_routing"]["priority"]) or "(no symbol)"
    quote_reasons_text = "\n".join(f"  - {reason}" for reason in summary["quote_routing"]["reasons"])
    return "\n".join(
        [
            "Hermes routing explanation",
            f"Model decision: {summary['model_routing']['decision']}",
            "Model routes:",
            model_routes_text,
            f"Quote market: {summary['quote_routing']['market']}",
            f"Quote priority: {quote_priority_text}",
            "Quote reasons:",
            quote_reasons_text,
            f"Search mode: {summary['search_routing']['official_gbrain_search_mode']}",
        ]
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Explain Hermes model/data/search routing without making live calls.")
    parser.add_argument("--query", default="")
    parser.add_argument("--symbol", default="")
    parser.add_argument("--source", default="", help="Explicit quote source override.")
    parser.add_argument("--complexity", default="standard", choices=["quick", "standard", "deep", "background"])
    parser.add_argument("--job-type", default="")
    parser.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--format", choices=["json", "text"], default="json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.env_file:
        load_env_file(args.env_file)
    else:
        load_env_file(PROJECT_ROOT / ".env.server")
        load_env_file(PROJECT_ROOT / ".env")
    summary = explain_routing(
        query=args.query,
        symbol=args.symbol,
        source=args.source,
        complexity=args.complexity,
        job_type=args.job_type,
        timeout_ms=args.timeout_ms,
    )
    if args.format == "text":
        print(render_text(summary))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
