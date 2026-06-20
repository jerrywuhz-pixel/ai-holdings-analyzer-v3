from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

MAX_REPORT_MODULE_CHARS = 200
ANALYSIS_CONTEXT_SCHEMA_VERSION = "stock_analysis_context_v2"

JsonDict = dict[str, Any]
AsyncJsonReader = Callable[[str], Awaitable[JsonDict]]
AsyncPositionsReader = Callable[[str], Awaitable[JsonDict]]
AsyncHistoryReader = Callable[[str, str], Awaitable[JsonDict]]
AsyncSectorContextReader = Callable[[str, str, str, Optional[str], Optional[str]], Awaitable[JsonDict]]
AsyncMarketRegimeReader = Callable[[str, str], Awaitable[JsonDict]]
AsyncNewsContextReader = Callable[[str, str, str, Optional[str], Optional[str]], Awaitable[JsonDict]]
AsyncSocialContextReader = Callable[[str, str, str, Optional[str], Optional[str]], Awaitable[JsonDict]]

CHINA_ADR_SYMBOLS = {
    "BABA",
    "JD",
    "PDD",
    "BIDU",
    "NIO",
    "XPEV",
    "LI",
    "TME",
    "BILI",
    "YMM",
    "BEKE",
    "FUTU",
    "TIGR",
}


@dataclass(frozen=True)
class StockAnalysisResult:
    tool: str
    ok: bool
    status: str
    data: JsonDict
    source_refs: list[dict[str, str]]

    def model_dump(self) -> JsonDict:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "status": self.status,
            "data": self.data,
            "source_refs": self.source_refs,
        }


class StockAnalysisPersistence:
    """Best-effort persistence for Hermes stock analysis artifacts.

    The runtime should remain useful when database credentials are unavailable
    or when a synthetic test tenant is used. Persistence failures are reported
    inside the tool payload instead of failing the user-facing analysis.
    """

    def __init__(self, client: Any | None = None, database_url: str = "") -> None:
        self._client = client
        self._database_url = database_url

    @classmethod
    def from_env(cls) -> "StockAnalysisPersistence":
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not url or not key:
            return cls(None, os.getenv("DATABASE_URL", "").strip())
        try:
            from supabase import create_client
        except ImportError:
            return cls(None, os.getenv("DATABASE_URL", "").strip())
        try:
            return cls(create_client(url, key))
        except Exception:
            return cls(None, os.getenv("DATABASE_URL", "").strip())

    async def save(
        self,
        *,
        tenant_id: str,
        symbol: str,
        analysis: JsonDict,
        context: JsonDict,
        entry_surface: str = "system",
        create_alert_drafts: bool = True,
    ) -> JsonDict:
        if self._client is None and not self._database_url:
            return {"status": "skipped", "reason": "persistence_not_configured"}
        if not _is_uuid(tenant_id):
            return {"status": "skipped", "reason": "tenant_id_is_not_uuid"}

        try:
            if self._database_url and self._client is None:
                return await asyncio.to_thread(
                    self._save_postgres_sync,
                    tenant_id=tenant_id,
                    symbol=symbol,
                    analysis=analysis,
                    context=context,
                    entry_surface=entry_surface,
                    create_alert_drafts=create_alert_drafts,
                )
            return await asyncio.to_thread(
                self._save_sync,
                tenant_id=tenant_id,
                symbol=symbol,
                analysis=analysis,
                context=context,
                entry_surface=entry_surface,
                create_alert_drafts=create_alert_drafts,
            )
        except Exception as exc:
            return {"status": "failed", "reason": str(exc)}

    def _save_sync(
        self,
        *,
        tenant_id: str,
        symbol: str,
        analysis: JsonDict,
        context: JsonDict,
        entry_surface: str,
        create_alert_drafts: bool,
    ) -> JsonDict:
        now = datetime.now(timezone.utc).isoformat()
        run_key = _run_key(symbol=symbol, analysis=analysis, entry_surface=entry_surface)
        actionability = analysis.get("actionability_cap") or "analysis_only"

        agent_run = _insert_one(
            self._client.table("agent_runs").insert(
                {
                    "tenant_id": tenant_id,
                    "trigger": "wechat_message" if entry_surface == "wechat" else "webapp_action" if entry_surface == "webapp" else "system_replay",
                    "entry_surface": entry_surface if entry_surface in {"wechat", "webapp", "system"} else "system",
                    "intent": "stock.analysis",
                    "complexity": "standard",
                    "risk_level": "low",
                    "runtime_target": "hermes",
                    "actionability_cap": actionability,
                    "status": "succeeded",
                    "page_context": {"symbol": symbol},
                    "input_refs": context.get("source_refs") or [],
                    "output_refs": [],
                    "idempotency_key": run_key,
                    "started_at": now,
                    "completed_at": now,
                }
            )
        )
        run_id = agent_run.get("id")

        run_contract = _insert_one(
            self._client.table("run_contracts").insert(
                {
                    "tenant_id": tenant_id,
                    "agent_run_id": run_id,
                    "contract_scope": "canonical",
                    "runtime_target": "hermes",
                    "policy_version": "stock-analysis-p1",
                    "policy_hash": "stock-analysis-p1:v1:modules<=200chars",
                    "tool_policy": {"tools": ["market.quote", "broker.positions_read", "stock.analysis"]},
                    "data_scope": {"tenant_id": tenant_id, "symbol": symbol},
                    "contract_payload": {"report_module_max_chars": MAX_REPORT_MODULE_CHARS},
                }
            )
        )
        contract_id = run_contract.get("id")

        context_pack = _insert_one(
            self._client.table("context_packs").insert(
                {
                    "tenant_id": tenant_id,
                    "agent_run_id": run_id,
                    "run_contract_id": contract_id,
                    "pack_kind": "data_snapshot",
                    "pack_key": f"stock-analysis-context:{symbol}:{run_id}",
                    "manifest": context,
                    "payload_hash": _sha256_json(context),
                }
            )
        )

        artifact = _insert_one(
            self._client.table("artifact_registry").insert(
                {
                    "tenant_id": tenant_id,
                    "source_run_id": run_id,
                    "run_contract_id": contract_id,
                    "artifact_key": f"stock-analysis:{symbol}:{run_id}",
                    "artifact_type": "stock_analysis_report",
                    "artifact_status": "ready",
                    "visibility": "tenant",
                    "storage_backend": "inline_metadata",
                    "storage_path": f"inline://stock-analysis/{run_id}.json",
                    "mime_type": "application/json",
                    "content_hash": _sha256_json(analysis),
                    "source_lineage": context.get("source_refs") or [],
                    "artifact_metadata": {
                        "schema_version": "stock_analysis_p1",
                        "report": analysis.get("report"),
                        "short_reply": analysis.get("short_reply"),
                        "quality_display": analysis.get("quality_display"),
                        "context_pack_id": context_pack.get("id"),
                        "module_max_chars": MAX_REPORT_MODULE_CHARS,
                    },
                }
            )
        )

        signal = _insert_one(
            self._client.table("decision_signals").insert(
                {
                    "tenant_id": tenant_id,
                    "source_run_id": run_id,
                    "source_artifact_id": artifact.get("id"),
                    "symbol": symbol,
                    "name": analysis.get("name"),
                    "market": analysis.get("market") or "US",
                    "source_type": "stock_analysis",
                    "source_agent": "hermes_stock_analysis",
                    "action": analysis.get("action") or "watch",
                    "action_label": analysis.get("action_label"),
                    "actionability_cap": actionability,
                    "confidence_score": analysis.get("confidence_score"),
                    "score": analysis.get("score"),
                    "horizon": "1d",
                    "watch_conditions": analysis.get("watch_conditions") or [],
                    "reason": {"conclusion": analysis.get("report", {}).get("conclusion")},
                    "risk_summary": {"items": analysis.get("risk_flags") or []},
                    "evidence": context.get("source_refs") or [],
                    "data_quality_summary": _analysis_data_quality_summary(analysis),
                    "plan_quality": "minimal",
                    "status": "active",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
                    "metadata": {"report_module_max_chars": MAX_REPORT_MODULE_CHARS},
                }
            )
        )

        discipline_check = _insert_one(
            self._client.table("discipline_checks").insert(
                _discipline_check_payload(
                    tenant_id=tenant_id,
                    agent_run_id=run_id,
                    symbol=symbol,
                    analysis=analysis,
                    source_artifact_id=artifact.get("id"),
                    decision_signal_id=signal.get("id"),
                )
            )
        )

        follow_item_id: str | None = None
        try:
            follow_item = self._sync_follow_item_sync(
                tenant_id=tenant_id,
                symbol=symbol,
                analysis=analysis,
                context=context,
                source_run_id=run_id,
                source_artifact_id=artifact.get("id"),
                decision_signal_id=signal.get("id"),
            )
            follow_item_id = str(follow_item.get("id")) if follow_item.get("id") else None
        except Exception:
            follow_item_id = None

        alert_ids: list[str] = []
        if create_alert_drafts:
            for alert_payload in _analysis_alert_payloads(
                tenant_id=tenant_id,
                symbol=symbol,
                analysis=analysis,
                decision_signal_id=signal.get("id"),
            ):
                alert = _insert_one(
                    self._client.table("alert_rules").insert(alert_payload)
                )
                if alert.get("id"):
                    alert_ids.append(str(alert["id"]))

        return {
            "status": "saved",
            "agent_run_id": run_id,
            "run_contract_id": contract_id,
            "context_pack_id": context_pack.get("id"),
            "artifact_id": artifact.get("id"),
            "decision_signal_id": signal.get("id"),
            "discipline_check_id": discipline_check.get("id"),
            "follow_view_item_id": follow_item_id,
            "alert_rule_ids": alert_ids,
        }

    def _sync_follow_item_sync(
        self,
        *,
        tenant_id: str,
        symbol: str,
        analysis: JsonDict,
        context: JsonDict,
        source_run_id: str | None,
        source_artifact_id: str | None,
        decision_signal_id: str | None,
    ) -> JsonDict:
        view = _insert_one(
            self._client.table("follow_views").upsert(
                {
                    "tenant_id": tenant_id,
                    "name": "关注清单",
                    "slug": "default-follow",
                    "strategy_focus": "watchlist",
                    "base_currency": "USD",
                    "is_default": True,
                    "settings": {"source": "hermes_stock_analysis"},
                },
                on_conflict="tenant_id,slug",
            )
        )
        follow_view_id = view.get("id")
        if not follow_view_id:
            existing = (
                self._client.table("follow_views")
                .select("id")
                .eq("tenant_id", tenant_id)
                .eq("slug", "default-follow")
                .limit(1)
                .execute()
            )
            rows = getattr(existing, "data", None) or []
            follow_view_id = rows[0].get("id") if rows else None
        if not follow_view_id:
            return {}

        payload = _follow_item_payload(
            tenant_id=tenant_id,
            follow_view_id=str(follow_view_id),
            symbol=symbol,
            analysis=analysis,
            context=context,
            source_run_id=source_run_id,
            source_artifact_id=source_artifact_id,
            decision_signal_id=decision_signal_id,
        )
        return _insert_one(
            self._client.table("follow_view_items").upsert(
                payload,
                on_conflict="follow_view_id,symbol,market",
            )
        )

    def _save_postgres_sync(
        self,
        *,
        tenant_id: str,
        symbol: str,
        analysis: JsonDict,
        context: JsonDict,
        entry_surface: str,
        create_alert_drafts: bool,
    ) -> JsonDict:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            return {"status": "skipped", "reason": f"psycopg_not_installed: {exc}"}

        now = datetime.now(timezone.utc)
        actionability = analysis.get("actionability_cap") or "analysis_only"
        trigger = "wechat_message" if entry_surface == "wechat" else "webapp_action" if entry_surface == "webapp" else "system_replay"
        normalized_surface = entry_surface if entry_surface in {"wechat", "webapp", "system"} else "system"
        run_key = _run_key(symbol=symbol, analysis=analysis, entry_surface=normalized_surface)

        with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                agent_run = _fetch_one(
                    cur.execute(
                        """
                        INSERT INTO public.agent_runs (
                          tenant_id, trigger, entry_surface, intent, complexity,
                          risk_level, runtime_target, actionability_cap, status,
                          page_context, input_refs, output_refs, idempotency_key,
                          started_at, completed_at
                        )
                        VALUES (
                          %(tenant_id)s, %(trigger)s, %(entry_surface)s, 'stock.analysis', 'standard',
                          'low', 'hermes', %(actionability)s, 'succeeded',
                          %(page_context)s, %(input_refs)s, %(output_refs)s, %(idempotency_key)s,
                          %(started_at)s, %(completed_at)s
                        )
                        RETURNING id
                        """,
                        {
                            "tenant_id": tenant_id,
                            "trigger": trigger,
                            "entry_surface": normalized_surface,
                            "actionability": actionability,
                            "page_context": Jsonb({"symbol": symbol}),
                            "input_refs": Jsonb(context.get("source_refs") or []),
                            "output_refs": Jsonb([]),
                            "idempotency_key": run_key,
                            "started_at": now,
                            "completed_at": now,
                        },
                    )
                )
                run_id = agent_run.get("id")

                run_contract = _fetch_one(
                    cur.execute(
                        """
                        INSERT INTO public.run_contracts (
                          tenant_id, agent_run_id, contract_scope, runtime_target,
                          policy_version, policy_hash, tool_policy, data_scope, contract_payload
                        )
                        VALUES (
                          %(tenant_id)s, %(agent_run_id)s, 'canonical', 'hermes',
                          'stock-analysis-p1', 'stock-analysis-p1:v1:modules<=200chars',
                          %(tool_policy)s, %(data_scope)s, %(contract_payload)s
                        )
                        RETURNING id
                        """,
                        {
                            "tenant_id": tenant_id,
                            "agent_run_id": run_id,
                            "tool_policy": Jsonb({"tools": ["market.quote", "broker.positions_read", "stock.analysis"]}),
                            "data_scope": Jsonb({"tenant_id": tenant_id, "symbol": symbol}),
                            "contract_payload": Jsonb({"report_module_max_chars": MAX_REPORT_MODULE_CHARS}),
                        },
                    )
                )
                contract_id = run_contract.get("id")

                context_pack = _fetch_one(
                    cur.execute(
                        """
                        INSERT INTO public.context_packs (
                          tenant_id, agent_run_id, run_contract_id, pack_kind,
                          pack_key, manifest, payload_hash
                        )
                        VALUES (
                          %(tenant_id)s, %(agent_run_id)s, %(run_contract_id)s, 'data_snapshot',
                          %(pack_key)s, %(manifest)s, %(payload_hash)s
                        )
                        RETURNING id
                        """,
                        {
                            "tenant_id": tenant_id,
                            "agent_run_id": run_id,
                            "run_contract_id": contract_id,
                            "pack_key": f"stock-analysis-context:{symbol}:{run_id}",
                            "manifest": Jsonb(context),
                            "payload_hash": _sha256_json(context),
                        },
                    )
                )

                artifact = _fetch_one(
                    cur.execute(
                        """
                        INSERT INTO public.artifact_registry (
                          tenant_id, source_run_id, run_contract_id, artifact_key,
                          artifact_type, artifact_status, visibility, storage_backend,
                          storage_path, mime_type, content_hash, source_lineage, artifact_metadata
                        )
                        VALUES (
                          %(tenant_id)s, %(source_run_id)s, %(run_contract_id)s, %(artifact_key)s,
                          'stock_analysis_report', 'ready', 'tenant', 'inline_metadata',
                          %(storage_path)s, 'application/json', %(content_hash)s, %(source_lineage)s, %(artifact_metadata)s
                        )
                        RETURNING id
                        """,
                        {
                            "tenant_id": tenant_id,
                            "source_run_id": run_id,
                            "run_contract_id": contract_id,
                            "artifact_key": f"stock-analysis:{symbol}:{run_id}",
                            "storage_path": f"inline://stock-analysis/{run_id}.json",
                            "content_hash": _sha256_json(analysis),
                            "source_lineage": Jsonb(context.get("source_refs") or []),
                            "artifact_metadata": Jsonb(
                                {
                                    "schema_version": "stock_analysis_p1",
                                    "report": analysis.get("report"),
                                    "short_reply": analysis.get("short_reply"),
                                    "quality_display": analysis.get("quality_display"),
                                    "context_pack_id": str(context_pack.get("id")) if context_pack.get("id") else None,
                                    "module_max_chars": MAX_REPORT_MODULE_CHARS,
                                }
                            ),
                        },
                    )
                )

                signal = _fetch_one(
                    cur.execute(
                        """
                        INSERT INTO public.decision_signals (
                          tenant_id, source_run_id, source_artifact_id, symbol, name,
                          market, source_type, source_agent, action, action_label,
                          actionability_cap, confidence_score, score, horizon,
                          watch_conditions, reason, risk_summary, evidence,
                          data_quality_summary, plan_quality, status, expires_at, metadata
                        )
                        VALUES (
                          %(tenant_id)s, %(source_run_id)s, %(source_artifact_id)s, %(symbol)s, %(name)s,
                          %(market)s, 'stock_analysis', 'hermes_stock_analysis', %(action)s, %(action_label)s,
                          %(actionability)s, %(confidence_score)s, %(score)s, '1d',
                          %(watch_conditions)s, %(reason)s, %(risk_summary)s, %(evidence)s,
                          %(data_quality_summary)s, 'minimal', 'active', %(expires_at)s, %(metadata)s
                        )
                        RETURNING id
                        """,
                        {
                            "tenant_id": tenant_id,
                            "source_run_id": run_id,
                            "source_artifact_id": artifact.get("id"),
                            "symbol": symbol,
                            "name": analysis.get("name"),
                            "market": analysis.get("market") or "US",
                            "action": analysis.get("action") or "watch",
                            "action_label": analysis.get("action_label"),
                            "actionability": actionability,
                            "confidence_score": analysis.get("confidence_score"),
                            "score": analysis.get("score"),
                            "watch_conditions": Jsonb(analysis.get("watch_conditions") or []),
                            "reason": Jsonb({"conclusion": analysis.get("report", {}).get("conclusion")}),
                            "risk_summary": Jsonb({"items": analysis.get("risk_flags") or []}),
                            "evidence": Jsonb(context.get("source_refs") or []),
                            "data_quality_summary": Jsonb(_analysis_data_quality_summary(analysis)),
                            "expires_at": datetime.now(timezone.utc) + timedelta(days=3),
                            "metadata": Jsonb({"report_module_max_chars": MAX_REPORT_MODULE_CHARS}),
                        },
                    )
                )

                discipline_payload = _discipline_check_payload(
                    tenant_id=tenant_id,
                    agent_run_id=run_id,
                    symbol=symbol,
                    analysis=analysis,
                    source_artifact_id=artifact.get("id"),
                    decision_signal_id=signal.get("id"),
                )
                discipline_check = _fetch_one(
                    cur.execute(
                        """
                        INSERT INTO public.discipline_checks (
                          tenant_id, agent_run_id, symbol, instrument_type, action_type,
                          result, triggered_rule_ids, highest_action, check_payload
                        )
                        VALUES (
                          %(tenant_id)s, %(agent_run_id)s, %(symbol)s, %(instrument_type)s, %(action_type)s,
                          %(result)s, %(triggered_rule_ids)s, %(highest_action)s, %(check_payload)s
                        )
                        RETURNING id
                        """,
                        {
                            **discipline_payload,
                            "triggered_rule_ids": [UUID(rule_id) for rule_id in discipline_payload.get("triggered_rule_ids") or []],
                            "check_payload": Jsonb(discipline_payload.get("check_payload") or {}),
                        },
                    )
                )

                follow_item_id: str | None = None
                try:
                    follow_item = _sync_follow_item_postgres(
                        cur=cur,
                        tenant_id=tenant_id,
                        symbol=symbol,
                        analysis=analysis,
                        context=context,
                        source_run_id=run_id,
                        source_artifact_id=artifact.get("id"),
                        decision_signal_id=signal.get("id"),
                    )
                    follow_item_id = str(follow_item.get("id")) if follow_item.get("id") else None
                except Exception:
                    follow_item_id = None

                alert_ids: list[str] = []
                if create_alert_drafts:
                    for alert_payload in _analysis_alert_payloads(
                        tenant_id=tenant_id,
                        symbol=symbol,
                        analysis=analysis,
                        decision_signal_id=signal.get("id"),
                    ):
                        alert = _fetch_one(
                            cur.execute(
                                """
                                INSERT INTO public.alert_rules (
                                  tenant_id, decision_signal_id, name, target_scope, target_symbol,
                                  market, alert_type, parameters, severity, enabled,
                                  cooldown_policy, notification_policy, source, expires_at
                                )
                                VALUES (
                                  %(tenant_id)s, %(decision_signal_id)s, %(name)s, %(target_scope)s, %(target_symbol)s,
                                  %(market)s, %(alert_type)s, %(parameters)s, %(severity)s, %(enabled)s,
                                  %(cooldown_policy)s, %(notification_policy)s, %(source)s, %(expires_at)s
                                )
                                RETURNING id
                                """,
                                {
                                    **alert_payload,
                                    "parameters": Jsonb(alert_payload.get("parameters") or {}),
                                    "cooldown_policy": Jsonb(alert_payload.get("cooldown_policy") or {}),
                                    "notification_policy": Jsonb(alert_payload.get("notification_policy") or {}),
                                },
                            )
                        )
                        if alert.get("id"):
                            alert_ids.append(str(alert["id"]))

            conn.commit()

        return {
            "status": "saved",
            "backend": "postgres",
            "agent_run_id": str(run_id) if run_id else None,
            "run_contract_id": str(contract_id) if contract_id else None,
            "context_pack_id": str(context_pack.get("id")) if context_pack.get("id") else None,
            "artifact_id": str(artifact.get("id")) if artifact.get("id") else None,
            "decision_signal_id": str(signal.get("id")) if signal.get("id") else None,
            "discipline_check_id": str(discipline_check.get("id")) if discipline_check.get("id") else None,
            "follow_view_item_id": follow_item_id,
            "alert_rule_ids": alert_ids,
        }


