"""
Post-confirmation task dispatcher.

The confirmation center owns user intent and confirmation state. This module
turns confirmed decisions into tenant-scoped background work without writing
business facts directly in the WeChat gateway request path.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from openclaw.gateway.confirmation_center import ConfirmationCommand, RoutingContext


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


@dataclass
class PostConfirmationTaskResult:
    task_id: str
    job_type: str
    status: str
    dedupe_key: str


class PostConfirmationTaskRepository(Protocol):
    async def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class InMemoryPostConfirmationTaskRepository:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.dedupe_index: dict[str, str] = {}

    async def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        dedupe_key = str(payload["config"]["dedupe_key"])
        existing_id = self.dedupe_index.get(dedupe_key)
        if existing_id and existing_id in self.tasks:
            return dict(self.tasks[existing_id])
        self.tasks[payload["id"]] = dict(payload)
        self.dedupe_index[dedupe_key] = payload["id"]
        return dict(payload)


class SupabasePostConfirmationTaskRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        dedupe_key = str(payload["config"]["dedupe_key"])

        def _upsert_like_insert() -> dict[str, Any]:
            existing = (
                self._client.table("job_runs")
                .select("*")
                .contains("config", {"dedupe_key": dedupe_key})
                .limit(1)
                .execute()
            )
            if existing.data:
                return existing.data[0]

            response = self._client.table("job_runs").insert(payload).execute()
            return response.data[0] if response.data else payload

        return await asyncio.to_thread(_upsert_like_insert)


class PostgresPostConfirmationTaskRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        self._database_url = database_url

    async def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        dedupe_key = str(payload["config"]["dedupe_key"])

        def _upsert_like_insert() -> dict[str, Any]:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb

            with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
                existing = conn.execute(
                    """
                    SELECT *
                    FROM public.job_runs
                    WHERE config @> %s::jsonb
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (Jsonb({"dedupe_key": dedupe_key}),),
                ).fetchone()
                if existing:
                    return dict(existing)

                row = conn.execute(
                    """
                    INSERT INTO public.job_runs (
                      id,
                      tenant_id,
                      job_type,
                      status,
                      config,
                      timeout_seconds,
                      runtime_target,
                      created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        payload["id"],
                        payload["tenant_id"],
                        payload["job_type"],
                        payload["status"],
                        Jsonb(_json_safe(payload.get("config") or {})),
                        payload.get("timeout_seconds"),
                        payload.get("runtime_target"),
                        payload.get("created_at"),
                    ),
                ).fetchone()
                conn.commit()
                return dict(row) if row else dict(payload)

        return await asyncio.to_thread(_upsert_like_insert)


class ConfirmationPostDecisionDispatcher:
    def __init__(
        self,
        repository: PostConfirmationTaskRepository,
        *,
        now_provider: callable | None = None,
    ) -> None:
        self._repository = repository
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def dispatch(
        self,
        *,
        context: RoutingContext,
        pending_action: dict[str, Any],
        session: dict[str, Any],
        command: ConfirmationCommand,
        post_decision: str,
    ) -> PostConfirmationTaskResult | None:
        if post_decision == "no_business_fact_write":
            return None

        task_spec = _resolve_task_spec(pending_action, post_decision)
        if task_spec is None:
            return None

        now = self._now_provider()
        task_id = str(uuid.uuid4())
        dedupe_key = _dedupe_key(
            post_decision=post_decision,
            pending_action_id=str(pending_action["id"]),
            confirmation_session_id=str(session["id"]),
            revision_text=command.revision_text,
        )
        config = {
            "dedupe_key": dedupe_key,
            "post_decision": post_decision,
            "decision_command": {
                "action": command.action,
                "via": command.via,
                "revision_text": command.revision_text,
                "session_hint": command.session_hint,
            },
            "pending_action": {
                "id": str(pending_action["id"]),
                "action_type": pending_action.get("action_type"),
                "action_scope": pending_action.get("action_scope"),
                "target_entity_type": pending_action.get("target_entity_type"),
                "target_entity_id": pending_action.get("target_entity_id"),
                "source_type": pending_action.get("source_type"),
                "source_surface": pending_action.get("source_surface"),
                "risk_level": pending_action.get("risk_level"),
                "confirmation_strength": pending_action.get("confirmation_strength"),
                "actionability_cap": pending_action.get("actionability_cap"),
                "action_payload": pending_action.get("action_payload") or {},
                "normalized_summary": pending_action.get("normalized_summary") or {},
            },
            "confirmation": {
                "session_id": str(session["id"]),
                "session_token": session.get("session_token"),
                "channel": session.get("channel"),
                "channel_binding_id": session.get("channel_binding_id"),
            },
            "routing": {
                "tenant_id": context.tenant_id,
                "channel_binding_id": context.channel_binding_id,
                "openclaw_account_id": context.openclaw_account_id,
                "context_token": context.context_token,
                "target_conversation": context.target_conversation,
                "session_space": context.session_space,
            },
            "execution_guard": _execution_guard(pending_action, post_decision),
            "source_write_guard": _source_write_guard(pending_action, post_decision),
            "task_category": task_spec["category"],
            "task_intent": task_spec["intent"],
        }
        payload: dict[str, Any] = {
            "id": task_id,
            "tenant_id": context.tenant_id,
            "job_type": task_spec["job_type"],
            "status": "PENDING",
            "config": config,
            "timeout_seconds": task_spec["timeout_seconds"],
            "runtime_target": "domain_worker",
            "created_at": now.isoformat(),
        }

        record = await self._repository.enqueue(payload)
        return PostConfirmationTaskResult(
            task_id=str(record["id"]),
            job_type=str(record.get("job_type", task_spec["job_type"])),
            status=str(record.get("status", "PENDING")),
            dedupe_key=str(record.get("config", {}).get("dedupe_key", dedupe_key)),
        )


def _resolve_task_spec(
    pending_action: dict[str, Any],
    post_decision: str,
) -> dict[str, Any] | None:
    if post_decision == "rebuild_confirmation_required":
        return {
            "job_type": "confirmation_rebuild_request",
            "category": "light",
            "intent": "根据用户修正内容重新生成待确认事项",
            "timeout_seconds": 300,
        }

    if post_decision != "commit_or_recalculate":
        return None

    action_type = str(pending_action.get("action_type") or "")
    target_entity_type = str(pending_action.get("target_entity_type") or "")

    if action_type == "position_snapshot_input":
        return {
            "job_type": "confirmed_position_snapshot_import",
            "category": "light",
            "intent": "确认持仓截图识别结果后写入持仓快照并刷新资产视图",
            "timeout_seconds": 300,
        }
    if action_type in {"trade_input", "asr_correction", "ocr_correction"}:
        return {
            "job_type": "confirmed_trade_recalculate_holdings",
            "category": "light",
            "intent": "确认交易记录后更新持仓、资产视图和相关分析缓存",
            "timeout_seconds": 300,
        }
    if action_type == "rule_override":
        return {
            "job_type": "confirmed_discipline_rule_save",
            "category": "light",
            "intent": "确认交易纪律变更后保存规则并刷新提醒策略",
            "timeout_seconds": 300,
        }
    if action_type == "trade_draft_ack" or target_entity_type == "sell_put_trade_draft":
        return {
            "job_type": "confirmed_sell_put_draft_finalize",
            "category": "deep",
            "intent": "确认 Sell Put 草稿后补全资金占用、风险提醒和候选说明",
            "timeout_seconds": 1800,
        }
    if action_type in {"broker_conflict", "broker_sync_conflict"}:
        return {
            "job_type": "confirmed_broker_conflict_reconcile",
            "category": "light",
            "intent": "确认券商同步冲突处理方案后执行数据修复",
            "timeout_seconds": 300,
        }
    if action_type == "portfolio_view_change":
        return {
            "job_type": "confirmed_portfolio_view_refresh",
            "category": "light",
            "intent": "确认资产视图调整后刷新账户展示",
            "timeout_seconds": 300,
        }
    return {
        "job_type": "confirmed_action_commit",
        "category": "light",
        "intent": "确认后执行对应业务处理",
        "timeout_seconds": 300,
    }


def _execution_guard(
    pending_action: dict[str, Any],
    post_decision: str,
) -> dict[str, Any]:
    trade_related = _is_trade_related_action(pending_action)
    guard = {
        "confirmation_record_required": True,
        "human_confirm_required": True,
        "auto_order_allowed": False,
        "trade_related": trade_related,
    }
    if trade_related:
        guard["draft_only"] = True
    if post_decision != "commit_or_recalculate":
        guard["fact_write_allowed"] = False
    return guard


def _source_write_guard(
    pending_action: dict[str, Any],
    post_decision: str,
) -> dict[str, Any]:
    payload = pending_action.get("action_payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    source_policy = payload.get("source_policy") or {}
    if not isinstance(source_policy, dict):
        source_policy = {}

    source_type = str(source_policy.get("source_type") or pending_action.get("source_type") or "manual")
    source_tier = str(source_policy.get("source_tier") or _default_source_tier(source_type))
    actionability = str(source_policy.get("actionability") or _default_source_actionability(source_type))
    fact_write_allowed = bool(source_policy.get("fact_write_allowed", actionability != "blocked"))
    if post_decision != "commit_or_recalculate":
        fact_write_allowed = False

    return {
        "source_type": source_type,
        "source_surface": source_policy.get("source_surface") or pending_action.get("source_surface"),
        "source_tier": source_tier,
        "actionability": actionability,
        "source_as_of": source_policy.get("as_of"),
        "fact_write_allowed": fact_write_allowed,
        "trade_action_allowed": bool(source_policy.get("trade_action_allowed", False)),
        "requires_human_confirmation": bool(source_policy.get("requires_human_confirmation", True)),
        "confidence": source_policy.get("confidence"),
        "quality_reasons": source_policy.get("quality_reasons") or [],
    }


def _default_source_tier(source_type: str) -> str:
    if "broker" in source_type:
        return "L1_trading"
    if source_type in {"ocr", "image_ocr", "voice_asr"}:
        return "user_confirmed"
    return "user_confirmed"


def _default_source_actionability(source_type: str) -> str:
    if "broker" in source_type:
        return "trade_draft"
    return "analysis_only"


def _is_trade_related_action(pending_action: dict[str, Any]) -> bool:
    action_type = str(pending_action.get("action_type") or "")
    action_scope = str(pending_action.get("action_scope") or "")
    target_entity_type = str(pending_action.get("target_entity_type") or "")
    return (
        action_type in {
            "trade_input",
            "trade_draft_ack",
            "asr_correction",
            "ocr_correction",
            "position_snapshot_input",
        }
        or action_scope == "fact_record"
        or target_entity_type in {"trade_event_input", "sell_put_trade_draft", "position_snapshot_input"}
    )


def _dedupe_key(
    *,
    post_decision: str,
    pending_action_id: str,
    confirmation_session_id: str,
    revision_text: str | None,
) -> str:
    raw = json.dumps(
        {
            "post_decision": post_decision,
            "pending_action_id": pending_action_id,
            "confirmation_session_id": confirmation_session_id,
            "revision_text": revision_text or "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"confirmation:{digest[:32]}"
