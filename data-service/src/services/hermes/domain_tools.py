from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shutil
import time
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from services.hermes.reference_capture import WebReferencePersistence, summarize_web_reference
from services.hermes.opportunity_research import OpportunityResearchWorkflow
from services.hermes.stock_analysis import HermesStockAnalysisService, load_market_regime, load_sector_context


HttpClientFactory = Callable[[], httpx.AsyncClient]
_SOCIAL_PROVIDER_LAST_CALLS: dict[str, float] = {}


class DomainToolError(RuntimeError):
    pass


def domain_tool_manifest() -> list[dict[str, Any]]:
    return [
        {
            "name": "market.quote",
            "description": "Read one fresh or reference quote through Hermes data-service.",
            "input_schema": {
                "symbol": "string",
                "source": "optional string: futu/yahoo/tushare/ftshare/akshare/longbridge",
                "require_fresh": "optional boolean",
                "max_age_seconds": "optional integer",
            },
            "safety": "read_only",
        },
        {
            "name": "market.batch_quote",
            "description": "Read multiple quotes through Hermes data-service.",
            "input_schema": {
                "symbols": "string[]",
                "source": "optional string",
                "require_fresh": "optional boolean",
                "max_age_seconds": "optional integer",
            },
            "safety": "read_only",
        },
        {
            "name": "sector.context",
            "description": "Read market/sector context snapshots for a stock analysis context pack.",
            "input_schema": {
                "tenant_id": "optional string",
                "symbol": "optional string",
                "market": "string: US/CN/HK",
                "sector": "string",
                "industry": "optional string",
                "limit": "optional integer",
            },
            "safety": "read_only",
        },
        {
            "name": "market.regime",
            "description": "Read current market regime inferred from sector snapshots.",
            "input_schema": {
                "tenant_id": "optional string",
                "market": "string: US/CN/HK",
                "limit": "optional integer",
            },
            "safety": "read_only",
        },
        {
            "name": "options.sell_put_rank",
            "description": "Rank Sell Put candidates using verified broker/option-chain inputs when available.",
            "input_schema": {
                "tenant_id": "string",
                "underlying_symbol": "string",
                "broker_connection_id": "optional string; uses Futu analyze-from-futu when present",
                "quote": "required for direct analyze mode",
                "option_candidates": "required for direct analyze mode",
            },
            "safety": "read_only_trade_draft_only",
        },
        {
            "name": "broker.positions_read",
            "description": "Read tenant-scoped persisted positions or live broker snapshot in read-only mode.",
            "input_schema": {
                "tenant_id": "string",
                "source": "optional string: portfolio_read_model/futu",
                "broker_connection_id": "required when source=futu",
            },
            "safety": "read_only",
        },
        {
            "name": "portfolio.overview",
            "description": "Read tenant-scoped portfolio overview totals, cash, margin, freshness, and source quality.",
            "input_schema": {
                "tenant_id": "string",
                "base_currency": "optional string",
            },
            "safety": "read_only",
        },
        {
            "name": "stock.analysis",
            "description": "Analyze one stock through Hermes using quote, tenant portfolio context, discipline-safe report structure, and optional persistence.",
            "input_schema": {
                "tenant_id": "string",
                "symbol": "string",
                "prompt": "optional string",
                "persist": "optional boolean; default true",
                "entry_surface": "optional string: wechat/webapp/system",
                "news_context": "optional object: normalized or raw news/events/catalysts context",
                "news_items": "optional array: latest headlines or news objects",
                "events": "optional array: upcoming company events",
                "catalysts": "optional array: catalyst objects",
                "social_context": "optional object: finite-account social sentiment snapshot",
                "social_items": "optional array: posts from configured social accounts only",
                "social_accounts": "optional array: explicit watched social accounts",
            },
            "safety": "read_only_analysis_artifact",
        },
        {
            "name": "opportunity.research.run",
            "description": "Run the Hermes opportunity research workflow: multi-state sensing, candidate research, four gates, paper ledger case creation, and delivery draft.",
            "input_schema": {
                "tenant_id": "string",
                "market": "string: US/CN/HK/CN_HK",
                "session_type": "optional string: premarket/manual/review",
                "report_date": "optional date string",
                "universe_policy": "optional string, default holdings_watchlist_hard_tech",
                "model_policy": "optional object with light_scan/deep_research/high_risk_review",
                "symbols": "optional string[] explicit seed/watchlist symbols",
                "sell_put_underlyings": "optional string[]",
                "delivery_context": "optional object: channel_binding_id/openclaw_account_id/target_conversation/context_token",
                "persist": "optional boolean; default true",
                "max_candidates": "optional integer",
            },
            "safety": "read_only_analysis_artifact_paper_ledger",
        },
        {
            "name": "opportunity.review.run",
            "description": "Review open or supplied opportunity cases against later facts and write paper-ledger marks.",
            "input_schema": {
                "tenant_id": "string",
                "market": "optional string",
                "review_date": "optional date string",
                "cases": "optional array of opportunity cases; defaults to persisted open cases",
                "persist": "optional boolean; default true",
            },
            "safety": "read_only_review_paper_ledger",
        },
        {
            "name": "opportunity.ledger.mark",
            "description": "Compute and optionally persist a deterministic paper-ledger mark for one opportunity case.",
            "input_schema": {
                "tenant_id": "string",
                "case_id": "string uuid",
                "mark": "object with entry_price/mark_price/benchmark prices/stretch_daily_returns/thesis_status/discipline_status",
                "persist": "optional boolean; default true",
            },
            "safety": "read_only_accounting_no_orders",
        },
        {
            "name": "reference.ima.search",
            "description": "Search IMA knowledge or notes as a research reference source.",
            "input_schema": {
                "query": "string",
                "scope": "optional string: knowledge/notes",
                "knowledge_base_id": "optional string",
                "limit": "optional integer",
            },
            "safety": "reference_only",
        },
        {
            "name": "reference.ima.read",
            "description": "Read IMA note content or media metadata as a cited research reference.",
            "input_schema": {
                "note_id": "optional string",
                "media_id": "optional string",
                "target_content_format": "optional integer",
            },
            "safety": "reference_only",
        },
        {
            "name": "reference.web.read",
            "description": "Read a public webpage URL as a sanitized reference-only research source.",
            "input_schema": {
                "tenant_id": "optional string",
                "url": "string",
                "mode": "optional string: auto/get/dynamic/stealthy",
                "allow_stealthy": "optional boolean; only honored when env + host allowlist permit it",
                "proxy_url": "optional string; only honored when proxy env + host allowlist permit it",
                "css_selector": "optional string",
                "timeout_ms": "optional integer",
                "max_chars": "optional integer",
                "prompt": "optional string: original user prompt for audit",
                "entry_surface": "optional string: wechat/webapp/system",
            },
            "safety": "reference_only",
        },
        {
            "name": "reference.web.search",
            "description": "Search configured public web/reference search backend and optionally read the top public URL.",
            "input_schema": {
                "tenant_id": "optional string",
                "query": "string",
                "limit": "optional integer",
                "read_top": "optional boolean",
                "providers": "optional string|string[]: ima/gbrain/api/searxng/bing_html provider chain",
                "mode": "optional string: auto/get/dynamic/stealthy for read_top",
                "prompt": "optional string: original user prompt for audit",
                "entry_surface": "optional string: wechat/webapp/system",
            },
            "safety": "reference_only",
        },
        {
            "name": "reference.social.watchlist",
            "description": "Return finite social accounts configured for a symbol/platform; never performs whole-web or keyword search.",
            "input_schema": {
                "tenant_id": "optional string",
                "symbol": "optional string",
                "platforms": "optional string|string[]: xueqiu/reddit/xhs/twitter/youtube",
                "accounts": "optional array: explicit account allowlist for this invocation",
            },
            "safety": "reference_only_finite_accounts",
        },
        {
            "name": "reference.social.health",
            "description": "Check configured social providers without broad search: X/twitter-cli, xiaohongshu-mcp over HTTP MCP or mcporter, and yt-dlp for YouTube.",
            "input_schema": {
                "providers": "optional string|string[]: twitter/xhs/youtube",
                "platforms": "optional alias for providers",
                "timeout_ms": "optional integer",
            },
            "safety": "reference_only_provider_health",
        },
        {
            "name": "reference.social.timeline",
            "description": "Read or normalize posts only from an explicit or configured social account allowlist.",
            "input_schema": {
                "tenant_id": "optional string",
                "symbol": "optional string",
                "platforms": "optional string|string[]: twitter/xhs/youtube/xueqiu/reddit",
                "accounts": "optional array: required unless env watchlist is configured",
                "items": "optional array: provider/test supplied posts from watched accounts",
                "window": "optional string, default 72h",
                "limit": "optional integer",
                "timeout_ms": "optional integer",
            },
            "safety": "reference_only_finite_accounts_no_global_search",
        },
        {
            "name": "sentiment.social.snapshot",
            "description": "Aggregate finite-account social posts into a social_context snapshot for stock or portfolio analysis.",
            "input_schema": {
                "tenant_id": "optional string",
                "symbol": "optional string",
                "platforms": "optional string|string[]",
                "accounts": "optional array: explicit watched social accounts",
                "items": "optional array: posts from watched accounts",
                "window": "optional string, default 72h",
                "limit": "optional integer",
            },
            "safety": "read_only_social_signal",
        },
    ]


