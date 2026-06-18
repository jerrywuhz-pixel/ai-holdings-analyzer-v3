from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Callable

import httpx


HttpClientFactory = Callable[[], httpx.AsyncClient]


class DomainToolError(RuntimeError):
    pass


def domain_tool_manifest() -> list[dict[str, Any]]:
    return [
        {
            "name": "market.quote",
            "description": "Read one fresh or reference quote through data-service.",
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
            "description": "Read multiple quotes through data-service.",
            "input_schema": {
                "symbols": "string[]",
                "source": "optional string",
                "require_fresh": "optional boolean",
                "max_age_seconds": "optional integer",
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
    ]


class DomainToolsFacade:
    """Hermes-facing read-only domain tool facade.

    The facade keeps Hermes away from provider-specific credentials and raw
    connector details. It returns structured results with source metadata so
    the caller can cite or degrade outputs safely.
    """

    def __init__(
        self,
        *,
        data_service_url: str | None = None,
        ima_skill_dir: str | Path | None = None,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        self.data_service_url = (data_service_url or os.getenv("DATA_SERVICE_URL", "http://data-service:8000")).rstrip("/")
        self.ima_skill_dir = Path(ima_skill_dir or os.getenv("IMA_SKILL_DIR", "/app/openclaw/skills/ima-skill"))
        self.http_client_factory = http_client_factory or httpx.AsyncClient

    async def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "market.quote":
            return await self.market_quote(arguments)
        if tool_name == "market.batch_quote":
            return await self.market_batch_quote(arguments)
        if tool_name == "options.sell_put_rank":
            return await self.options_sell_put_rank(arguments)
        if tool_name == "broker.positions_read":
            return await self.broker_positions_read(arguments)
        if tool_name == "reference.ima.search":
            return await self.ima_search(arguments)
        if tool_name == "reference.ima.read":
            return await self.ima_read(arguments)
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
        return _tool_result("market.quote", payload, source_refs=[_source_ref("data-service", f"/api/quote/{symbol}")])

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
        return _tool_result("market.batch_quote", payload, source_refs=[_source_ref("data-service", "/api/quote/batch")])

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
                source_refs=[_source_ref("data-service", "/api/v3/options/sell-put/analyze-from-futu")],
            )

        payload = await self._post_json("/api/v3/options/sell-put/analyze", arguments)
        return _tool_result(
            "options.sell_put_rank",
            _with_sell_put_summary(payload),
            source_refs=[_source_ref("data-service", "/api/v3/options/sell-put/analyze")],
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
            return _tool_result("broker.positions_read", payload, source_refs=[_source_ref("data-service", "/api/v3/broker/futu/snapshot")])

        payload = await self._get_json("/api/v3/portfolio/positions", params={"tenant_id": tenant_id})
        return _tool_result("broker.positions_read", payload, source_refs=[_source_ref("data-service", "/api/v3/portfolio/positions")])

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


def _source_ref(source: str, ref: str) -> dict[str, str]:
    return {"source": source, "ref": ref}


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
        data = {
            **data,
            "summary": {
                "underlying_symbol": analysis.get("underlying_symbol"),
                "overall_actionability": analysis.get("overall_actionability"),
                "top_candidates": ranking[:5],
                "broker_snapshot_mode": analysis.get("broker_snapshot_mode"),
                "data_quality_note": analysis.get("data_quality_note"),
            },
        }
    return {**payload, "data": data}
