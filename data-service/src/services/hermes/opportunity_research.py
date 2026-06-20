from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID


JsonDict = dict[str, Any]
AsyncToolReader = Callable[[dict[str, Any]], Awaitable[JsonDict]]

OPPORTUNITY_RESEARCH_SCHEMA_VERSION = "opportunity_research_v1"
OPPORTUNITY_LEDGER_SCHEMA_VERSION = "opportunity_ledger_v1"
OPPORTUNITY_CANDIDATE_POOL_SCHEMA_VERSION = "opportunity_candidate_pool_v1"
DEFAULT_STRATEGY_MODEL_VERSION = "opportunity-research-v1"
LEADER_MIN_STRENGTH_SCORE = 45.0
LEADER_GROUP_TOP_N = 3

FIVE_LAYER_CAKE_LAYERS = {
    "accelerated_compute": "GPU/ASIC/加速计算",
    "networking": "高速网络/互联",
    "systems_foundry": "整机/代工/封测",
    "power_infrastructure": "电力/数据中心基础设施",
    "ai_application": "AI 应用/云平台变现",
}

THEME_PATHS = {
    "ai_semiconductor_power_chain": "AI / 半导体 / 电力链",
    "traditional_cycle_demand_smallcap": "传统周期 / 内需 / 小盘",
    "gold": "黄金",
    "copper_miner": "铜 / 铜矿",
    "broad_commodities": "商品广谱",
    "cash_short_duration": "现金 / 短债",
}

THEMATIC_CANDIDATE_UNIVERSE: dict[str, list[JsonDict]] = {
    "US": [
        {"symbol": "NVDA", "asset_theme": "AI compute", "asset_path": "ai_semiconductor_power_chain", "five_layer": "accelerated_compute", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "AVGO", "asset_theme": "AI networking/custom silicon", "asset_path": "ai_semiconductor_power_chain", "five_layer": "networking", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "AMD", "asset_theme": "AI accelerator challenger", "asset_path": "ai_semiconductor_power_chain", "five_layer": "accelerated_compute", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "TSM", "asset_theme": "advanced foundry", "asset_path": "ai_semiconductor_power_chain", "five_layer": "systems_foundry", "playbook_key": "ai_capex"},
        {"symbol": "SMH", "asset_theme": "semiconductor basket", "asset_path": "ai_semiconductor_power_chain", "five_layer": "systems_foundry", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "QQQ", "asset_theme": "Nasdaq AI beta", "asset_path": "ai_semiconductor_power_chain", "five_layer": "ai_application", "playbook_key": "ai_capex"},
        {"symbol": "VRT", "asset_theme": "AI data center power/cooling", "asset_path": "ai_semiconductor_power_chain", "five_layer": "power_infrastructure", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "ANET", "asset_theme": "AI data center networking", "asset_path": "ai_semiconductor_power_chain", "five_layer": "networking", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "MSFT", "asset_theme": "AI cloud platform", "asset_path": "ai_semiconductor_power_chain", "five_layer": "ai_application", "playbook_key": "ai_capex"},
        {"symbol": "GDX", "asset_theme": "gold miners", "asset_path": "gold", "five_layer": "macro_hedge", "playbook_key": "gold"},
        {"symbol": "COPX", "asset_theme": "copper miners", "asset_path": "copper_miner", "five_layer": "commodity_supply", "playbook_key": "copper"},
        {"symbol": "IWM", "asset_theme": "small-cap cyclicals", "asset_path": "traditional_cycle_demand_smallcap", "five_layer": "rate_sensitive_beta", "playbook_key": "cycle_repair"},
    ],
    "CN": [
        {"symbol": "SH588000", "asset_theme": "科创硬科技", "asset_path": "ai_semiconductor_power_chain", "five_layer": "ai_application", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "SH512480", "asset_theme": "半导体国产替代", "asset_path": "ai_semiconductor_power_chain", "five_layer": "systems_foundry", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "SH688008", "asset_theme": "内存接口芯片", "asset_path": "ai_semiconductor_power_chain", "five_layer": "networking", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "SH688521", "asset_theme": "IP/芯片设计服务", "asset_path": "ai_semiconductor_power_chain", "five_layer": "systems_foundry", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "SZ159915", "asset_theme": "创业板成长", "asset_path": "traditional_cycle_demand_smallcap", "five_layer": "rate_sensitive_beta", "playbook_key": "cycle_repair"},
        {"symbol": "SH518880", "asset_theme": "黄金 ETF", "asset_path": "gold", "five_layer": "macro_hedge", "playbook_key": "gold"},
        {"symbol": "SH512400", "asset_theme": "有色金属", "asset_path": "copper_miner", "five_layer": "commodity_supply", "playbook_key": "copper"},
    ],
    "HK": [
        {"symbol": "HK03033", "asset_theme": "恒生科技 beta", "asset_path": "ai_semiconductor_power_chain", "five_layer": "ai_application", "playbook_key": "ai_capex"},
        {"symbol": "HK00981", "asset_theme": "中芯制造链", "asset_path": "ai_semiconductor_power_chain", "five_layer": "systems_foundry", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "HK01347", "asset_theme": "半导体设备链", "asset_path": "ai_semiconductor_power_chain", "five_layer": "systems_foundry", "playbook_key": "hard_tech_acceleration"},
        {"symbol": "HK02800", "asset_theme": "港股大盘修复", "asset_path": "traditional_cycle_demand_smallcap", "five_layer": "rate_sensitive_beta", "playbook_key": "cycle_repair"},
        {"symbol": "HK02840", "asset_theme": "黄金 ETF", "asset_path": "gold", "five_layer": "macro_hedge", "playbook_key": "gold"},
    ],
}

BENCHMARK_BY_PLAYBOOK: dict[str, dict[str, str]] = {
    "hard_tech_acceleration": {"US": "SOXX", "CN": "SH512480", "HK": "HK03033"},
    "ai_capex": {"US": "QQQ", "CN": "SH588000", "HK": "HK03033"},
    "sell_put_income": {"US": "QQQ", "CN": "SH510300", "HK": "HK02800"},
    "default": {"US": "QQQ", "CN": "SH510300", "HK": "HK02800"},
}


@dataclass(frozen=True)
class OpportunityResearchResult:
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