class DomainToolsFacade:
    """Hermes-facing read-only domain tool facade.

    This lives inside data-service for the Hermes-only lightweight runtime. It
    keeps model workers away from provider credentials and raw connector details.
    """

    def __init__(
        self,
        *,
        data_service_url: str | None = None,
        reference_capture_url: str | None = None,
        ima_skill_dir: str | Path | None = None,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        self.data_service_url = (
            data_service_url
            or os.getenv("HERMES_DATA_SERVICE_INTERNAL_URL")
            or os.getenv("HERMES_DOMAIN_TOOLS_URL")
            or os.getenv("DATA_SERVICE_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        self.reference_capture_url = (
            reference_capture_url or os.getenv("HERMES_REFERENCE_CAPTURE_URL", "http://reference-capture:8010")
        ).rstrip("/")
        self.ima_skill_dir = Path(ima_skill_dir or os.getenv("IMA_SKILL_DIR", "/app/skills/ima-skill"))
        self.http_client_factory = http_client_factory or httpx.AsyncClient

    async def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "market.quote":
            return await self.market_quote(arguments)
        if tool_name == "market.batch_quote":
            return await self.market_batch_quote(arguments)
        if tool_name == "sector.context":
            return await self.sector_context(arguments)
        if tool_name == "market.regime":
            return await self.market_regime(arguments)
        if tool_name == "options.sell_put_rank":
            return await self.options_sell_put_rank(arguments)
        if tool_name == "broker.positions_read":
            return await self.broker_positions_read(arguments)
        if tool_name == "portfolio.overview":
            return await self.portfolio_overview(arguments)
        if tool_name == "stock.analysis":
            return await self.stock_analysis(arguments)
        if tool_name == "opportunity.research.run":
            return await self.opportunity_research_run(arguments)
        if tool_name == "opportunity.review.run":
            return await self.opportunity_review_run(arguments)
        if tool_name == "opportunity.ledger.mark":
            return await self.opportunity_ledger_mark(arguments)
        if tool_name == "reference.ima.search":
            return await self.ima_search(arguments)
        if tool_name == "reference.ima.read":
            return await self.ima_read(arguments)
        if tool_name == "reference.web.read":
            return await self.reference_web_read(arguments)
        if tool_name == "reference.web.search":
            return await self.reference_web_search(arguments)
        if tool_name == "reference.social.watchlist":
            return await self.reference_social_watchlist(arguments)
        if tool_name == "reference.social.health":
            return await self.reference_social_health(arguments)
        if tool_name == "reference.social.timeline":
            return await self.reference_social_timeline(arguments)
        if tool_name == "sentiment.social.snapshot":
            return await self.social_sentiment_snapshot(arguments)
        raise DomainToolError(f"unknown domain tool: {tool_name}")

    async def market_quote(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = _required_str(arguments, "symbol")
        params = _compact_params(
            {
                "source": arguments.get("source"),
                "require_fresh": _optional_bool_str(arguments.get("require_fresh")),
                "max_age_seconds": arguments.get("max_age_seconds"),
            }
        )
        payload = await self._get_json(f"/api/quote/{symbol}", params=params)
        return _tool_result("market.quote", payload, source_refs=[_source_ref("hermes-data-service", f"/api/quote/{symbol}")])

    async def market_batch_quote(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbols = arguments.get("symbols")
        if not isinstance(symbols, list) or not all(isinstance(item, str) and item.strip() for item in symbols):
            raise DomainToolError("symbols must be a non-empty string list")
        params = _compact_params(
            {
                "source": arguments.get("source"),
                "require_fresh": _optional_bool_str(arguments.get("require_fresh")),
                "max_age_seconds": arguments.get("max_age_seconds"),
            }
        )
        payload = await self._post_json("/api/quote/batch", {"symbols": symbols}, params=params)
        return _tool_result("market.batch_quote", payload, source_refs=[_source_ref("hermes-data-service", "/api/quote/batch")])

    async def sector_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        market = _required_str(arguments, "market").upper()
        sector = _required_str(arguments, "sector")
        industry = arguments.get("industry")
        limit = int(arguments.get("limit") or 5)
        payload = await load_sector_context(
            tenant_id=str(arguments.get("tenant_id") or ""),
            market=market,
            sector=sector,
            industry=str(industry).strip() if isinstance(industry, str) and industry.strip() else None,
            limit=limit,
        )
        refs = payload.get("source_refs") if isinstance(payload.get("source_refs"), list) else []
        if arguments.get("symbol"):
            refs = [*refs, _source_ref("symbol", str(arguments["symbol"]))]
        return _tool_result("sector.context", payload, source_refs=refs)

    async def market_regime(self, arguments: dict[str, Any]) -> dict[str, Any]:
        market = _required_str(arguments, "market").upper()
        limit = int(arguments.get("limit") or 30)
        payload = await load_market_regime(
            tenant_id=str(arguments.get("tenant_id") or ""),
            market=market,
            limit=limit,
        )
        refs = payload.get("source_refs") if isinstance(payload.get("source_refs"), list) else []
        return _tool_result("market.regime", payload, source_refs=refs)

    async def options_sell_put_rank(self, arguments: dict[str, Any]) -> dict[str, Any]:
        broker_connection_id = arguments.get("broker_connection_id")
        if broker_connection_id:
            body = {
                "tenant_id": _required_str(arguments, "tenant_id"),
                "broker_connection_id": broker_connection_id,
                "underlying_symbol": _required_str(arguments, "underlying_symbol"),
                "underlying_price": arguments.get("underlying_price"),
                "currency": arguments.get("currency", "USD"),
                "snapshot_label": arguments.get("snapshot_label", "default"),
                "option_type": arguments.get("option_type", "put"),
                "min_days_to_expiry": arguments.get("min_days_to_expiry", 20),
                "max_days_to_expiry": arguments.get("max_days_to_expiry", 60),
                "connector_mode": arguments.get("connector_mode", "auto"),
                "allow_mock_fallback": bool(arguments.get("allow_mock_fallback", False)),
                "max_market_staleness_seconds": arguments.get("max_market_staleness_seconds", 60),
                "max_broker_staleness_seconds": arguments.get("max_broker_staleness_seconds", 300),
            }
            payload = await self._post_json("/api/v3/options/sell-put/analyze-from-futu", body)
            return _tool_result(
                "options.sell_put_rank",
                _with_sell_put_summary(payload),
                source_refs=[_source_ref("hermes-data-service", "/api/v3/options/sell-put/analyze-from-futu")],
            )

        payload = await self._post_json("/api/v3/options/sell-put/analyze", arguments)
        return _tool_result(
            "options.sell_put_rank",
            _with_sell_put_summary(payload),
            source_refs=[_source_ref("hermes-data-service", "/api/v3/options/sell-put/analyze")],
        )

    async def broker_positions_read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        tenant_id = _required_str(arguments, "tenant_id")
        source = str(arguments.get("source") or "portfolio_read_model")
        if source == "futu":
            body = {
                "tenant_id": tenant_id,
                "broker_connection_id": _required_str(arguments, "broker_connection_id"),
                "snapshot_label": arguments.get("snapshot_label", "default"),
                "include_positions": True,
                "include_cash": bool(arguments.get("include_cash", True)),
                "connector_mode": arguments.get("connector_mode", "auto"),
                "allow_mock_fallback": bool(arguments.get("allow_mock_fallback", False)),
            }
            payload = await self._post_json("/api/v3/broker/futu/snapshot", body)
            return _tool_result("broker.positions_read", payload, source_refs=[_source_ref("hermes-data-service", "/api/v3/broker/futu/snapshot")])

        payload = await self._get_json("/api/v3/portfolio/positions", params={"tenant_id": tenant_id})
        return _tool_result("broker.positions_read", payload, source_refs=[_source_ref("hermes-data-service", "/api/v3/portfolio/positions")])

    async def portfolio_overview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        tenant_id = _required_str(arguments, "tenant_id")
        params = _compact_params(
            {
                "tenant_id": tenant_id,
                "base_currency": arguments.get("base_currency"),
            }
        )
        payload = await self._get_json("/api/v3/portfolio/overview", params=params)
        return _tool_result("portfolio.overview", payload, source_refs=[_source_ref("hermes-data-service", "/api/v3/portfolio/overview")])

    async def stock_analysis(self, arguments: dict[str, Any]) -> dict[str, Any]:
        tenant_id = _required_str(arguments, "tenant_id")
        symbol = _required_str(arguments, "symbol")
        prompt = arguments.get("prompt")
        persist = bool(arguments.get("persist", True))
        entry_surface = str(arguments.get("entry_surface") or "system")

        async def quote_reader(target_symbol: str) -> dict[str, Any]:
            return await self._get_json(f"/api/quote/{target_symbol}")

        async def positions_reader(target_tenant_id: str) -> dict[str, Any]:
            return await self._get_json("/api/v3/portfolio/positions", params={"tenant_id": target_tenant_id})

        async def history_reader(target_symbol: str, market: str) -> dict[str, Any]:
            end_date = arguments.get("history_end_date")
            start_date = arguments.get("history_start_date")
            if not end_date:
                end_date = datetime.utcnow().date().isoformat()
            if not start_date:
                start_date = (datetime.utcnow().date() - timedelta(days=60)).isoformat()
            return await self._get_json(
                f"/api/quote/{target_symbol}/history",
                params={
                    "tenant_id": tenant_id,
                    "market": market,
                    "interval": str(arguments.get("history_interval") or "1d"),
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )

        async def sector_context_reader(
            target_tenant_id: str,
            target_symbol: str,
            target_market: str,
            target_sector: str | None,
            target_industry: str | None,
        ) -> dict[str, Any]:
            if not target_sector:
                return {
                    "tool": "sector.context",
                    "ok": False,
                    "status": "not_available",
                    "data": {
                        "schema_version": "sector_context_v1",
                        "sector_context": {
                            "status": "not_available",
                            "reason": "sector_missing",
                            "sector": None,
                            "industry": target_industry,
                            "snapshots": [],
                        },
                    },
                    "source_refs": [],
                }
            return await self.sector_context(
                {
                    "tenant_id": target_tenant_id,
                    "symbol": target_symbol,
                    "market": target_market,
                    "sector": target_sector,
                    "industry": target_industry,
                }
            )

        async def market_regime_reader(target_tenant_id: str, target_market: str) -> dict[str, Any]:
            return await self.market_regime({"tenant_id": target_tenant_id, "market": target_market})

        async def news_context_reader(
            _target_tenant_id: str,
            target_symbol: str,
            target_market: str,
            _target_sector: str | None,
            _target_industry: str | None,
        ) -> dict[str, Any]:
            raw_context = arguments.get("news_context")
            if isinstance(raw_context, dict):
                context = raw_context
            else:
                context = {
                    "symbol": target_symbol,
                    "market": target_market,
                    "items": arguments.get("news_items") or arguments.get("news") or [],
                    "catalysts": arguments.get("catalysts") or arguments.get("events") or [],
                    "summary": arguments.get("news_summary"),
                }
            if not isinstance(context, dict) or not (context.get("items") or context.get("news") or context.get("news_items") or context.get("catalysts") or context.get("events") or context.get("summary")):
                return {}
            return {
                "tool": "news.context",
                "ok": True,
                "status": "available",
                "data": {
                    "schema_version": "stock_news_context_v1",
                    "news_context": context,
                },
                "source_refs": [{"source": "domain_tool_arguments", "ref": "stock.analysis.news_context"}],
            }

        async def social_context_reader(
            _target_tenant_id: str,
            target_symbol: str,
            target_market: str,
            _target_sector: str | None,
            _target_industry: str | None,
        ) -> dict[str, Any]:
            raw_context = arguments.get("social_context")
            if isinstance(raw_context, dict):
                context = raw_context
            else:
                context = {
                    "symbol": target_symbol,
                    "market": target_market,
                    "items": arguments.get("social_items") or arguments.get("social_posts") or [],
                    "accounts": arguments.get("social_accounts") or [],
                    "themes": arguments.get("social_themes") or [],
                    "risk_flags": arguments.get("social_risk_flags") or [],
                    "summary": arguments.get("social_summary"),
                }
            if not isinstance(context, dict) or not (
                context.get("items")
                or context.get("posts")
                or context.get("themes")
                or context.get("risk_flags")
                or context.get("summary")
            ):
                return {}
            return {
                "tool": "sentiment.social.snapshot",
                "ok": True,
                "status": "available",
                "data": {
                    "schema_version": "social_sentiment_snapshot_v1",
                    "social_context": context,
                },
                "source_refs": [{"source": "domain_tool_arguments", "ref": "stock.analysis.social_context"}],
            }

        service = HermesStockAnalysisService(
            quote_reader=quote_reader,
            positions_reader=positions_reader,
            history_reader=history_reader,
            sector_context_reader=sector_context_reader,
            market_regime_reader=market_regime_reader,
            news_context_reader=news_context_reader,
            social_context_reader=social_context_reader,
        )
        result = await service.analyze(
            tenant_id=tenant_id,
            symbol=symbol,
            prompt=str(prompt) if prompt is not None else None,
            persist=persist,
            entry_surface=entry_surface,
        )
        return result.model_dump()

    async def opportunity_research_run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        tenant_id = _required_str(arguments, "tenant_id")
        market = _required_str(arguments, "market")
        workflow = self._opportunity_workflow()
        result = await workflow.run_research(
            tenant_id=tenant_id,
            market=market,
            session_type=str(arguments.get("session_type") or "premarket"),
            report_date=str(arguments.get("report_date")) if arguments.get("report_date") else None,
            universe_policy=str(arguments.get("universe_policy") or "holdings_watchlist_hard_tech"),
            model_policy=arguments.get("model_policy") if isinstance(arguments.get("model_policy"), dict) else None,
            symbols=_string_list(arguments.get("symbols") or arguments.get("watchlist_symbols")),
            sell_put_underlyings=_string_list(arguments.get("sell_put_underlyings")),
            delivery_context=arguments.get("delivery_context") if isinstance(arguments.get("delivery_context"), dict) else None,
            persist=bool(arguments.get("persist", True)),
            max_candidates=int(arguments.get("max_candidates") or 6),
        )
        return result.model_dump()

    async def opportunity_review_run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        tenant_id = _required_str(arguments, "tenant_id")
        workflow = self._opportunity_workflow()
        raw_cases = arguments.get("cases")
        result = await workflow.run_review(
            tenant_id=tenant_id,
            market=str(arguments.get("market")) if arguments.get("market") else None,
            review_date=str(arguments.get("review_date")) if arguments.get("review_date") else None,
            cases=raw_cases if isinstance(raw_cases, list) else None,
            persist=bool(arguments.get("persist", True)),
        )
        return result.model_dump()

    async def opportunity_ledger_mark(self, arguments: dict[str, Any]) -> dict[str, Any]:
        tenant_id = _required_str(arguments, "tenant_id")
        case_id = _required_str(arguments, "case_id")
        mark = arguments.get("mark")
        if not isinstance(mark, dict):
            raise DomainToolError("mark must be an object")
        workflow = self._opportunity_workflow()
        result = await workflow.mark_ledger(
            tenant_id=tenant_id,
            case_id=case_id,
            mark=mark,
            persist=bool(arguments.get("persist", True)),
        )
        return result.model_dump()

    def _opportunity_workflow(self) -> OpportunityResearchWorkflow:
        async def market_regime_reader(args: dict[str, Any]) -> dict[str, Any]:
            return await self.market_regime(args)

        async def portfolio_overview_reader(args: dict[str, Any]) -> dict[str, Any]:
            return await self.portfolio_overview(args)

        async def positions_reader(args: dict[str, Any]) -> dict[str, Any]:
            return await self.broker_positions_read(args)

        async def quote_reader(args: dict[str, Any]) -> dict[str, Any]:
            return await self.market_quote(args)

        async def stock_analysis_reader(args: dict[str, Any]) -> dict[str, Any]:
            return await self.stock_analysis(args)

        async def sell_put_reader(args: dict[str, Any]) -> dict[str, Any]:
            return await self.options_sell_put_rank(args)

        return OpportunityResearchWorkflow(
            market_regime_reader=market_regime_reader,
            portfolio_overview_reader=portfolio_overview_reader,
            positions_reader=positions_reader,
            quote_reader=quote_reader,
            stock_analysis_reader=stock_analysis_reader,
            sell_put_reader=sell_put_reader,
        )

    async def ima_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        disabled = self._ima_disabled_result("reference.ima.search")
        if disabled:
            return disabled
        query = _required_str(arguments, "query")
        scope = str(arguments.get("scope") or "knowledge")
        limit = int(arguments.get("limit") or 10)
        if scope == "notes":
            body = {
                "search_type": 1,
                "query_info": {"content": query},
                "start": 0,
                "end": limit,
            }
            raw = await self._ima_api("openapi/note/v1/search_note", body)
        else:
            body = _compact_params(
                {
                    "query": query,
                    "knowledge_base_id": arguments.get("knowledge_base_id") or os.getenv("IMA_DEFAULT_KNOWLEDGE_BASE_ID"),
                    "cursor": arguments.get("cursor", ""),
                    "limit": limit,
                }
            )
            raw = await self._ima_api("openapi/wiki/v1/search_knowledge", body)
        return _tool_result(
            "reference.ima.search",
            {"ok": raw.get("code") in {0, "0", None}, "data": raw, "reference_only": True},
            source_refs=[_source_ref("ima", scope)],
        )

    async def ima_read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        disabled = self._ima_disabled_result("reference.ima.read")
        if disabled:
            return disabled
        if arguments.get("note_id"):
            raw = await self._ima_api(
                "openapi/note/v1/get_doc_content",
                {
                    "note_id": arguments["note_id"],
                    "target_content_format": int(arguments.get("target_content_format") or 0),
                },
            )
            ref = f"note:{arguments['note_id']}"
        elif arguments.get("media_id"):
            raw = await self._ima_api("openapi/wiki/v1/get_media_info", {"media_id": arguments["media_id"]})
            ref = f"media:{arguments['media_id']}"
        else:
            raise DomainToolError("note_id or media_id is required")
        return _tool_result(
            "reference.ima.read",
            {"ok": raw.get("code") in {0, "0", None}, "data": raw, "reference_only": True},
            source_refs=[_source_ref("ima", ref)],
        )

    async def reference_web_read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = _required_str(arguments, "url")
        tenant_id = str(arguments.get("tenant_id") or "")
        prompt = str(arguments.get("prompt") or "")
        entry_surface = str(arguments.get("entry_surface") or "system")
        read_policy = _reference_read_policy(url, arguments)
        body = _compact_params(
            {
                "url": url,
                "tenant_id": tenant_id,
                "mode": read_policy["mode"],
                "css_selector": arguments.get("css_selector"),
                "timeout_ms": int(arguments.get("timeout_ms") or 30000),
                "max_chars": int(arguments.get("max_chars") or 12000),
                "proxy_url": read_policy.get("proxy_url"),
            }
        )
        try:
            reference = await self._post_reference_capture("/read", body)
        except Exception as exc:  # noqa: BLE001 - keep reference failures auditable.
            reference = {
                "ok": False,
                "status": "reference_capture_unavailable",
                "schema_version": "web_reference_snapshot_v1",
                "reference_only": True,
                "url": url,
                "canonical_url": url,
                "content_text": "",
                "content_markdown": "",
                "content_hash": _hash_text(f"{url}\nreference_capture_unavailable\n{exc}"),
                "source_refs": [_source_ref("web", url)],
                "failed": {"reason": "reference_capture_unavailable", "message": str(exc)},
                "audit": {"failure_reason": "reference_capture_unavailable", "failure_message": str(exc)},
            }

        persistence = await WebReferencePersistence.from_env().save(
            tenant_id=tenant_id,
            reference=reference,
            entry_surface=entry_surface,
            prompt=prompt,
        )
        summary = summarize_web_reference(reference)
        source_refs = reference.get("source_refs") if isinstance(reference.get("source_refs"), list) else [_source_ref("web", url)]
        return {
            "tool": "reference.web.read",
            "ok": bool(reference.get("ok")),
            "status": reference.get("status") or ("ok" if reference.get("ok") else "error"),
            "data": {
                "schema_version": "web_reference_tool_result_v1",
                "reference_only": True,
                "reference": reference,
                "summary": summary,
                "persistence": persistence,
                "audit": {
                    "entry_surface": entry_surface,
                    "prompt": prompt[:1000],
                    "requested_url": url,
                    "sidecar_url": self.reference_capture_url,
                    "read_policy": {
                        key: value for key, value in read_policy.items() if key != "proxy_url"
                    },
                    "persistence": persistence,
                    "failed": reference.get("failed"),
                },
            },
            "failed": reference.get("failed"),
            "source_refs": source_refs,
        }

    async def reference_web_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = _required_str(arguments, "query")
        tenant_id = str(arguments.get("tenant_id") or "")
        prompt = str(arguments.get("prompt") or query)
        entry_surface = str(arguments.get("entry_surface") or "system")
        limit = max(1, min(10, int(arguments.get("limit") or 5)))
        providers = _reference_search_provider_chain(arguments)
        endpoint = (os.getenv("HERMES_REFERENCE_SEARCH_URL") or os.getenv("HERMES_REFERENCE_SEARCH_API_URL") or "").strip()
        attempts: list[dict[str, Any]] = []
        last_empty_result: dict[str, Any] | None = None

        for provider in providers:
            try:
                raw, items, configured = await self._reference_search_provider(
                    provider=provider,
                    endpoint=endpoint,
                    tenant_id=tenant_id,
                    query=query,
                    limit=limit,
                    arguments=arguments,
                )
                attempts.append(
                    {
                        "provider": provider,
                        "configured": configured,
                        "ok": True,
                        "items": len(items),
                    }
                )
                if not configured:
                    continue

                read_result = None
                if bool(arguments.get("read_top")) and items:
                    top_url = str(items[0].get("url") or "")
                    if _is_http_url(top_url):
                        read_result = await self.reference_web_read(
                            {
                                "tenant_id": tenant_id,
                                "url": top_url,
                                "mode": arguments.get("mode") or "auto",
                                "allow_stealthy": arguments.get("allow_stealthy"),
                                "prompt": prompt,
                                "entry_surface": entry_surface,
                            }
                        )
                source_refs = [_source_ref("reference-search", provider)]
                for item in items[:3]:
                    source_refs.append(_source_ref(str(item.get("source") or provider), str(item.get("url") or item.get("id") or provider)))
                if read_result:
                    source_refs.extend(read_result.get("source_refs") or [])
                result = {
                    "tool": "reference.web.search",
                    "ok": True,
                    "status": "ok",
                    "data": {
                        "schema_version": "web_reference_search_result_v1",
                        "reference_only": True,
                        "query": query,
                        "provider": provider,
                        "providers_attempted": attempts,
                        "items": items,
                        "read_result": read_result,
                        "audit": {
                            "entry_surface": entry_surface,
                            "prompt": prompt[:1000],
                            "endpoint_configured": bool(endpoint),
                            "limit": limit,
                            "read_top": bool(arguments.get("read_top")),
                            "search_raw_status": raw.get("status") if isinstance(raw, dict) else None,
                        },
                    },
                    "source_refs": _dedupe_source_refs(source_refs),
                }
                if items:
                    return result
                last_empty_result = result
            except Exception as exc:  # noqa: BLE001 - continue provider chain and keep audit.
                attempts.append({"provider": provider, "configured": True, "ok": False, "error": str(exc)})

        if last_empty_result:
            return last_empty_result

        provider = providers[0] if providers else "none"
        failed_message = "No configured reference search provider returned results"
        if not any(item.get("configured") for item in attempts):
            failed_message = "IMA, GBrain, and reference search API are not configured"
            return {
                "tool": "reference.web.search",
                "ok": False,
                "status": "search_source_not_configured",
                "data": {
                    "schema_version": "web_reference_search_result_v1",
                    "reference_only": True,
                    "query": query,
                    "provider": provider,
                    "providers_attempted": attempts,
                    "items": [],
                    "read_result": None,
                    "audit": {
                        "entry_surface": entry_surface,
                        "prompt": prompt[:1000],
                        "failed": {
                            "reason": "search_source_not_configured",
                            "message": failed_message,
                        },
                    },
                },
                "failed": {
                    "reason": "search_source_not_configured",
                    "message": failed_message,
                },
                "source_refs": [_source_ref("reference-search", "disabled")],
            }

        return {
            "tool": "reference.web.search",
            "ok": False,
            "status": "search_failed",
            "data": {
                "schema_version": "web_reference_search_result_v1",
                "reference_only": True,
                "query": query,
                "provider": provider,
                "providers_attempted": attempts,
                "items": [],
                "read_result": None,
                "audit": {
                    "entry_surface": entry_surface,
                    "prompt": prompt[:1000],
                    "failed": {"reason": "search_failed", "message": failed_message},
                },
            },
            "failed": {"reason": "search_failed", "message": failed_message},
            "source_refs": [_source_ref("reference-search", provider)],
        }

    async def reference_social_watchlist(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = str(arguments.get("symbol") or "").strip().upper()
        platforms = _social_platform_filter(arguments.get("platforms") or arguments.get("platform"))
        accounts = _social_watch_accounts(arguments.get("accounts"))
        if not accounts:
            accounts = [
                *await _social_watch_accounts_from_db(str(arguments.get("tenant_id") or "").strip()),
                *_social_watch_accounts_from_env(),
            ]
        accounts = _filter_social_accounts(accounts, symbol=symbol, platforms=platforms)
        status = "ok" if accounts else "social_watchlist_not_configured"
        return {
            "tool": "reference.social.watchlist",
            "ok": bool(accounts),
            "status": status,
            "data": {
                "schema_version": "social_account_watchlist_v1",
                "reference_only": True,
                "symbol": symbol or None,
                "platforms": platforms,
                "accounts": accounts,
                "account_count": len(accounts),
                "audit": {
                    "scope": "finite_accounts_only",
                    "global_search_enabled": False,
                    "db_configured": bool(os.getenv("DATABASE_URL", "").strip()),
                    "env_configured": bool(os.getenv("HERMES_SOCIAL_WATCHLIST_JSON", "").strip()),
                },
            },
            "failed": None if accounts else {"reason": "social_watchlist_not_configured", "message": "No finite social account watchlist is configured."},
            "source_refs": [_source_ref("social-watchlist", f"{item['platform']}:{item['handle']}") for item in accounts],
        }

    async def reference_social_health(self, arguments: dict[str, Any]) -> dict[str, Any]:
        providers = _social_provider_filter(arguments.get("providers") or arguments.get("platforms") or arguments.get("platform"))
        if not providers:
            providers = _social_enabled_provider_names()
        timeout_seconds = _social_timeout_seconds(arguments)
        attempts = [await _social_provider_health(provider, timeout_seconds=timeout_seconds) for provider in providers]
        ok_count = sum(1 for attempt in attempts if attempt.get("ok"))
        return {
            "tool": "reference.social.health",
            "ok": bool(attempts and ok_count == len(attempts)),
            "status": "ok" if attempts and ok_count == len(attempts) else ("partial" if ok_count else "not_configured"),
            "data": {
                "schema_version": "social_provider_health_v1",
                "reference_only": True,
                "providers_attempted": attempts,
                "data_quality": {
                    "status": "available" if ok_count else "not_configured",
                    "providers_requested": providers,
                    "providers_ok_count": ok_count,
                    "providers_attempted_count": len(attempts),
                    "limited_to_accounts": True,
                    "global_search_enabled": False,
                    "timeout_seconds": timeout_seconds,
                },
                "audit": {"scope": "finite_accounts_only", "global_search_enabled": False},
            },
            "failed": None if ok_count else {"reason": "social_provider_not_configured", "message": "No requested social provider is healthy."},
            "source_refs": [_source_ref("social-provider", str(item.get("provider") or "")) for item in attempts],
        }

    async def reference_social_timeline(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = str(arguments.get("symbol") or "").strip().upper()
        limit = max(1, min(50, int(arguments.get("limit") or 20)))
        window = str(arguments.get("window") or "72h")
        timeout_seconds = _social_timeout_seconds(arguments)
        watchlist = await self.reference_social_watchlist(arguments)
        accounts = watchlist.get("data", {}).get("accounts") if isinstance(watchlist.get("data"), dict) else []
        accounts = accounts if isinstance(accounts, list) else []
        if not accounts:
            data_quality = _social_timeline_data_quality(
                accounts=[],
                items=[],
                provider_attempts=[],
                requested_limit=limit,
                clipped_count=0,
                deduped_count=0,
                timeout_seconds=timeout_seconds,
            )
            return {
                "tool": "reference.social.timeline",
                "ok": False,
                "status": "social_watchlist_required",
                "data": {
                    "schema_version": "social_reference_timeline_v1",
                    "reference_only": True,
                    "symbol": symbol or None,
                    "window": window,
                    "items": [],
                    "accounts": [],
                    "providers_attempted": [],
                    "data_quality": data_quality,
                    "audit": {"scope": "finite_accounts_only", "global_search_enabled": False},
                },
                "failed": {"reason": "social_watchlist_required", "message": "Social timeline requires explicit or configured watched accounts."},
                "source_refs": [],
            }
        raw_items = arguments.get("items") or arguments.get("posts") or []
        clipped = {"count": 0}
        items = _normalize_social_items(raw_items, accounts=accounts, symbol=symbol, limit=limit, clipped=clipped)
        provider_attempts: list[dict[str, Any]] = []
        if len(items) < limit:
            provider_names = _social_provider_names_for_accounts(arguments, accounts)
            for provider in provider_names:
                provider_result = await _read_social_provider(
                    provider,
                    accounts=[account for account in accounts if str(account.get("platform") or "") == provider],
                    symbol=symbol,
                    limit=max(1, limit - len(items)),
                    timeout_seconds=timeout_seconds,
                )
                provider_attempts.append(provider_result["attempt"])
                items.extend(provider_result["items"])
                clipped["count"] += int(provider_result.get("clipped_count") or 0)
                if len(items) >= limit:
                    break
        items, deduped_count = _dedupe_social_items(items, limit=limit)
        status = "ok" if items else "social_source_not_configured"
        inline_attempt = {
            "provider": "inline_items",
            "configured": bool(raw_items),
            "ok": bool(raw_items and items),
            "items": len(_normalize_social_items(raw_items, accounts=accounts, symbol=symbol, limit=limit)) if raw_items else 0,
            "status": "ok" if raw_items else "not_supplied",
        }
        attempts = [inline_attempt, *provider_attempts]
        data_quality = _social_timeline_data_quality(
            accounts=accounts,
            items=items,
            provider_attempts=attempts,
            requested_limit=limit,
            clipped_count=clipped["count"],
            deduped_count=deduped_count,
            timeout_seconds=timeout_seconds,
        )
        return {
            "tool": "reference.social.timeline",
            "ok": bool(items),
            "status": status,
            "data": {
                "schema_version": "social_reference_timeline_v1",
                "reference_only": True,
                "symbol": symbol or None,
                "window": window,
                "items": items,
                "accounts": accounts,
                "providers_attempted": attempts,
                "data_quality": data_quality,
                "audit": {
                    "scope": "finite_accounts_only",
                    "global_search_enabled": False,
                    "query_ignored": bool(arguments.get("query")),
                },
            },
            "failed": None if items else {"reason": "social_source_not_configured", "message": "No configured social provider returned finite-account posts."},
            "source_refs": _dedupe_source_refs([_source_ref(str(item.get("platform") or "social"), str(item.get("url") or item.get("account_id") or "watched-account")) for item in items]),
        }

    async def social_sentiment_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = str(arguments.get("symbol") or "").strip().upper()
        timeline = await self.reference_social_timeline(arguments)
        data = timeline.get("data") if isinstance(timeline.get("data"), dict) else {}
        items = data.get("items") if isinstance(data.get("items"), list) else []
        accounts = data.get("accounts") if isinstance(data.get("accounts"), list) else []
        snapshot = _build_social_snapshot(
            symbol=symbol,
            window=str(arguments.get("window") or data.get("window") or "72h"),
            items=items,
            accounts=accounts,
            failed=timeline.get("failed") if isinstance(timeline.get("failed"), dict) else None,
            providers_attempted=data.get("providers_attempted") if isinstance(data.get("providers_attempted"), list) else [],
            data_quality=data.get("data_quality") if isinstance(data.get("data_quality"), dict) else {},
        )
        return {
            "tool": "sentiment.social.snapshot",
            "ok": snapshot["status"] == "available",
            "status": snapshot["status"],
            "data": {
                "schema_version": "social_sentiment_tool_result_v1",
                "reference_only": True,
                "social_context": snapshot,
                "timeline": data,
                "providers_attempted": snapshot.get("providers_attempted") or [],
                "data_quality": snapshot.get("data_quality") or {},
                "audit": {"scope": "finite_accounts_only", "global_search_enabled": False},
            },
            "failed": timeline.get("failed"),
            "source_refs": timeline.get("source_refs") or [],
        }

    async def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self.http_client_factory() as client:
            response = await client.get(f"{self.data_service_url}{path}", params=params)
            response.raise_for_status()
            return response.json()

    async def _post_json(
        self,
        path: str,
        body: dict[str, Any],
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self.http_client_factory() as client:
            response = await client.post(f"{self.data_service_url}{path}", params=params, json=body)
            response.raise_for_status()
            return response.json()

    async def _post_reference_capture(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async with self.http_client_factory() as client:
            response = await client.post(f"{self.reference_capture_url}{path}", json=body, timeout=130)
            response.raise_for_status()
            return response.json()

    async def _reference_search(self, *, provider: str, endpoint: str, query: str, limit: int) -> dict[str, Any]:
        if provider in {"bing", "bing_html"}:
            search_url = endpoint or "https://www.bing.com/search"
            async with self.http_client_factory() as client:
                response = await client.get(search_url, params={"q": query}, timeout=30)
                response.raise_for_status()
                parser = _BingHtmlResultParser(limit=limit)
                parser.feed(response.text)
                return {"results": parser.items}
        if provider == "api":
            if not endpoint:
                raise DomainToolError("HERMES_REFERENCE_SEARCH_API_URL or HERMES_REFERENCE_SEARCH_URL is not configured")
            async with self.http_client_factory() as client:
                response = await client.get(endpoint, params={"q": query, "query": query, "limit": limit}, timeout=30)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
                raise DomainToolError("reference search API returned non-object JSON")
        if provider != "searxng":
            raise DomainToolError(f"unsupported reference search provider: {provider}")
        if not endpoint:
            raise DomainToolError("HERMES_REFERENCE_SEARCH_URL is not configured")
        async with self.http_client_factory() as client:
            response = await client.get(
                endpoint,
                params={"q": query, "format": "json", "language": os.getenv("HERMES_REFERENCE_SEARCH_LANGUAGE", "zh-CN")},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise DomainToolError("reference search returned non-object JSON")

    async def _reference_search_provider(
        self,
        *,
        provider: str,
        endpoint: str,
        tenant_id: str,
        query: str,
        limit: int,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
        provider = provider.strip().lower()
        if provider == "ima":
            raw_result = await self.ima_search(
                {
                    "query": query,
                    "scope": arguments.get("ima_scope") or arguments.get("scope") or _default_ima_search_scope(),
                    "knowledge_base_id": arguments.get("knowledge_base_id"),
                    "limit": limit,
                }
            )
            configured = bool(raw_result.get("ok"))
            return raw_result, _normalize_ima_search_items(raw_result, limit=limit), configured
        if provider == "gbrain":
            raw = await self._gbrain_search(tenant_id=tenant_id, query=query, limit=limit)
            configured = raw.get("status") != "disabled"
            return raw, _normalize_search_items(raw, limit=limit), configured
        if provider in {"searxng", "api"} and not endpoint:
            return {"status": "disabled", "reason": "endpoint_missing"}, [], False
        raw = await self._reference_search(provider=provider, endpoint=endpoint, query=query, limit=limit)
        return raw, _normalize_search_items(raw, limit=limit), True

    async def _gbrain_search(self, *, tenant_id: str, query: str, limit: int) -> dict[str, Any]:
        database_url = (os.getenv("GBRAIN_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
        if not database_url or not tenant_id:
            return {"status": "disabled", "reason": "gbrain_database_or_tenant_missing", "results": []}
        return await asyncio.to_thread(_gbrain_search_sync, database_url, tenant_id, query, limit)

    def _ima_disabled_result(self, tool_name: str) -> dict[str, Any] | None:
        enabled = os.getenv("IMA_REFERENCE_SOURCE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
        has_credentials = bool(os.getenv("IMA_OPENAPI_CLIENTID", "").strip() and os.getenv("IMA_OPENAPI_APIKEY", "").strip())
        script_exists = (self.ima_skill_dir / "ima_api.cjs").exists()
        if enabled and has_credentials and script_exists:
            return None
        reasons = []
        if not enabled:
            reasons.append("IMA_REFERENCE_SOURCE_ENABLED is false")
        if not has_credentials:
            reasons.append("IMA_OPENAPI_CLIENTID or IMA_OPENAPI_APIKEY is missing")
        if not script_exists:
            reasons.append(f"ima_api.cjs not found under {self.ima_skill_dir}")
        return {
            "tool": tool_name,
            "ok": False,
            "status": "disabled",
            "error": "IMA reference source is not configured",
            "reasons": reasons,
            "reference_only": True,
            "source_refs": [_source_ref("ima", "disabled")],
        }

    async def _ima_api(self, api_path: str, body: dict[str, Any]) -> dict[str, Any]:
        script = self.ima_skill_dir / "ima_api.cjs"
        options = json.dumps(
            {
                "clientId": os.getenv("IMA_OPENAPI_CLIENTID", ""),
                "apiKey": os.getenv("IMA_OPENAPI_APIKEY", ""),
                "baseUrl": os.getenv("IMA_BASE_URL", "https://ima.qq.com"),
            },
            ensure_ascii=False,
        )
        process = await asyncio.create_subprocess_exec(
            "node",
            str(script),
            api_path,
            json.dumps(body, ensure_ascii=False),
            options,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise DomainToolError(f"IMA API call failed: {stderr.decode('utf-8', errors='replace')}")
        try:
            return json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise DomainToolError(f"IMA API returned invalid JSON: {exc}") from exc


def _required_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DomainToolError(f"{key} is required")
    return value.strip()


def _optional_bool_str(value: Any) -> str | None:
    if value is None:
        return None
    return "true" if bool(value) else "false"


def _compact_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None and value != ""}


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _csv_values(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").split(",")
    return [str(item).strip().lower() for item in raw_items if str(item).strip()]


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        return []
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _host_matches(host: str, patterns: list[str]) -> bool:
    if not host or not patterns:
        return False
    for pattern in patterns:
        pattern = pattern.strip().lower()
        if not pattern:
            continue
        if pattern == "*":
            return True
        if pattern.startswith("*."):
            suffix = pattern[2:]
            if host == suffix or host.endswith(f".{suffix}"):
                return True
        if host == pattern or host.endswith(f".{pattern}"):
            return True
    return False


def _reference_read_policy(url: str, arguments: dict[str, Any]) -> dict[str, Any]:
    requested_mode = str(arguments.get("mode") or "auto").strip().lower() or "auto"
    host = (urlparse(url).hostname or "").lower()
    stealthy_enabled = _env_bool("HERMES_REFERENCE_STEALTHY_ENABLED")
    stealthy_hosts = _csv_values(os.getenv("HERMES_REFERENCE_STEALTHY_HOSTS", ""))
    stealthy_default_hosts = _csv_values(os.getenv("HERMES_REFERENCE_STEALTHY_REQUIRED_HOSTS", ""))
    allow_stealthy_arg = bool(arguments.get("allow_stealthy"))
    stealthy_allowed = stealthy_enabled and _host_matches(host, stealthy_hosts)
    mode = requested_mode if requested_mode in {"auto", "get", "dynamic", "stealthy"} else "auto"
    stealthy_reason = "not_requested"
    if mode == "stealthy":
        if stealthy_allowed and allow_stealthy_arg:
            stealthy_reason = "explicit_host_allowlist"
        else:
            mode = "auto"
            stealthy_reason = "disabled_or_host_not_allowed"
    elif mode == "auto" and stealthy_allowed and _host_matches(host, stealthy_default_hosts):
        mode = "stealthy"
        stealthy_reason = "host_required"

    proxy_enabled = _env_bool("HERMES_REFERENCE_PROXY_ENABLED")
    proxy_url = str(arguments.get("proxy_url") or os.getenv("HERMES_REFERENCE_PROXY_URL") or "").strip()
    proxy_hosts = _csv_values(os.getenv("HERMES_REFERENCE_PROXY_HOSTS", ""))
    proxy_allowed = bool(proxy_enabled and proxy_url and _host_matches(host, proxy_hosts))
    return {
        "mode": mode,
        "requested_mode": requested_mode,
        "host": host,
        "stealthy_enabled": stealthy_enabled,
        "stealthy_allowed": stealthy_allowed,
        "stealthy_reason": stealthy_reason,
        "proxy_enabled": proxy_enabled,
        "proxy_configured": bool(proxy_url),
        "proxy_allowed": proxy_allowed,
        "proxy_url": proxy_url if proxy_allowed else "",
    }


def _reference_search_provider_chain(arguments: dict[str, Any]) -> list[str]:
    explicit = arguments.get("providers") or arguments.get("provider_chain")
    if explicit:
        providers = _csv_values(explicit)
    elif os.getenv("HERMES_REFERENCE_SEARCH_PROVIDERS"):
        providers = _csv_values(os.getenv("HERMES_REFERENCE_SEARCH_PROVIDERS"))
    elif os.getenv("HERMES_REFERENCE_SEARCH_PROVIDER"):
        providers = _csv_values(os.getenv("HERMES_REFERENCE_SEARCH_PROVIDER"))
    elif os.getenv("HERMES_REFERENCE_SEARCH_URL") or os.getenv("HERMES_REFERENCE_SEARCH_API_URL"):
        providers = ["searxng"]
    else:
        providers = ["ima", "gbrain", "searxng"]
    aliases = {"search_api": "api", "web": "searxng", "bing": "bing_html"}
    normalized: list[str] = []
    for provider in providers:
        provider = aliases.get(provider, provider)
        if provider and provider not in normalized:
            normalized.append(provider)
    return normalized or ["ima", "gbrain", "searxng"]


def _default_ima_search_scope() -> str:
    configured = os.getenv("IMA_REFERENCE_SEARCH_SCOPE", "").strip().lower()
    if configured in {"knowledge", "notes"}:
        return configured
    return "knowledge" if os.getenv("IMA_DEFAULT_KNOWLEDGE_BASE_ID", "").strip() else "notes"


def _source_ref(source: str, ref: str) -> dict[str, str]:
    return {"source": source, "ref": ref}


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _is_http_url(value: str) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _normalize_search_items(raw: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    candidates = raw.get("results")
    if not isinstance(candidates, list):
        candidates = raw.get("items")
    if not isinstance(candidates, list):
        return []
    items: list[dict[str, Any]] = []
    for row in candidates:
        if not isinstance(row, dict):
            continue
        url = row.get("url") or row.get("link")
        source = row.get("engine") or row.get("source") or "reference-search"
        if not isinstance(url, str):
            continue
        if not url.startswith(("http://", "https://")) and source not in {"ima", "gbrain"}:
            continue
        title = row.get("title") or row.get("name") or url
        snippet = row.get("content") or row.get("snippet") or row.get("description") or ""
        items.append(
            {
                "title": str(title).strip()[:300],
                "url": url.strip(),
                "snippet": str(snippet).strip()[:1000],
                "source": source,
                "reference_only": True,
            }
        )
        if len(items) >= limit:
            break
    return items


def _normalize_ima_search_items(raw_result: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    payload = raw_result.get("data") if isinstance(raw_result.get("data"), dict) else raw_result
    candidates = _collect_search_like_dicts(payload, limit=limit * 4)
    items: list[dict[str, Any]] = []
    for row in candidates:
        title = row.get("title") or row.get("name") or row.get("doc_title") or row.get("note_title")
        snippet = row.get("content") or row.get("summary") or row.get("snippet") or row.get("description") or row.get("abstract")
        url = row.get("url") or row.get("link") or row.get("source_url")
        note_id = row.get("note_id") or row.get("id") or row.get("doc_id") or row.get("media_id")
        if not title and not snippet:
            continue
        ref_url = str(url).strip() if isinstance(url, str) and url.strip() else f"ima://reference/{note_id or len(items) + 1}"
        items.append(
            {
                "title": str(title or ref_url).strip()[:300],
                "url": ref_url,
                "snippet": str(snippet or "").strip()[:1000],
                "source": "ima",
                "id": str(note_id or ""),
                "reference_only": True,
            }
        )
        if len(items) >= limit:
            break
    return items


def _collect_search_like_dicts(value: Any, *, limit: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if len(found) >= limit:
            return
        if isinstance(node, dict):
            if any(key in node for key in ("title", "name", "content", "summary", "snippet", "url", "link", "note_id", "media_id")):
                found.append(node)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return found


def _gbrain_search_sync(database_url: str, tenant_id: str, query: str, limit: int) -> dict[str, Any]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        table = conn.execute("SELECT to_regclass('public.gbrain_pages') AS table_name").fetchone()
        if not table or not table.get("table_name"):
            return {"status": "disabled", "reason": "gbrain_pages_missing", "results": []}
        rows = conn.execute(
            """
            SELECT id::text, path, title, content, page_type, metadata, updated_at,
                   ts_rank_cd(search_vector, plainto_tsquery('simple', %(query)s)) AS rank
            FROM public.gbrain_pages
            WHERE tenant_id::text = %(tenant_id)s
              AND (
                search_vector @@ plainto_tsquery('simple', %(query)s)
                OR title ILIKE %(like_query)s
                OR content ILIKE %(like_query)s
              )
            ORDER BY rank DESC NULLS LAST, updated_at DESC
            LIMIT %(limit)s
            """,
            {"tenant_id": tenant_id, "query": query, "like_query": f"%{query}%", "limit": limit},
        ).fetchall()
    results = []
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        url = metadata.get("url") or metadata.get("source_url") or f"gbrain://{row.get('path') or row.get('id')}"
        results.append(
            {
                "title": row.get("title") or row.get("path") or "GBrain reference",
                "url": url,
                "content": _collapse_text(str(row.get("content") or ""))[:1000],
                "source": "gbrain",
                "id": row.get("id"),
                "path": row.get("path"),
                "page_type": row.get("page_type"),
            }
        )
    return {"status": "ok", "results": results}


class _BingHtmlResultParser(HTMLParser):
    def __init__(self, *, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.items: list[dict[str, Any]] = []
        self._li_depth = 0
        self._in_result = False
        self._capture_title = False
        self._capture_snippet = False
        self._current_url: str | None = None
        self._title_chunks: list[str] = []
        self._snippet_chunks: list[str] = []
        self._h2_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs if key}
        classes = set(attrs_dict.get("class", "").split())
        if tag == "li" and "b_algo" in classes:
            self._start_result()
        elif self._in_result and tag == "li":
            self._li_depth += 1
        if not self._in_result:
            return
        if tag == "h2":
            self._h2_depth += 1
        if tag == "a" and self._h2_depth > 0 and not self._current_url:
            href = attrs_dict.get("href", "")
            normalized_url = _normalize_search_result_url(href)
            if normalized_url:
                self._current_url = normalized_url
                self._capture_title = True
        elif tag == "p" and self._current_url:
            self._capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if not self._in_result:
            return
        if tag == "a":
            self._capture_title = False
        elif tag == "h2" and self._h2_depth:
            self._h2_depth -= 1
        elif tag == "p":
            self._capture_snippet = False
        elif tag == "li":
            if self._li_depth <= 1:
                self._finish_result()
            else:
                self._li_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._in_result:
            return
        if self._capture_title:
            self._title_chunks.append(data)
        elif self._capture_snippet:
            self._snippet_chunks.append(data)

    def _start_result(self) -> None:
        self._in_result = True
        self._li_depth = 1
        self._capture_title = False
        self._capture_snippet = False
        self._current_url = None
        self._title_chunks = []
        self._snippet_chunks = []
        self._h2_depth = 0

    def _finish_result(self) -> None:
        if self._current_url and len(self.items) < self.limit:
            title = _collapse_text(" ".join(self._title_chunks)) or self._current_url
            snippet = _collapse_text(" ".join(self._snippet_chunks))
            self.items.append(
                {
                    "title": title,
                    "url": self._current_url,
                    "content": snippet,
                    "engine": "bing_html",
                }
            )
        self._in_result = False
        self._li_depth = 0
        self._capture_title = False
        self._capture_snippet = False
        self._current_url = None
        self._title_chunks = []
        self._snippet_chunks = []
        self._h2_depth = 0


def _normalize_search_result_url(url: str) -> str | None:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    if host == "bing.com" or host.endswith(".bing.com"):
        decoded = _decode_bing_redirect_url(url)
        if decoded and decoded != url:
            return _normalize_search_result_url(decoded)
        return None
    blocked_suffixes = ("microsoft.com",)
    if any(host == suffix or host.endswith(f".{suffix}") for suffix in blocked_suffixes):
        return None
    return url


def _decode_bing_redirect_url(url: str) -> str | None:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("u") or []
    if not values:
        return None
    encoded = unquote(values[0])
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8", errors="replace")
    except Exception:
        return None
    return decoded if decoded.startswith(("http://", "https://")) else None


def _collapse_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _dedupe_source_refs(refs: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for ref in refs:
        source = str(ref.get("source") or "")
        target = str(ref.get("ref") or "")
        key = (source, target)
        if not source or not target or key in seen:
            continue
        seen.add(key)
        result.append({"source": source, "ref": target})
    return result


def _social_platform_filter(value: Any) -> list[str]:
    allowed = {"xueqiu", "reddit", "xhs", "xiaohongshu", "twitter", "x", "youtube", "yt"}
    aliases = {"xiaohongshu": "xhs", "x": "twitter", "yt": "youtube"}
    platforms = []
    for item in _csv_values(value):
        platform = aliases.get(item, item)
        if platform in allowed and platform not in platforms:
            platforms.append(platform)
    return platforms


def _social_provider_filter(value: Any) -> list[str]:
    requested = _social_platform_filter(value)
    providers = []
    for platform in requested:
        provider = _social_platform_name(platform)
        if provider in {"twitter", "xhs", "youtube"} and provider not in providers:
            providers.append(provider)
    return providers


def _social_watch_accounts(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    accounts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        platform = _social_platform_name(row.get("platform"))
        handle = str(row.get("handle") or row.get("account_id") or row.get("user_id") or row.get("id") or "").strip()
        if not platform or not handle:
            continue
        key = (platform, handle.lower())
        if key in seen:
            continue
        seen.add(key)
        symbols = [str(item).strip().upper() for item in row.get("symbols", []) if str(item).strip()] if isinstance(row.get("symbols"), list) else []
        accounts.append(
            {
                "platform": platform,
                "handle": handle,
                "display_name": str(row.get("display_name") or row.get("name") or "").strip() or None,
                "url": str(row.get("url") or row.get("profile_url") or "").strip() or None,
                "channel_url": str(row.get("channel_url") or row.get("youtube_url") or row.get("url") or "").strip() or None,
                "user_id": str(row.get("user_id") or row.get("uid") or "").strip() or None,
                "xsec_token": str(row.get("xsec_token") or row.get("xsecToken") or "").strip() or None,
                "symbols": symbols,
                "priority": int(row.get("priority") or 100),
            }
        )
    return accounts[:100]


def _social_watch_accounts_from_env() -> list[dict[str, Any]]:
    raw = os.getenv("HERMES_SOCIAL_WATCHLIST_JSON", "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        payload = payload.get("accounts")
    return _social_watch_accounts(payload)


async def _social_watch_accounts_from_db(tenant_id: str = "") -> list[dict[str, Any]]:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return []
    return await asyncio.to_thread(_social_watch_accounts_from_db_sync, database_url, tenant_id)


def _social_watch_accounts_from_db_sync(database_url: str, tenant_id: str = "") -> list[dict[str, Any]]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception:
        return []

    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                if tenant_id:
                    cur.execute(
                        """
                        SELECT
                          platform, handle, display_name, url, channel_url, user_id,
                          xsec_token, symbols, priority
                        FROM public.social_watch_accounts
                        WHERE is_active = true
                          AND (tenant_id IS NULL OR tenant_id = %s::uuid)
                        ORDER BY priority ASC, platform ASC, handle ASC
                        LIMIT 100
                        """,
                        (tenant_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT
                          platform, handle, display_name, url, channel_url, user_id,
                          xsec_token, symbols, priority
                        FROM public.social_watch_accounts
                        WHERE is_active = true
                        ORDER BY priority ASC, platform ASC, handle ASC
                        LIMIT 100
                        """
                    )
                rows = cur.fetchall()
    except Exception:
        return []
    return _social_watch_accounts(
        [
            {
                "platform": row.get("platform"),
                "handle": row.get("handle"),
                "display_name": row.get("display_name"),
                "url": row.get("url"),
                "channel_url": row.get("channel_url"),
                "user_id": row.get("user_id"),
                "xsec_token": row.get("xsec_token"),
                "symbols": row.get("symbols") or ["*"],
                "priority": row.get("priority") or 100,
            }
            for row in rows
        ]
    )


def _filter_social_accounts(
    accounts: list[dict[str, Any]],
    *,
    symbol: str,
    platforms: list[str],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    platform_set = set(platforms)
    for account in accounts:
        platform = str(account.get("platform") or "")
        if platform_set and platform not in platform_set:
            continue
        symbols = [str(item).upper() for item in account.get("symbols", []) if str(item).strip()] if isinstance(account.get("symbols"), list) else []
        if symbol and symbols and symbol not in symbols and "*" not in symbols:
            continue
        filtered.append(account)
    return sorted(filtered, key=lambda item: int(item.get("priority") or 100))[:50]


def _social_platform_name(value: Any) -> str:
    platform = str(value or "").strip().lower()
    if platform == "x":
        return "twitter"
    if platform == "xiaohongshu":
        return "xhs"
    if platform == "yt":
        return "youtube"
    if platform in {"xueqiu", "reddit", "xhs", "twitter", "youtube"}:
        return platform
    return ""


def _normalize_social_items(
    value: Any,
    *,
    accounts: list[dict[str, Any]],
    symbol: str,
    limit: int,
    clipped: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    allowed = {(str(row.get("platform") or ""), str(row.get("handle") or "").lower()) for row in accounts}
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        platform = _social_platform_name(row.get("platform") or row.get("source"))
        handle = str(row.get("account_id") or row.get("handle") or row.get("author_id") or row.get("author") or "").strip()
        if not platform or not handle or (platform, handle.lower()) not in allowed:
            continue
        symbols = [str(item).strip().upper() for item in row.get("symbols", []) if str(item).strip()] if isinstance(row.get("symbols"), list) else []
        text = str(row.get("text") or row.get("content") or row.get("summary") or row.get("body") or "").strip()
        if not text:
            continue
        if symbol and symbols and symbol not in symbols:
            continue
        item = {
            "platform": platform,
            "account_id": handle,
            "account_name": str(row.get("account_name") or row.get("display_name") or row.get("author_name") or row.get("author") or "").strip() or handle,
            "url": str(row.get("url") or row.get("link") or "").strip() or None,
            "published_at": str(row.get("published_at") or row.get("time") or row.get("created_at") or "").strip() or None,
            "text": _clip_social_text(text, clipped=clipped),
            "sentiment": str(row.get("sentiment") or row.get("tone") or "").strip() or _infer_social_sentiment(text),
            "symbols": symbols,
            "engagement": row.get("engagement") if isinstance(row.get("engagement"), dict) else {},
            "reference_only": True,
        }
        items.append(item)
        if len(items) >= limit:
            break
    return items


def _clip_social_text(text: str, *, clipped: dict[str, int] | None = None, max_chars: int | None = None) -> str:
    limit = max_chars or max(200, min(4000, int(os.getenv("HERMES_SOCIAL_TEXT_MAX_CHARS", "1000") or "1000")))
    if len(text) > limit and clipped is not None:
        clipped["count"] = int(clipped.get("count") or 0) + 1
    return text[:limit]


def _dedupe_social_items(items: list[dict[str, Any]], *, limit: int) -> tuple[list[dict[str, Any]], int]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    deduped = 0
    for item in items:
        platform = str(item.get("platform") or "")
        account_id = str(item.get("account_id") or "").lower()
        url = str(item.get("url") or "")
        text_hash = _hash_text(str(item.get("text") or "")[:300])[:16]
        key = (platform, account_id, url or text_hash)
        if key in seen:
            deduped += 1
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    overflow = max(0, len(items) - len(result) - deduped)
    return result, deduped + overflow


def _social_enabled_provider_names() -> list[str]:
    configured = _social_provider_filter(os.getenv("HERMES_SOCIAL_PROVIDERS", ""))
    return configured or ["twitter", "xhs", "youtube"]


def _social_provider_names_for_accounts(arguments: dict[str, Any], accounts: list[dict[str, Any]]) -> list[str]:
    requested = _social_provider_filter(arguments.get("providers") or arguments.get("platforms") or arguments.get("platform"))
    provider_names = requested or [str(account.get("platform") or "") for account in accounts]
    normalized: list[str] = []
    for provider in provider_names:
        provider = _social_platform_name(provider)
        if provider in {"twitter", "xhs", "youtube"} and provider not in normalized:
            normalized.append(provider)
    return normalized


def _social_timeout_seconds(arguments: dict[str, Any]) -> float:
    raw = arguments.get("timeout_seconds")
    if raw is None:
        raw = arguments.get("timeout_ms")
        if raw is not None:
            try:
                return max(1.0, min(120.0, float(raw) / 1000.0))
            except (TypeError, ValueError):
                pass
    if raw is None:
        raw = os.getenv("HERMES_SOCIAL_PROVIDER_TIMEOUT_SECONDS", "25")
    try:
        return max(1.0, min(120.0, float(raw)))
    except (TypeError, ValueError):
        return 25.0


def _social_timeline_data_quality(
    *,
    accounts: list[dict[str, Any]],
    items: list[dict[str, Any]],
    provider_attempts: list[dict[str, Any]],
    requested_limit: int,
    clipped_count: int,
    deduped_count: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    healthy_providers = [attempt.get("provider") for attempt in provider_attempts if attempt.get("ok")]
    configured_providers = [attempt.get("provider") for attempt in provider_attempts if attempt.get("configured")]
    if items:
        status = "available"
    elif configured_providers:
        status = "empty"
    elif accounts:
        status = "provider_not_configured"
    else:
        status = "watchlist_required"
    return {
        "status": status,
        "account_count": len(accounts),
        "item_count": len(items),
        "requested_limit": requested_limit,
        "providers_attempted_count": len(provider_attempts),
        "providers_configured_count": len(configured_providers),
        "providers_ok_count": len(healthy_providers),
        "healthy_providers": healthy_providers,
        "sample_clipped_count": clipped_count,
        "deduped_count": deduped_count,
        "limited_to_accounts": True,
        "global_search_enabled": False,
        "timeout_seconds": timeout_seconds,
    }


async def _read_social_provider(
    provider: str,
    *,
    accounts: list[dict[str, Any]],
    symbol: str,
    limit: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    health = await _social_provider_health(provider, timeout_seconds=min(timeout_seconds, 10.0))
    if not health.get("ok"):
        return {"items": [], "attempt": {**health, "items": 0}, "clipped_count": 0}
    await _social_provider_rate_limit(provider)
    if provider == "twitter":
        return await _read_twitter_accounts(accounts, symbol=symbol, limit=limit, timeout_seconds=timeout_seconds)
    if provider == "youtube":
        return await _read_youtube_accounts(accounts, symbol=symbol, limit=limit, timeout_seconds=timeout_seconds)
    if provider == "xhs":
        return await _read_xhs_accounts(accounts, symbol=symbol, limit=limit, timeout_seconds=timeout_seconds)
    return {
        "items": [],
        "attempt": {
            "provider": provider,
            "configured": False,
            "ok": False,
            "status": "unsupported_provider",
            "items": 0,
        },
        "clipped_count": 0,
    }


async def _social_provider_health(provider: str, *, timeout_seconds: float) -> dict[str, Any]:
    provider = _social_platform_name(provider)
    if provider == "twitter":
        result = await _run_social_command("twitter", ["status"], timeout_seconds=timeout_seconds)
        if result["ok"]:
            return {"provider": "twitter", "configured": True, "ok": True, "status": "ok", "setup_hint": None}
        if result.get("missing"):
            return {
                "provider": "twitter",
                "configured": False,
                "ok": False,
                "status": "twitter_cli_missing",
                "setup_hint": "告诉 Agent「帮我配 Twitter」以安装并登录 twitter-cli/OpenCLI。",
                "error": result.get("error"),
            }
        return {
            "provider": "twitter",
            "configured": False,
            "ok": False,
            "status": "twitter_auth_unhealthy",
            "setup_hint": "告诉 Agent「帮我配 Twitter」以检查 X/Twitter 登录状态。",
            "error": result.get("stderr") or result.get("error"),
        }
    if provider == "youtube":
        result = await _run_social_command("yt-dlp", ["--version"], timeout_seconds=timeout_seconds)
        return {
            "provider": "youtube",
            "configured": bool(result["ok"]),
            "ok": bool(result["ok"]),
            "status": "ok" if result["ok"] else ("yt_dlp_missing" if result.get("missing") else "yt_dlp_unhealthy"),
            "setup_hint": None if result["ok"] else "安装 yt-dlp 后，给 watchlist 账号配置 channel_url/url。",
            "error": None if result["ok"] else result.get("error") or result.get("stderr"),
        }
    if provider == "xhs":
        mcp_url = _xhs_mcp_url()
        if mcp_url:
            result = await _call_xhs_mcp_tool("check_login_status", {}, timeout_seconds=timeout_seconds)
            if result.get("ok") and _xhs_login_ok(result.get("data")):
                return {
                    "provider": "xhs",
                    "configured": True,
                    "ok": True,
                    "status": "ok",
                    "transport": "http_mcp",
                    "endpoint": mcp_url,
                    "setup_hint": None,
                }
            return {
                "provider": "xhs",
                "configured": bool(result.get("ok")),
                "ok": False,
                "status": "xhs_not_logged_in" if result.get("ok") else "xhs_mcp_unhealthy",
                "transport": "http_mcp",
                "endpoint": mcp_url,
                "setup_hint": "调用 xiaohongshu-mcp 的 get_login_qrcode 工具并扫码登录。",
                "error": None if result.get("ok") else result.get("error"),
            }
        result = await _run_social_command("mcporter", ["config", "list"], timeout_seconds=timeout_seconds)
        if result["ok"]:
            return {
                "provider": "xhs",
                "configured": True,
                "ok": True,
                "status": "ok",
                "setup_hint": "如未登录小红书，使用 xiaohongshu-mcp 的二维码登录能力扫码。",
            }
        return {
            "provider": "xhs",
            "configured": False,
            "ok": False,
            "status": "mcporter_or_xiaohongshu_mcp_missing",
            "setup_hint": "安装 autoclaw-cc/xiaohongshu-mcp-skills，并通过二维码登录小红书。",
            "error": result.get("error") or result.get("stderr"),
        }
    return {"provider": provider, "configured": False, "ok": False, "status": "unsupported_provider"}


async def _social_provider_rate_limit(provider: str) -> None:
    interval = float(os.getenv("HERMES_SOCIAL_PROVIDER_MIN_INTERVAL_SECONDS", "1.5") or "1.5")
    interval = max(0.0, min(30.0, interval))
    if interval <= 0:
        return
    key = _social_platform_name(provider)
    now = time.monotonic()
    last = _SOCIAL_PROVIDER_LAST_CALLS.get(key, 0.0)
    delay = interval - (now - last)
    if delay > 0:
        await asyncio.sleep(delay)
    _SOCIAL_PROVIDER_LAST_CALLS[key] = time.monotonic()


async def _run_social_command(command: str, args: list[str], *, timeout_seconds: float) -> dict[str, Any]:
    executable = _social_command_executable(command)
    if not executable:
        return {"ok": False, "missing": True, "error": f"{command} not found"}
    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return {"ok": False, "timeout": True, "error": f"{command} timed out after {timeout_seconds:.1f}s"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    return {
        "ok": process.returncode == 0,
        "returncode": process.returncode,
        "stdout": stdout_text,
        "stderr": stderr_text,
    }


def _social_command_executable(command: str) -> str | None:
    env_by_command = {
        "twitter": "HERMES_TWITTER_CLI_PATH",
        "yt-dlp": "HERMES_YTDLP_PATH",
        "mcporter": "HERMES_MCPORTER_PATH",
    }
    env_path = os.getenv(env_by_command.get(command, ""), "").strip()
    if env_path and Path(env_path).exists():
        return env_path
    executable = shutil.which(command)
    if executable:
        return executable
    for parent in [Path.cwd(), *Path(__file__).resolve().parents]:
        candidate = parent / ".venv-agent-reach" / "bin" / command
        if candidate.exists():
            return str(candidate)
    return None


async def _read_twitter_accounts(
    accounts: list[dict[str, Any]],
    *,
    symbol: str,
    limit: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    clipped = {"count": 0}
    errors: list[str] = []
    for account in accounts:
        handle = str(account.get("handle") or "").lstrip("@")
        if not handle:
            continue
        result = await _run_social_command(
            "twitter",
            ["user-posts", handle, "-n", str(max(1, min(20, limit))), "--json"],
            timeout_seconds=timeout_seconds,
        )
        if not result["ok"]:
            errors.append(result.get("stderr") or result.get("error") or f"twitter user-posts @{handle} failed")
            continue
        parsed = _parse_json_or_json_lines(result.get("stdout") or "")
        items.extend(_normalize_social_items(_twitter_rows_to_social_items(parsed, account), accounts=accounts, symbol=symbol, limit=limit, clipped=clipped))
        if len(items) >= limit:
            break
    return {
        "items": items[:limit],
        "clipped_count": clipped["count"],
        "attempt": {
            "provider": "twitter",
            "configured": True,
            "ok": bool(items),
            "status": "ok" if items else "empty_or_command_failed",
            "items": len(items[:limit]),
            "errors": errors[:3],
            "setup_hint": None if items else "告诉 Agent「帮我配 Twitter」以检查 X/Twitter 账号读取权限。",
        },
    }


async def _read_youtube_accounts(
    accounts: list[dict[str, Any]],
    *,
    symbol: str,
    limit: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    clipped = {"count": 0}
    errors: list[str] = []
    for account in accounts:
        url = str(account.get("channel_url") or account.get("url") or "").strip()
        if not url:
            errors.append(f"youtube account {account.get('handle')} missing channel_url")
            continue
        result = await _run_social_command(
            "yt-dlp",
            ["--dump-json", "--flat-playlist", "--playlist-end", str(max(1, min(20, limit))), url],
            timeout_seconds=timeout_seconds,
        )
        if not result["ok"]:
            errors.append(result.get("stderr") or result.get("error") or f"yt-dlp failed for {url}")
            continue
        parsed = _parse_json_or_json_lines(result.get("stdout") or "")
        items.extend(_normalize_social_items(_youtube_rows_to_social_items(parsed, account), accounts=accounts, symbol=symbol, limit=limit, clipped=clipped))
        if len(items) >= limit:
            break
    return {
        "items": items[:limit],
        "clipped_count": clipped["count"],
        "attempt": {
            "provider": "youtube",
            "configured": True,
            "ok": bool(items),
            "status": "ok" if items else "empty_or_command_failed",
            "items": len(items[:limit]),
            "errors": errors[:3],
        },
    }


async def _read_xhs_accounts(
    accounts: list[dict[str, Any]],
    *,
    symbol: str,
    limit: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    if _xhs_mcp_url():
        return await _read_xhs_accounts_via_http_mcp(accounts, symbol=symbol, limit=limit, timeout_seconds=timeout_seconds)

    items: list[dict[str, Any]] = []
    clipped = {"count": 0}
    errors: list[str] = []
    for account in accounts:
        user_id = str(account.get("user_id") or account.get("handle") or "").strip()
        if not user_id:
            continue
        expr = f"xiaohongshu.get_user_notes(user_id='{user_id}', limit={max(1, min(20, limit))})"
        result = await _run_social_command("mcporter", ["call", expr], timeout_seconds=timeout_seconds)
        if not result["ok"]:
            errors.append(result.get("stderr") or result.get("error") or f"xiaohongshu MCP user notes failed for {user_id}")
            continue
        parsed = _parse_json_or_json_lines(result.get("stdout") or "")
        items.extend(_normalize_social_items(_xhs_rows_to_social_items(parsed, account), accounts=accounts, symbol=symbol, limit=limit, clipped=clipped))
        if len(items) >= limit:
            break
    return {
        "items": items[:limit],
        "clipped_count": clipped["count"],
        "attempt": {
            "provider": "xhs",
            "configured": True,
            "ok": bool(items),
            "status": "ok" if items else "empty_or_mcp_tool_mismatch",
            "items": len(items[:limit]),
            "errors": errors[:3],
            "setup_hint": None if items else "确认 xiaohongshu-mcp 已扫码登录；若工具名不同，在账号 items 中直接注入样本或调整 MCP 调用表达式。",
        },
    }


async def _read_xhs_accounts_via_http_mcp(
    accounts: list[dict[str, Any]],
    *,
    symbol: str,
    limit: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    clipped = {"count": 0}
    errors: list[str] = []
    for account in accounts:
        user_id = str(account.get("user_id") or account.get("handle") or "").strip()
        xsec_token = str(account.get("xsec_token") or "").strip()
        if not user_id or not xsec_token:
            errors.append(f"xhs account {account.get('handle')} missing user_id or xsec_token")
            continue
        result = await _call_xhs_mcp_tool(
            "user_profile",
            {"user_id": user_id, "xsec_token": xsec_token},
            timeout_seconds=timeout_seconds,
        )
        if not result.get("ok"):
            errors.append(str(result.get("error") or f"xiaohongshu MCP user_profile failed for {user_id}"))
            continue
        rows = _xhs_profile_rows(result.get("data"))
        items.extend(_normalize_social_items(_xhs_rows_to_social_items(rows, account), accounts=accounts, symbol=symbol, limit=limit, clipped=clipped))
        if len(items) >= limit:
            break
    return {
        "items": items[:limit],
        "clipped_count": clipped["count"],
        "attempt": {
            "provider": "xhs",
            "configured": True,
            "ok": bool(items),
            "status": "ok" if items else "empty_or_missing_xsec_token",
            "items": len(items[:limit]),
            "errors": errors[:3],
            "setup_hint": None if items else "确认 xiaohongshu-mcp 已扫码登录，并在 watchlist 的小红书账号中配置 user_id 与 xsec_token。",
        },
    }


def _xhs_mcp_url() -> str:
    return os.getenv("HERMES_XHS_MCP_URL", "").strip().rstrip("/")


async def _call_xhs_mcp_tool(tool_name: str, arguments: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    url = _xhs_mcp_url()
    if not url:
        return {"ok": False, "error": "HERMES_XHS_MCP_URL not configured"}
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            init_response = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "hermes-data-service", "version": "0.1"},
                    },
                },
                headers=headers,
                timeout=timeout_seconds,
            )
            init_response.raise_for_status()
            session_id = init_response.headers.get("mcp-session-id") or init_response.headers.get("Mcp-Session-Id")
            call_headers = dict(headers)
            if session_id:
                call_headers["mcp-session-id"] = session_id
                await _send_xhs_mcp_initialized(client, url, call_headers, timeout_seconds=timeout_seconds)
            call_response = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                headers=call_headers,
                timeout=timeout_seconds,
            )
            call_response.raise_for_status()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    payload = _parse_mcp_http_payload(call_response.text)
    if isinstance(payload, dict) and payload.get("error"):
        return {"ok": False, "error": payload.get("error")}
    return {"ok": True, "data": _mcp_result_data(payload)}


async def _send_xhs_mcp_initialized(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    *,
    timeout_seconds: float,
) -> None:
    try:
        await client.post(
            url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=headers,
            timeout=min(5.0, timeout_seconds),
        )
    except Exception:
        return


def _parse_mcp_http_payload(text: str) -> Any:
    text = text.strip()
    if not text:
        return {}
    if text.startswith("event:") or text.startswith("data:"):
        payloads = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            raw = line.removeprefix("data:").strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                payloads.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        if payloads:
            return payloads[-1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


def _mcp_result_data(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list):
        text_parts = [str(item.get("text") or "").strip() for item in content if isinstance(item, dict) and str(item.get("text") or "").strip()]
        if text_parts:
            text = "\n".join(text_parts)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    return result


def _xhs_login_ok(data: Any) -> bool:
    if data is True:
        return True
    if not isinstance(data, dict):
        return False
    for key in ["is_logged_in", "isLogin", "logged_in", "login", "ok", "success"]:
        if data.get(key) is True:
            return True
    status = str(data.get("status") or data.get("message") or data.get("text") or "").lower()
    return "logged" in status or "已登录" in status or "登录成功" in status


def _xhs_profile_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ["notes", "items", "results"]:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        nested = data.get("data")
        if isinstance(nested, dict):
            for key in ["notes", "items", "results"]:
                value = nested.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _parse_json_or_json_lines(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    candidates: Any
    if isinstance(payload, dict):
        candidates = payload.get("items") or payload.get("data") or payload.get("results") or payload.get("notes") or payload
    else:
        candidates = payload
    if isinstance(candidates, dict):
        nested = candidates.get("items") or candidates.get("results") or candidates.get("notes")
        if isinstance(nested, list):
            candidates = nested
        else:
            candidates = [candidates]
    if isinstance(candidates, list):
        return [item for item in candidates if isinstance(item, dict)]
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _twitter_rows_to_social_items(rows: list[dict[str, Any]], account: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "platform": "twitter",
            "account_id": account.get("handle"),
            "account_name": account.get("display_name") or account.get("handle"),
            "url": row.get("url") or row.get("tweet_url") or row.get("link"),
            "published_at": row.get("created_at") or row.get("time") or row.get("published_at"),
            "text": row.get("text") or row.get("content") or row.get("full_text"),
            "engagement": row.get("engagement") if isinstance(row.get("engagement"), dict) else {},
        }
        for row in rows
    ]


def _youtube_rows_to_social_items(rows: list[dict[str, Any]], account: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "platform": "youtube",
            "account_id": account.get("handle"),
            "account_name": account.get("display_name") or account.get("handle"),
            "url": row.get("webpage_url") or row.get("url") or row.get("original_url"),
            "published_at": row.get("timestamp") or row.get("upload_date") or row.get("release_timestamp"),
            "text": " ".join(str(part or "").strip() for part in [row.get("title"), row.get("description")] if str(part or "").strip()),
            "engagement": {
                "view_count": row.get("view_count"),
                "like_count": row.get("like_count"),
                "comment_count": row.get("comment_count"),
            },
        }
        for row in rows
    ]


def _xhs_rows_to_social_items(rows: list[dict[str, Any]], account: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "platform": "xhs",
            "account_id": account.get("handle"),
            "account_name": account.get("display_name") or account.get("handle"),
            "url": row.get("url") or row.get("note_url") or row.get("share_url"),
            "published_at": row.get("time") or row.get("created_at") or row.get("publish_time"),
            "text": " ".join(str(part or "").strip() for part in [row.get("title"), row.get("desc") or row.get("content") or row.get("text")] if str(part or "").strip()),
            "engagement": row.get("engagement") if isinstance(row.get("engagement"), dict) else {},
        }
        for row in rows
    ]


def _build_social_snapshot(
    *,
    symbol: str,
    window: str,
    items: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    failed: dict[str, Any] | None,
    providers_attempted: list[dict[str, Any]] | None = None,
    data_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not items:
        reason = (failed or {}).get("reason") or ("social_source_not_configured" if accounts else "social_watchlist_required")
        return {
            "schema_version": "social_sentiment_snapshot_v1",
            "status": "not_configured",
            "reason": reason,
            "symbol": symbol or None,
            "window": window,
            "sentiment": {"label": "unknown", "score": None, "confidence": "low"},
            "summary": "未读取到有限账号清单中的社媒样本",
            "items": [],
            "accounts": accounts,
            "providers_attempted": providers_attempted or [],
            "data_quality": data_quality or {},
            "themes": [],
            "risk_flags": [],
        }
    score = _social_sentiment_score(items)
    label = "mixed"
    if score >= 0.25:
        label = "bullish"
    elif score <= -0.25:
        label = "bearish"
    themes = _social_themes_from_items(items)
    risk_flags = []
    if len(items) >= 5 and abs(score) >= 0.6:
        risk_flags.append({"type": "social_consensus", "severity": "watch", "description": "有限账号清单出现较一致的社媒情绪"})
    return {
        "schema_version": "social_sentiment_snapshot_v1",
        "status": "available",
        "reason": "finite_account_posts",
        "symbol": symbol or None,
        "window": window,
        "sample_count": len(items),
        "sentiment": {"label": label, "score": round(score, 3), "confidence": "medium" if len(items) >= 3 else "low"},
        "summary": f"已读取 {len(items)} 条有限账号清单社媒样本，整体情绪 {label}",
        "items": items,
        "accounts": accounts,
        "providers_attempted": providers_attempted or [],
        "data_quality": data_quality or {},
        "themes": themes,
        "risk_flags": risk_flags,
    }


def _infer_social_sentiment(text: str) -> str:
    lowered = text.lower()
    bullish = ("看多", "利好", "突破", "强劲", "增长", "bull", "bullish", "beat", "strong")
    bearish = ("看空", "利空", "下跌", "风险", "泡沫", "bear", "bearish", "miss", "weak")
    bull_count = sum(1 for keyword in bullish if keyword in lowered or keyword in text)
    bear_count = sum(1 for keyword in bearish if keyword in lowered or keyword in text)
    if bull_count > bear_count:
        return "bullish"
    if bear_count > bull_count:
        return "bearish"
    return "neutral"


def _social_sentiment_score(items: list[dict[str, Any]]) -> float:
    values = {"bullish": 1.0, "positive": 1.0, "bearish": -1.0, "negative": -1.0, "neutral": 0.0, "mixed": 0.0}
    scores = [values.get(str(item.get("sentiment") or "").lower(), 0.0) for item in items]
    return sum(scores) / len(scores) if scores else 0.0


def _social_themes_from_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = [
        ("财报/业绩", ("财报", "earnings", "业绩", "revenue", "guidance")),
        ("估值/风险", ("估值", "风险", "泡沫", "valuation", "risk")),
        ("需求/增长", ("需求", "增长", "订单", "demand", "growth")),
        ("产品/技术", ("产品", "芯片", "ai", "gpu", "launch", "roadmap")),
    ]
    themes: list[dict[str, Any]] = []
    for label, keywords in buckets:
        count = sum(1 for item in items if any(keyword in str(item.get("text") or "").lower() for keyword in keywords))
        if count:
            themes.append({"label": label, "stance": "unknown", "evidence_count": count})
    return themes[:5]


def _tool_result(tool: str, payload: dict[str, Any], *, source_refs: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "tool": tool,
        "ok": bool(payload.get("ok", True)),
        "status": "ok" if payload.get("ok", True) else "error",
        "data": payload.get("data", payload),
        "failed": payload.get("failed"),
        "source_refs": source_refs,
    }


def _with_sell_put_summary(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else data
    if isinstance(analysis, dict):
        ranking = analysis.get("candidate_ranking") or []
        payload = dict(payload)
        payload["summary"] = {
            "status": analysis.get("overall_actionability"),
            "top_candidate": ranking[0] if ranking else None,
            "candidate_count": len(ranking) if isinstance(ranking, list) else 0,
        }
    return payload