class HermesStockAnalysisService:
    def __init__(
        self,
        *,
        quote_reader: AsyncJsonReader,
        positions_reader: AsyncPositionsReader,
        history_reader: AsyncHistoryReader | None = None,
        sector_context_reader: AsyncSectorContextReader | None = None,
        market_regime_reader: AsyncMarketRegimeReader | None = None,
        news_context_reader: AsyncNewsContextReader | None = None,
        social_context_reader: AsyncSocialContextReader | None = None,
        persistence: StockAnalysisPersistence | None = None,
    ) -> None:
        self._quote_reader = quote_reader
        self._positions_reader = positions_reader
        self._history_reader = history_reader
        self._sector_context_reader = sector_context_reader
        self._market_regime_reader = market_regime_reader
        self._news_context_reader = news_context_reader
        self._social_context_reader = social_context_reader
        self._persistence = persistence or StockAnalysisPersistence.from_env()

    async def analyze(
        self,
        *,
        tenant_id: str,
        symbol: str,
        prompt: str | None = None,
        persist: bool = True,
        entry_surface: str = "system",
    ) -> StockAnalysisResult:
        normalized_symbol = _normalize_symbol(symbol)
        quote_payload = await _safe_call(self._quote_reader, normalized_symbol)
        quote = _payload_data(quote_payload)
        positions_payload = await _safe_call(self._positions_reader, tenant_id)
        positions = _payload_data(positions_payload)
        market = _market_from_quote_or_symbol(quote, normalized_symbol)
        history_payload: JsonDict = {}
        if self._history_reader is not None:
            history_payload = await _safe_call(self._history_reader, normalized_symbol, market)

        held = _find_position(normalized_symbol, positions)
        sector = _first_text(quote, "sector", "industry_sector") or _first_text(held or {}, "sector")
        industry = _first_text(quote, "industry", "industry_name") or _first_text(held or {}, "industry")
        sector_context_payload: JsonDict = {}
        if self._sector_context_reader is not None:
            sector_context_payload = await _safe_call(
                self._sector_context_reader,
                tenant_id,
                normalized_symbol,
                market,
                sector,
                industry,
            )
        market_regime_payload: JsonDict = {}
        if self._market_regime_reader is not None:
            market_regime_payload = await _safe_call(self._market_regime_reader, tenant_id, market)
        news_context_payload: JsonDict = {}
        if self._news_context_reader is not None:
            news_context_payload = await _safe_call(
                self._news_context_reader,
                tenant_id,
                normalized_symbol,
                market,
                sector,
                industry,
            )
        social_context_payload: JsonDict = {}
        if self._social_context_reader is not None:
            social_context_payload = await _safe_call(
                self._social_context_reader,
                tenant_id,
                normalized_symbol,
                market,
                sector,
                industry,
            )
        enrichment = await _load_context_enrichment(
            tenant_id=tenant_id,
            symbol=normalized_symbol,
            market=market,
            quote=quote,
            held_position=held,
            sector_context_payload=sector_context_payload,
            market_regime_payload=market_regime_payload,
            news_context_payload=news_context_payload,
            social_context_payload=social_context_payload,
        )
        context = _build_context(
            tenant_id=tenant_id,
            symbol=normalized_symbol,
            prompt=prompt,
            quote_payload=quote_payload,
            positions_payload=positions_payload,
            history_payload=history_payload,
            held_position=held,
            market=market,
            enrichment=enrichment,
        )
        analysis = _build_analysis(
            symbol=normalized_symbol,
            market=market,
            quote=quote,
            positions=positions,
            held_position=held,
            history_payload=history_payload,
            prompt=prompt,
            context=context,
        )

        persistence_result = {"status": "skipped", "reason": "persist_false"}
        if persist:
            persistence_result = await self._persistence.save(
                tenant_id=tenant_id,
                symbol=normalized_symbol,
                analysis=analysis,
                context=context,
                entry_surface=entry_surface,
            )
        analysis["persistence"] = persistence_result

        return StockAnalysisResult(
            tool="stock.analysis",
            ok=True,
            status="ok",
            data=analysis,
            source_refs=context["source_refs"],
        )


