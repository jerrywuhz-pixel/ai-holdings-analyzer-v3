from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from services.hermes.reference_capture import WebReferencePersistence, summarize_web_reference
from services.hermes.stock_analysis import HermesStockAnalysisService, load_market_regime, load_sector_context


HttpClientFactory = Callable[[], httpx.AsyncClient]


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
            },
            "safety": "read_only_analysis_artifact",
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
        self.data_service_url = (data_service_url or os.getenv("DATA_SERVICE_URL", "http://127.0.0.1:8000")).rstrip("/")
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
        if tool_name == "reference.ima.search":
            return await self.ima_search(arguments)
        if tool_name == "reference.ima.read":
            return await self.ima_read(arguments)
        if tool_name == "reference.web.read":
            return await self.reference_web_read(arguments)
        if tool_name == "reference.web.search":
            return await self.reference_web_search(arguments)
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

        service = HermesStockAnalysisService(
            quote_reader=quote_reader,
            positions_reader=positions_reader,
            history_reader=history_reader,
            sector_context_reader=sector_context_reader,
            market_regime_reader=market_regime_reader,
            news_context_reader=news_context_reader,
        )
        result = await service.analyze(
            tenant_id=tenant_id,
            symbol=symbol,
            prompt=str(prompt) if prompt is not None else None,
            persist=persist,
            entry_surface=entry_surface,
        )
        return result.model_dump()

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