class OpportunityResearchPersistence:
    def __init__(self, client: Any | None = None, database_url: str = "") -> None:
        self._client = client
        self._database_url = database_url

    @classmethod
    def from_env(cls) -> "OpportunityResearchPersistence":
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

    async def save_research(
        self,
        *,
        tenant_id: str,
        market: str,
        session_type: str,
        report_date: str,
        payload: JsonDict,
        cases: list[JsonDict],
        delivery_context: JsonDict | None = None,
    ) -> JsonDict:
        if self._client is None and not self._database_url:
            return {"status": "skipped", "reason": "persistence_not_configured"}
        if not _is_uuid(tenant_id):
            return {"status": "skipped", "reason": "tenant_id_is_not_uuid"}
        try:
            if self._database_url and self._client is None:
                return await asyncio.to_thread(
                    self._save_research_postgres_sync,
                    tenant_id=tenant_id,
                    market=market,
                    session_type=session_type,
                    report_date=report_date,
                    payload=payload,
                    cases=cases,
                    delivery_context=delivery_context or {},
                )
            return await asyncio.to_thread(
                self._save_research_supabase_sync,
                tenant_id=tenant_id,
                market=market,
                session_type=session_type,
                report_date=report_date,
                payload=payload,
                cases=cases,
                delivery_context=delivery_context or {},
            )
        except Exception as exc:
            return {"status": "failed", "reason": str(exc)}

    async def mark_case(
        self,
        *,
        tenant_id: str,
        case_id: str,
        mark: JsonDict,
    ) -> JsonDict:
        if self._client is None and not self._database_url:
            return {"status": "skipped", "reason": "persistence_not_configured", "mark": mark}
        if not _is_uuid(tenant_id) or not _is_uuid(case_id):
            return {"status": "skipped", "reason": "invalid_uuid", "mark": mark}
        try:
            if self._database_url and self._client is None:
                return await asyncio.to_thread(self._mark_case_postgres_sync, tenant_id=tenant_id, case_id=case_id, mark=mark)
            return await asyncio.to_thread(self._mark_case_supabase_sync, tenant_id=tenant_id, case_id=case_id, mark=mark)
        except Exception as exc:
            return {"status": "failed", "reason": str(exc), "mark": mark}

    async def load_open_cases(self, *, tenant_id: str, market: str | None = None, limit: int = 20) -> list[JsonDict]:
        if not self._database_url or not _is_uuid(tenant_id):
            return []
        return await asyncio.to_thread(self._load_open_cases_postgres_sync, tenant_id=tenant_id, market=market, limit=limit)

    async def load_candidate_pool(self, *, tenant_id: str, market: str) -> list[JsonDict]:
        if self._client is None and not self._database_url:
            return []
        if not _is_uuid(tenant_id):
            return []
        try:
            if self._database_url and self._client is None:
                return await asyncio.to_thread(self._load_candidate_pool_postgres_sync, tenant_id=tenant_id, market=market)
            return await asyncio.to_thread(self._load_candidate_pool_supabase_sync, tenant_id=tenant_id, market=market)
        except Exception:
            return []

    def _save_research_supabase_sync(
        self,
        *,
        tenant_id: str,
        market: str,
        session_type: str,
        report_date: str,
        payload: JsonDict,
        cases: list[JsonDict],
        delivery_context: JsonDict,
    ) -> JsonDict:
        now = datetime.now(timezone.utc).isoformat()
        run_key = f"opportunity-research:{tenant_id}:{market}:{report_date}:{session_type}"
        agent_run = _insert_one(
            self._client.table("agent_runs").upsert(
                {
                    "tenant_id": tenant_id,
                    "trigger": "cron" if session_type != "manual" else "webapp_action",
                    "entry_surface": "system",
                    "intent": "opportunity.research",
                    "complexity": "standard",
                    "risk_level": "medium",
                    "runtime_target": "hermes",
                    "actionability_cap": payload.get("max_actionability") or "analysis_only",
                    "status": "succeeded",
                    "page_context": {"market": market, "report_date": report_date, "session_type": session_type},
                    "input_refs": payload.get("source_refs") or [],
                    "output_refs": [],
                    "idempotency_key": run_key,
                    "started_at": now,
                    "completed_at": now,
                },
                on_conflict="tenant_id,idempotency_key",
            )
        )
        run_id = agent_run.get("id")
        artifact = _insert_one(
            self._client.table("artifact_registry").upsert(
                {
                    "tenant_id": tenant_id,
                    "source_run_id": run_id,
                    "artifact_key": f"opportunity-research:{market}:{report_date}:{session_type}",
                    "artifact_type": "opportunity_research_report",
                    "artifact_status": "ready",
                    "visibility": "tenant",
                    "storage_backend": "inline_metadata",
                    "storage_path": f"inline://opportunity-research/{run_id or run_key}.json",
                    "mime_type": "application/json",
                    "content_hash": _sha256_json(payload),
                    "source_lineage": payload.get("source_refs") or [],
                    "artifact_metadata": payload,
                },
                on_conflict="tenant_id,artifact_key",
            )
        )
        inserted_cases = []
        for case in cases:
            inserted = _insert_one(self._client.table("opportunity_cases").upsert(_case_payload(tenant_id, run_id, artifact.get("id"), case), on_conflict="tenant_id,dedupe_key"))
            if inserted:
                inserted_cases.append(inserted)
        candidate_pool = self._save_candidate_pool_supabase_sync(tenant_id=tenant_id, report_date=report_date, candidate_pool=payload.get("candidate_pool") or {})
        delivery = self._enqueue_delivery_supabase(
            tenant_id=tenant_id,
            run_id=run_id,
            artifact_id=artifact.get("id"),
            market=market,
            report_date=report_date,
            session_type=session_type,
            payload=payload,
            delivery_context=delivery_context,
        )
        return {"status": "saved", "backend": "supabase", "agent_run_id": run_id, "artifact_id": artifact.get("id"), "opportunity_case_ids": [row.get("id") for row in inserted_cases if row.get("id")], "candidate_pool": candidate_pool, "delivery": delivery}

    def _save_research_postgres_sync(
        self,
        *,
        tenant_id: str,
        market: str,
        session_type: str,
        report_date: str,
        payload: JsonDict,
        cases: list[JsonDict],
        delivery_context: JsonDict,
    ) -> JsonDict:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            return {"status": "skipped", "reason": f"psycopg_not_installed: {exc}"}

        now = datetime.now(timezone.utc)
        run_key = f"opportunity-research:{tenant_id}:{market}:{report_date}:{session_type}"
        with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                run = _fetch_one(
                    cur.execute(
                        """
                        INSERT INTO public.agent_runs (
                          tenant_id, trigger, entry_surface, intent, complexity, risk_level,
                          runtime_target, actionability_cap, status, page_context, input_refs,
                          output_refs, idempotency_key, started_at, completed_at
                        )
                        VALUES (
                          %(tenant_id)s, %(trigger)s, 'system', 'opportunity.research',
                          'standard', 'medium', 'hermes', %(actionability)s, 'succeeded',
                          %(page_context)s, %(input_refs)s, '[]'::jsonb, %(run_key)s, %(now)s, %(now)s
                        )
                        ON CONFLICT (tenant_id, idempotency_key) DO UPDATE SET
                          actionability_cap = EXCLUDED.actionability_cap,
                          status = EXCLUDED.status,
                          page_context = EXCLUDED.page_context,
                          input_refs = EXCLUDED.input_refs,
                          completed_at = EXCLUDED.completed_at
                        RETURNING id
                        """,
                        {
                            "tenant_id": tenant_id,
                            "trigger": "cron" if session_type != "manual" else "webapp_action",
                            "actionability": payload.get("max_actionability") or "analysis_only",
                            "page_context": Jsonb({"market": market, "report_date": report_date, "session_type": session_type}),
                            "input_refs": Jsonb(payload.get("source_refs") or []),
                            "run_key": run_key,
                            "now": now,
                        },
                    )
                )
                run_id = run.get("id")
                artifact = _fetch_one(
                    cur.execute(
                        """
                        INSERT INTO public.artifact_registry (
                          tenant_id, source_run_id, artifact_key, artifact_type, artifact_status,
                          visibility, storage_backend, storage_path, mime_type, content_hash,
                          source_lineage, artifact_metadata
                        )
                        VALUES (
                          %(tenant_id)s, %(run_id)s, %(artifact_key)s, 'opportunity_research_report',
                          'ready', 'tenant', 'inline_metadata', %(storage_path)s, 'application/json',
                          %(content_hash)s, %(source_lineage)s, %(artifact_metadata)s
                        )
                        ON CONFLICT (tenant_id, artifact_key) DO UPDATE SET
                          source_run_id = EXCLUDED.source_run_id,
                          content_hash = EXCLUDED.content_hash,
                          source_lineage = EXCLUDED.source_lineage,
                          artifact_metadata = EXCLUDED.artifact_metadata,
                          updated_at = now()
                        RETURNING id
                        """,
                        {
                            "tenant_id": tenant_id,
                            "run_id": run_id,
                            "artifact_key": f"opportunity-research:{market}:{report_date}:{session_type}",
                            "storage_path": f"inline://opportunity-research/{run_id or run_key}.json",
                            "content_hash": _sha256_json(payload),
                            "source_lineage": Jsonb(payload.get("source_refs") or []),
                            "artifact_metadata": Jsonb(payload),
                        },
                    )
                )
                case_ids = []
                for case in cases:
                    case_row = _case_payload(tenant_id, run_id, artifact.get("id"), case)
                    inserted = _fetch_one(
                        cur.execute(
                            """
                            INSERT INTO public.opportunity_cases (
                              tenant_id, source_run_id, source_artifact_id, decision_signal_id,
                              market, symbol, instrument_type, asset_theme, narrative, playbook_key,
                              horizon, actionability_cap, position_layer, budget_layer, entry_rule,
                              exit_rule, benchmark_policy, strategy_model_version, status,
                              invalidation, trigger_conditions, source_refs, data_quality,
                              discipline_snapshot, dedupe_key, opened_at, expires_at
                            )
                            VALUES (
                              %(tenant_id)s, %(source_run_id)s, %(source_artifact_id)s, %(decision_signal_id)s,
                              %(market)s, %(symbol)s, %(instrument_type)s, %(asset_theme)s, %(narrative)s, %(playbook_key)s,
                              %(horizon)s, %(actionability_cap)s, %(position_layer)s, %(budget_layer)s, %(entry_rule)s,
                              %(exit_rule)s, %(benchmark_policy)s, %(strategy_model_version)s, %(status)s,
                              %(invalidation)s, %(trigger_conditions)s, %(source_refs)s, %(data_quality)s,
                              %(discipline_snapshot)s, %(dedupe_key)s, %(opened_at)s, %(expires_at)s
                            )
                            ON CONFLICT (tenant_id, dedupe_key) DO UPDATE SET
                              source_run_id = EXCLUDED.source_run_id,
                              source_artifact_id = EXCLUDED.source_artifact_id,
                              decision_signal_id = COALESCE(EXCLUDED.decision_signal_id, opportunity_cases.decision_signal_id),
                              narrative = EXCLUDED.narrative,
                              actionability_cap = EXCLUDED.actionability_cap,
                              source_refs = EXCLUDED.source_refs,
                              data_quality = EXCLUDED.data_quality,
                              discipline_snapshot = EXCLUDED.discipline_snapshot,
                              updated_at = now()
                            RETURNING id
                            """,
                            {
                                **case_row,
                                "entry_rule": Jsonb(case_row["entry_rule"]),
                                "exit_rule": Jsonb(case_row["exit_rule"]),
                                "benchmark_policy": Jsonb(case_row["benchmark_policy"]),
                                "invalidation": Jsonb(case_row["invalidation"]),
                                "trigger_conditions": Jsonb(case_row["trigger_conditions"]),
                                "source_refs": Jsonb(case_row["source_refs"]),
                                "data_quality": Jsonb(case_row["data_quality"]),
                                "discipline_snapshot": Jsonb(case_row["discipline_snapshot"]),
                            },
                        )
                    )
                    if inserted.get("id"):
                        case_ids.append(str(inserted["id"]))
                candidate_pool = self._save_candidate_pool_postgres_sync(cur=cur, tenant_id=tenant_id, report_date=report_date, candidate_pool=payload.get("candidate_pool") or {})
                delivery = self._enqueue_delivery_postgres(
                    cur=cur,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    artifact_id=artifact.get("id"),
                    market=market,
                    report_date=report_date,
                    session_type=session_type,
                    payload=payload,
                    delivery_context=delivery_context,
                )
            conn.commit()
        return {"status": "saved", "backend": "postgres", "agent_run_id": str(run_id) if run_id else None, "artifact_id": str(artifact.get("id")) if artifact.get("id") else None, "opportunity_case_ids": case_ids, "candidate_pool": candidate_pool, "delivery": delivery}

    def _mark_case_supabase_sync(self, *, tenant_id: str, case_id: str, mark: JsonDict) -> JsonDict:
        inserted = _insert_one(self._client.table("opportunity_case_marks").upsert(_mark_payload(tenant_id, case_id, mark), on_conflict="opportunity_case_id,mark_date,mark_type"))
        if mark.get("case_status"):
            self._client.table("opportunity_cases").update({"status": mark["case_status"], "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", case_id).eq("tenant_id", tenant_id).execute()
        return {"status": "saved", "backend": "supabase", "opportunity_case_mark_id": inserted.get("id"), "mark": mark}

    def _mark_case_postgres_sync(self, *, tenant_id: str, case_id: str, mark: JsonDict) -> JsonDict:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            return {"status": "skipped", "reason": f"psycopg_not_installed: {exc}", "mark": mark}
        payload = _mark_payload(tenant_id, case_id, mark)
        with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                inserted = _fetch_one(
                    cur.execute(
                        """
                        INSERT INTO public.opportunity_case_marks (
                          tenant_id, opportunity_case_id, mark_date, mark_type, mark_price,
                          mark_nav, paper_pnl, paper_pnl_pct, benchmark_return,
                          stretch_return, excess_return, drawdown_pct, thesis_status,
                          discipline_status, review_note, fact_snapshot, benchmark_snapshot
                        )
                        VALUES (
                          %(tenant_id)s, %(opportunity_case_id)s, %(mark_date)s, %(mark_type)s, %(mark_price)s,
                          %(mark_nav)s, %(paper_pnl)s, %(paper_pnl_pct)s, %(benchmark_return)s,
                          %(stretch_return)s, %(excess_return)s, %(drawdown_pct)s, %(thesis_status)s,
                          %(discipline_status)s, %(review_note)s, %(fact_snapshot)s, %(benchmark_snapshot)s
                        )
                        ON CONFLICT (opportunity_case_id, mark_date, mark_type) DO UPDATE SET
                          mark_price = EXCLUDED.mark_price,
                          mark_nav = EXCLUDED.mark_nav,
                          paper_pnl = EXCLUDED.paper_pnl,
                          paper_pnl_pct = EXCLUDED.paper_pnl_pct,
                          benchmark_return = EXCLUDED.benchmark_return,
                          stretch_return = EXCLUDED.stretch_return,
                          excess_return = EXCLUDED.excess_return,
                          drawdown_pct = EXCLUDED.drawdown_pct,
                          thesis_status = EXCLUDED.thesis_status,
                          discipline_status = EXCLUDED.discipline_status,
                          review_note = EXCLUDED.review_note,
                          fact_snapshot = EXCLUDED.fact_snapshot,
                          benchmark_snapshot = EXCLUDED.benchmark_snapshot,
                          updated_at = now()
                        RETURNING id
                        """,
                        {
                            **payload,
                            "fact_snapshot": Jsonb(payload["fact_snapshot"]),
                            "benchmark_snapshot": Jsonb(payload["benchmark_snapshot"]),
                        },
                    )
                )
                if mark.get("case_status"):
                    cur.execute(
                        "UPDATE public.opportunity_cases SET status = %(status)s, updated_at = now() WHERE tenant_id = %(tenant_id)s AND id = %(case_id)s",
                        {"status": mark["case_status"], "tenant_id": tenant_id, "case_id": case_id},
                    )
            conn.commit()
        return {"status": "saved", "backend": "postgres", "opportunity_case_mark_id": str(inserted.get("id")) if inserted.get("id") else None, "mark": mark}

    def _load_open_cases_postgres_sync(self, *, tenant_id: str, market: str | None, limit: int) -> list[JsonDict]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            return []
        where_market = "AND market = %(market)s" if market else ""
        with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                f"""
                SELECT id::text, tenant_id::text, market, symbol, instrument_type,
                       playbook_key, entry_rule, exit_rule, benchmark_policy,
                       strategy_model_version, status, opened_at
                FROM public.opportunity_cases
                WHERE tenant_id = %(tenant_id)s
                  AND status IN ('open', 'tracking')
                  {where_market}
                ORDER BY opened_at DESC
                LIMIT %(limit)s
                """,
                {"tenant_id": tenant_id, "market": market, "limit": max(1, min(100, int(limit or 20)))},
            ).fetchall()
        return [dict(row) for row in rows]

    def _load_candidate_pool_supabase_sync(self, *, tenant_id: str, market: str) -> list[JsonDict]:
        markets = _markets_for_scope(market)
        response = (
            self._client.table("opportunity_candidate_pool")
            .select("*")
            .eq("tenant_id", tenant_id)
            .in_("market", markets)
            .in_("status", ["active", "watching"])
            .execute()
        )
        data = getattr(response, "data", None)
        return [dict(row) for row in data] if isinstance(data, list) else []

    def _load_candidate_pool_postgres_sync(self, *, tenant_id: str, market: str) -> list[JsonDict]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            return []
        with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT id::text, tenant_id::text, market, symbol, asset_path, asset_theme,
                       five_layer, playbook_key, status, strength_score, leader_rank,
                       move_decision, move_reason, last_price, change_pct,
                       relative_strength, source_refs, metadata, last_evaluated_at
                FROM public.opportunity_candidate_pool
                WHERE tenant_id = %(tenant_id)s
                  AND market = ANY(%(markets)s)
                  AND status IN ('active', 'watching')
                ORDER BY status ASC, strength_score DESC NULLS LAST, updated_at DESC
                LIMIT 100
                """,
                {"tenant_id": tenant_id, "markets": _markets_for_scope(market)},
            ).fetchall()
        return [dict(row) for row in rows]

    def _save_candidate_pool_supabase_sync(self, *, tenant_id: str, report_date: str, candidate_pool: JsonDict) -> JsonDict:
        rows = _candidate_pool_rows(tenant_id=tenant_id, report_date=report_date, candidate_pool=candidate_pool)
        if not rows:
            return {"status": "skipped", "reason": "empty_candidate_pool"}
        response = self._client.table("opportunity_candidate_pool").upsert(rows, on_conflict="tenant_id,market,symbol").execute()
        data = getattr(response, "data", None)
        return {"status": "saved", "backend": "supabase", "rows": len(data) if isinstance(data, list) else len(rows)}

    def _save_candidate_pool_postgres_sync(self, *, cur: Any, tenant_id: str, report_date: str, candidate_pool: JsonDict) -> JsonDict:
        rows = _candidate_pool_rows(tenant_id=tenant_id, report_date=report_date, candidate_pool=candidate_pool)
        if not rows:
            return {"status": "skipped", "reason": "empty_candidate_pool"}
        try:
            from psycopg.types.json import Jsonb
        except ImportError:
            return {"status": "skipped", "reason": "psycopg_json_not_available"}
        for row in rows:
            cur.execute(
                """
                INSERT INTO public.opportunity_candidate_pool (
                  tenant_id, market, symbol, asset_path, asset_theme, five_layer, playbook_key,
                  status, strength_score, leader_rank, move_decision, move_reason,
                  last_price, change_pct, relative_strength, source_refs, metadata,
                  last_evaluated_at
                )
                VALUES (
                  %(tenant_id)s, %(market)s, %(symbol)s, %(asset_path)s, %(asset_theme)s,
                  %(five_layer)s, %(playbook_key)s, %(status)s, %(strength_score)s,
                  %(leader_rank)s, %(move_decision)s, %(move_reason)s, %(last_price)s,
                  %(change_pct)s, %(relative_strength)s, %(source_refs)s, %(metadata)s,
                  %(last_evaluated_at)s
                )
                ON CONFLICT (tenant_id, market, symbol) DO UPDATE SET
                  asset_path = EXCLUDED.asset_path,
                  asset_theme = EXCLUDED.asset_theme,
                  five_layer = EXCLUDED.five_layer,
                  playbook_key = EXCLUDED.playbook_key,
                  status = EXCLUDED.status,
                  strength_score = EXCLUDED.strength_score,
                  leader_rank = EXCLUDED.leader_rank,
                  move_decision = EXCLUDED.move_decision,
                  move_reason = EXCLUDED.move_reason,
                  last_price = EXCLUDED.last_price,
                  change_pct = EXCLUDED.change_pct,
                  relative_strength = EXCLUDED.relative_strength,
                  source_refs = EXCLUDED.source_refs,
                  metadata = EXCLUDED.metadata,
                  last_evaluated_at = EXCLUDED.last_evaluated_at,
                  updated_at = now()
                """,
                {**row, "source_refs": Jsonb(row["source_refs"]), "metadata": Jsonb(row["metadata"])},
            )
        return {"status": "saved", "backend": "postgres", "rows": len(rows)}

    def _enqueue_delivery_supabase(
        self,
        *,
        tenant_id: str,
        run_id: Any,
        artifact_id: Any,
        market: str,
        report_date: str,
        session_type: str,
        payload: JsonDict,
        delivery_context: JsonDict,
    ) -> JsonDict:
        channel_binding_id = delivery_context.get("channel_binding_id")
        if not channel_binding_id:
            return {"status": "skipped", "reason": "channel_binding_id_missing"}
        row = _delivery_payload(tenant_id, run_id, artifact_id, market, report_date, session_type, payload, delivery_context)
        inserted = _insert_one(self._client.table("delivery_outbox").upsert(row, on_conflict="tenant_id,dedupe_key"))
        return {"status": "enqueued", "delivery_outbox_id": inserted.get("id"), "dedupe_key": row["dedupe_key"]}

    def _enqueue_delivery_postgres(
        self,
        *,
        cur: Any,
        tenant_id: str,
        run_id: Any,
        artifact_id: Any,
        market: str,
        report_date: str,
        session_type: str,
        payload: JsonDict,
        delivery_context: JsonDict,
    ) -> JsonDict:
        channel_binding_id = delivery_context.get("channel_binding_id")
        if not channel_binding_id:
            return {"status": "skipped", "reason": "channel_binding_id_missing"}
        try:
            from psycopg.types.json import Jsonb
        except ImportError:
            return {"status": "skipped", "reason": "psycopg_json_not_available"}
        row = _delivery_payload(tenant_id, run_id, artifact_id, market, report_date, session_type, payload, delivery_context)
        inserted = _fetch_one(
            cur.execute(
                """
                INSERT INTO public.delivery_outbox (
                  tenant_id, channel_binding_id, source_run_id, artifact_id,
                  openclaw_account_id, content_type, content, content_snapshot_hash,
                  content_summary, priority, dedupe_key, status, attempt_count,
                  next_retry_at, target_conversation, context_token, asset_source_refs,
                  data_snapshot_refs, expires_at
                )
                VALUES (
                  %(tenant_id)s, %(channel_binding_id)s, %(source_run_id)s, %(artifact_id)s,
                  %(openclaw_account_id)s, %(content_type)s, %(content)s, %(content_snapshot_hash)s,
                  %(content_summary)s, %(priority)s, %(dedupe_key)s, 'pending', 0,
                  now(), %(target_conversation)s, %(context_token)s, %(asset_source_refs)s,
                  %(data_snapshot_refs)s, %(expires_at)s
                )
                ON CONFLICT (tenant_id, dedupe_key) DO UPDATE SET
                  content = EXCLUDED.content,
                  content_snapshot_hash = EXCLUDED.content_snapshot_hash,
                  content_summary = EXCLUDED.content_summary,
                  priority = EXCLUDED.priority,
                  status = CASE WHEN delivery_outbox.status = 'delivered' THEN delivery_outbox.status ELSE 'pending'::public.outbox_status END,
                  updated_at = now()
                RETURNING id
                """,
                {
                    **row,
                    "content": Jsonb(row["content"]),
                    "content_summary": Jsonb(row["content_summary"]),
                    "asset_source_refs": Jsonb(row["asset_source_refs"]),
                    "data_snapshot_refs": Jsonb(row["data_snapshot_refs"]),
                },
            )
        )
        return {"status": "enqueued", "delivery_outbox_id": str(inserted.get("id")) if inserted.get("id") else None, "dedupe_key": row["dedupe_key"]}


class OpportunityResearchWorkflow:
    def __init__(
        self,
        *,
        market_regime_reader: AsyncToolReader,
        portfolio_overview_reader: AsyncToolReader,
        positions_reader: AsyncToolReader,
        quote_reader: AsyncToolReader,
        stock_analysis_reader: AsyncToolReader,
        sell_put_reader: AsyncToolReader | None = None,
        persistence: OpportunityResearchPersistence | None = None,
    ) -> None:
        self._market_regime_reader = market_regime_reader
        self._portfolio_overview_reader = portfolio_overview_reader
        self._positions_reader = positions_reader
        self._quote_reader = quote_reader
        self._stock_analysis_reader = stock_analysis_reader
        self._sell_put_reader = sell_put_reader
        self._persistence = persistence or OpportunityResearchPersistence.from_env()

    async def run_research(
        self,
        *,
        tenant_id: str,
        market: str,
        session_type: str = "premarket",
        report_date: str | None = None,
        universe_policy: str = "holdings_watchlist_hard_tech",
        model_policy: JsonDict | None = None,
        symbols: list[str] | None = None,
        sell_put_underlyings: list[str] | None = None,
        delivery_context: JsonDict | None = None,
        persist: bool = True,
        max_candidates: int = 6,
    ) -> OpportunityResearchResult:
        normalized_market = _normalize_market(market)
        report_date = report_date or date.today().isoformat()
        model_policy = _model_policy(model_policy)

        state = await self._sense_state(tenant_id=tenant_id, market=normalized_market)
        existing_pool = await self._persistence.load_candidate_pool(tenant_id=tenant_id, market=normalized_market)
        candidate_universe = _discover_candidates(
            market=normalized_market,
            positions=state.get("positions") or {},
            symbols=symbols or [],
            universe_policy=universe_policy,
            existing_pool=existing_pool,
            max_candidates=max_candidates,
        )
        evaluated_candidates = await self._rank_candidate_pool(candidate_universe)
        selected_candidates = _select_leaders(evaluated_candidates, max_candidates=max_candidates)
        candidate_pool = _candidate_pool_payload(
            market=normalized_market,
            report_date=report_date,
            universe_policy=universe_policy,
            existing_pool=existing_pool,
            evaluated_candidates=evaluated_candidates,
            selected_candidates=selected_candidates,
        )

        cases: list[JsonDict] = []
        source_refs = list(state.get("source_refs") or [])
        for candidate in selected_candidates:
            analysis_result = await self._stock_analysis_reader(
                {
                    "tenant_id": tenant_id,
                    "symbol": candidate["symbol"],
                    "prompt": _research_prompt(candidate, state),
                    "persist": True,
                    "entry_surface": "system",
                }
            )
            case = _case_from_analysis(candidate=candidate, analysis_result=analysis_result, state=state, model_policy=model_policy)
            cases.append(case)
            source_refs.extend(case.get("source_refs") or [])

        sell_put_cases = await self._sell_put_cases(
            tenant_id=tenant_id,
            market=normalized_market,
            underlyings=sell_put_underlyings or [case["symbol"] for case in cases if case.get("market") == "US"][:2],
            model_policy=model_policy,
            state=state,
        )
        cases.extend(sell_put_cases)

        summary = _research_summary(market=normalized_market, session_type=session_type, report_date=report_date, state=state, cases=cases, candidate_pool=candidate_pool)
        payload = {
            "schema_version": OPPORTUNITY_RESEARCH_SCHEMA_VERSION,
            "tenant_id": tenant_id,
            "market": normalized_market,
            "session_type": session_type,
            "report_date": report_date,
            "universe_policy": universe_policy,
            "model_policy": model_policy,
            "state": state,
            "candidate_pool": candidate_pool,
            "cases": cases,
            "summary": summary,
            "max_actionability": _max_actionability(cases),
            "source_refs": _dedupe_refs(source_refs),
            "safety": {"places_orders": False, "accounting": "paper_signal_ledger"},
        }
        persistence = {"status": "skipped", "reason": "persist_false"}
        if persist:
            persistence = await self._persistence.save_research(
                tenant_id=tenant_id,
                market=normalized_market,
                session_type=session_type,
                report_date=report_date,
                payload=payload,
                cases=cases,
                delivery_context=delivery_context or {},
            )
        payload["persistence"] = persistence
        return OpportunityResearchResult("opportunity.research.run", True, "ok", payload, payload["source_refs"])

    async def run_review(
        self,
        *,
        tenant_id: str,
        market: str | None = None,
        review_date: str | None = None,
        cases: list[JsonDict] | None = None,
        persist: bool = True,
    ) -> OpportunityResearchResult:
        review_date = review_date or date.today().isoformat()
        cases = cases if cases is not None else await self._persistence.load_open_cases(tenant_id=tenant_id, market=_normalize_market(market) if market else None)
        marks: list[JsonDict] = []
        for case in cases:
            symbol = str(case.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            quote_result = await _safe_tool_call(self._quote_reader, {"symbol": symbol})
            quote = _tool_data(quote_result)
            entry_rule = case.get("entry_rule") if isinstance(case.get("entry_rule"), dict) else {}
            benchmark_policy = case.get("benchmark_policy") if isinstance(case.get("benchmark_policy"), dict) else {}
            mark = build_opportunity_mark(
                entry_price=_number(entry_rule.get("reference_price")),
                mark_price=_number(quote.get("price") or quote.get("last_price") or quote.get("close")),
                benchmark_entry_price=_number(benchmark_policy.get("entry_price")),
                benchmark_mark_price=_number(benchmark_policy.get("mark_price")),
                stretch_daily_returns=benchmark_policy.get("stretch_daily_returns") if isinstance(benchmark_policy.get("stretch_daily_returns"), list) else [],
                thesis_status="waiting_confirmation",
                discipline_status="unknown",
                review_note="自动复盘：已读取最新事实价格，等待更多事件确认 thesis。" if quote else f"自动复盘：报价读取失败或不可用，保留等待确认状态。{quote_result.get('error') or ''}".strip(),
                mark_date=review_date,
                fact_snapshot={"quote": quote},
                benchmark_snapshot=benchmark_policy,
            )
            case_id = str(case.get("id") or case.get("opportunity_case_id") or "")
            if persist and case_id:
                persistence_result = await self._persistence.mark_case(tenant_id=tenant_id, case_id=case_id, mark=mark)
                if isinstance(persistence_result, dict):
                    mark["persistence"] = {key: value for key, value in persistence_result.items() if key != "mark"}
            marks.append({"case_id": case_id or None, "symbol": symbol, "mark": mark})
        payload = {
            "schema_version": OPPORTUNITY_LEDGER_SCHEMA_VERSION,
            "tenant_id": tenant_id,
            "market": _normalize_market(market) if market else None,
            "review_date": review_date,
            "reviewed_cases": len(marks),
            "marks": marks,
            "summary": _review_summary(marks),
            "safety": {"places_orders": False, "accounting": "paper_signal_ledger"},
        }
        return OpportunityResearchResult("opportunity.review.run", True, "ok", payload, [{"source": "postgres", "ref": "opportunity_cases"}] if cases else [])

    async def mark_ledger(self, *, tenant_id: str, case_id: str, mark: JsonDict, persist: bool = True) -> OpportunityResearchResult:
        computed = build_opportunity_mark(**mark)
        persistence = {"status": "skipped", "reason": "persist_false"}
        if persist:
            persistence = await self._persistence.mark_case(tenant_id=tenant_id, case_id=case_id, mark=computed)
        payload = {"schema_version": OPPORTUNITY_LEDGER_SCHEMA_VERSION, "tenant_id": tenant_id, "opportunity_case_id": case_id, "mark": computed, "persistence": persistence}
        return OpportunityResearchResult("opportunity.ledger.mark", True, "ok", payload, [])

    async def _sense_state(self, *, tenant_id: str, market: str) -> JsonDict:
        markets = ["CN", "HK"] if market == "CN_HK" else [market]
        regimes = []
        source_refs: list[dict[str, str]] = []
        for item_market in markets:
            regime = await _safe_tool_call(self._market_regime_reader, {"tenant_id": tenant_id, "market": item_market})
            regimes.append({"market": item_market, "result": regime})
            source_refs.extend(regime.get("source_refs") or [])
        positions = await _safe_tool_call(self._positions_reader, {"tenant_id": tenant_id})
        overview = await _safe_tool_call(self._portfolio_overview_reader, {"tenant_id": tenant_id})
        source_refs.extend(positions.get("source_refs") or [])
        source_refs.extend(overview.get("source_refs") or [])
        return {
            "market_state": regimes,
            "portfolio_overview": _tool_data(overview),
            "positions": _tool_data(positions),
            "ai_capex": _theme_state(regimes, "ai_capex"),
            "k_shaped_split": _theme_state(regimes, "k_shaped_split"),
            "hard_tech_acceleration": _theme_state(regimes, "hard_tech_acceleration"),
            "profit_cushion": _profit_cushion_state(_tool_data(overview)),
            "capital_path_split": _capital_path_split(regimes),
            "source_refs": _dedupe_refs(source_refs),
        }

    async def _sell_put_cases(
        self,
        *,
        tenant_id: str,
        market: str,
        underlyings: list[str],
        model_policy: JsonDict,
        state: JsonDict,
    ) -> list[JsonDict]:
        if market not in {"US", "CN_HK"} or self._sell_put_reader is None:
            return []
        cases: list[JsonDict] = []
        for underlying in [item.strip().upper() for item in underlyings if item.strip()][:2]:
            result = await _safe_tool_call(
                self._sell_put_reader,
                {
                    "tenant_id": tenant_id,
                    "underlying_symbol": underlying,
                    "quote": {},
                    "option_candidates": [],
                    "strategy_model_version": model_policy.get("deep_research", {}).get("model") or DEFAULT_STRATEGY_MODEL_VERSION,
                },
            )
            cases.append(_sell_put_case(underlying=underlying, result=result, model_policy=model_policy, state=state))
        return cases

    async def _rank_candidate_pool(self, candidates: list[JsonDict]) -> list[JsonDict]:
        async def enrich(candidate: JsonDict) -> JsonDict:
            quote_result = await _safe_tool_call(self._quote_reader, {"symbol": candidate["symbol"], "market": candidate.get("market")})
            quote = _tool_data(quote_result)
            return _evaluated_candidate(candidate=candidate, quote=quote, source_refs=quote_result.get("source_refs") or [])

        evaluated = await asyncio.gather(*(enrich(candidate) for candidate in candidates[:50]))
        return _assign_leader_ranks(list(evaluated))


def build_opportunity_mark(
    *,
    entry_price: Any = None,
    mark_price: Any = None,
    benchmark_entry_price: Any = None,
    benchmark_mark_price: Any = None,
    stretch_daily_returns: list[Any] | None = None,
    mark_date: str | None = None,
    mark_type: str = "daily",
    thesis_status: str = "waiting_confirmation",
    discipline_status: str = "unknown",
    review_note: str = "",
    fact_snapshot: JsonDict | None = None,
    benchmark_snapshot: JsonDict | None = None,
    case_status: str | None = None,
) -> JsonDict:
    entry = _number(entry_price)
    mark = _number(mark_price)
    benchmark_entry = _number(benchmark_entry_price)
    benchmark_mark = _number(benchmark_mark_price)
    paper_return = (mark / entry - 1.0) if entry and mark is not None else None
    benchmark_return = (benchmark_mark / benchmark_entry - 1.0) if benchmark_entry and benchmark_mark is not None else None
    stretch_return = qqq_2x_daily_reset_return(stretch_daily_returns or [])
    excess = paper_return - benchmark_return if paper_return is not None and benchmark_return is not None else None
    return {
        "schema_version": OPPORTUNITY_LEDGER_SCHEMA_VERSION,
        "mark_date": mark_date or date.today().isoformat(),
        "mark_type": mark_type,
        "mark_price": mark,
        "mark_nav": mark,
        "paper_pnl": (mark - entry) if entry is not None and mark is not None else None,
        "paper_pnl_pct": round(paper_return * 100, 4) if paper_return is not None else None,
        "benchmark_return": round(benchmark_return * 100, 4) if benchmark_return is not None else None,
        "stretch_return": round(stretch_return * 100, 4) if stretch_return is not None else None,
        "excess_return": round(excess * 100, 4) if excess is not None else None,
        "drawdown_pct": min(0.0, round((paper_return or 0.0) * 100, 4)) if paper_return is not None else None,
        "thesis_status": thesis_status,
        "discipline_status": discipline_status,
        "review_note": review_note,
        "fact_snapshot": fact_snapshot or {},
        "benchmark_snapshot": benchmark_snapshot or {},
        "case_status": case_status,
    }


def qqq_2x_daily_reset_return(daily_returns: list[Any]) -> float | None:
    if not daily_returns:
        return None
    value = 1.0
    for raw in daily_returns:
        daily = _number(raw)
        if daily is None:
            continue
        value *= 1.0 + (2.0 * daily)
    return value - 1.0


def _discover_candidates(*, market: str, positions: JsonDict, symbols: list[str], universe_policy: str, existing_pool: list[JsonDict], max_candidates: int) -> list[JsonDict]:
    candidates: list[JsonDict] = []
    for symbol in symbols:
        if symbol:
            candidates.append(_candidate(symbol=symbol, market=_market_for_symbol(symbol, market), source="explicit_symbol"))
    for row in _position_rows(positions):
        symbol = str(row.get("symbol") or row.get("provider_symbol") or "").strip().upper()
        if symbol:
            candidates.append(_candidate(symbol=symbol, market=_market_for_symbol(symbol, market), source="holding", name=row.get("name")))
    for row in existing_pool:
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol:
            candidates.append(_candidate_from_pool_row(row=row, fallback_market=_market_for_symbol(symbol, market)))
    if any(key in universe_policy for key in ("hard_tech", "thematic", "holdings_watchlist")):
        seed_markets = _markets_for_scope(market)
        for seed_market in seed_markets:
            for seed in THEMATIC_CANDIDATE_UNIVERSE.get(seed_market, []):
                candidates.append({**_candidate(symbol=seed["symbol"], market=seed_market, source="thematic_seed"), **seed})
    deduped: list[JsonDict] = []
    seen = set()
    for item in candidates:
        key = (item["market"], item["symbol"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    universe_cap = max(10, min(50, int(max_candidates or 6) * 5))
    return deduped[:universe_cap]


def _evaluated_candidate(*, candidate: JsonDict, quote: JsonDict, source_refs: list[dict[str, str]]) -> JsonDict:
    change_pct = _quote_change_pct(quote)
    relative_strength = _relative_strength(quote, change_pct)
    strength_score = _candidate_strength_score(candidate=candidate, quote=quote, change_pct=change_pct, relative_strength=relative_strength)
    return {
        **candidate,
        "asset_path": candidate.get("asset_path") or _asset_path_for(candidate),
        "asset_path_label": THEME_PATHS.get(str(candidate.get("asset_path") or _asset_path_for(candidate)), str(candidate.get("asset_path") or _asset_path_for(candidate))),
        "five_layer": candidate.get("five_layer") or _five_layer_for(candidate),
        "five_layer_label": FIVE_LAYER_CAKE_LAYERS.get(str(candidate.get("five_layer") or _five_layer_for(candidate)), str(candidate.get("five_layer") or _five_layer_for(candidate))),
        "quote_snapshot": quote,
        "last_price": _number(quote.get("price") or quote.get("last_price") or quote.get("current_price") or quote.get("close")),
        "change_pct": change_pct,
        "relative_strength": relative_strength,
        "strength_score": strength_score,
        "source_refs": _dedupe_refs(source_refs),
    }


def _assign_leader_ranks(candidates: list[JsonDict]) -> list[JsonDict]:
    grouped: dict[tuple[str, str, str], list[JsonDict]] = {}
    for candidate in candidates:
        key = (str(candidate.get("market") or "US"), str(candidate.get("asset_path") or "default"), str(candidate.get("five_layer") or "default"))
        grouped.setdefault(key, []).append(candidate)
    ranked: list[JsonDict] = []
    for rows in grouped.values():
        ordered = sorted(rows, key=lambda item: (_number(item.get("strength_score")) or 0.0, _source_priority(item.get("source"))), reverse=True)
        for index, row in enumerate(ordered, start=1):
            ranked.append({**row, "leader_rank": index, "leader_group_size": len(ordered)})
    return sorted(ranked, key=lambda item: (_number(item.get("strength_score")) or 0.0, -int(item.get("leader_rank") or 99)), reverse=True)


def _select_leaders(candidates: list[JsonDict], *, max_candidates: int) -> list[JsonDict]:
    cap = max(1, min(12, int(max_candidates or 6)))
    selected = [
        {**candidate, "selected_for_research": True, "selection_reason": "theme_layer_top3_leader"}
        for candidate in candidates
        if int(candidate.get("leader_rank") or 99) <= LEADER_GROUP_TOP_N and (_number(candidate.get("strength_score")) or 0.0) >= LEADER_MIN_STRENGTH_SCORE
    ]
    return selected[:cap]


def _candidate_pool_payload(*, market: str, report_date: str, universe_policy: str, existing_pool: list[JsonDict], evaluated_candidates: list[JsonDict], selected_candidates: list[JsonDict]) -> JsonDict:
    selected_keys = {(item.get("market"), item.get("symbol")) for item in selected_candidates}
    existing_by_key = {(item.get("market"), item.get("symbol")): item for item in existing_pool if item.get("market") and item.get("symbol")}
    evaluated_keys = {(item.get("market"), item.get("symbol")) for item in evaluated_candidates}
    decisions: list[JsonDict] = []
    for candidate in evaluated_candidates:
        key = (candidate.get("market"), candidate.get("symbol"))
        existing = existing_by_key.get(key)
        selected = key in selected_keys
        if selected and not existing:
            decision = "add"
            status = "active"
            reason = "new_theme_layer_top3_leader"
        elif selected:
            decision = "keep"
            status = "active"
            reason = "top3_leader_confirmed"
        elif existing and existing.get("status") in {"active", "watching"}:
            decision = "remove"
            status = "removed"
            reason = "lost_leader_rank_or_strength"
        else:
            decision = "watch"
            status = "watching"
            reason = "not_current_leader"
        decisions.append(_candidate_decision(candidate=candidate, decision=decision, status=status, reason=reason))
    for key, row in existing_by_key.items():
        if key in evaluated_keys:
            continue
        if row.get("status") not in {"active", "watching"}:
            continue
        decisions.append(
            _candidate_decision(
                candidate=_candidate_from_pool_row(row=row, fallback_market=str(row.get("market") or market)),
                decision="remove",
                status="removed",
                reason="no_longer_in_universe",
            )
        )
    additions = [item for item in decisions if item.get("move_decision") == "add"]
    keeps = [item for item in decisions if item.get("move_decision") == "keep"]
    removals = [item for item in decisions if item.get("move_decision") == "remove"]
    watchlist = [item for item in decisions if item.get("move_decision") == "watch"]
    return {
        "schema_version": OPPORTUNITY_CANDIDATE_POOL_SCHEMA_VERSION,
        "mode": "centaur_leader_rotation",
        "market": market,
        "report_date": report_date,
        "universe_policy": universe_policy,
        "policy": {
            "asset_paths": THEME_PATHS,
            "five_layer_cake": FIVE_LAYER_CAKE_LAYERS,
            "leader_only": True,
            "leader_top_n_per_group": LEADER_GROUP_TOP_N,
            "leader_min_strength_score": LEADER_MIN_STRENGTH_SCORE,
            "rotation_rule": "每日按主题路径与五层蛋糕分组，只让每组强度前三名进入深研；失去前三名或强度不足的候选移除或降级观察。",
        },
        "evaluated_count": len(evaluated_candidates),
        "selected_count": len(selected_candidates),
        "additions": additions,
        "keeps": keeps,
        "removals": removals,
        "watchlist": watchlist,
        "decisions": decisions,
    }


def _candidate_decision(*, candidate: JsonDict, decision: str, status: str, reason: str) -> JsonDict:
    return {
        "market": candidate.get("market") or "US",
        "symbol": candidate.get("symbol"),
        "asset_path": candidate.get("asset_path") or _asset_path_for(candidate),
        "asset_theme": candidate.get("asset_theme"),
        "five_layer": candidate.get("five_layer") or _five_layer_for(candidate),
        "five_layer_label": FIVE_LAYER_CAKE_LAYERS.get(str(candidate.get("five_layer") or _five_layer_for(candidate)), str(candidate.get("five_layer") or _five_layer_for(candidate))),
        "playbook_key": candidate.get("playbook_key") or _playbook_for(candidate.get("asset_theme"), str(candidate.get("symbol") or "")),
        "status": status,
        "move_decision": decision,
        "move_reason": reason,
        "strength_score": _number(candidate.get("strength_score")),
        "leader_rank": candidate.get("leader_rank"),
        "last_price": _number(candidate.get("last_price")),
        "change_pct": _number(candidate.get("change_pct")),
        "relative_strength": _number(candidate.get("relative_strength")),
        "source_refs": candidate.get("source_refs") or [],
        "metadata": {
            "source": candidate.get("source"),
            "asset_path_label": THEME_PATHS.get(str(candidate.get("asset_path") or _asset_path_for(candidate)), str(candidate.get("asset_path") or _asset_path_for(candidate))),
            "leader_group_size": candidate.get("leader_group_size"),
            "quote_snapshot": candidate.get("quote_snapshot") or {},
        },
    }


def _case_from_analysis(*, candidate: JsonDict, analysis_result: JsonDict, state: JsonDict, model_policy: JsonDict) -> JsonDict:
    data = _tool_data(analysis_result)
    persistence = data.get("persistence") if isinstance(data.get("persistence"), dict) else {}
    source_refs = _dedupe_refs([*(analysis_result.get("source_refs") or []), *(candidate.get("source_refs") or []), *(state.get("source_refs") or [])])
    gates = _four_gates(data=data, source_refs=source_refs, state=state, instrument_type="stock")
    raw_playbook = candidate.get("playbook_key")
    playbook = raw_playbook if raw_playbook and raw_playbook != "default" else _playbook_for(candidate.get("asset_theme"), candidate["symbol"])
    benchmark = _benchmark_policy(playbook_key=playbook, market=candidate.get("market") or data.get("market") or "US", current_price=data.get("current_price"))
    actionability = _actionability_from_gates(gates, requested=data.get("actionability_cap"))
    return {
        "schema_version": OPPORTUNITY_RESEARCH_SCHEMA_VERSION,
        "symbol": data.get("symbol") or candidate["symbol"],
        "name": data.get("name") or candidate.get("name"),
        "market": data.get("market") or candidate.get("market") or "US",
        "instrument_type": "stock",
        "asset_theme": candidate.get("asset_theme") or data.get("sector") or "机会观察",
        "asset_path": candidate.get("asset_path") or _asset_path_for(candidate),
        "five_layer": candidate.get("five_layer") or _five_layer_for(candidate),
        "leader_rank": candidate.get("leader_rank"),
        "strength_score": candidate.get("strength_score"),
        "narrative": _narrative(data=data, candidate=candidate, state=state),
        "playbook_key": playbook,
        "horizon": "3d",
        "actionability_cap": actionability,
        "position_layer": _position_layer(actionability, state),
        "budget_layer": _budget_layer(actionability, state),
        "entry_rule": {"type": "paper_next_open", "reference_price": data.get("current_price"), "no_live_order": True},
        "exit_rule": {"type": "thesis_or_risk_invalidation", "watch_conditions": data.get("watch_conditions") or [], "review_after_days": 3},
        "benchmark_policy": benchmark,
        "strategy_model_version": model_policy.get("deep_research", {}).get("model") or DEFAULT_STRATEGY_MODEL_VERSION,
        "status": "open" if actionability in {"suggested_action", "trade_draft"} else "tracking",
        "invalidation": {"conditions": data.get("risk_flags") or []},
        "trigger_conditions": data.get("watch_conditions") or [],
        "source_refs": source_refs,
        "data_quality": {"level": _data_quality_level(data, source_refs), "raw": data.get("data_quality") or {}, "candidate_strength": {"score": candidate.get("strength_score"), "leader_rank": candidate.get("leader_rank")}},
        "discipline_snapshot": {
            "four_gates": gates,
            "discipline_result": data.get("discipline_result") or {},
            "candidate_pool": {
                "mode": "centaur_leader_rotation",
                "asset_path": candidate.get("asset_path") or _asset_path_for(candidate),
                "five_layer": candidate.get("five_layer") or _five_layer_for(candidate),
                "five_layer_label": candidate.get("five_layer_label"),
                "leader_rank": candidate.get("leader_rank"),
                "leader_group_size": candidate.get("leader_group_size"),
                "strength_score": candidate.get("strength_score"),
                "selection_reason": candidate.get("selection_reason"),
            },
        },
        "decision_signal_id": persistence.get("decision_signal_id"),
        "dedupe_key": f"{candidate.get('market') or data.get('market') or 'US'}:{data.get('symbol') or candidate['symbol']}:stock:{date.today().isoformat()}",
        "summary": data.get("short_reply"),
    }


def _sell_put_case(*, underlying: str, result: JsonDict, model_policy: JsonDict, state: JsonDict) -> JsonDict:
    data = _tool_data(result)
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    top = summary.get("top_candidate") if isinstance(summary.get("top_candidate"), dict) else {}
    has_contract = bool(top.get("strike") and top.get("expiry") and (top.get("premium") or top.get("mid")))
    actionability = "trade_draft" if has_contract and top.get("cash_secured_amount") and top.get("strategy_model_version") else "analysis_only"
    gates = {
        "fact_gate": {"status": "passed" if has_contract else "blocked", "reason": "contract_snapshot_available" if has_contract else "missing_contract_snapshot"},
        "narrative_gate": {"status": "passed", "reason": "sell_put_income_candidate"},
        "discipline_gate": {"status": "passed" if actionability == "trade_draft" else "warned", "reason": "cash_secured_required"},
        "execution_gate": {"status": "passed" if actionability == "trade_draft" else "blocked", "reason": "requires_dte_delta_premium_cash_strategy_version"},
        "profit_cushion_attack_gate": {"status": "warned", "reason": "paper_ledger_only_no_live_order"},
    }
    return {
        "schema_version": OPPORTUNITY_RESEARCH_SCHEMA_VERSION,
        "symbol": underlying,
        "market": "US",
        "instrument_type": "sell_put",
        "asset_theme": "sell put income",
        "narrative": f"{underlying} Sell Put 候选；缺少完整合约快照时仅做观察。",
        "playbook_key": "sell_put_income",
        "horizon": "20-60d",
        "actionability_cap": actionability,
        "position_layer": "income_overlay" if actionability == "trade_draft" else "watch",
        "budget_layer": "cash_secured",
        "entry_rule": {"type": "paper_sell_put_snapshot", "underlying": underlying, "contract": top, "no_live_order": True},
        "exit_rule": {"type": "expiry_or_50pct_premium_capture", "requires_manual_confirmation": True},
        "benchmark_policy": _benchmark_policy(playbook_key="sell_put_income", market="US", current_price=None),
        "strategy_model_version": top.get("strategy_model_version") or model_policy.get("deep_research", {}).get("model") or DEFAULT_STRATEGY_MODEL_VERSION,
        "status": "open" if actionability == "trade_draft" else "tracking",
        "invalidation": {"conditions": ["earnings_window", "cash_buffer_breach", "delta_or_dte_out_of_range"]},
        "trigger_conditions": ["premium/IV rank improves", "delta and DTE enter configured range"],
        "source_refs": result.get("source_refs") or [],
        "data_quality": {"level": "L2" if has_contract else "L4", "raw": data.get("data_quality") or {}},
        "discipline_snapshot": {"four_gates": gates, "raw": summary},
        "dedupe_key": f"US:{underlying}:sell_put:{date.today().isoformat()}",
        "summary": summary,
    }


def _four_gates(*, data: JsonDict, source_refs: list[dict[str, str]], state: JsonDict, instrument_type: str) -> JsonDict:
    current_price = data.get("current_price")
    watch_conditions = data.get("watch_conditions") if isinstance(data.get("watch_conditions"), list) else []
    discipline = data.get("discipline_result") if isinstance(data.get("discipline_result"), dict) else {}
    quality_level = _data_quality_level(data, source_refs)
    profit_cushion = state.get("profit_cushion") if isinstance(state.get("profit_cushion"), dict) else {}
    profit_cushion_ready = profit_cushion.get("status") in {"available", "configured"}
    return {
        "fact_gate": {"status": "passed" if source_refs and current_price is not None and quality_level in {"L1", "L2"} else "blocked", "quality_level": quality_level},
        "narrative_gate": {"status": "passed" if data.get("report") or data.get("short_reply") else "blocked", "reason": "thesis_present" if data.get("report") else "missing_thesis"},
        "discipline_gate": {"status": "blocked" if discipline.get("actionability_cap") == "blocked" else "passed", "reason": discipline.get("status") or "discipline_checked"},
        "execution_gate": {"status": "passed" if watch_conditions and current_price is not None else "warned", "reason": "has_trigger_and_reference_price" if watch_conditions and current_price is not None else "missing_trigger_or_reference_price"},
        "profit_cushion_attack_gate": {"status": "passed" if profit_cushion_ready else "warned", "reason": "profit_cushion_available" if profit_cushion_ready else profit_cushion.get("reason") or "profit_cushion_not_configured"},
    }


def _actionability_from_gates(gates: JsonDict, requested: Any) -> str:
    if any(gate.get("status") == "blocked" for gate in gates.values() if isinstance(gate, dict)):
        return "analysis_only"
    if all(gate.get("status") == "passed" for gate in gates.values() if isinstance(gate, dict)) and requested in {"suggested_action", "trade_draft"}:
        return str(requested)
    return "suggested_action" if gates.get("fact_gate", {}).get("status") == "passed" else "analysis_only"


def _data_quality_level(data: JsonDict, source_refs: list[dict[str, str]]) -> str:
    raw = data.get("data_quality") if isinstance(data.get("data_quality"), dict) else {}
    if data.get("current_price") is None:
        return "L4"
    if raw.get("quote_actionability") == "trade_draft" and source_refs:
        return "L1"
    if source_refs and raw.get("quote_source"):
        return "L2"
    return "L3"


def _benchmark_policy(*, playbook_key: str, market: str, current_price: Any) -> JsonDict:
    benchmark = BENCHMARK_BY_PLAYBOOK.get(playbook_key, BENCHMARK_BY_PLAYBOOK["default"]).get(market, "QQQ")
    policy = {
        "primary_benchmark": benchmark,
        "entry_price": None,
        "mark_price": None,
        "comparison": "excess_return_vs_primary_benchmark",
    }
    if playbook_key in {"hard_tech_acceleration", "ai_capex"} and market == "US":
        policy["stretch_comparator"] = "QQQ_2x_daily_reset"
        policy["stretch_note"] = "Only a high-beta sleeve comparator; not a whole-account benchmark."
    return policy


def _model_policy(policy: JsonDict | None) -> JsonDict:
    policy = policy if isinstance(policy, dict) else {}
    return {
        "light_scan": policy.get("light_scan") if isinstance(policy.get("light_scan"), dict) else {"model": "glm-5.2"},
        "deep_research": policy.get("deep_research") if isinstance(policy.get("deep_research"), dict) else {"model": "gpt-5.5", "fallback": "glm-5.2"},
        "high_risk_review": policy.get("high_risk_review") if isinstance(policy.get("high_risk_review"), dict) else {"mode": "second_model_critique"},
        "provider_status": {"glm-5.2": "supported_when_gbrain_glm_provider_credentials_are_configured"},
    }


def _research_summary(*, market: str, session_type: str, report_date: str, state: JsonDict, cases: list[JsonDict], candidate_pool: JsonDict | None = None) -> JsonDict:
    candidate_pool = candidate_pool if isinstance(candidate_pool, dict) else {}
    top = sorted(cases, key=lambda item: {"trade_draft": 3, "suggested_action": 2, "analysis_only": 1}.get(str(item.get("actionability_cap")), 0), reverse=True)[:3]
    return {
        "title": f"Hermes 机会研究｜{market}｜{report_date}｜{session_type}",
        "top_opportunities": [
            {
                "symbol": item.get("symbol"),
                "theme": item.get("asset_theme"),
                "asset_path": item.get("asset_path"),
                "five_layer": item.get("five_layer"),
                "leader_rank": item.get("leader_rank"),
                "strength_score": item.get("strength_score"),
                "actionability": item.get("actionability_cap"),
                "discipline": item.get("discipline_snapshot", {}).get("four_gates"),
            }
            for item in top
        ],
        "state_brief": {
            "ai_capex": state.get("ai_capex"),
            "hard_tech_acceleration": state.get("hard_tech_acceleration"),
            "profit_cushion": state.get("profit_cushion"),
            "capital_path_split": state.get("capital_path_split"),
        },
        "candidate_pool": {
            "mode": candidate_pool.get("mode"),
            "leader_only": candidate_pool.get("policy", {}).get("leader_only"),
            "leader_top_n_per_group": candidate_pool.get("policy", {}).get("leader_top_n_per_group"),
            "evaluated": candidate_pool.get("evaluated_count", 0),
            "selected": candidate_pool.get("selected_count", 0),
            "additions": len(candidate_pool.get("additions") or []),
            "keeps": len(candidate_pool.get("keeps") or []),
            "removals": len(candidate_pool.get("removals") or []),
            "watchlist": len(candidate_pool.get("watchlist") or []),
        },
        "counts": {"cases": len(cases), "trade_drafts": sum(1 for item in cases if item.get("actionability_cap") == "trade_draft"), "suggested_actions": sum(1 for item in cases if item.get("actionability_cap") == "suggested_action")},
    }


def _review_summary(marks: list[JsonDict]) -> JsonDict:
    returns = [_number(item.get("mark", {}).get("paper_pnl_pct")) for item in marks]
    returns = [item for item in returns if item is not None]
    return {
        "title": "Hermes 机会研究每日复盘",
        "reviewed_cases": len(marks),
        "average_paper_pnl_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "best_case": max(marks, key=lambda item: _number(item.get("mark", {}).get("paper_pnl_pct")) or -10**9, default=None),
        "worst_case": min(marks, key=lambda item: _number(item.get("mark", {}).get("paper_pnl_pct")) or 10**9, default=None),
    }


def _delivery_payload(tenant_id: str, run_id: Any, artifact_id: Any, market: str, report_date: str, session_type: str, payload: JsonDict, delivery_context: JsonDict) -> JsonDict:
    content = {
        "title": payload.get("summary", {}).get("title") or "Hermes 机会研究",
        "text": _wechat_summary(payload),
        "task": "opportunity_research",
        "market": market,
        "session_type": session_type,
        "report_date": report_date,
        "summary": payload.get("summary") or {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    snapshot_hash = _sha256_json(content)
    return {
        "tenant_id": tenant_id,
        "channel_binding_id": delivery_context.get("channel_binding_id"),
        "source_run_id": str(run_id) if run_id else None,
        "artifact_id": str(artifact_id) if artifact_id else None,
        "openclaw_account_id": delivery_context.get("openclaw_account_id") or delivery_context.get("channel_account_id"),
        "content_type": "opportunity_research_summary",
        "content": content,
        "content_snapshot_hash": snapshot_hash,
        "content_summary": {"title": content["title"], "market": market, "session_type": session_type, "top_count": len(payload.get("summary", {}).get("top_opportunities") or [])},
        "priority": "high" if any(item.get("actionability_cap") == "trade_draft" for item in payload.get("cases") or []) else "normal",
        "dedupe_key": f"opportunity_research:{tenant_id}:{market}:{report_date}:{session_type}",
        "target_conversation": delivery_context.get("target_conversation"),
        "context_token": delivery_context.get("context_token"),
        "asset_source_refs": [{"kind": "opportunity_research", "market": market, "session_type": session_type}],
        "data_snapshot_refs": payload.get("source_refs") or [],
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
    }


def _wechat_summary(payload: JsonDict) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [f"【抓钱小螃蟹】{summary.get('title') or 'Hermes 机会研究'}"]
    lines.append("账户动作：不自动下单；以下为信号账本建议。")
    for index, item in enumerate(summary.get("top_opportunities") or [], start=1):
        lines.append(f"{index}. {item.get('symbol')}｜{item.get('theme')}｜{item.get('actionability')}")
    if not summary.get("top_opportunities"):
        lines.append("今日未形成高质量机会，保持观察。")
    lines.append("完整报告已归档；强触发机会会单独进入提醒。")
    return "\n".join(lines)


def _case_payload(tenant_id: str, run_id: Any, artifact_id: Any, case: JsonDict) -> JsonDict:
    opened_at = datetime.now(timezone.utc)
    return {
        "tenant_id": tenant_id,
        "source_run_id": str(run_id) if run_id else None,
        "source_artifact_id": str(artifact_id) if artifact_id else None,
        "decision_signal_id": case.get("decision_signal_id"),
        "market": case.get("market") or "US",
        "symbol": case.get("symbol"),
        "instrument_type": case.get("instrument_type") or "stock",
        "asset_theme": case.get("asset_theme"),
        "narrative": case.get("narrative"),
        "playbook_key": case.get("playbook_key") or "default",
        "horizon": case.get("horizon") or "3d",
        "actionability_cap": case.get("actionability_cap") or "analysis_only",
        "position_layer": case.get("position_layer"),
        "budget_layer": case.get("budget_layer"),
        "entry_rule": case.get("entry_rule") or {},
        "exit_rule": case.get("exit_rule") or {},
        "benchmark_policy": case.get("benchmark_policy") or {},
        "strategy_model_version": case.get("strategy_model_version") or DEFAULT_STRATEGY_MODEL_VERSION,
        "status": case.get("status") or "tracking",
        "invalidation": case.get("invalidation") or {},
        "trigger_conditions": case.get("trigger_conditions") or [],
        "source_refs": case.get("source_refs") or [],
        "data_quality": case.get("data_quality") or {},
        "discipline_snapshot": case.get("discipline_snapshot") or {},
        "dedupe_key": case.get("dedupe_key") or f"{case.get('market') or 'US'}:{case.get('symbol')}:{case.get('instrument_type') or 'stock'}:{opened_at.date().isoformat()}",
        "opened_at": opened_at.isoformat(),
        "expires_at": (opened_at + timedelta(days=14)).isoformat(),
    }


def _mark_payload(tenant_id: str, case_id: str, mark: JsonDict) -> JsonDict:
    return {
        "tenant_id": tenant_id,
        "opportunity_case_id": case_id,
        "mark_date": mark.get("mark_date") or date.today().isoformat(),
        "mark_type": mark.get("mark_type") or "daily",
        "mark_price": mark.get("mark_price"),
        "mark_nav": mark.get("mark_nav"),
        "paper_pnl": mark.get("paper_pnl"),
        "paper_pnl_pct": mark.get("paper_pnl_pct"),
        "benchmark_return": mark.get("benchmark_return"),
        "stretch_return": mark.get("stretch_return"),
        "excess_return": mark.get("excess_return"),
        "drawdown_pct": mark.get("drawdown_pct"),
        "thesis_status": mark.get("thesis_status") or "waiting_confirmation",
        "discipline_status": mark.get("discipline_status") or "unknown",
        "review_note": mark.get("review_note"),
        "fact_snapshot": mark.get("fact_snapshot") or {},
        "benchmark_snapshot": mark.get("benchmark_snapshot") or {},
    }


def _candidate(symbol: str, market: str, source: str, name: Any = None) -> JsonDict:
    return {"symbol": str(symbol).strip().upper(), "market": market, "name": name, "asset_theme": "持仓/关注机会", "playbook_key": "default", "source": source}


def _candidate_from_pool_row(*, row: JsonDict, fallback_market: str) -> JsonDict:
    symbol = str(row.get("symbol") or "").strip().upper()
    return {
        "symbol": symbol,
        "market": row.get("market") or fallback_market,
        "name": row.get("name"),
        "asset_theme": row.get("asset_theme") or "候选池延续观察",
        "asset_path": row.get("asset_path") or "ai_semiconductor_power_chain",
        "five_layer": row.get("five_layer") or "ai_application",
        "playbook_key": row.get("playbook_key") or "default",
        "source": "candidate_pool",
    }


def _markets_for_scope(market: str) -> list[str]:
    normalized = _normalize_market(market)
    return ["CN", "HK"] if normalized == "CN_HK" else [normalized]


def _asset_path_for(candidate: JsonDict) -> str:
    playbook = str(candidate.get("playbook_key") or "").lower()
    text = f"{candidate.get('asset_theme') or ''} {candidate.get('symbol') or ''}".lower()
    if "gold" in playbook or "黄金" in text or "gdx" in text:
        return "gold"
    if "copper" in playbook or "铜" in text or "copx" in text:
        return "copper_miner"
    if "cycle" in playbook or "small" in text or "小盘" in text or "iwm" in text:
        return "traditional_cycle_demand_smallcap"
    if "cash" in playbook or "短债" in text:
        return "cash_short_duration"
    return "ai_semiconductor_power_chain"


def _five_layer_for(candidate: JsonDict) -> str:
    text = f"{candidate.get('asset_theme') or ''} {candidate.get('symbol') or ''}".lower()
    if any(key in text for key in ("nvda", "amd", "gpu", "accelerator", "加速")):
        return "accelerated_compute"
    if any(key in text for key in ("avgo", "anet", "network", "互联", "接口")):
        return "networking"
    if any(key in text for key in ("tsm", "smh", "foundry", "半导体", "芯片", "设备", "封测", "制造")):
        return "systems_foundry"
    if any(key in text for key in ("vrt", "power", "cooling", "电力", "数据中心")):
        return "power_infrastructure"
    if _asset_path_for(candidate) == "gold":
        return "macro_hedge"
    if _asset_path_for(candidate) == "copper_miner":
        return "commodity_supply"
    if _asset_path_for(candidate) == "traditional_cycle_demand_smallcap":
        return "rate_sensitive_beta"
    return "ai_application"


def _position_rows(positions: JsonDict) -> list[JsonDict]:
    rows: list[JsonDict] = []
    for key in ("equity_positions", "positions"):
        value = positions.get(key)
        if isinstance(value, list):
            rows.extend([row for row in value if isinstance(row, dict)])
    return rows


def _candidate_pool_rows(*, tenant_id: str, report_date: str, candidate_pool: JsonDict) -> list[JsonDict]:
    rows: list[JsonDict] = []
    for item in candidate_pool.get("decisions") or []:
        if not isinstance(item, dict) or not item.get("symbol"):
            continue
        rows.append(
            {
                "tenant_id": tenant_id,
                "market": item.get("market") or candidate_pool.get("market") or "US",
                "symbol": str(item.get("symbol")).strip().upper(),
                "asset_path": item.get("asset_path"),
                "asset_theme": item.get("asset_theme"),
                "five_layer": item.get("five_layer"),
                "playbook_key": item.get("playbook_key") or "default",
                "status": item.get("status") or "watching",
                "strength_score": item.get("strength_score"),
                "leader_rank": item.get("leader_rank"),
                "move_decision": item.get("move_decision"),
                "move_reason": item.get("move_reason"),
                "last_price": item.get("last_price"),
                "change_pct": item.get("change_pct"),
                "relative_strength": item.get("relative_strength"),
                "source_refs": item.get("source_refs") or [],
                "metadata": {**(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}), "report_date": report_date, "policy": candidate_pool.get("policy") or {}},
                "last_evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return rows


def _quote_change_pct(quote: JsonDict) -> float | None:
    for key in ("change_pct", "percent_change", "pct_change", "regularMarketChangePercent", "change_rate"):
        raw = _number(quote.get(key))
        if raw is None:
            continue
        if key == "change_rate" and abs(raw) <= 1:
            return raw * 100.0
        return raw * 100.0 if abs(raw) <= 1 and key != "regularMarketChangePercent" else raw
    price = _number(quote.get("price") or quote.get("last_price") or quote.get("current_price") or quote.get("close"))
    previous = _number(quote.get("previous_close") or quote.get("prev_close"))
    if price is not None and previous:
        return (price / previous - 1.0) * 100.0
    return None


def _relative_strength(quote: JsonDict, change_pct: float | None) -> float | None:
    for key in ("relative_strength", "rs_score", "rs_rating", "relative_strength_score"):
        raw = _number(quote.get(key))
        if raw is None:
            continue
        return raw * 100.0 if 0 <= raw <= 1 else raw
    if change_pct is None:
        return None
    return max(0.0, min(100.0, 50.0 + change_pct * 5.0))


def _candidate_strength_score(*, candidate: JsonDict, quote: JsonDict, change_pct: float | None, relative_strength: float | None) -> float:
    rs_component = relative_strength if relative_strength is not None else 50.0
    momentum_component = 50.0 + max(-25.0, min(25.0, (change_pct or 0.0) * 5.0))
    source_bonus = _source_priority(candidate.get("source")) * 1.5
    single_name_bonus = -2.0 if str(candidate.get("symbol") or "").upper() in {"QQQ", "SMH", "IWM", "GDX", "COPX", "SH588000", "SH512480", "SZ159915", "SH518880", "SH512400", "HK03033", "HK02800", "HK02840"} else 2.0
    score = (rs_component * 0.65) + (momentum_component * 0.35) + source_bonus + single_name_bonus
    return round(max(0.0, min(100.0, score)), 4)


def _source_priority(source: Any) -> int:
    return {"explicit_symbol": 4, "holding": 3, "candidate_pool": 2, "thematic_seed": 1}.get(str(source or ""), 0)


def _tool_data(result: JsonDict) -> JsonDict:
    if not isinstance(result, dict):
        return {}
    data = result.get("data")
    if isinstance(data, dict):
        nested = data.get("data")
        return nested if isinstance(nested, dict) else data
    return result if result.get("ok") is not False else {}


async def _safe_tool_call(fn: AsyncToolReader, arguments: JsonDict) -> JsonDict:
    try:
        return await fn(arguments)
    except Exception as exc:
        return {"ok": False, "status": "error", "error": str(exc), "data": {}, "source_refs": []}


def _normalize_market(market: str | None) -> str:
    value = str(market or "US").strip().upper().replace("/", "_").replace("+", "_")
    if value in {"A", "CN", "A股"}:
        return "CN"
    if value in {"H", "HK", "港股"}:
        return "HK"
    if value in {"CN_HK", "HK_CN", "A_HK", "AH"}:
        return "CN_HK"
    return value or "US"


def _market_for_symbol(symbol: str, fallback_market: str) -> str:
    symbol = symbol.upper()
    if symbol.startswith(("SH", "SZ")):
        return "CN"
    if symbol.startswith("HK"):
        return "HK"
    return "US" if fallback_market == "CN_HK" else fallback_market


def _playbook_for(theme: Any, symbol: str) -> str:
    text = f"{theme or ''} {symbol}".lower()
    if any(key in text for key in ("ai", "半导体", "芯片", "硬科技", "smh", "nvda", "qqq")):
        return "hard_tech_acceleration"
    return "default"


def _narrative(*, data: JsonDict, candidate: JsonDict, state: JsonDict) -> str:
    conclusion = ""
    report = data.get("report") if isinstance(data.get("report"), dict) else {}
    if report.get("conclusion"):
        conclusion = str(report["conclusion"])
    return conclusion or f"{candidate.get('symbol')} 属于 {candidate.get('asset_theme') or '机会观察'}，需要通过四道门后才进入信号账本。"


def _position_layer(actionability: str, state: JsonDict) -> str:
    if actionability == "trade_draft":
        return "mainline_or_high_beta_budget"
    if actionability == "suggested_action":
        return "watch_or_starter"
    return "watch"


def _budget_layer(actionability: str, state: JsonDict) -> str:
    cushion = state.get("profit_cushion") if isinstance(state.get("profit_cushion"), dict) else {}
    if actionability == "trade_draft" and cushion.get("status") in {"available", "configured"}:
        return "profit_cushion_attack_budget"
    return "research_only"


def _profit_cushion_state(overview: JsonDict) -> JsonDict:
    cushion = overview.get("profit_cushion") if isinstance(overview.get("profit_cushion"), dict) else {}
    if cushion:
        return {"status": "available", **cushion}
    realized = _number(overview.get("realized_pnl") or overview.get("year_to_date_profit"))
    if realized is not None and realized > 0:
        return {"status": "available", "source": "portfolio_overview", "year_to_date_profit": realized}
    return {"status": "missing", "reason": "profit_cushion_not_configured"}


def _theme_state(regimes: list[JsonDict], theme: str) -> JsonDict:
    summaries = []
    for regime in regimes:
        data = _tool_data(regime.get("result") if isinstance(regime.get("result"), dict) else {})
        market_regime = data.get("market_regime") if isinstance(data.get("market_regime"), dict) else {}
        summaries.append({"market": regime.get("market"), "regime": market_regime.get("regime"), "risk_bias": market_regime.get("risk_bias")})
    return {"theme": theme, "status": "observed", "evidence": summaries}


def _capital_path_split(regimes: list[JsonDict]) -> JsonDict:
    return {"status": "observed", "paths": [{"market": item.get("market"), "bias": _tool_data(item.get("result") or {}).get("market_regime", {}).get("risk_bias")} for item in regimes]}


def _research_prompt(candidate: JsonDict, state: JsonDict) -> str:
    return (
        f"机会研究：围绕 {candidate.get('asset_theme')} 分析 {candidate['symbol']}。"
        "必须按事实门、叙事门、纪律门、执行门输出；不下单；需要给出触发条件、失效条件和仓位层。"
    )


def _max_actionability(cases: list[JsonDict]) -> str:
    order = ["blocked", "info_only", "analysis_only", "suggested_action", "trade_draft"]
    best = "analysis_only"
    for case in cases:
        value = str(case.get("actionability_cap") or "analysis_only")
        if value in order and order.index(value) > order.index(best):
            best = value
    return best


def _dedupe_refs(refs: list[Any]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        source = str(ref.get("source") or "").strip()
        target = str(ref.get("ref") or ref.get("url") or "").strip()
        if not source or not target:
            continue
        key = (source, target)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"source": source, "ref": target})
    return deduped


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _sha256_json(payload: JsonDict) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