def _build_analysis(
    *,
    symbol: str,
    market: str,
    quote: JsonDict,
    positions: JsonDict,
    held_position: JsonDict | None,
    history_payload: JsonDict,
    prompt: str | None,
    context: JsonDict | None = None,
) -> JsonDict:
    price = _first_number(quote, "price", "last_price", "current_price", "close")
    name = str(quote.get("name") or quote.get("stock_name") or (held_position or {}).get("name") or symbol)
    currency = str(quote.get("currency") or (held_position or {}).get("currency") or "")
    source = str(quote.get("source") or "unknown")
    quote_actionability = str(quote.get("quote_actionability") or "analysis_only")
    freshness_seconds = quote.get("freshness_seconds")
    quote_as_of = _first_temporal_text(quote, "as_of", "received_at", "updated_at", "timestamp", "quote_time", "last_updated", "last_trade_time")
    sector = _first_text(quote, "sector", "industry_sector") or _first_text(held_position or {}, "sector")
    industry = _first_text(quote, "industry", "industry_name") or _first_text(held_position or {}, "industry")
    next_earnings = _first_text(quote, "next_earnings_date", "earnings_date", "earnings_at")
    trend = _history_trend(history_payload)
    context = context or {}
    rules_context = context.get("rules_context") if isinstance(context.get("rules_context"), dict) else {}
    sector_context = context.get("sector_context") if isinstance(context.get("sector_context"), dict) else {}
    market_regime = context.get("market_regime") if isinstance(context.get("market_regime"), dict) else {}
    historical_decisions = context.get("historical_decisions") if isinstance(context.get("historical_decisions"), dict) else {}
    news_context = context.get("news_context") if isinstance(context.get("news_context"), dict) else _empty_news_context()
    social_context = context.get("social_context") if isinstance(context.get("social_context"), dict) else _empty_social_context()
    active_rules = rules_context.get("active_rules") if isinstance(rules_context.get("active_rules"), list) else []
    trading_rules = rules_context.get("trading_rules") if isinstance(rules_context.get("trading_rules"), list) else []
    previous_signals = historical_decisions.get("items") if isinstance(historical_decisions.get("items"), list) else []
    news_items = news_context.get("items") if isinstance(news_context.get("items"), list) else []
    catalysts = news_context.get("catalysts") if isinstance(news_context.get("catalysts"), list) else []
    social_items = social_context.get("items") if isinstance(social_context.get("items"), list) else []
    social_accounts = social_context.get("accounts") if isinstance(social_context.get("accounts"), list) else []
    pnl_pct = _first_number(held_position or {}, "unrealized_pnl_pct", "pnl_percent")
    quantity = _first_number(held_position or {}, "quantity", "shares")
    average_cost = _first_number(held_position or {}, "average_cost", "avg_buy_price")

    risk_flags: list[str] = []
    if not quote:
        risk_flags.append("行情不可用，不能形成可执行建议")
    if quote_actionability not in {"trade_draft", "analysis_only"}:
        risk_flags.append("行情新鲜度不足，建议只观察")
    if held_position and pnl_pct is not None and pnl_pct <= -10:
        risk_flags.append("持仓浮亏超过 10%，需要复核止损或 thesis")
    if held_position and pnl_pct is not None and pnl_pct >= 20:
        risk_flags.append("持仓浮盈超过 20%，需要复核止盈计划")
    if _positions_total(positions) == 0:
        risk_flags.append("未读到组合上下文，仓位和集中度无法判断")
    if next_earnings:
        risk_flags.append(f"存在财报/事件窗口：{next_earnings}")
    if catalysts:
        catalyst_label = _first_text(catalysts[0], "label", "title", "event_type") if isinstance(catalysts[0], dict) else None
        if catalyst_label:
            risk_flags.append(f"近期催化剂：{catalyst_label}")
    if active_rules:
        risk_flags.append(f"已有 {len(active_rules)} 条观察/纪律规则，需要避免重复承诺")
    if market_regime.get("regime") == "risk_off":
        risk_flags.append("市场状态偏 risk_off，建议降低追高和杠杆动作")
    for flag in social_context.get("risk_flags") or []:
        if isinstance(flag, dict):
            label = _first_text(flag, "description", "label", "type")
            if label:
                risk_flags.append(f"社媒信号：{label}")

    action = "watch"
    action_label = "观察"
    actionability = "analysis_only"
    score = 55
    if not quote:
        action = "data_blocked"
        action_label = "数据阻断"
        actionability = "blocked"
        score = 30
    elif held_position:
        action = "review_position"
        action_label = "复核持仓"
        score = 60
        if pnl_pct is not None and pnl_pct >= 20:
            action = "review_take_profit"
            action_label = "复核止盈"
            score = 68
        elif pnl_pct is not None and pnl_pct <= -10:
            action = "review_risk"
            action_label = "复核风险"
            score = 42

    watch_conditions = _watch_conditions(price=price, held_position=held_position, pnl_pct=pnl_pct)
    discipline_result = _evaluate_discipline(
        symbol=symbol,
        market=market,
        prompt=prompt,
        quote=quote,
        positions=positions,
        held_position=held_position,
        context=context,
        candidate_action=action,
        candidate_actionability=actionability,
    )
    cap = discipline_result.get("actionability_cap") or "analysis_only"
    if cap == "blocked":
        actionability = "blocked"
        if action != "data_blocked":
            action = "discipline_blocked"
            action_label = "纪律阻断"
            score = min(score, 35)
    elif cap == "analysis_only":
        actionability = "analysis_only"
    history_compare = _historical_decision_compare(
        current_action=action,
        current_action_label=action_label,
        current_score=score,
        current_watch_conditions=watch_conditions,
        previous_signals=previous_signals,
    )
    if history_compare.get("status") == "changed":
        risk_flags.append(f"结论较上次发生变化：{history_compare.get('action_change')}")
    if history_compare.get("repeated_watch_conditions_count"):
        risk_flags.append(f"有 {history_compare['repeated_watch_conditions_count']} 条观察条件与历史重复，需复核是否已失效")
    for violation in discipline_result.get("violations") or []:
        message = violation.get("message") if isinstance(violation, dict) else None
        if message:
            risk_flags.append(str(message))
    why_changed = _why_changed_summary(
        history_compare=history_compare,
        news_context=news_context,
        social_context=social_context,
        market_regime=market_regime,
        sector_context=sector_context,
        trend=trend,
    )
    data_quality = {
        "quote_source": source,
        "quote_actionability": quote_actionability,
        "quote_as_of": quote_as_of,
        "freshness_seconds": freshness_seconds,
        "history_status": _history_status(history_payload),
        "portfolio_context": "available" if held_position else "not_held_or_unavailable",
        "sector": sector,
        "industry": industry,
        "trend": trend,
        "next_earnings": next_earnings,
        "context_schema_version": context.get("schema_version") or ANALYSIS_CONTEXT_SCHEMA_VERSION,
        "active_rules_count": len(active_rules),
        "trading_rules_count": len(trading_rules),
        "previous_decisions_count": len(previous_signals),
        "sector_context_status": sector_context.get("status") or "missing",
        "market_regime_status": market_regime.get("status") or "missing",
        "market_regime": market_regime.get("regime"),
        "discipline_status": discipline_result.get("status"),
        "discipline_actionability_cap": discipline_result.get("actionability_cap"),
        "news_status": news_context.get("status") or "missing",
        "news_items_count": len(news_items),
        "catalysts_count": len(catalysts),
        "social_status": social_context.get("status") or "missing",
        "social_items_count": len(social_items),
        "social_accounts_count": len(social_accounts),
        "social_providers_attempted": social_context.get("providers_attempted") if isinstance(social_context.get("providers_attempted"), list) else [],
        "social_data_quality": social_context.get("data_quality") if isinstance(social_context.get("data_quality"), dict) else {},
        "why_changed_status": why_changed.get("status"),
    }
    quality_display = _stock_quality_display(
        source=source,
        as_of=quote_as_of,
        freshness_seconds=freshness_seconds,
        quote_actionability=quote_actionability,
        actionability=actionability,
        has_quote=bool(quote),
        has_positions_context=_positions_total(positions) > 0,
        has_held_position=bool(held_position),
        context_data_quality=context.get("data_quality") if isinstance(context.get("data_quality"), dict) else {},
    )
    review_due_at = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    report = {
        "conclusion": _clip_module(
            f"{name}（{symbol}）当前结论：{action_label}。"
            f"{'已读取持仓上下文，重点看仓位、成本和纪律。' if held_position else '当前未匹配到持仓，适合作为观察/关注清单候选。'}"
        ),
        "position": _clip_module(
            _position_module(held_position=held_position, quantity=quantity, average_cost=average_cost, pnl_pct=pnl_pct, currency=currency)
        ),
        "market": _clip_module(
            f"最新价 {price if price is not None else '不可用'} {currency}，数据源 {source}。"
            f"市场：{_market_regime_text(market_regime)}；行业/板块：{_sector_context_text(sector, industry, sector_context)}；趋势：{_trend_text(trend)}。"
        ),
        "history_compare": _clip_module(_history_compare_text(history_compare)),
        "events": _clip_module(_news_context_text(news_context)),
        "social": _clip_module(_social_context_text(social_context)),
        "why_changed": _clip_module(_why_changed_text(why_changed)),
        "risk": _clip_module("；".join(risk_flags) if risk_flags else "暂未发现硬性阻断，但仍需结合财报、事件窗口和组合集中度复核。"),
        "discipline": _clip_module(_discipline_text(discipline_result)),
        "next_steps": _clip_module("；".join(watch_conditions[:3]) if watch_conditions else "可回复“加入关注 {symbol}”或“设置提醒 {symbol} 价格”。"),
    }
    short_reply = (
        f"{report['conclusion']}\n"
        f"数据质量：{quality_display['summary']}。\n"
        f"行动等级：{actionability} / {action_label}。\n"
        f"变化解释：{report['why_changed']}\n"
        f"下一步：{report['next_steps']}"
    )
    return {
        "schema_version": "stock_analysis_p1",
        "symbol": symbol,
        "name": name,
        "market": market,
        "action": action,
        "action_label": action_label,
        "actionability_cap": actionability,
        "confidence_score": 0.65 if quote else 0.35,
        "score": score,
        "risk_flags": risk_flags,
        "watch_conditions": watch_conditions,
        "current_price": price,
        "currency": currency,
        "sector": sector,
        "industry": industry,
        "trend": trend,
        "next_earnings": next_earnings,
        "review_due_at": review_due_at,
        "data_quality": data_quality,
        "quality_display": quality_display,
        "discipline_result": discipline_result,
        "history_compare": history_compare,
        "news_context": news_context,
        "social_context": social_context,
        "why_changed": why_changed,
        "context_pack": {
            "schema_version": context.get("schema_version") or ANALYSIS_CONTEXT_SCHEMA_VERSION,
            "summary": context.get("summary") or {},
            "data_quality": context.get("data_quality") or {},
            "discipline_result": discipline_result,
        },
        "report": report,
        "short_reply": short_reply,
        "report_constraints": {"conclusion_first": True, "module_max_chars": MAX_REPORT_MODULE_CHARS},
        "prompt": prompt,
    }


def _build_context(
    *,
    tenant_id: str,
    symbol: str,
    prompt: str | None,
    quote_payload: JsonDict,
    positions_payload: JsonDict,
    history_payload: JsonDict,
    held_position: JsonDict | None,
    market: str,
    enrichment: JsonDict | None = None,
) -> JsonDict:
    quote = _payload_data(quote_payload)
    positions = _payload_data(positions_payload)
    history = _payload_data(history_payload) if history_payload else {}
    enrichment = enrichment if isinstance(enrichment, dict) else {}
    sector = _first_text(quote, "sector", "industry_sector") or _first_text(held_position or {}, "sector")
    industry = _first_text(quote, "industry", "industry_name") or _first_text(held_position or {}, "industry")
    position_context = _position_context(positions, held_position)
    market_context = {
        "quote": quote,
        "market": market,
        "sector": sector,
        "industry": industry,
        "next_earnings": _first_text(quote, "next_earnings_date", "earnings_date", "earnings_at"),
        "trend": _history_trend(history_payload),
    }
    rules_context = enrichment.get("rules_context") if isinstance(enrichment.get("rules_context"), dict) else _empty_rules_context()
    historical_decisions = (
        enrichment.get("historical_decisions")
        if isinstance(enrichment.get("historical_decisions"), dict)
        else _empty_historical_decisions()
    )
    sector_context = enrichment.get("sector_context") if isinstance(enrichment.get("sector_context"), dict) else _empty_sector_context(sector, industry)
    market_regime = enrichment.get("market_regime") if isinstance(enrichment.get("market_regime"), dict) else _empty_market_regime(market)
    news_context = enrichment.get("news_context") if isinstance(enrichment.get("news_context"), dict) else _empty_news_context()
    social_context = enrichment.get("social_context") if isinstance(enrichment.get("social_context"), dict) else _empty_social_context()
    data_quality = _context_data_quality(
        quote_payload=quote_payload,
        positions_payload=positions_payload,
        history_payload=history_payload,
        position_context=position_context,
        sector_context=sector_context,
        market_regime=market_regime,
        rules_context=rules_context,
        historical_decisions=historical_decisions,
        news_context=news_context,
        social_context=social_context,
    )
    source_refs = [
        {"source": "hermes-data-service", "ref": f"/api/quote/{symbol}"},
        {"source": "hermes-data-service", "ref": "/api/v3/portfolio/positions"},
    ]
    if history_payload:
        source_refs.append({"source": "hermes-data-service", "ref": f"/api/quote/{symbol}/history"})
    source_refs.extend(enrichment.get("source_refs") or [])
    return {
        "schema_version": ANALYSIS_CONTEXT_SCHEMA_VERSION,
        "legacy_schema_version": "stock_analysis_context_p1",
        "tenant_id": tenant_id,
        "symbol": symbol,
        "prompt": prompt,
        "identity": {
            "tenant_id": tenant_id,
            "symbol": symbol,
            "market": market,
            "prompt": prompt,
        },
        "quote": quote,
        "portfolio_summary": {
            "positions_count": _positions_total(positions),
            "held_position": held_position,
        },
        "history": history,
        "position_context": position_context,
        "market_context": market_context,
        "market_regime": market_regime,
        "sector_context": sector_context,
        "rules_context": rules_context,
        "historical_decisions": historical_decisions,
        "news_context": news_context,
        "social_context": social_context,
        "data_quality": data_quality,
        "summary": {
            "held": bool(held_position),
            "positions_count": position_context["positions_count"],
            "active_rules_count": len(rules_context.get("active_rules") or []),
            "trading_rules_count": len(rules_context.get("trading_rules") or []),
            "previous_decisions_count": len(historical_decisions.get("items") or []),
            "market_regime_status": market_regime.get("status"),
            "market_regime": market_regime.get("regime"),
            "sector_context_status": sector_context.get("status"),
            "news_status": news_context.get("status"),
            "social_status": social_context.get("status"),
        },
        "source_refs": source_refs,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def _position_module(
    *,
    held_position: JsonDict | None,
    quantity: float | None,
    average_cost: float | None,
    pnl_pct: float | None,
    currency: str,
) -> str:
    if not held_position:
        return "未在当前持仓读模型中匹配到该标的；不能判断仓位、成本、集中度或是否应止盈止损。"
    return (
        f"当前匹配到持仓：数量 {quantity if quantity is not None else '未知'}，"
        f"成本 {average_cost if average_cost is not None else '未知'} {currency}，"
        f"浮盈亏 {pnl_pct if pnl_pct is not None else '未知'}%。"
    )


async def _load_context_enrichment(
    *,
    tenant_id: str,
    symbol: str,
    market: str,
    quote: JsonDict,
    held_position: JsonDict | None,
    sector_context_payload: JsonDict | None = None,
    market_regime_payload: JsonDict | None = None,
    news_context_payload: JsonDict | None = None,
    social_context_payload: JsonDict | None = None,
) -> JsonDict:
    database_url = os.getenv("DATABASE_URL", "").strip()
    sector = _first_text(quote, "sector", "industry_sector") or _first_text(held_position or {}, "sector")
    industry = _first_text(quote, "industry", "industry_name") or _first_text(held_position or {}, "industry")
    preferred_sector_context = _sector_context_from_tool_payload(sector_context_payload, sector, industry)
    preferred_market_regime = _market_regime_from_tool_payload(market_regime_payload, market)
    preferred_news_context = _news_context_from_payload_or_quote(news_context_payload, symbol, market, quote)
    preferred_social_context = _social_context_from_payload(social_context_payload, symbol, market)
    preferred_source_refs = [
        *_source_refs_from_tool_payload(sector_context_payload),
        *_source_refs_from_tool_payload(market_regime_payload),
        *_source_refs_from_tool_payload(news_context_payload),
        *_source_refs_from_tool_payload(social_context_payload),
    ]
    if not database_url or not _is_uuid(tenant_id):
        return {
            "sector_context": preferred_sector_context or _empty_sector_context(sector, industry),
            "market_regime": preferred_market_regime or _empty_market_regime(market),
            "rules_context": _empty_rules_context("database_not_configured" if not database_url else "tenant_id_is_not_uuid"),
            "historical_decisions": _empty_historical_decisions("database_not_configured" if not database_url else "tenant_id_is_not_uuid"),
            "news_context": preferred_news_context or _empty_news_context(),
            "social_context": preferred_social_context or _empty_social_context(),
            "source_refs": preferred_source_refs,
        }
    return await asyncio.to_thread(
        _load_context_enrichment_sync,
        database_url=database_url,
        tenant_id=tenant_id,
        symbol=symbol,
        market=market,
        sector=sector,
        industry=industry,
        preferred_sector_context=preferred_sector_context,
        preferred_market_regime=preferred_market_regime,
        preferred_news_context=preferred_news_context,
        preferred_social_context=preferred_social_context,
        preferred_source_refs=preferred_source_refs,
    )


def _load_context_enrichment_sync(
    *,
    database_url: str,
    tenant_id: str,
    symbol: str,
    market: str,
    sector: str | None,
    industry: str | None,
    preferred_sector_context: JsonDict | None = None,
    preferred_market_regime: JsonDict | None = None,
    preferred_news_context: JsonDict | None = None,
    preferred_social_context: JsonDict | None = None,
    preferred_source_refs: list[JsonDict] | None = None,
) -> JsonDict:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        return {
            "sector_context": preferred_sector_context or _empty_sector_context(sector, industry, f"psycopg_not_installed: {exc}"),
            "market_regime": preferred_market_regime or _empty_market_regime(market, f"psycopg_not_installed: {exc}"),
            "rules_context": _empty_rules_context(f"psycopg_not_installed: {exc}"),
            "historical_decisions": _empty_historical_decisions(f"psycopg_not_installed: {exc}"),
            "news_context": preferred_news_context or _empty_news_context(),
            "social_context": preferred_social_context or _empty_social_context(),
            "source_refs": preferred_source_refs or [],
        }

    now = datetime.now(timezone.utc)
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            previous_signals = conn.execute(
                """
                SELECT id, source_artifact_id, action, action_label, actionability_cap,
                       confidence_score, score, watch_conditions, risk_summary,
                       data_quality_summary, status, expires_at, created_at
                FROM public.decision_signals
                WHERE tenant_id = %(tenant_id)s
                  AND symbol = %(symbol)s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                {"tenant_id": tenant_id, "symbol": symbol},
            ).fetchall()
            active_rules = conn.execute(
                """
                SELECT id, decision_signal_id, name, alert_type, severity,
                       parameters, cooldown_policy, notification_policy,
                       expires_at, updated_at
                FROM public.alert_rules
                WHERE tenant_id = %(tenant_id)s
                  AND target_symbol = %(symbol)s
                  AND enabled = true
                  AND (expires_at IS NULL OR expires_at >= %(now)s)
                ORDER BY severity DESC, updated_at DESC
                LIMIT 20
                """,
                {"tenant_id": tenant_id, "symbol": symbol, "now": now},
            ).fetchall()
            recent_triggers = conn.execute(
                """
                SELECT at.id, at.rule_id, at.reason, at.status, at.triggered_at,
                       ar.alert_type, ar.severity
                FROM public.alert_triggers at
                LEFT JOIN public.alert_rules ar ON ar.id = at.rule_id
                WHERE at.tenant_id = %(tenant_id)s
                  AND at.target_symbol = %(symbol)s
                  AND at.triggered_at >= %(since)s
                ORDER BY at.triggered_at DESC
                LIMIT 20
                """,
                {"tenant_id": tenant_id, "symbol": symbol, "since": now - timedelta(days=7)},
            ).fetchall()
            trading_rules = conn.execute(
                """
                SELECT id, name, rule_key, rule_type, scopes, markets, instruments,
                       condition, message, action_on_violation, priority, source,
                       updated_at
                FROM public.trading_rules
                WHERE tenant_id = %(tenant_id)s
                  AND is_active = true
                  AND (COALESCE(array_length(markets, 1), 0) = 0 OR %(market)s = ANY(markets))
                ORDER BY priority ASC, updated_at DESC
                LIMIT 50
                """,
                {"tenant_id": tenant_id, "market": market},
            ).fetchall()
            sector_rows = []
            if sector:
                sector_rows = conn.execute(
                    """
                    SELECT market, sector, industry, snapshot_date, change_pct,
                           relative_strength, breadth, leaders, laggards,
                           source_key, quality_status, created_at
                    FROM public.sector_daily_snapshots
                    WHERE market = %(market)s
                      AND sector = %(sector)s
                      AND (tenant_id IS NULL OR tenant_id = %(tenant_id)s)
                    ORDER BY snapshot_date DESC, created_at DESC
                    LIMIT 5
                    """,
                    {"tenant_id": tenant_id, "market": market, "sector": sector},
                ).fetchall()
            market_regime_rows = conn.execute(
                """
                SELECT market, sector, industry, snapshot_date, change_pct,
                       relative_strength, breadth, leaders, laggards,
                       source_key, quality_status, created_at
                FROM public.sector_daily_snapshots
                WHERE market = %(market)s
                  AND (tenant_id IS NULL OR tenant_id = %(tenant_id)s)
                ORDER BY snapshot_date DESC, created_at DESC
                LIMIT 30
                """,
                {"tenant_id": tenant_id, "market": market},
            ).fetchall()
    except Exception as exc:
        reason = f"database_read_failed: {exc}"
        return {
            "sector_context": preferred_sector_context or _empty_sector_context(sector, industry, reason),
            "market_regime": preferred_market_regime or _empty_market_regime(market, reason),
            "rules_context": _empty_rules_context(reason),
            "historical_decisions": _empty_historical_decisions(reason),
            "news_context": preferred_news_context or _empty_news_context(),
            "social_context": preferred_social_context or _empty_social_context(),
            "source_refs": preferred_source_refs or [],
        }

    return {
        "sector_context": preferred_sector_context or _sector_context_from_rows(sector=sector, industry=industry, rows=[dict(row) for row in sector_rows]),
        "market_regime": preferred_market_regime or _market_regime_from_rows(market=market, rows=[dict(row) for row in market_regime_rows]),
        "rules_context": {
            "status": "available",
            "active_rules": [_compact_rule_context(dict(row)) for row in active_rules],
            "recent_triggers": [_compact_trigger_context(dict(row)) for row in recent_triggers],
            "trading_rules": [_compact_trading_rule_context(dict(row)) for row in trading_rules],
        },
        "historical_decisions": {
            "status": "available",
            "items": [_compact_decision_context(dict(row)) for row in previous_signals],
        },
        "news_context": preferred_news_context or _empty_news_context(),
        "social_context": preferred_social_context or _empty_social_context(),
        "source_refs": [
            {"source": "postgres", "ref": "decision_signals"},
            {"source": "postgres", "ref": "alert_rules"},
            {"source": "postgres", "ref": "alert_triggers"},
            {"source": "postgres", "ref": "trading_rules"},
            {"source": "postgres", "ref": "sector_daily_snapshots"},
        ] + (preferred_source_refs or []),
    }


async def load_sector_context(
    *,
    tenant_id: str = "",
    market: str,
    sector: str | None,
    industry: str | None = None,
    limit: int = 5,
    database_url: str = "",
) -> JsonDict:
    database_url = database_url or os.getenv("DATABASE_URL", "").strip()
    if not sector:
        return _sector_context_tool_payload(_empty_sector_context(sector, industry, "sector_missing"), source_refs=[])
    if not database_url:
        return _sector_context_tool_payload(_empty_sector_context(sector, industry, "database_not_configured"), source_refs=[])
    return await asyncio.to_thread(
        _load_sector_context_sync,
        database_url=database_url,
        tenant_id=tenant_id,
        market=market,
        sector=sector,
        industry=industry,
        limit=max(1, min(30, int(limit or 5))),
    )


async def load_market_regime(
    *,
    tenant_id: str = "",
    market: str,
    limit: int = 30,
    database_url: str = "",
) -> JsonDict:
    database_url = database_url or os.getenv("DATABASE_URL", "").strip()
    if not market:
        return _market_regime_tool_payload(_empty_market_regime(market, "market_missing"), source_refs=[])
    if not database_url:
        return _market_regime_tool_payload(_empty_market_regime(market, "database_not_configured"), source_refs=[])
    return await asyncio.to_thread(
        _load_market_regime_sync,
        database_url=database_url,
        tenant_id=tenant_id,
        market=market,
        limit=max(1, min(100, int(limit or 30))),
    )


def _load_market_regime_sync(
    *,
    database_url: str,
    tenant_id: str,
    market: str,
    limit: int,
) -> JsonDict:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        return _market_regime_tool_payload(_empty_market_regime(market, f"psycopg_not_installed: {exc}"), source_refs=[])

    tenant_uuid = tenant_id if _is_uuid(tenant_id) else None
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT market, sector, industry, snapshot_date, change_pct,
                       relative_strength, breadth, leaders, laggards,
                       source_key, quality_status, created_at
                FROM public.sector_daily_snapshots
                WHERE market = %(market)s
                  AND (tenant_id IS NULL OR tenant_id = %(tenant_id)s)
                ORDER BY snapshot_date DESC, created_at DESC
                LIMIT %(limit)s
                """,
                {"tenant_id": tenant_uuid, "market": market, "limit": limit},
            ).fetchall()
    except Exception as exc:
        return _market_regime_tool_payload(_empty_market_regime(market, f"database_read_failed: {exc}"), source_refs=[])

    return _market_regime_tool_payload(
        _market_regime_from_rows(market=market, rows=[dict(row) for row in rows]),
        source_refs=[{"source": "postgres", "ref": "sector_daily_snapshots"}],
    )


def _load_sector_context_sync(
    *,
    database_url: str,
    tenant_id: str,
    market: str,
    sector: str,
    industry: str | None,
    limit: int,
) -> JsonDict:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        return _sector_context_tool_payload(_empty_sector_context(sector, industry, f"psycopg_not_installed: {exc}"), source_refs=[])

    tenant_uuid = tenant_id if _is_uuid(tenant_id) else None
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT market, sector, industry, snapshot_date, change_pct,
                       relative_strength, breadth, leaders, laggards,
                       source_key, quality_status, created_at
                FROM public.sector_daily_snapshots
                WHERE market = %(market)s
                  AND sector = %(sector)s
                  AND (tenant_id IS NULL OR tenant_id = %(tenant_id)s)
                ORDER BY snapshot_date DESC, created_at DESC
                LIMIT %(limit)s
                """,
                {"tenant_id": tenant_uuid, "market": market, "sector": sector, "limit": limit},
            ).fetchall()
    except Exception as exc:
        return _sector_context_tool_payload(_empty_sector_context(sector, industry, f"database_read_failed: {exc}"), source_refs=[])

    context = _sector_context_from_rows(sector=sector, industry=industry, rows=[dict(row) for row in rows])
    return _sector_context_tool_payload(
        context,
        source_refs=[{"source": "postgres", "ref": "sector_daily_snapshots"}],
    )


def _position_context(positions: JsonDict, held_position: JsonDict | None) -> JsonDict:
    equity_positions = positions.get("equity_positions") if isinstance(positions.get("equity_positions"), list) else []
    option_positions = positions.get("option_positions") if isinstance(positions.get("option_positions"), list) else []
    total_market_value = _sum_numbers([_first_number(row, "market_value", "marketValue", "position_value") for row in equity_positions])
    held_market_value = _first_number(held_position or {}, "market_value", "marketValue", "position_value")
    concentration_pct = None
    if total_market_value and held_market_value is not None:
        concentration_pct = round((held_market_value / total_market_value) * 100, 2)
    return {
        "status": "held" if held_position else "not_held_or_unavailable",
        "positions_count": len(equity_positions) + len(option_positions),
        "equity_positions_count": len(equity_positions),
        "option_positions_count": len(option_positions),
        "held_position": held_position,
        "quantity": _first_number(held_position or {}, "quantity", "shares"),
        "average_cost": _first_number(held_position or {}, "average_cost", "avg_buy_price"),
        "unrealized_pnl_pct": _first_number(held_position or {}, "unrealized_pnl_pct", "pnl_percent"),
        "market_value": held_market_value,
        "portfolio_market_value": total_market_value,
        "concentration_pct": concentration_pct,
    }


def _context_data_quality(
    *,
    quote_payload: JsonDict,
    positions_payload: JsonDict,
    history_payload: JsonDict,
    position_context: JsonDict,
    sector_context: JsonDict,
    market_regime: JsonDict,
    rules_context: JsonDict,
    historical_decisions: JsonDict,
    news_context: JsonDict,
    social_context: JsonDict,
) -> JsonDict:
    missing: list[str] = []
    if not _payload_data(quote_payload):
        missing.append("quote")
    if not _payload_data(positions_payload):
        missing.append("positions")
    if not _payload_data(history_payload):
        missing.append("history")
    if sector_context.get("status") != "available":
        missing.append("sector_context")
    if market_regime.get("status") != "available":
        missing.append("market_regime")
    if news_context.get("status") != "available":
        missing.append("news")
    if social_context.get("status") != "available":
        missing.append("social")
    coverage = {
        "quote": bool(_payload_data(quote_payload)),
        "positions": bool(_payload_data(positions_payload)),
        "held_position": position_context.get("status") == "held",
        "history": bool(_payload_data(history_payload)),
        "sector_context": sector_context.get("status") == "available",
        "market_regime": market_regime.get("status") == "available",
        "active_rules": rules_context.get("status") == "available",
        "historical_decisions": historical_decisions.get("status") == "available",
        "news": news_context.get("status") == "available",
        "social": social_context.get("status") == "available",
    }
    if "quote" in missing:
        actionability_floor = "blocked"
    elif "positions" in missing or "history" in missing:
        actionability_floor = "analysis_only"
    else:
        actionability_floor = "analysis_only"
    return {
        "status": "complete" if not missing else "partial",
        "coverage": coverage,
        "missing": missing,
        "actionability_floor": actionability_floor,
    }


def _stock_quality_display(
    *,
    source: str,
    as_of: str | None,
    freshness_seconds: Any,
    quote_actionability: str,
    actionability: str,
    has_quote: bool,
    has_positions_context: bool,
    has_held_position: bool,
    context_data_quality: JsonDict,
) -> JsonDict:
    freshness = _freshness_state(
        freshness_seconds=freshness_seconds,
        as_of=as_of,
        has_quote=has_quote,
        quote_actionability=quote_actionability,
    )
    degrade_reason = _quality_degrade_reason(
        freshness=freshness,
        actionability=actionability,
        has_quote=has_quote,
        has_positions_context=has_positions_context,
        has_held_position=has_held_position,
        context_data_quality=context_data_quality,
    )
    return {
        "schema_version": "quality_display_v1",
        "source": source or "unknown",
        "as_of": as_of,
        "freshness": freshness,
        "freshness_label": _freshness_label(freshness),
        "actionability": actionability or "analysis_only",
        "actionability_label": _actionability_label(actionability),
        "degrade_reason": degrade_reason,
        "degrade_reason_label": _degrade_reason_label(degrade_reason),
        "summary": _quality_summary(
            actionability=actionability,
            freshness=freshness,
            degrade_reason=degrade_reason,
            source=source,
        ),
    }


def _freshness_state(
    *,
    freshness_seconds: Any,
    as_of: str | None,
    has_quote: bool,
    quote_actionability: str,
) -> str:
    if not has_quote:
        return "missing"
    seconds = _json_number(freshness_seconds)
    if quote_actionability in {"stale", "blocked", "not_available"}:
        return "stale"
    if seconds is None:
        return "unknown" if not as_of else "fresh"
    if seconds > 15 * 60:
        return "stale"
    if seconds > 5 * 60:
        return "degraded"
    return "fresh"


def _quality_degrade_reason(
    *,
    freshness: str,
    actionability: str,
    has_quote: bool,
    has_positions_context: bool,
    has_held_position: bool,
    context_data_quality: JsonDict,
) -> str | None:
    missing = context_data_quality.get("missing") if isinstance(context_data_quality.get("missing"), list) else []
    if not has_quote:
        return "quote_unavailable"
    if freshness == "stale":
        return "data_stale"
    if not has_positions_context or "positions" in missing:
        return "no_portfolio_context"
    if not has_held_position:
        return "no_position_context"
    if actionability == "blocked":
        return "action_blocked"
    if actionability == "analysis_only":
        return "analysis_only"
    if freshness in {"degraded", "unknown"}:
        return "freshness_uncertain"
    return None


def _freshness_label(value: str) -> str:
    return {
        "fresh": "数据新鲜",
        "degraded": "数据降级",
        "stale": "数据过期",
        "missing": "数据缺失",
        "unknown": "新鲜度未知",
    }.get(value, "新鲜度未知")


def _actionability_label(value: str | None) -> str:
    return {
        "trade_draft": "可行动",
        "analysis_only": "只能观察",
        "blocked": "不可行动",
    }.get(str(value or "analysis_only"), "只能观察")


def _degrade_reason_label(value: str | None) -> str:
    return {
        None: "无降级",
        "quote_unavailable": "行情不可用",
        "data_stale": "数据过期",
        "no_portfolio_context": "无持仓上下文",
        "no_position_context": "无持仓上下文",
        "action_blocked": "纪律或数据阻断",
        "analysis_only": "只能观察",
        "freshness_uncertain": "新鲜度待复核",
    }.get(value, str(value))


def _quality_summary(*, actionability: str, freshness: str, degrade_reason: str | None, source: str) -> str:
    parts = [_actionability_label(actionability), _freshness_label(freshness)]
    reason_label = _degrade_reason_label(degrade_reason)
    if degrade_reason and reason_label not in parts:
        parts.append(reason_label)
    parts.append(f"来源 {source or 'unknown'}")
    return " / ".join(parts)


def _analysis_data_quality_summary(analysis: JsonDict) -> JsonDict:
    summary = dict(analysis.get("data_quality") or {})
    if analysis.get("quality_display"):
        summary["quality_display"] = analysis.get("quality_display")
    return summary


def _empty_sector_context(sector: str | None, industry: str | None, reason: str = "not_available") -> JsonDict:
    return {"status": "not_available", "reason": reason, "sector": sector, "industry": industry, "snapshots": []}


def _empty_market_regime(market: str | None, reason: str = "not_available") -> JsonDict:
    return {
        "status": "not_available",
        "reason": reason,
        "market": market,
        "regime": "unknown",
        "risk_bias": "unknown",
        "summary": "市场状态数据不足",
        "sector_count": 0,
        "positive_sector_ratio": None,
        "average_change_pct": None,
        "average_relative_strength": None,
        "as_of": None,
    }


def _empty_rules_context(reason: str = "not_available") -> JsonDict:
    return {"status": "not_available", "reason": reason, "active_rules": [], "recent_triggers": [], "trading_rules": []}


def _empty_historical_decisions(reason: str = "not_available") -> JsonDict:
    return {"status": "not_available", "reason": reason, "items": []}


def _empty_news_context(reason: str = "news_reader_not_configured") -> JsonDict:
    return {"status": "not_configured", "reason": reason, "items": [], "catalysts": [], "summary": "未配置新闻/事件源"}


def _empty_social_context(reason: str = "social_reader_not_configured") -> JsonDict:
    return {
        "schema_version": "social_sentiment_snapshot_v1",
        "status": "not_configured",
        "reason": reason,
        "items": [],
        "accounts": [],
        "providers_attempted": [],
        "data_quality": {},
        "themes": [],
        "risk_flags": [],
        "summary": "未配置社媒账号清单或社媒信号源",
    }


def _sector_context_tool_payload(context: JsonDict, *, source_refs: list[JsonDict]) -> JsonDict:
    return {
        "ok": context.get("status") == "available",
        "status": context.get("status") or "not_available",
        "data": {
            "schema_version": "sector_context_v1",
            "sector_context": context,
        },
        "source_refs": source_refs,
    }


def _market_regime_tool_payload(regime: JsonDict, *, source_refs: list[JsonDict]) -> JsonDict:
    return {
        "ok": regime.get("status") == "available",
        "status": regime.get("status") or "not_available",
        "data": {
            "schema_version": "market_regime_v1",
            "market_regime": regime,
        },
        "source_refs": source_refs,
    }


def _sector_context_from_tool_payload(payload: JsonDict | None, sector: str | None, industry: str | None) -> JsonDict | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    context = data.get("sector_context") if isinstance(data, dict) else None
    if isinstance(context, dict):
        return context
    if data.get("schema_version") == "sector_context_v1":
        return _empty_sector_context(sector, industry, "sector_context_missing")
    return None


def _news_context_from_payload_or_quote(payload: JsonDict | None, symbol: str, market: str, quote: JsonDict) -> JsonDict | None:
    if isinstance(payload, dict) and payload:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        context = data.get("news_context") if isinstance(data, dict) else None
        if isinstance(context, dict):
            return _normalize_news_context(context, symbol=symbol, market=market)
        if isinstance(data, dict) and data.get("schema_version") == "stock_news_context_v1":
            return _empty_news_context("news_context_missing")
        if isinstance(data, dict):
            normalized = _normalize_news_context(data, symbol=symbol, market=market)
            if normalized.get("status") == "available":
                return normalized

    derived = _news_context_from_quote(quote, symbol=symbol, market=market)
    return derived


def _social_context_from_payload(payload: JsonDict | None, symbol: str, market: str) -> JsonDict | None:
    if not isinstance(payload, dict) or not payload:
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    context = data.get("social_context") if isinstance(data, dict) else None
    if isinstance(context, dict):
        return _normalize_social_context(context, symbol=symbol, market=market)
    if isinstance(data, dict) and data.get("schema_version") == "social_sentiment_snapshot_v1":
        return _normalize_social_context(data, symbol=symbol, market=market)
    return None


def _normalize_social_context(context: JsonDict, *, symbol: str, market: str) -> JsonDict:
    items = _compact_social_items(context.get("items") or context.get("posts"))
    accounts = _compact_social_accounts(context.get("accounts") or context.get("watch_accounts"))
    themes = _compact_social_themes(context.get("themes"))
    risk_flags = _compact_social_risk_flags(context.get("risk_flags"))
    sentiment = context.get("sentiment") if isinstance(context.get("sentiment"), dict) else {}
    providers_attempted = context.get("providers_attempted") if isinstance(context.get("providers_attempted"), list) else []
    data_quality = context.get("data_quality") if isinstance(context.get("data_quality"), dict) else {}
    summary = _first_text(context, "summary", "brief", "overview")
    status = str(context.get("status") or "").strip() or ("available" if items or themes or summary else "not_configured")
    if status != "available" and (items or themes or summary):
        status = "available"
    return {
        "schema_version": "social_sentiment_snapshot_v1",
        "status": status,
        "reason": _first_text(context, "reason", "error") or ("ok" if status == "available" else "social_reader_not_configured"),
        "symbol": str(context.get("symbol") or symbol),
        "market": str(context.get("market") or market),
        "window": _first_text(context, "window") or "unspecified",
        "sentiment": {
            "label": _first_text(sentiment, "label") or _first_text(context, "sentiment_label") or "unknown",
            "score": _json_number(sentiment.get("score") if isinstance(sentiment, dict) else context.get("sentiment_score")),
            "confidence": _first_text(sentiment, "confidence") or _first_text(context, "confidence") or "low",
        },
        "summary": summary or ("未配置社媒账号清单或社媒信号源" if status != "available" else "已有社媒账号清单信号"),
        "items": items,
        "accounts": accounts,
        "providers_attempted": providers_attempted[:10],
        "data_quality": data_quality,
        "themes": themes,
        "risk_flags": risk_flags,
        "as_of": _iso(context.get("as_of") or context.get("updated_at")),
    }


def _normalize_news_context(context: JsonDict, *, symbol: str, market: str) -> JsonDict:
    items = _compact_news_items(
        context.get("items")
        if isinstance(context.get("items"), list)
        else context.get("news")
        if isinstance(context.get("news"), list)
        else context.get("news_items")
    )
    catalysts = _compact_catalysts(
        context.get("catalysts")
        if isinstance(context.get("catalysts"), list)
        else context.get("events")
        if isinstance(context.get("events"), list)
        else context.get("calendar")
    )
    summary = _first_text(context, "summary", "brief", "overview")
    status = str(context.get("status") or "").strip() or ("available" if items or catalysts or summary else "not_configured")
    if status != "available" and (items or catalysts or summary):
        status = "available"
    reason = _first_text(context, "reason", "error") or ("ok" if status == "available" else "news_reader_not_configured")
    return {
        "status": status,
        "reason": reason,
        "symbol": str(context.get("symbol") or symbol),
        "market": str(context.get("market") or market),
        "summary": summary or ("未配置新闻/事件源" if status != "available" else "已有新闻/事件上下文"),
        "items": items,
        "catalysts": catalysts,
        "as_of": _iso(context.get("as_of") or context.get("updated_at")),
    }


def _news_context_from_quote(quote: JsonDict, *, symbol: str, market: str) -> JsonDict | None:
    items = _compact_news_items(quote.get("news") or quote.get("news_items") or quote.get("headlines"))
    catalysts = _compact_catalysts(quote.get("catalysts") or quote.get("events") or quote.get("calendar"))
    next_earnings = _first_text(quote, "next_earnings_date", "earnings_date", "earnings_at")
    if next_earnings and not any(item.get("type") == "earnings" for item in catalysts):
        catalysts.append(
            {
                "type": "earnings",
                "label": "财报窗口",
                "date": next_earnings,
                "impact": "volatility",
                "summary": f"预计财报/事件时间：{next_earnings}",
            }
        )
    if not items and not catalysts:
        return None
    return {
        "status": "available",
        "reason": "quote_payload",
        "symbol": symbol,
        "market": market,
        "summary": "行情源提供了新闻/事件上下文",
        "items": items,
        "catalysts": catalysts,
        "as_of": _iso(quote.get("updated_at") or quote.get("as_of")),
    }


def _compact_news_items(value: Any) -> list[JsonDict]:
    rows = value if isinstance(value, list) else []
    items: list[JsonDict] = []
    for row in rows:
        if isinstance(row, str):
            headline = row.strip()
            if headline:
                items.append({"headline": headline})
            continue
        if not isinstance(row, dict):
            continue
        headline = _first_text(row, "headline", "title", "summary", "content")
        if not headline:
            continue
        items.append(
            {
                "headline": headline,
                "source": _first_text(row, "source", "publisher"),
                "published_at": _iso(row.get("published_at") or row.get("time") or row.get("datetime")),
                "url": _first_text(row, "url", "link"),
                "sentiment": _first_text(row, "sentiment", "tone"),
                "impact": _first_text(row, "impact", "importance"),
            }
        )
    return items[:10]


def _compact_social_items(value: Any) -> list[JsonDict]:
    rows = value if isinstance(value, list) else []
    items: list[JsonDict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = _first_text(row, "text", "content", "summary", "body")
        if not text:
            continue
        items.append(
            {
                "platform": _first_text(row, "platform", "source") or "unknown",
                "account_id": _first_text(row, "account_id", "handle", "author_id", "author"),
                "account_name": _first_text(row, "account_name", "display_name", "author_name", "author"),
                "url": _first_text(row, "url", "link"),
                "published_at": _iso(row.get("published_at") or row.get("time") or row.get("created_at")),
                "text": text[:1000],
                "sentiment": _first_text(row, "sentiment", "tone"),
                "symbols": row.get("symbols") if isinstance(row.get("symbols"), list) else [],
                "engagement": row.get("engagement") if isinstance(row.get("engagement"), dict) else {},
            }
        )
    return items[:30]


def _compact_social_accounts(value: Any) -> list[JsonDict]:
    rows = value if isinstance(value, list) else []
    accounts: list[JsonDict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        platform = (_first_text(row, "platform") or "").lower()
        handle = _first_text(row, "handle", "account_id", "user_id", "id")
        if not platform or not handle:
            continue
        key = (platform, handle.lower())
        if key in seen:
            continue
        seen.add(key)
        accounts.append(
            {
                "platform": platform,
                "handle": handle,
                "display_name": _first_text(row, "display_name", "name"),
                "url": _first_text(row, "url", "profile_url"),
                "symbols": row.get("symbols") if isinstance(row.get("symbols"), list) else [],
            }
        )
    return accounts[:50]


def _compact_social_themes(value: Any) -> list[JsonDict]:
    rows = value if isinstance(value, list) else []
    themes: list[JsonDict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = _first_text(row, "label", "theme", "name")
        if not label:
            continue
        themes.append(
            {
                "label": label,
                "stance": _first_text(row, "stance", "sentiment") or "unknown",
                "evidence_count": int(_json_number(row.get("evidence_count") or row.get("count")) or 0),
            }
        )
    return themes[:12]


def _compact_social_risk_flags(value: Any) -> list[JsonDict]:
    rows = value if isinstance(value, list) else []
    flags: list[JsonDict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = _first_text(row, "description", "label", "type")
        if not label:
            continue
        flags.append(
            {
                "type": _first_text(row, "type") or "social_signal",
                "severity": _first_text(row, "severity") or "watch",
                "description": label,
            }
        )
    return flags[:10]


def _compact_catalysts(value: Any) -> list[JsonDict]:
    rows = value if isinstance(value, list) else []
    catalysts: list[JsonDict] = []
    for row in rows:
        if isinstance(row, str):
            label = row.strip()
            if label:
                catalysts.append({"label": label})
            continue
        if not isinstance(row, dict):
            continue
        label = _first_text(row, "label", "title", "name", "headline", "event_type", "type")
        if not label:
            continue
        catalysts.append(
            {
                "type": _first_text(row, "type", "event_type"),
                "label": label,
                "date": _iso(row.get("date") or row.get("expected_at") or row.get("published_at")),
                "impact": _first_text(row, "impact", "importance", "bias"),
                "summary": _first_text(row, "summary", "description", "reason"),
            }
        )
    return catalysts[:10]


def _market_regime_from_tool_payload(payload: JsonDict | None, market: str | None) -> JsonDict | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    regime = data.get("market_regime") if isinstance(data, dict) else None
    if isinstance(regime, dict):
        return regime
    if data.get("schema_version") == "market_regime_v1":
        return _empty_market_regime(market, "market_regime_missing")
    return None


def _source_refs_from_tool_payload(payload: JsonDict | None) -> list[JsonDict]:
    if not isinstance(payload, dict):
        return []
    refs = payload.get("source_refs")
    if isinstance(refs, list):
        return [ref for ref in refs if isinstance(ref, dict)]
    return []


def _sector_context_from_rows(*, sector: str | None, industry: str | None, rows: list[JsonDict]) -> JsonDict:
    if not rows:
        return _empty_sector_context(sector, industry, "no_sector_snapshot")
    snapshots = [_compact_sector_snapshot(row) for row in rows]
    latest = snapshots[0]
    return {
        "status": "available",
        "sector": latest.get("sector") or sector,
        "industry": latest.get("industry") or industry,
        "latest": latest,
        "snapshots": snapshots,
    }


def _market_regime_from_rows(*, market: str, rows: list[JsonDict]) -> JsonDict:
    if not rows:
        return _empty_market_regime(market, "no_market_snapshots")

    latest_date = rows[0].get("snapshot_date")
    same_day_rows = [row for row in rows if row.get("snapshot_date") == latest_date]
    if not same_day_rows:
        same_day_rows = rows

    changes = [_json_number(row.get("change_pct")) for row in same_day_rows]
    changes = [value for value in changes if value is not None]
    relative_strengths = [_json_number(row.get("relative_strength")) for row in same_day_rows]
    relative_strengths = [value for value in relative_strengths if value is not None]
    sector_count = len(same_day_rows)
    average_change = round(sum(changes) / len(changes), 2) if changes else None
    average_relative_strength = round(sum(relative_strengths) / len(relative_strengths), 2) if relative_strengths else None
    positive_ratio = round(len([value for value in changes if value > 0]) / len(changes), 2) if changes else None

    regime = "neutral"
    risk_bias = "balanced"
    if average_change is not None and positive_ratio is not None:
        if average_change <= -1.5 or positive_ratio <= 0.35:
            regime = "risk_off"
            risk_bias = "defensive"
        elif average_change >= 1.0 and positive_ratio >= 0.6:
            regime = "risk_on"
            risk_bias = "constructive"

    return {
        "status": "available",
        "market": market,
        "regime": regime,
        "risk_bias": risk_bias,
        "summary": _market_regime_summary(regime, average_change, positive_ratio),
        "sector_count": sector_count,
        "positive_sector_ratio": positive_ratio,
        "average_change_pct": average_change,
        "average_relative_strength": average_relative_strength,
        "as_of": _iso(latest_date),
        "sectors": [_compact_sector_snapshot(row) for row in same_day_rows[:20]],
    }


def _market_regime_summary(regime: str, average_change: float | None, positive_ratio: float | None) -> str:
    if average_change is None or positive_ratio is None:
        return "市场状态数据不足"
    if regime == "risk_off":
        return f"市场偏防守，板块平均 {average_change:+.2f}%，上涨占比 {positive_ratio:.0%}"
    if regime == "risk_on":
        return f"市场风险偏好较强，板块平均 {average_change:+.2f}%，上涨占比 {positive_ratio:.0%}"
    return f"市场中性震荡，板块平均 {average_change:+.2f}%，上涨占比 {positive_ratio:.0%}"


def _compact_sector_snapshot(row: JsonDict) -> JsonDict:
    return {
        "market": row.get("market"),
        "sector": row.get("sector"),
        "industry": row.get("industry"),
        "snapshot_date": _iso(row.get("snapshot_date")),
        "change_pct": _json_number(row.get("change_pct")),
        "relative_strength": _json_number(row.get("relative_strength")),
        "breadth": row.get("breadth") if isinstance(row.get("breadth"), dict) else {},
        "leaders": row.get("leaders") if isinstance(row.get("leaders"), list) else [],
        "laggards": row.get("laggards") if isinstance(row.get("laggards"), list) else [],
        "source_key": row.get("source_key"),
        "quality_status": row.get("quality_status"),
    }


def _compact_decision_context(row: JsonDict) -> JsonDict:
    return {
        "id": str(row.get("id")),
        "source_artifact_id": str(row.get("source_artifact_id")) if row.get("source_artifact_id") else None,
        "action": row.get("action"),
        "action_label": row.get("action_label"),
        "actionability_cap": row.get("actionability_cap"),
        "confidence_score": _json_number(row.get("confidence_score")),
        "score": row.get("score"),
        "watch_conditions": row.get("watch_conditions") if isinstance(row.get("watch_conditions"), list) else [],
        "risk_summary": row.get("risk_summary") if isinstance(row.get("risk_summary"), dict) else {},
        "data_quality_summary": row.get("data_quality_summary") if isinstance(row.get("data_quality_summary"), dict) else {},
        "status": row.get("status"),
        "expires_at": _iso(row.get("expires_at")),
        "created_at": _iso(row.get("created_at")),
    }


def _compact_rule_context(row: JsonDict) -> JsonDict:
    return {
        "id": str(row.get("id")),
        "decision_signal_id": str(row.get("decision_signal_id")) if row.get("decision_signal_id") else None,
        "name": row.get("name"),
        "alert_type": row.get("alert_type"),
        "severity": row.get("severity"),
        "parameters": row.get("parameters") if isinstance(row.get("parameters"), dict) else {},
        "cooldown_policy": row.get("cooldown_policy") if isinstance(row.get("cooldown_policy"), dict) else {},
        "notification_policy": row.get("notification_policy") if isinstance(row.get("notification_policy"), dict) else {},
        "expires_at": _iso(row.get("expires_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _compact_trading_rule_context(row: JsonDict) -> JsonDict:
    return {
        "id": str(row.get("id")),
        "name": row.get("name"),
        "rule_key": row.get("rule_key"),
        "rule_type": row.get("rule_type"),
        "scopes": _string_list(row.get("scopes")),
        "markets": _string_list(row.get("markets")),
        "instruments": _string_list(row.get("instruments")),
        "condition": row.get("condition") if isinstance(row.get("condition"), dict) else {},
        "message": row.get("message"),
        "action_on_violation": _normalize_discipline_action(row.get("action_on_violation")),
        "priority": row.get("priority"),
        "source": row.get("source"),
        "updated_at": _iso(row.get("updated_at")),
    }


def _compact_trigger_context(row: JsonDict) -> JsonDict:
    return {
        "id": str(row.get("id")),
        "rule_id": str(row.get("rule_id")) if row.get("rule_id") else None,
        "alert_type": row.get("alert_type"),
        "severity": row.get("severity"),
        "reason": row.get("reason"),
        "status": row.get("status"),
        "triggered_at": _iso(row.get("triggered_at")),
    }


def _sector_text(sector: str | None, industry: str | None) -> str:
    if sector and industry:
        return f"{sector}/{industry}"
    return sector or industry or "未提供"


def _sector_context_text(sector: str | None, industry: str | None, sector_context: JsonDict) -> str:
    base = _sector_text(sector, industry)
    latest = sector_context.get("latest") if isinstance(sector_context.get("latest"), dict) else {}
    relative_strength = latest.get("relative_strength")
    change_pct = latest.get("change_pct")
    if isinstance(relative_strength, (int, float)) or isinstance(change_pct, (int, float)):
        parts = [base]
        if isinstance(change_pct, (int, float)):
            parts.append(f"板块{change_pct:+.2f}%")
        if isinstance(relative_strength, (int, float)):
            parts.append(f"相对强度{relative_strength:+.2f}")
        return "，".join(parts)
    return base


def _market_regime_text(market_regime: JsonDict) -> str:
    if market_regime.get("status") != "available":
        return "未提供"
    summary = str(market_regime.get("summary") or "").strip()
    if summary:
        return summary
    regime = str(market_regime.get("regime") or "unknown")
    return regime


def _evaluate_discipline(
    *,
    symbol: str,
    market: str,
    prompt: str | None,
    quote: JsonDict,
    positions: JsonDict,
    held_position: JsonDict | None,
    context: JsonDict,
    candidate_action: str,
    candidate_actionability: str,
) -> JsonDict:
    checks: list[JsonDict] = []
    violations: list[JsonDict] = []
    prompt_text = str(prompt or "")
    position_context = context.get("position_context") if isinstance(context.get("position_context"), dict) else _position_context(positions, held_position)
    market_regime = context.get("market_regime") if isinstance(context.get("market_regime"), dict) else {}
    price = _first_number(quote, "price", "last_price", "current_price", "close")
    is_trade_intent = _looks_like_trade_intent(prompt_text)
    is_sell_put_intent = _looks_like_sell_put_intent(prompt_text)

    def add_check(rule: str, status: str, message: str, action: str = "none", severity: str = "info", details: JsonDict | None = None) -> None:
        item = {
            "rule": rule,
            "status": status,
            "action": action,
            "severity": severity,
            "message": message,
            "details": details or {},
        }
        checks.append(item)
        if action in {"warn", "block", "require_confirmation"}:
            violations.append(item)

    if not quote:
        add_check("quote_required", "failed", "行情不可用，不能形成建议。", "block", "critical")
    else:
        add_check("quote_required", "passed", "行情可用。")

    if is_trade_intent and not _is_regular_us_session(market):
        add_check(
            "regular_session_only",
            "failed",
            "当前不在美股常规交易时段，交易型建议降级为仅分析。",
            "require_confirmation",
            "warning",
            {"market": market},
        )

    concentration = _json_number(position_context.get("concentration_pct"))
    if concentration is not None:
        if concentration >= 50:
            add_check(
                "position_concentration",
                "failed",
                f"{symbol} 单票集中度约 {concentration:.1f}%，超过 50% 高集中阈值。",
                "require_confirmation",
                "warning",
                {"concentration_pct": concentration, "threshold_pct": 50},
            )
        elif concentration >= 30:
            add_check(
                "position_concentration",
                "warned",
                f"{symbol} 单票集中度约 {concentration:.1f}%，需要控制加仓。",
                "warn",
                "warning",
                {"concentration_pct": concentration, "threshold_pct": 30},
            )
        else:
            add_check("position_concentration", "passed", "单票集中度未触发纪律阈值。", details={"concentration_pct": concentration})
    else:
        add_check("position_concentration", "unknown", "缺少组合市值，无法判断单票集中度。", "warn", "info")

    if market_regime.get("regime") == "risk_off" and is_trade_intent:
        add_check(
            "market_regime_risk_off",
            "failed",
            "市场处于 risk_off，交易型动作降级为仅分析。",
            "require_confirmation",
            "warning",
            {"regime": market_regime.get("regime")},
        )

    cash = _portfolio_cash_context(positions)
    if is_trade_intent and cash.get("available_cash") is not None and cash.get("cash_buffer_ratio") is not None:
        buffer_ratio = float(cash["cash_buffer_ratio"])
        if buffer_ratio < 0.05:
            add_check(
                "cash_buffer",
                "failed",
                f"现金缓冲约 {buffer_ratio:.1%}，低于 5% 底线。",
                "block",
                "critical",
                cash,
            )
        elif buffer_ratio < 0.10:
            add_check(
                "cash_buffer",
                "warned",
                f"现金缓冲约 {buffer_ratio:.1%}，低于 10% 舒适线。",
                "require_confirmation",
                "warning",
                cash,
            )
        else:
            add_check("cash_buffer", "passed", "现金缓冲未触发纪律阈值。", details=cash)

    if is_sell_put_intent:
        cash_requirement = price * 100 if price else None
        available_cash = _json_number(cash.get("available_cash"))
        if cash_requirement is None:
            add_check("sell_put_cash_secured", "failed", "缺少标的价格，无法校验 Sell Put 现金担保。", "block", "critical")
        elif available_cash is None:
            add_check("sell_put_cash_secured", "unknown", "缺少可用现金，Sell Put 只能停留在分析。", "require_confirmation", "warning")
        elif available_cash < cash_requirement:
            add_check(
                "sell_put_cash_secured",
                "failed",
                f"Sell Put 现金担保不足：约需 {cash_requirement:.0f}，可用现金 {available_cash:.0f}。",
                "block",
                "critical",
                {"cash_requirement": cash_requirement, "available_cash": available_cash},
            )
        else:
            add_check("sell_put_cash_secured", "passed", "Sell Put 现金担保初步满足。", details={"cash_requirement": cash_requirement, "available_cash": available_cash})

    for configured_check in _evaluate_configured_trading_rules(
        symbol=symbol,
        market=market,
        prompt=prompt_text,
        quote=quote,
        held_position=held_position,
        context=context,
        position_context=position_context,
        cash=cash,
        price=price,
        is_trade_intent=is_trade_intent,
        is_sell_put_intent=is_sell_put_intent,
    ):
        checks.append(configured_check)
        if configured_check.get("action") in {"warn", "block", "require_confirmation"}:
            violations.append(configured_check)

    highest_action = _highest_discipline_action(violations)
    actionability_cap = _discipline_actionability_cap(highest_action, candidate_actionability)
    status = "blocked" if highest_action == "block" else "requires_confirmation" if highest_action == "require_confirmation" else "warned" if highest_action == "warn" else "passed"
    summary = _discipline_summary(status, violations)
    return {
        "schema_version": "discipline_result_v1",
        "status": status,
        "actionability_cap": actionability_cap,
        "highest_action": highest_action,
        "candidate_action": candidate_action,
        "candidate_actionability": candidate_actionability,
        "checks": checks,
        "violations": violations,
        "summary": summary,
    }


def _evaluate_configured_trading_rules(
    *,
    symbol: str,
    market: str,
    prompt: str,
    quote: JsonDict,
    held_position: JsonDict | None,
    context: JsonDict,
    position_context: JsonDict,
    cash: JsonDict,
    price: float | None,
    is_trade_intent: bool,
    is_sell_put_intent: bool,
) -> list[JsonDict]:
    rules_context = context.get("rules_context") if isinstance(context.get("rules_context"), dict) else {}
    rules = rules_context.get("trading_rules") if isinstance(rules_context.get("trading_rules"), list) else []
    checks: list[JsonDict] = []
    for rule in sorted(rules, key=lambda item: _json_number((item or {}).get("priority")) or 100):
        if not isinstance(rule, dict) or not _trading_rule_applies(
            rule,
            market=market,
            is_trade_intent=is_trade_intent,
            is_sell_put_intent=is_sell_put_intent,
        ):
            continue
        check = _evaluate_configured_trading_rule(
            rule,
            symbol=symbol,
            market=market,
            prompt=prompt,
            quote=quote,
            held_position=held_position,
            position_context=position_context,
            cash=cash,
            price=price,
            is_trade_intent=is_trade_intent,
            is_sell_put_intent=is_sell_put_intent,
        )
        if check:
            checks.append(check)
    return checks


def _trading_rule_applies(rule: JsonDict, *, market: str, is_trade_intent: bool, is_sell_put_intent: bool) -> bool:
    markets = {item.upper() for item in _string_list(rule.get("markets"))}
    if markets and market.upper() not in markets:
        return False

    scopes = {item.lower() for item in _string_list(rule.get("scopes"))}
    scope_candidates = {"stock", "equity", "stock_analysis", "equity_analysis"}
    if is_trade_intent:
        scope_candidates.update({"trade", "trade_draft", "trade_intent"})
    if is_sell_put_intent:
        scope_candidates.add("sell_put")
    if scopes and not scopes.intersection(scope_candidates):
        return False

    instruments = {item.lower() for item in _string_list(rule.get("instruments"))}
    instrument_candidates = {"stock", "equity", "etf"}
    if is_sell_put_intent:
        instrument_candidates.update({"option", "option_contract"})
    if instruments and not instruments.intersection(instrument_candidates):
        return False
    return True


def _evaluate_configured_trading_rule(
    rule: JsonDict,
    *,
    symbol: str,
    market: str,
    prompt: str,
    quote: JsonDict,
    held_position: JsonDict | None,
    position_context: JsonDict,
    cash: JsonDict,
    price: float | None,
    is_trade_intent: bool,
    is_sell_put_intent: bool,
) -> JsonDict | None:
    rule_type = str(rule.get("rule_type") or "").lower()
    rule_key = str(rule.get("rule_key") or rule.get("name") or "custom")
    condition = rule.get("condition") if isinstance(rule.get("condition"), dict) else {}

    if rule_type == "time_window" or bool(condition.get("forbid_extended_hours") or condition.get("regular_session_only") or condition.get("market_hours_only")):
        if not is_trade_intent:
            return None
        if _is_regular_us_session(market):
            return _configured_rule_check(rule, "passed", "当前处于常规交易时段。", details={"market": market})
        return _configured_rule_check(rule, "failed", str(rule.get("message") or "当前不在常规交易时段。"), details={"market": market})

    concentration_threshold = _condition_number(
        condition,
        "max_concentration_pct",
        "max_position_concentration_pct",
        "max_single_position_pct",
        "threshold_pct",
    )
    if rule_type == "position_limit" or "concentration" in rule_key.lower() or concentration_threshold is not None:
        threshold_pct = _threshold_to_pct(concentration_threshold if concentration_threshold is not None else 30)
        concentration_pct = _json_number(position_context.get("concentration_pct"))
        if concentration_pct is None:
            return _configured_rule_check(rule, "unknown", "缺少组合市值，无法校验单票集中度。", action="require_confirmation", details={"threshold_pct": threshold_pct})
        if concentration_pct >= threshold_pct:
            return _configured_rule_check(
                rule,
                "failed",
                str(rule.get("message") or f"单票集中度 {concentration_pct:.1f}% 超过规则阈值 {threshold_pct:.1f}%。"),
                details={"concentration_pct": concentration_pct, "threshold_pct": threshold_pct},
            )
        return _configured_rule_check(rule, "passed", "单票集中度符合已配置纪律规则。", details={"concentration_pct": concentration_pct, "threshold_pct": threshold_pct})

    cash_threshold = _condition_number(condition, "min_cash_buffer_pct", "min_cash_buffer_ratio", "cash_buffer_min")
    if rule_type == "risk_budget" or "cash" in rule_key.lower() or cash_threshold is not None:
        if not (is_trade_intent or is_sell_put_intent):
            return None
        threshold_ratio = _threshold_to_ratio(cash_threshold if cash_threshold is not None else 0.1)
        buffer_ratio = _json_number(cash.get("cash_buffer_ratio"))
        if buffer_ratio is None:
            return _configured_rule_check(rule, "unknown", "缺少可用现金或总权益，无法校验现金缓冲纪律。", action="require_confirmation", details=cash)
        if buffer_ratio < threshold_ratio:
            return _configured_rule_check(
                rule,
                "failed",
                str(rule.get("message") or f"现金缓冲 {buffer_ratio:.1%} 低于规则阈值 {threshold_ratio:.1%}。"),
                details={**cash, "threshold_ratio": threshold_ratio},
            )
        return _configured_rule_check(rule, "passed", "现金缓冲符合已配置纪律规则。", details={**cash, "threshold_ratio": threshold_ratio})

    if rule_type == "blocklist" or _rule_key_mentions_china(rule_key):
        if _symbol_or_name_matches_rule(symbol=symbol, quote=quote, held_position=held_position, condition=condition, rule_key=rule_key):
            return _configured_rule_check(rule, "failed", str(rule.get("message") or "标的命中已配置禁止/提醒规则。"), details={"symbol": symbol})
        return None

    if rule_type == "confirmation_required" and bool(condition.get("always")):
        return _configured_rule_check(rule, "failed", str(rule.get("message") or "该动作需要确认。"), details={"prompt": prompt[:120]})

    if is_sell_put_intent and bool(condition.get("cash_secured")):
        cash_requirement = price * 100 if price else None
        available_cash = _json_number(cash.get("available_cash"))
        if cash_requirement is None or available_cash is None:
            return _configured_rule_check(rule, "unknown", "缺少价格或现金，无法校验 Sell Put 现金担保规则。", action="require_confirmation", details=cash)
        if available_cash < cash_requirement:
            return _configured_rule_check(
                rule,
                "failed",
                str(rule.get("message") or "Sell Put 现金担保不足。"),
                details={"cash_requirement": cash_requirement, "available_cash": available_cash},
            )
        return _configured_rule_check(rule, "passed", "Sell Put 现金担保符合已配置纪律规则。", details={"cash_requirement": cash_requirement, "available_cash": available_cash})

    return None


def _configured_rule_check(
    rule: JsonDict,
    status: str,
    message: str,
    *,
    action: str | None = None,
    details: JsonDict | None = None,
) -> JsonDict:
    normalized_action = _normalize_discipline_action(action or rule.get("action_on_violation"))
    if status == "passed":
        normalized_action = "none"
    return {
        "rule": f"trading_rules:{rule.get('rule_key') or rule.get('id') or 'custom'}",
        "rule_id": str(rule.get("id")) if rule.get("id") else None,
        "name": rule.get("name"),
        "status": status,
        "action": normalized_action,
        "severity": _severity_for_discipline_action(normalized_action),
        "message": message,
        "source": "trading_rules",
        "details": details or {},
    }


def _symbol_or_name_matches_rule(
    *,
    symbol: str,
    quote: JsonDict,
    held_position: JsonDict | None,
    condition: JsonDict,
    rule_key: str,
) -> bool:
    root_symbol = symbol.split(".", 1)[0].upper()
    patterns = _string_list(condition.get("symbol_patterns")) + _string_list(condition.get("symbols"))
    for pattern in patterns:
        normalized = pattern.strip().upper()
        if not normalized:
            continue
        if normalized.endswith("*") and root_symbol.startswith(normalized[:-1]):
            return True
        if root_symbol == normalized.split(".", 1)[0]:
            return True
    if _rule_key_mentions_china(rule_key) and root_symbol in CHINA_ADR_SYMBOLS:
        return True

    name_blob = " ".join(
        str(value or "")
        for value in (
            quote.get("name"),
            quote.get("stock_name"),
            (held_position or {}).get("name"),
            (held_position or {}).get("stock_name"),
        )
    )
    return any(keyword and keyword in name_blob for keyword in _string_list(condition.get("match_name_keywords")))


def _rule_key_mentions_china(rule_key: str) -> bool:
    lowered = rule_key.lower()
    return "china" in lowered or "adr" in lowered or "中概" in rule_key


def _condition_number(condition: JsonDict, *keys: str) -> float | None:
    for key in keys:
        value = _json_number(condition.get(key))
        if value is not None:
            return value
    return None


def _threshold_to_pct(value: float) -> float:
    return value * 100 if 0 < value <= 1 else value


def _threshold_to_ratio(value: float) -> float:
    return value / 100 if value > 1 else value


def _normalize_discipline_action(value: Any) -> str:
    action = str(value or "warn").strip().lower()
    return action if action in {"warn", "block", "require_confirmation"} else "warn"


def _severity_for_discipline_action(action: str) -> str:
    if action == "block":
        return "critical"
    if action == "require_confirmation":
        return "warning"
    if action == "warn":
        return "warning"
    return "info"


def _looks_like_trade_intent(prompt: str) -> bool:
    lowered = prompt.lower()
    keywords = ("买", "卖", "加仓", "减仓", "止盈", "止损", "要不要", "sell put", "下单", "开仓", "平仓")
    return any(keyword in lowered or keyword in prompt for keyword in keywords)


def _looks_like_sell_put_intent(prompt: str) -> bool:
    lowered = prompt.lower()
    return "sell put" in lowered or "卖put" in prompt or "卖 put" in prompt or "现金担保" in prompt


def _is_regular_us_session(market: str) -> bool:
    if market.upper() != "US":
        return True
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (13 * 60 + 30) <= minutes <= (20 * 60)


def _portfolio_cash_context(positions: JsonDict) -> JsonDict:
    available_cash = _first_number(positions, "available_cash", "cash", "cash_balance", "buying_power")
    total_equity = _first_number(positions, "total_equity", "net_liquidation", "portfolio_value", "total_market_value")
    if total_equity is None:
        total_equity = _sum_numbers(
            [
                _first_number(row, "market_value", "marketValue", "position_value")
                for row in positions.get("equity_positions", [])
                if isinstance(row, dict)
            ]
        )
        if total_equity is not None and available_cash is not None:
            total_equity += available_cash
    cash_buffer_ratio = None
    if available_cash is not None and total_equity and total_equity > 0:
        cash_buffer_ratio = available_cash / total_equity
    return {
        "available_cash": available_cash,
        "total_equity": total_equity,
        "cash_buffer_ratio": cash_buffer_ratio,
    }


def _highest_discipline_action(violations: list[JsonDict]) -> str:
    order = {"none": 0, "warn": 1, "require_confirmation": 2, "block": 3}
    highest = "none"
    for item in violations:
        action = str(item.get("action") or "none")
        if order.get(action, 0) > order[highest]:
            highest = action
    return highest


def _discipline_actionability_cap(highest_action: str, candidate_actionability: str) -> str:
    if highest_action == "block":
        return "blocked"
    if highest_action in {"warn", "require_confirmation"}:
        return "analysis_only"
    return candidate_actionability if candidate_actionability in {"blocked", "analysis_only", "trade_draft"} else "analysis_only"


def _discipline_summary(status: str, violations: list[JsonDict]) -> str:
    if status == "passed":
        return "纪律检查通过：未发现需要前置降级的规则。"
    action_rank = {"block": 0, "require_confirmation": 1, "warn": 2}
    ordered = sorted(violations, key=lambda item: action_rank.get(str(item.get("action") or "warn"), 9))
    messages = [str(item.get("message")) for item in ordered[:4] if item.get("message")]
    return "；".join(messages) if messages else f"纪律检查状态：{status}"


def _discipline_text(discipline_result: JsonDict) -> str:
    cap = discipline_result.get("actionability_cap") or "analysis_only"
    summary = discipline_result.get("summary") or "纪律检查完成。"
    return f"纪律前置：{cap}。{summary} 本报告不写入持仓事实，不下券商订单。"


def _historical_decision_compare(
    *,
    current_action: str,
    current_action_label: str,
    current_score: int | None,
    current_watch_conditions: list[str],
    previous_signals: list[JsonDict],
) -> JsonDict:
    if not previous_signals:
        return {
            "status": "no_history",
            "previous_count": 0,
            "summary": "暂无历史结论可比。",
            "latest": None,
            "action_change": None,
            "score_change": None,
            "repeated_watch_conditions_count": 0,
        }

    latest = previous_signals[0]
    previous_action = str(latest.get("action") or "")
    previous_label = str(latest.get("action_label") or previous_action or "未知")
    previous_score = _json_number(latest.get("score"))
    score_change = None
    if current_score is not None and previous_score is not None:
        score_change = round(float(current_score) - previous_score, 2)

    previous_conditions = {
        str(item).strip()
        for item in (latest.get("watch_conditions") or [])
        if str(item).strip()
    }
    current_conditions = {str(item).strip() for item in current_watch_conditions if str(item).strip()}
    repeated_count = len(previous_conditions & current_conditions)
    changed = previous_action != current_action
    status = "changed" if changed else "stable"
    action_change = f"{previous_label} -> {current_action_label}" if changed else f"维持 {current_action_label}"
    score_text = f"，评分变化 {score_change:+.0f}" if score_change is not None else ""
    repeated_text = f"，重复观察条件 {repeated_count} 条" if repeated_count else ""

    return {
        "status": status,
        "previous_count": len(previous_signals),
        "summary": f"上次结论 {previous_label}，本次 {current_action_label}{score_text}{repeated_text}。",
        "latest": latest,
        "action_change": action_change,
        "score_change": score_change,
        "repeated_watch_conditions_count": repeated_count,
    }


def _history_compare_text(history_compare: JsonDict) -> str:
    if history_compare.get("status") == "no_history":
        return "历史对比：暂无历史结论可比。"
    return f"历史对比：{history_compare.get('summary') or '已有历史结论，但摘要不足。'}"


def _news_context_text(news_context: JsonDict) -> str:
    if news_context.get("status") != "available":
        return "新闻/催化剂：未配置可用新闻或事件源，结论不能覆盖突发消息。"
    items = news_context.get("items") if isinstance(news_context.get("items"), list) else []
    catalysts = news_context.get("catalysts") if isinstance(news_context.get("catalysts"), list) else []
    parts: list[str] = []
    if items:
        headline = _first_text(items[0], "headline") if isinstance(items[0], dict) else None
        if headline:
            parts.append(f"最新消息：{headline}")
    if catalysts:
        catalyst = catalysts[0] if isinstance(catalysts[0], dict) else {}
        label = _first_text(catalyst, "label", "type") or "事件窗口"
        date_text = _first_text(catalyst, "date")
        parts.append(f"催化剂：{label}{'（' + date_text + '）' if date_text else ''}")
    summary = str(news_context.get("summary") or "").strip()
    if summary and not parts:
        parts.append(summary)
    return "新闻/催化剂：" + ("；".join(parts) if parts else "已接入来源，但暂无高置信新闻或事件。")


def _social_context_text(social_context: JsonDict) -> str:
    if social_context.get("status") != "available":
        return "社媒信号：未配置有限账号清单或社媒读取源，不纳入社区情绪判断。"
    items = social_context.get("items") if isinstance(social_context.get("items"), list) else []
    themes = social_context.get("themes") if isinstance(social_context.get("themes"), list) else []
    sentiment = social_context.get("sentiment") if isinstance(social_context.get("sentiment"), dict) else {}
    parts: list[str] = []
    label = _first_text(sentiment, "label")
    confidence = _first_text(sentiment, "confidence")
    if label and label != "unknown":
        parts.append(f"情绪 {label}{'（' + confidence + '）' if confidence else ''}")
    if themes:
        theme = themes[0] if isinstance(themes[0], dict) else {}
        theme_label = _first_text(theme, "label")
        stance = _first_text(theme, "stance")
        if theme_label:
            parts.append(f"主题：{theme_label}{'/' + stance if stance else ''}")
    if items and not parts:
        text = _first_text(items[0], "text")
        if text:
            parts.append(f"样本：{text[:80]}")
    summary = str(social_context.get("summary") or "").strip()
    if summary and not parts:
        parts.append(summary)
    return "社媒信号：" + ("；".join(parts) if parts else "有限账号清单已接入，但暂无高置信社区信号。")


def _why_changed_summary(
    *,
    history_compare: JsonDict,
    news_context: JsonDict,
    social_context: JsonDict,
    market_regime: JsonDict,
    sector_context: JsonDict,
    trend: JsonDict,
) -> JsonDict:
    drivers: list[str] = []
    if history_compare.get("status") == "changed":
        drivers.append(f"结论变化：{history_compare.get('action_change')}")
    change_5d = trend.get("change_5d_pct")
    if isinstance(change_5d, (int, float)):
        if abs(change_5d) >= 5:
            drivers.append(f"5日价格变化 {change_5d:+.2f}%")
        elif abs(change_5d) >= 2:
            drivers.append(f"5日小幅变化 {change_5d:+.2f}%")
    latest_sector = sector_context.get("latest") if isinstance(sector_context.get("latest"), dict) else {}
    sector_change = latest_sector.get("change_pct")
    if isinstance(sector_change, (int, float)) and abs(sector_change) >= 1:
        drivers.append(f"板块变化 {sector_change:+.2f}%")
    if market_regime.get("status") == "available" and market_regime.get("regime") not in {None, "unknown"}:
        drivers.append(f"市场状态 {market_regime.get('regime')}")
    if news_context.get("status") == "available":
        items = news_context.get("items") if isinstance(news_context.get("items"), list) else []
        catalysts = news_context.get("catalysts") if isinstance(news_context.get("catalysts"), list) else []
        if items:
            drivers.append(f"新增消息 {len(items)} 条")
        if catalysts:
            drivers.append(f"催化剂 {len(catalysts)} 个")
    if social_context.get("status") == "available":
        items = social_context.get("items") if isinstance(social_context.get("items"), list) else []
        sentiment = social_context.get("sentiment") if isinstance(social_context.get("sentiment"), dict) else {}
        sentiment_label = _first_text(sentiment, "label")
        if items:
            drivers.append(f"有限账号社媒样本 {len(items)} 条")
        if sentiment_label and sentiment_label != "unknown":
            drivers.append(f"社媒情绪 {sentiment_label}")

    if not drivers:
        return {
            "status": "insufficient_context",
            "drivers": [],
            "summary": "为什么变了：缺少可解释的历史、新闻、社媒或市场上下文，先按数据质量降级处理。",
        }
    status = "changed_explained" if history_compare.get("status") == "changed" else "context_explained"
    return {
        "status": status,
        "drivers": drivers,
        "summary": "为什么变了：" + "；".join(drivers[:4]) + "。",
    }


def _why_changed_text(why_changed: JsonDict) -> str:
    summary = str(why_changed.get("summary") or "").strip()
    if summary:
        return summary
    return "为什么变了：解释上下文不足。"


def _trend_text(trend: JsonDict) -> str:
    parts: list[str] = []
    for label, key in (("5日", "change_5d_pct"), ("10日", "change_10d_pct")):
        value = trend.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{label}{value:+.2f}%")
    return "，".join(parts) if parts else "历史数据不足"


def _history_trend(history_payload: JsonDict) -> JsonDict:
    data = _payload_data(history_payload)
    bars = data.get("bars") if isinstance(data.get("bars"), list) else []
    closes: list[float] = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        value = _first_number(bar, "close", "close_price", "adj_close")
        if value is not None:
            closes.append(value)
    if len(closes) < 2:
        return {"status": _history_status(history_payload)}

    return {
        "status": _history_status(history_payload),
        "change_5d_pct": _period_change(closes, 5),
        "change_10d_pct": _period_change(closes, 10),
    }


def _period_change(closes: list[float], periods: int) -> float | None:
    if len(closes) <= periods:
        return None
    base = closes[-periods - 1]
    latest = closes[-1]
    if base == 0:
        return None
    return round(((latest - base) / base) * 100, 2)


def _watch_conditions(*, price: float | None, held_position: JsonDict | None, pnl_pct: float | None) -> list[str]:
    conditions: list[str] = []
    if price is not None:
        conditions.append(f"观察价格是否有效突破或跌破 {price:.2f} 附近")
    if held_position and pnl_pct is not None and pnl_pct >= 20:
        conditions.append("复核是否需要分批止盈或上移止损")
    if held_position and pnl_pct is not None and pnl_pct <= -10:
        conditions.append("复核原始买入理由是否仍成立")
    if not held_position:
        conditions.append("如符合纪律，可加入关注清单并设置目标买入区")
    return conditions


def _follow_item_payload(
    *,
    tenant_id: str,
    follow_view_id: str,
    symbol: str,
    analysis: JsonDict,
    context: JsonDict,
    source_run_id: Any,
    source_artifact_id: Any,
    decision_signal_id: Any,
) -> JsonDict:
    report = analysis.get("report") if isinstance(analysis.get("report"), dict) else {}
    watch_conditions = analysis.get("watch_conditions") if isinstance(analysis.get("watch_conditions"), list) else []
    trigger_rules = [
        {
            "source": "stock.analysis",
            "condition": str(condition),
            "actionability_cap": analysis.get("actionability_cap") or "analysis_only",
        }
        for condition in watch_conditions
        if str(condition).strip()
    ]
    current_price = analysis.get("current_price")
    if isinstance(current_price, (int, float)):
        trigger_rules.append(
            {
                "source": "stock.analysis",
                "condition": "price_move_from_analysis_reference",
                "reference_price": current_price,
                "move_threshold_pct": 5,
            }
        )

    return {
        "tenant_id": tenant_id,
        "follow_view_id": follow_view_id,
        "symbol": symbol,
        "name": analysis.get("name") or symbol,
        "market": analysis.get("market") or "US",
        "target_action": analysis.get("action") or "watch",
        "thesis": report.get("conclusion") or analysis.get("short_reply") or f"{symbol} 分析观察项",
        "target_buy_zone": {},
        "sell_put_preferences": {},
        "trigger_rules": trigger_rules,
        "risk_flags": [str(item) for item in (analysis.get("risk_flags") or [])],
        "next_review_at": analysis.get("review_due_at"),
        "data_lineage": [
            {
                "source": "stock.analysis",
                "source_run_id": str(source_run_id) if source_run_id else None,
                "source_artifact_id": str(source_artifact_id) if source_artifact_id else None,
                "decision_signal_id": str(decision_signal_id) if decision_signal_id else None,
                "source_refs": context.get("source_refs") or [],
            }
        ],
    }


def _analysis_alert_payloads(
    *,
    tenant_id: str,
    symbol: str,
    analysis: JsonDict,
    decision_signal_id: Any,
) -> list[JsonDict]:
    market = analysis.get("market") or "US"
    review_due_at = analysis.get("review_due_at")
    base_parameters = {
        "actionability_cap": analysis.get("actionability_cap") or "analysis_only",
        "review_due_at": review_due_at,
        "reference_price": analysis.get("current_price"),
        "currency": analysis.get("currency"),
        "move_threshold_pct": 5,
        "evaluation": "price_move_or_review_due",
    }
    notification_policy = {
        "channels": ["wechat"],
        "message_style": "brief",
        "command_hint": f"复核 {symbol}",
    }
    cooldown_policy = {"cooldown_hours": 18, "same_trading_day": True}

    payloads: list[JsonDict] = []
    for index, condition in enumerate(analysis.get("watch_conditions") or []):
        condition_text = str(condition).strip()
        if not condition_text:
            continue
        payloads.append(
            {
                "tenant_id": tenant_id,
                "decision_signal_id": str(decision_signal_id) if decision_signal_id else None,
                "name": f"{symbol} 观察条件 {index + 1}",
                "target_scope": "single_symbol",
                "target_symbol": symbol,
                "market": market,
                "alert_type": "decision_watch_condition",
                "parameters": {**base_parameters, "condition": condition_text},
                "severity": "warning",
                "enabled": True,
                "cooldown_policy": cooldown_policy,
                "notification_policy": notification_policy,
                "source": "decision_signal",
                "expires_at": review_due_at,
            }
        )
    return payloads


def _discipline_check_payload(
    *,
    tenant_id: str,
    agent_run_id: Any,
    symbol: str,
    analysis: JsonDict,
    source_artifact_id: Any,
    decision_signal_id: Any,
) -> JsonDict:
    discipline_result = analysis.get("discipline_result") if isinstance(analysis.get("discipline_result"), dict) else {}
    result = _normalize_discipline_result(discipline_result.get("status"))
    highest_action = str(discipline_result.get("highest_action") or "none")
    if highest_action not in {"none", "warn", "block", "require_confirmation"}:
        highest_action = "none"
    triggered_rule_ids = _triggered_trading_rule_ids(discipline_result)
    prompt = str(analysis.get("prompt") or "")
    return {
        "tenant_id": tenant_id,
        "agent_run_id": agent_run_id,
        "symbol": symbol,
        "instrument_type": "option_contract" if _looks_like_sell_put_intent(prompt) else "stock",
        "action_type": str(analysis.get("action") or "stock.analysis"),
        "result": result,
        "triggered_rule_ids": triggered_rule_ids,
        "highest_action": highest_action,
        "check_payload": {
            "schema_version": "discipline_check_payload_v1",
            "source": "stock.analysis",
            "source_artifact_id": str(source_artifact_id) if source_artifact_id else None,
            "decision_signal_id": str(decision_signal_id) if decision_signal_id else None,
            "actionability_cap": analysis.get("actionability_cap"),
            "action": analysis.get("action"),
            "action_label": analysis.get("action_label"),
            "summary": discipline_result.get("summary"),
            "checks": discipline_result.get("checks") or [],
            "violations": discipline_result.get("violations") or [],
        },
    }


def _normalize_discipline_result(value: Any) -> str:
    status = str(value or "").strip().lower()
    return status if status in {"passed", "warned", "blocked", "requires_confirmation"} else "passed"


def _triggered_trading_rule_ids(discipline_result: JsonDict) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    items: list[Any] = []
    for key in ("violations", "checks"):
        values = discipline_result.get(key)
        if isinstance(values, list):
            items.extend(values)
    for item in items:
        if not isinstance(item, dict) or item.get("source") != "trading_rules":
            continue
        rule_id = str(item.get("rule_id") or "").strip()
        if not rule_id or rule_id in seen or not _is_uuid(rule_id):
            continue
        seen.add(rule_id)
        ids.append(rule_id)
    return ids


def _sync_follow_item_postgres(
    *,
    cur: Any,
    tenant_id: str,
    symbol: str,
    analysis: JsonDict,
    context: JsonDict,
    source_run_id: Any,
    source_artifact_id: Any,
    decision_signal_id: Any,
) -> JsonDict:
    from psycopg.types.json import Jsonb

    view = _fetch_one(
        cur.execute(
            """
            WITH existing AS (
              SELECT id
              FROM public.follow_views
              WHERE tenant_id = %(tenant_id)s
              ORDER BY is_default DESC, created_at ASC
              LIMIT 1
            ), inserted AS (
              INSERT INTO public.follow_views (
                tenant_id, name, slug, strategy_focus, base_currency, is_default, settings
              )
              SELECT %(tenant_id)s, '关注清单', 'default-follow', 'watchlist', 'USD', true, %(settings)s
              WHERE NOT EXISTS (SELECT 1 FROM existing)
              ON CONFLICT (tenant_id, slug) DO UPDATE
              SET name = EXCLUDED.name,
                  strategy_focus = EXCLUDED.strategy_focus,
                  settings = public.follow_views.settings || EXCLUDED.settings
              RETURNING id
            )
            SELECT id FROM inserted
            UNION ALL
            SELECT id FROM existing
            LIMIT 1
            """,
            {"tenant_id": tenant_id, "settings": Jsonb({"source": "hermes_stock_analysis"})},
        )
    )
    follow_view_id = view.get("id")
    if not follow_view_id:
        return {}

    payload = _follow_item_payload(
        tenant_id=tenant_id,
        follow_view_id=str(follow_view_id),
        symbol=symbol,
        analysis=analysis,
        context=context,
        source_run_id=source_run_id,
        source_artifact_id=source_artifact_id,
        decision_signal_id=decision_signal_id,
    )
    return _fetch_one(
        cur.execute(
            """
            INSERT INTO public.follow_view_items (
              tenant_id, follow_view_id, symbol, name, market, target_action,
              thesis, target_buy_zone, sell_put_preferences, trigger_rules,
              risk_flags, next_review_at, data_lineage
            )
            VALUES (
              %(tenant_id)s, %(follow_view_id)s, %(symbol)s, %(name)s, %(market)s, %(target_action)s,
              %(thesis)s, %(target_buy_zone)s, %(sell_put_preferences)s, %(trigger_rules)s,
              %(risk_flags)s, %(next_review_at)s, %(data_lineage)s
            )
            ON CONFLICT (follow_view_id, symbol, market) DO UPDATE
            SET name = EXCLUDED.name,
                target_action = EXCLUDED.target_action,
                thesis = EXCLUDED.thesis,
                trigger_rules = EXCLUDED.trigger_rules,
                risk_flags = EXCLUDED.risk_flags,
                next_review_at = EXCLUDED.next_review_at,
                data_lineage = public.follow_view_items.data_lineage || EXCLUDED.data_lineage,
                updated_at = now()
            RETURNING id
            """,
            {
                **payload,
                "target_buy_zone": Jsonb(payload["target_buy_zone"]),
                "sell_put_preferences": Jsonb(payload["sell_put_preferences"]),
                "trigger_rules": Jsonb(payload["trigger_rules"]),
                "data_lineage": Jsonb(payload["data_lineage"]),
            },
        )
    )


async def _safe_call(fn: Callable[..., Awaitable[JsonDict]], *args: Any) -> JsonDict:
    try:
        return await fn(*args)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "data": {}}


def _payload_data(payload: JsonDict) -> JsonDict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, dict):
            return nested
        return data
    return payload if payload.get("ok") is not False else {}


def _find_position(symbol: str, positions: JsonDict) -> JsonDict | None:
    candidates: list[JsonDict] = []
    for key in ("equity_positions", "option_positions"):
        rows = positions.get(key)
        if isinstance(rows, list):
            candidates.extend([row for row in rows if isinstance(row, dict)])
    normalized = _normalize_symbol(symbol)
    for row in candidates:
        row_symbol = _normalize_symbol(str(row.get("symbol") or row.get("provider_symbol") or ""))
        if row_symbol == normalized:
            return row
    return None


def _positions_total(positions: JsonDict) -> int:
    total = 0
    for key in ("equity_positions", "option_positions"):
        rows = positions.get(key)
        if isinstance(rows, list):
            total += len(rows)
    return total


def _first_number(payload: JsonDict, *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_text(payload: JsonDict, *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_temporal_text(payload: JsonDict, *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and value > 0:
            seconds = value / 1000 if value > 10_000_000_000 else value
            try:
                return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                continue
    return None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _sum_numbers(values: list[float | None]) -> float | None:
    total = 0.0
    found = False
    for value in values:
        if value is None:
            continue
        total += value
        found = True
    return total if found else None


def _json_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _market_from_quote_or_symbol(quote: JsonDict, symbol: str) -> str:
    market = str(quote.get("market") or "").upper()
    if market:
        return market
    if symbol.startswith(("SH", "SZ")):
        return "CN"
    if symbol.startswith("HK"):
        return "HK"
    return "US"


def _history_status(payload: JsonDict) -> str:
    data = _payload_data(payload)
    if not data:
        return "unavailable"
    return str(data.get("cache_status") or data.get("status") or "unknown")


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _clip_module(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= MAX_REPORT_MODULE_CHARS:
        return compact
    return compact[: MAX_REPORT_MODULE_CHARS - 1].rstrip() + "…"


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _insert_one(builder: Any) -> JsonDict:
    response = builder.execute()
    data = getattr(response, "data", None)
    if isinstance(data, list) and data:
        return dict(data[0])
    if isinstance(data, dict):
        return dict(data)
    return {}


def _fetch_one(cursor: Any) -> JsonDict:
    row = cursor.fetchone()
    return dict(row) if row else {}


def _run_key(*, symbol: str, analysis: JsonDict, entry_surface: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"stock-analysis:{entry_surface}:{symbol}:{timestamp}:{_short_hash(analysis)}"


def _short_hash(payload: JsonDict) -> str:
    return _sha256_json(payload)[:10]


def _sha256_json(payload: JsonDict) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
