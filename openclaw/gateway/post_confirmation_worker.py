"""
Worker for jobs created after user confirmations.

The gateway request path only records the user's decision and enqueues a
job_runs record. This worker performs the background side effects and marks the
pending action as committed once the work has been accepted by the domain layer.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from openclaw.gateway.confirmation_center import parse_position_snapshot_rows
from openclaw.gateway.outbox import DeliveryEnvelope, DeliveryOutboxService, DeliveryQueueResult

logger = logging.getLogger(__name__)

SUPPORTED_POST_CONFIRMATION_JOB_TYPES = {
    "confirmed_trade_recalculate_holdings",
    "confirmed_position_snapshot_import",
    "confirmed_sell_put_draft_finalize",
    "confirmed_discipline_rule_save",
    "confirmed_broker_conflict_reconcile",
    "confirmed_portfolio_view_refresh",
    "confirmed_action_commit",
    "confirmation_rebuild_request",
}


def _json_safe(value: Any) -> Any:
    import json

    return json.loads(json.dumps(value, default=str))


@dataclass
class PostConfirmationWorkerStats:
    scanned: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    receipts_queued: int = 0
    receipts_failed: int = 0


class PostConfirmationWorkerRepository(Protocol):
    async def list_pending_jobs(self, job_types: set[str], limit: int = 20) -> list[dict[str, Any]]:
        ...

    async def start_job(self, job_id: str, now: datetime) -> None:
        ...

    async def complete_job(self, job_id: str, result: dict[str, Any], now: datetime) -> None:
        ...

    async def fail_job(self, job_id: str, error: str, now: datetime) -> None:
        ...

    async def update_pending_action(self, pending_action_id: str, updates: dict[str, Any]) -> None:
        ...

    async def append_confirmation_event(self, payload: dict[str, Any]) -> None:
        ...

    async def insert_trade_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    async def list_trade_events(self, tenant_id: str, symbol: str) -> list[dict[str, Any]]:
        ...

    async def upsert_position_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    async def upsert_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class ReceiptOutbox(Protocol):
    async def enqueue(
        self,
        envelope: DeliveryEnvelope,
        *,
        quiet_hours: dict[str, Any] | None = None,
    ) -> DeliveryQueueResult:
        ...


class InMemoryPostConfirmationWorkerRepository:
    def __init__(
        self,
        *,
        jobs: dict[str, dict[str, Any]] | None = None,
        pending_actions: dict[str, dict[str, Any]] | None = None,
        confirmation_events: list[dict[str, Any]] | None = None,
    ) -> None:
        self.jobs = jobs if jobs is not None else {}
        self.pending_actions = pending_actions if pending_actions is not None else {}
        self.confirmation_events = confirmation_events if confirmation_events is not None else []
        self.trade_events: list[dict[str, Any]] = []
        self.position_snapshots: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.artifacts: dict[tuple[str, str], dict[str, Any]] = {}

    async def list_pending_jobs(self, job_types: set[str], limit: int = 20) -> list[dict[str, Any]]:
        records = [
            record
            for record in self.jobs.values()
            if record.get("status") == "PENDING" and record.get("job_type") in job_types
        ]
        records.sort(key=lambda item: str(item.get("created_at", "")))
        return [dict(record) for record in records[:limit]]

    async def start_job(self, job_id: str, now: datetime) -> None:
        self.jobs[job_id].update({"status": "RUNNING", "started_at": now.isoformat()})

    async def complete_job(self, job_id: str, result: dict[str, Any], now: datetime) -> None:
        self.jobs[job_id].update(
            {
                "status": "SUCCESS",
                "result_summary": result,
                "completed_at": now.isoformat(),
            }
        )

    async def fail_job(self, job_id: str, error: str, now: datetime) -> None:
        current = self.jobs[job_id]
        current.update(
            {
                "status": "FAILED",
                "error_message": error,
                "retry_count": int(current.get("retry_count") or 0) + 1,
                "completed_at": now.isoformat(),
            }
        )

    async def update_pending_action(self, pending_action_id: str, updates: dict[str, Any]) -> None:
        self.pending_actions[pending_action_id].update(updates)

    async def append_confirmation_event(self, payload: dict[str, Any]) -> None:
        self.confirmation_events.append(dict(payload))

    async def insert_trade_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        fingerprint = payload.get("broker_message_fingerprint")
        for record in self.trade_events:
            if fingerprint and record.get("broker_message_fingerprint") == fingerprint:
                return dict(record)
        self.trade_events.append(dict(payload))
        return dict(payload)

    async def list_trade_events(self, tenant_id: str, symbol: str) -> list[dict[str, Any]]:
        records = [
            record
            for record in self.trade_events
            if record.get("tenant_id") == tenant_id and record.get("symbol") == symbol
        ]
        records.sort(key=lambda item: (str(item.get("trade_date", "")), str(item.get("created_at", ""))))
        return [dict(record) for record in records]

    async def upsert_position_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = (str(payload["tenant_id"]), str(payload["symbol"]), str(payload["snapshot_date"]))
        existing = self.position_snapshots.get(key, {})
        record = {**existing, **payload}
        if "id" not in record:
            record["id"] = str(uuid.uuid4())
        self.position_snapshots[key] = record
        return dict(record)

    async def upsert_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = (str(payload["tenant_id"]), str(payload["artifact_key"]))
        existing = self.artifacts.get(key, {})
        record = {**existing, **payload}
        if "id" not in record:
            record["id"] = str(uuid.uuid4())
        self.artifacts[key] = record
        return dict(record)


class SupabasePostConfirmationWorkerRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def list_pending_jobs(self, job_types: set[str], limit: int = 20) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            response = (
                self._client.table("job_runs")
                .select("*")
                .eq("status", "PENDING")
                .in_("job_type", sorted(job_types))
                .order("created_at", desc=False)
                .limit(limit)
                .execute()
            )
            return response.data or []

        return await asyncio.to_thread(_query)

    async def start_job(self, job_id: str, now: datetime) -> None:
        await self._update_job(job_id, {"status": "RUNNING", "started_at": now.isoformat()})

    async def complete_job(self, job_id: str, result: dict[str, Any], now: datetime) -> None:
        await self._update_job(
            job_id,
            {
                "status": "SUCCESS",
                "result_summary": result,
                "completed_at": now.isoformat(),
            },
        )

    async def fail_job(self, job_id: str, error: str, now: datetime) -> None:
        def _update() -> None:
            response = (
                self._client.table("job_runs")
                .select("retry_count")
                .eq("id", job_id)
                .limit(1)
                .execute()
            )
            retry_count = int(response.data[0].get("retry_count") or 0) if response.data else 0
            self._client.table("job_runs").update(
                {
                    "status": "FAILED",
                    "error_message": error,
                    "retry_count": retry_count + 1,
                    "completed_at": now.isoformat(),
                }
            ).eq("id", job_id).execute()

        await asyncio.to_thread(_update)

    async def update_pending_action(self, pending_action_id: str, updates: dict[str, Any]) -> None:
        def _update() -> None:
            self._client.table("pending_actions").update(updates).eq("id", pending_action_id).execute()

        await asyncio.to_thread(_update)

    async def append_confirmation_event(self, payload: dict[str, Any]) -> None:
        def _insert() -> None:
            self._client.table("confirmation_events").insert(payload).execute()

        await asyncio.to_thread(_insert)

    async def insert_trade_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        fingerprint = payload.get("broker_message_fingerprint")

        def _insert() -> dict[str, Any]:
            if fingerprint:
                existing = (
                    self._client.table("trade_events")
                    .select("*")
                    .eq("tenant_id", payload["tenant_id"])
                    .eq("broker_message_fingerprint", fingerprint)
                    .limit(1)
                    .execute()
                )
                if existing.data:
                    return existing.data[0]
            response = self._client.table("trade_events").insert(payload).execute()
            return response.data[0] if response.data else payload

        return await asyncio.to_thread(_insert)

    async def list_trade_events(self, tenant_id: str, symbol: str) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            response = (
                self._client.table("trade_events")
                .select("*")
                .eq("tenant_id", tenant_id)
                .eq("symbol", symbol)
                .order("trade_date", desc=False)
                .order("created_at", desc=False)
                .execute()
            )
            return response.data or []

        return await asyncio.to_thread(_query)

    async def upsert_position_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _upsert() -> dict[str, Any]:
            existing = (
                self._client.table("position_snapshots")
                .select("id")
                .eq("tenant_id", payload["tenant_id"])
                .eq("symbol", payload["symbol"])
                .eq("snapshot_date", payload["snapshot_date"])
                .limit(1)
                .execute()
            )
            if existing.data:
                record_id = existing.data[0]["id"]
                response = (
                    self._client.table("position_snapshots")
                    .update(payload)
                    .eq("id", record_id)
                    .execute()
                )
                return response.data[0] if response.data else {**payload, "id": record_id}
            response = self._client.table("position_snapshots").insert(payload).execute()
            return response.data[0] if response.data else payload

        return await asyncio.to_thread(_upsert)

    async def upsert_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _upsert() -> dict[str, Any]:
            existing = (
                self._client.table("artifact_registry")
                .select("id")
                .eq("tenant_id", payload["tenant_id"])
                .eq("artifact_key", payload["artifact_key"])
                .limit(1)
                .execute()
            )
            if existing.data:
                record_id = existing.data[0]["id"]
                response = (
                    self._client.table("artifact_registry")
                    .update(payload)
                    .eq("id", record_id)
                    .execute()
                )
                return response.data[0] if response.data else {**payload, "id": record_id}
            response = self._client.table("artifact_registry").insert(payload).execute()
            return response.data[0] if response.data else payload

        return await asyncio.to_thread(_upsert)

    async def _update_job(self, job_id: str, updates: dict[str, Any]) -> None:
        def _update() -> None:
            self._client.table("job_runs").update(updates).eq("id", job_id).execute()

        await asyncio.to_thread(_update)


class PostgresPostConfirmationWorkerRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        self._database_url = database_url

    async def list_pending_jobs(self, job_types: set[str], limit: int = 20) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            import psycopg
            from psycopg.rows import dict_row

            with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM public.job_runs
                    WHERE status = 'PENDING'
                      AND job_type = ANY(%s)
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (sorted(job_types), limit),
                ).fetchall()
                return [dict(row) for row in rows]

        return await asyncio.to_thread(_query)

    async def start_job(self, job_id: str, now: datetime) -> None:
        await self._update_job(job_id, {"status": "RUNNING", "started_at": now.isoformat()})

    async def complete_job(self, job_id: str, result: dict[str, Any], now: datetime) -> None:
        await self._update_job(
            job_id,
            {
                "status": "SUCCESS",
                "result_summary": _json_safe(result),
                "completed_at": now.isoformat(),
            },
        )

    async def fail_job(self, job_id: str, error: str, now: datetime) -> None:
        def _update() -> None:
            import psycopg

            with psycopg.connect(self._database_url) as conn:
                conn.execute(
                    """
                    UPDATE public.job_runs
                    SET status = 'FAILED',
                        error_message = %s,
                        retry_count = COALESCE(retry_count, 0) + 1,
                        completed_at = %s
                    WHERE id = %s::uuid
                    """,
                    (error, now.isoformat(), job_id),
                )
                conn.commit()

        await asyncio.to_thread(_update)

    async def update_pending_action(self, pending_action_id: str, updates: dict[str, Any]) -> None:
        await self._update_row("pending_actions", pending_action_id, updates)

    async def append_confirmation_event(self, payload: dict[str, Any]) -> None:
        def _insert() -> None:
            import psycopg
            from psycopg.types.json import Jsonb

            safe = _json_safe(payload)
            with psycopg.connect(self._database_url) as conn:
                conn.execute(
                    """
                    INSERT INTO public.confirmation_events (
                      id, tenant_id, pending_action_id, confirmation_session_id,
                      event_type, actor_type, actor_ref, event_payload, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        safe.get("id") or str(uuid.uuid4()),
                        safe["tenant_id"],
                        safe.get("pending_action_id"),
                        safe.get("confirmation_session_id"),
                        safe["event_type"],
                        safe.get("actor_type"),
                        safe.get("actor_ref"),
                        Jsonb(safe.get("event_payload") or {}),
                        safe.get("created_at"),
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_insert)

    async def insert_trade_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        fingerprint = payload.get("broker_message_fingerprint")

        def _insert() -> dict[str, Any]:
            import psycopg
            from psycopg.rows import dict_row

            with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
                if fingerprint:
                    existing = conn.execute(
                        """
                        SELECT *
                        FROM public.trade_events
                        WHERE tenant_id = %s
                          AND broker_message_fingerprint = %s
                        LIMIT 1
                        """,
                        (payload["tenant_id"], fingerprint),
                    ).fetchone()
                    if existing:
                        return dict(existing)
                safe = _json_safe(payload)
                row = conn.execute(
                    """
                    INSERT INTO public.trade_events (
                      id, tenant_id, symbol, provider_symbol, market, exchange,
                      stock_name, side, price, quantity, trade_amount, trade_date,
                      note, strategy_tag, source, broker_message_fingerprint, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        safe.get("id") or str(uuid.uuid4()),
                        safe["tenant_id"],
                        safe["symbol"],
                        safe.get("provider_symbol"),
                        safe.get("market"),
                        safe.get("exchange"),
                        safe.get("stock_name"),
                        safe["side"],
                        safe.get("price"),
                        safe.get("quantity"),
                        safe.get("trade_amount"),
                        safe.get("trade_date"),
                        safe.get("note"),
                        safe.get("strategy_tag"),
                        safe.get("source"),
                        safe.get("broker_message_fingerprint"),
                        safe.get("created_at"),
                    ),
                ).fetchone()
                conn.commit()
                return dict(row) if row else safe

        return await asyncio.to_thread(_insert)

    async def list_trade_events(self, tenant_id: str, symbol: str) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            import psycopg
            from psycopg.rows import dict_row

            with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM public.trade_events
                    WHERE tenant_id = %s
                      AND symbol = %s
                    ORDER BY trade_date ASC, created_at ASC
                    """,
                    (tenant_id, symbol),
                ).fetchall()
                return [dict(row) for row in rows]

        return await asyncio.to_thread(_query)

    async def upsert_position_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _upsert() -> dict[str, Any]:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb

            safe = _json_safe(payload)
            with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
                existing = conn.execute(
                    """
                    SELECT id
                    FROM public.position_snapshots
                    WHERE tenant_id = %s
                      AND symbol = %s
                      AND snapshot_date = %s
                    LIMIT 1
                    """,
                    (safe["tenant_id"], safe["symbol"], safe["snapshot_date"]),
                ).fetchone()
                record_id = str(existing["id"]) if existing else (safe.get("id") or str(uuid.uuid4()))
                row = conn.execute(
                    """
                    INSERT INTO public.position_snapshots (
                      id, tenant_id, symbol, provider_symbol, market, exchange,
                      stock_name, total_quantity, average_cost, total_cost,
                      snapshot_date, computed_from_event_ids, created_at,
                      source_type, source_tier, source_actionability, source_as_of, source_lineage
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[], %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      provider_symbol = EXCLUDED.provider_symbol,
                      market = EXCLUDED.market,
                      exchange = EXCLUDED.exchange,
                      stock_name = EXCLUDED.stock_name,
                      total_quantity = EXCLUDED.total_quantity,
                      average_cost = EXCLUDED.average_cost,
                      total_cost = EXCLUDED.total_cost,
                      computed_from_event_ids = EXCLUDED.computed_from_event_ids,
                      source_type = EXCLUDED.source_type,
                      source_tier = EXCLUDED.source_tier,
                      source_actionability = EXCLUDED.source_actionability,
                      source_as_of = EXCLUDED.source_as_of,
                      source_lineage = EXCLUDED.source_lineage
                    RETURNING *
                    """,
                    (
                        record_id,
                        safe["tenant_id"],
                        safe["symbol"],
                        safe.get("provider_symbol"),
                        safe.get("market"),
                        safe.get("exchange"),
                        safe.get("stock_name"),
                        safe.get("total_quantity"),
                        safe.get("average_cost"),
                        safe.get("total_cost"),
                        safe.get("snapshot_date"),
                        safe.get("computed_from_event_ids") or [],
                        safe.get("created_at"),
                        safe.get("source_type"),
                        safe.get("source_tier"),
                        safe.get("source_actionability"),
                        safe.get("source_as_of"),
                        Jsonb(safe.get("source_lineage") or {}),
                    ),
                ).fetchone()
                conn.commit()
                return dict(row) if row else safe

        return await asyncio.to_thread(_upsert)

    async def upsert_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _upsert() -> dict[str, Any]:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb

            safe = _json_safe(payload)
            with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
                existing = conn.execute(
                    """
                    SELECT id
                    FROM public.artifact_registry
                    WHERE tenant_id = %s
                      AND artifact_key = %s
                    LIMIT 1
                    """,
                    (safe["tenant_id"], safe["artifact_key"]),
                ).fetchone()
                record_id = str(existing["id"]) if existing else (safe.get("id") or str(uuid.uuid4()))
                row = conn.execute(
                    """
                    INSERT INTO public.artifact_registry (
                      id, tenant_id, source_run_id, run_contract_id, artifact_key,
                      artifact_type, artifact_status, visibility, storage_backend,
                      storage_bucket, storage_path, mime_type, content_hash,
                      source_lineage, artifact_metadata, retention_until, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      artifact_type = EXCLUDED.artifact_type,
                      artifact_status = EXCLUDED.artifact_status,
                      visibility = EXCLUDED.visibility,
                      storage_backend = EXCLUDED.storage_backend,
                      storage_bucket = EXCLUDED.storage_bucket,
                      storage_path = EXCLUDED.storage_path,
                      mime_type = EXCLUDED.mime_type,
                      content_hash = EXCLUDED.content_hash,
                      source_lineage = EXCLUDED.source_lineage,
                      artifact_metadata = EXCLUDED.artifact_metadata,
                      retention_until = EXCLUDED.retention_until,
                      updated_at = EXCLUDED.updated_at
                    RETURNING *
                    """,
                    (
                        record_id,
                        safe["tenant_id"],
                        safe.get("source_run_id"),
                        safe.get("run_contract_id"),
                        safe["artifact_key"],
                        safe["artifact_type"],
                        safe.get("artifact_status", "ready"),
                        safe.get("visibility", "tenant"),
                        safe.get("storage_backend"),
                        safe.get("storage_bucket"),
                        safe.get("storage_path"),
                        safe.get("mime_type"),
                        safe.get("content_hash"),
                        Jsonb(safe.get("source_lineage") or {}),
                        Jsonb(safe.get("artifact_metadata") or {}),
                        safe.get("retention_until"),
                        safe.get("created_at"),
                        safe.get("updated_at"),
                    ),
                ).fetchone()
                conn.commit()
                return dict(row) if row else safe

        return await asyncio.to_thread(_upsert)

    async def _update_job(self, job_id: str, updates: dict[str, Any]) -> None:
        await self._update_row("job_runs", job_id, updates)

    async def _update_row(self, table: str, row_id: str, updates: dict[str, Any]) -> None:
        if not updates:
            return
        allowed_tables = {"job_runs", "pending_actions"}
        if table not in allowed_tables:
            raise ValueError(f"unsupported table update: {table}")

        def _update() -> None:
            import psycopg
            from psycopg.types.json import Jsonb

            assignments: list[str] = []
            values: list[Any] = []
            for key, value in updates.items():
                assignments.append(f"{key} = %s")
                if key in {"config", "result_summary", "action_payload", "normalized_summary"}:
                    values.append(Jsonb(_json_safe(value)))
                else:
                    values.append(value)
            values.append(row_id)
            with psycopg.connect(self._database_url) as conn:
                cursor = conn.execute(
                    f"UPDATE public.{table} SET {', '.join(assignments)} WHERE id = %s::uuid",
                    tuple(values),
                )
                if cursor.rowcount == 0:
                    raise ValueError(f"{table} row not found: {row_id}")
                conn.commit()

        await asyncio.to_thread(_update)


class PostConfirmationJobWorker:
    def __init__(
        self,
        repository: PostConfirmationWorkerRepository,
        *,
        receipt_outbox: ReceiptOutbox | None = None,
        now_provider: callable | None = None,
    ) -> None:
        self._repository = repository
        self._receipt_outbox = receipt_outbox
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def process_once(self, *, limit: int = 20) -> PostConfirmationWorkerStats:
        jobs = await self._repository.list_pending_jobs(SUPPORTED_POST_CONFIRMATION_JOB_TYPES, limit=limit)
        stats = PostConfirmationWorkerStats(scanned=len(jobs))
        for job in jobs:
            job_id = str(job["id"])
            now = self._now_provider()
            try:
                await self._repository.start_job(job_id, now)
                result = await self._handle_job(job, now)
                receipt_result = await self._enqueue_receipt(
                    job,
                    result,
                    success=True,
                    now=self._now_provider(),
                )
                if receipt_result is not None:
                    result["receipt_delivery_id"] = receipt_result.delivery_id
                    result["receipt_status"] = receipt_result.status
                    stats.receipts_queued += 1
                await self._repository.complete_job(job_id, result, self._now_provider())
                stats.succeeded += 1
            except Exception as exc:
                logger.exception("Post-confirmation job failed (job_id=%s)", job_id)
                await self._mark_job_failed(job, str(exc), self._now_provider())
                receipt_result = await self._enqueue_receipt(
                    job,
                    {},
                    success=False,
                    error=str(exc),
                    now=self._now_provider(),
                )
                if receipt_result is not None:
                    stats.receipts_queued += 1
                stats.failed += 1
        return stats

    async def _handle_job(self, job: dict[str, Any], now: datetime) -> dict[str, Any]:
        job_type = str(job.get("job_type") or "")
        if job_type not in SUPPORTED_POST_CONFIRMATION_JOB_TYPES:
            return {"skipped": True, "reason": "unsupported_job_type", "job_type": job_type}

        _assert_confirmation_guard(job)
        if job_type == "confirmed_trade_recalculate_holdings":
            result = await self._handle_trade_recalculation(job, now)
        elif job_type == "confirmed_position_snapshot_import":
            result = await self._handle_position_snapshot_import(job, now)
        elif job_type == "confirmation_rebuild_request":
            result = await self._handle_rebuild_request(job, now)
        else:
            result = await self._handle_artifact_only_commit(job, now)

        await self._mark_pending_committed_if_needed(job, result, now)
        return result

    async def _handle_trade_recalculation(self, job: dict[str, Any], now: datetime) -> dict[str, Any]:
        config = _job_config(job)
        pending = _pending_action(config)
        trade_event = _parse_trade_event_from_pending(
            tenant_id=str(job["tenant_id"]),
            pending=pending,
            dedupe_key=str(config.get("dedupe_key") or job["id"]),
            now=now,
        )
        stored_trade = await self._repository.insert_trade_event(trade_event)
        events = await self._repository.list_trade_events(str(job["tenant_id"]), trade_event["symbol"])
        snapshot_payload = _build_position_snapshot(
            tenant_id=str(job["tenant_id"]),
            symbol=trade_event["symbol"],
            events=events,
            now=now,
        )
        warnings = list(snapshot_payload.pop("warnings", []))
        snapshot = await self._repository.upsert_position_snapshot(snapshot_payload)
        return {
            "handler": "confirmed_trade_recalculate_holdings",
            "trade_event_id": stored_trade.get("id"),
            "symbol": trade_event["symbol"],
            "snapshot_id": snapshot.get("id"),
            "position_quantity": snapshot.get("total_quantity"),
            "warnings": warnings,
        }

    async def _handle_position_snapshot_import(self, job: dict[str, Any], now: datetime) -> dict[str, Any]:
        config = _job_config(job)
        pending = _pending_action(config)
        positions = _position_rows_from_pending(pending)
        if not positions:
            raise ValueError("confirmed position snapshot input has no parseable positions")

        snapshot_ids: list[str] = []
        symbols: list[str] = []
        symbols_requiring_review: list[str] = []
        for position in positions:
            payload = _position_snapshot_payload_from_row(
                tenant_id=str(job["tenant_id"]),
                position=position,
                now=now,
            )
            snapshot = await self._repository.upsert_position_snapshot(payload)
            snapshot_ids.append(str(snapshot.get("id") or ""))
            symbols.append(str(payload["symbol"]))
            if (payload.get("source_lineage") or {}).get("requires_symbol_review"):
                symbols_requiring_review.append(str(payload["symbol"]))

        return {
            "handler": "confirmed_position_snapshot_import",
            "positions_count": len(positions),
            "symbols": symbols,
            "symbols_requiring_review": symbols_requiring_review,
            "requires_symbol_review_count": len(symbols_requiring_review),
            "snapshot_ids": [item for item in snapshot_ids if item],
            "snapshot_id": snapshot_ids[0] if snapshot_ids else None,
        }

    async def _handle_artifact_only_commit(self, job: dict[str, Any], now: datetime) -> dict[str, Any]:
        config = _job_config(job)
        job_type = str(job.get("job_type") or "confirmed_action_commit")
        artifact_type = _artifact_type_for_job(job_type)
        guard = _execution_guard(config)
        artifact = await self._repository.upsert_artifact(
            _artifact_payload(
                tenant_id=str(job["tenant_id"]),
                job=job,
                artifact_type=artifact_type,
                now=now,
                metadata={
                    "post_decision": config.get("post_decision"),
                    "decision_command": config.get("decision_command") or {},
                    "pending_action": config.get("pending_action") or {},
                    "routing": config.get("routing") or {},
                    "task_intent": config.get("task_intent"),
                    "draft_only": bool(guard.get("draft_only")),
                    "human_confirm_required": bool(guard.get("human_confirm_required")),
                    "auto_order_allowed": guard.get("auto_order_allowed"),
                    "requires_manual_order": job_type == "confirmed_sell_put_draft_finalize",
                    "execution_note": _artifact_execution_note(job_type),
                },
            )
        )
        return {
            "handler": job_type,
            "artifact_id": artifact.get("id"),
            "artifact_type": artifact_type,
        }

    async def _handle_rebuild_request(self, job: dict[str, Any], now: datetime) -> dict[str, Any]:
        config = _job_config(job)
        artifact = await self._repository.upsert_artifact(
            _artifact_payload(
                tenant_id=str(job["tenant_id"]),
                job=job,
                artifact_type="confirmation_rebuild_request",
                now=now,
                metadata={
                    "revision_text": (config.get("decision_command") or {}).get("revision_text"),
                    "pending_action": config.get("pending_action") or {},
                    "routing": config.get("routing") or {},
                    "execution_note": "User requested a revised confirmation; no business fact was committed.",
                },
            )
        )
        return {
            "handler": "confirmation_rebuild_request",
            "artifact_id": artifact.get("id"),
            "artifact_type": "confirmation_rebuild_request",
        }

    async def _mark_pending_committed_if_needed(
        self,
        job: dict[str, Any],
        result: dict[str, Any],
        now: datetime,
    ) -> None:
        config = _job_config(job)
        if config.get("post_decision") != "commit_or_recalculate":
            return
        pending = _pending_action(config)
        confirmation = _confirmation(config)
        pending_action_id = pending.get("id")
        if not pending_action_id:
            return
        await self._repository.update_pending_action(
            str(pending_action_id),
            {
                "status": "committed",
                "committed_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )
        await self._repository.append_confirmation_event(
            _confirmation_event_payload(
                tenant_id=str(job["tenant_id"]),
                pending_action_id=str(pending_action_id),
                confirmation_session_id=confirmation.get("session_id"),
                event_type="commit_succeeded",
                event_payload={
                    "job_run_id": str(job["id"]),
                    "job_type": job.get("job_type"),
                    "result": result,
                },
                now=now,
            )
        )

    async def _mark_job_failed(self, job: dict[str, Any], error: str, now: datetime) -> None:
        await self._repository.fail_job(str(job["id"]), error, now)
        config = _job_config(job)
        pending = _pending_action(config)
        confirmation = _confirmation(config)
        pending_action_id = pending.get("id")
        if not pending_action_id:
            return
        if config.get("post_decision") == "commit_or_recalculate":
            await self._repository.update_pending_action(
                str(pending_action_id),
                {
                    "status": "failed_retryable",
                    "updated_at": now.isoformat(),
                },
            )
        await self._repository.append_confirmation_event(
            _confirmation_event_payload(
                tenant_id=str(job["tenant_id"]),
                pending_action_id=str(pending_action_id),
                confirmation_session_id=confirmation.get("session_id"),
                event_type="commit_failed",
                event_payload={
                    "job_run_id": str(job["id"]),
                    "job_type": job.get("job_type"),
                    "error": error,
                },
                now=now,
            )
        )

    async def _enqueue_receipt(
        self,
        job: dict[str, Any],
        result: dict[str, Any],
        *,
        success: bool,
        now: datetime,
        error: str | None = None,
    ) -> DeliveryQueueResult | None:
        if self._receipt_outbox is None:
            return None

        envelope = _receipt_delivery_envelope(
            job,
            result,
            success=success,
            now=now,
            error=error,
        )
        if envelope is None:
            logger.info(
                "Skip post-confirmation receipt because routing is incomplete (job_id=%s)",
                job.get("id"),
            )
            return None
        try:
            return await self._receipt_outbox.enqueue(envelope)
        except Exception:
            logger.exception("Failed to enqueue post-confirmation receipt (job_id=%s)", job.get("id"))
            return None


def _job_config(job: dict[str, Any]) -> dict[str, Any]:
    config = job.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("job config must be an object")
    return config


def _pending_action(config: dict[str, Any]) -> dict[str, Any]:
    pending = config.get("pending_action") or {}
    if not isinstance(pending, dict):
        raise ValueError("pending_action config must be an object")
    return pending


def _confirmation(config: dict[str, Any]) -> dict[str, Any]:
    confirmation = config.get("confirmation") or {}
    if not isinstance(confirmation, dict):
        return {}
    return confirmation


def _execution_guard(config: dict[str, Any]) -> dict[str, Any]:
    guard = config.get("execution_guard") or {}
    if not isinstance(guard, dict):
        raise ValueError("execution_guard config must be an object")
    return guard


def _source_write_guard(config: dict[str, Any]) -> dict[str, Any]:
    guard = config.get("source_write_guard") or {}
    if not isinstance(guard, dict):
        raise ValueError("source_write_guard config must be an object")
    return guard


def _assert_confirmation_guard(job: dict[str, Any]) -> None:
    job_type = str(job.get("job_type") or "")
    if job_type not in {
        "confirmed_trade_recalculate_holdings",
        "confirmed_position_snapshot_import",
        "confirmed_sell_put_draft_finalize",
    }:
        return

    config = _job_config(job)
    guard = _execution_guard(config)
    confirmation = _confirmation(config)
    decision_command = config.get("decision_command") or {}
    if not isinstance(decision_command, dict):
        raise ValueError("decision_command config must be an object")

    if not guard.get("confirmation_record_required"):
        raise ValueError("confirmation record is required before trade-related processing")
    if not confirmation.get("session_id"):
        raise ValueError("confirmation session is required before trade-related processing")
    if decision_command.get("action") != "confirm":
        raise ValueError("trade-related processing requires explicit user confirmation")
    if not guard.get("human_confirm_required"):
        raise ValueError("trade-related processing must remain human_confirm_required")
    if not guard.get("draft_only"):
        raise ValueError("trade-related processing must remain draft_only")
    if guard.get("auto_order_allowed") is not False:
        raise ValueError("trade-related processing must never allow automatic orders")
    _assert_source_write_guard(job)


def _assert_source_write_guard(job: dict[str, Any]) -> None:
    config = _job_config(job)
    source_guard = _source_write_guard(config)
    if not source_guard:
        return
    if not source_guard.get("fact_write_allowed"):
        raise ValueError("source freshness/actionability gate does not allow fact writes")
    if source_guard.get("requires_human_confirmation") and not _confirmation(config).get("session_id"):
        raise ValueError("source write requires confirmation session")
    if source_guard.get("trade_action_allowed") is True:
        raise ValueError("post-confirmation fact writes must not allow automatic trade actions")
    if str(source_guard.get("actionability") or "") == "blocked":
        raise ValueError("blocked source cannot be written to holdings")


def _parse_trade_event_from_pending(
    *,
    tenant_id: str,
    pending: dict[str, Any],
    dedupe_key: str,
    now: datetime,
) -> dict[str, Any]:
    payload = pending.get("action_payload") or {}
    summary = pending.get("normalized_summary") or {}
    structured = payload.get("structured_trade")
    if isinstance(structured, dict):
        return _trade_event_from_structured_payload(
            tenant_id=tenant_id,
            pending=pending,
            structured=structured,
            dedupe_key=dedupe_key,
            now=now,
        )
    text = str(
        payload.get("normalized_text")
        or payload.get("raw_text")
        or payload.get("raw_transcript")
        or summary.get("body")
        or ""
    ).strip()
    if not text:
        raise ValueError("confirmed trade input has no text payload")

    side = _parse_side(text)
    symbol = _parse_symbol(text)
    quantity = _parse_quantity(text, symbol)
    price = _parse_price(text, quantity)
    market, exchange = _infer_market_exchange(symbol)
    trade_amount = round(price * quantity, 2)
    event_id = str(uuid.uuid4())
    return {
        "id": event_id,
        "tenant_id": tenant_id,
        "symbol": symbol,
        "provider_symbol": symbol,
        "market": market,
        "exchange": exchange,
        "stock_name": None,
        "side": side,
        "price": price,
        "quantity": quantity,
        "trade_amount": trade_amount,
        "trade_date": now.date().isoformat(),
        "note": text,
        "strategy_tag": None,
        "source": _trade_source_from_pending(pending),
        "broker_message_fingerprint": dedupe_key,
        "created_at": now.isoformat(),
    }


def _trade_event_from_structured_payload(
    *,
    tenant_id: str,
    pending: dict[str, Any],
    structured: dict[str, Any],
    dedupe_key: str,
    now: datetime,
) -> dict[str, Any]:
    symbol = str(structured.get("symbol") or "").upper().strip()
    side = str(structured.get("side") or "").upper().strip()
    quantity = int(float(structured.get("quantity") or 0))
    price = float(structured.get("price") or 0)
    if side not in {"BUY", "SELL"}:
        raise ValueError("structured trade side is invalid")
    if not symbol:
        raise ValueError("structured trade symbol is missing")
    if quantity <= 0:
        raise ValueError("structured trade quantity is invalid")
    if price <= 0:
        raise ValueError("structured trade price is invalid")

    market = str(structured.get("market") or _infer_market_exchange(symbol)[0])
    exchange = str(structured.get("exchange") or _infer_market_exchange(symbol)[1])
    trade_date = _structured_trade_date(structured, now)
    payload = pending.get("action_payload") or {}
    raw_text = str(payload.get("raw_text") or payload.get("normalized_text") or "").strip()
    fingerprint = (
        structured.get("fingerprint")
        or payload.get("broker_message_fingerprint")
        or dedupe_key
    )
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "symbol": symbol,
        "provider_symbol": str(structured.get("provider_symbol") or symbol),
        "market": market,
        "exchange": exchange,
        "stock_name": structured.get("stock_name"),
        "side": side,
        "price": price,
        "quantity": quantity,
        "trade_amount": round(float(structured.get("trade_amount") or price * quantity), 2),
        "trade_date": trade_date,
        "note": raw_text,
        "strategy_tag": None,
        "source": _trade_source_from_pending(pending),
        "broker_message_fingerprint": str(fingerprint),
        "created_at": now.isoformat(),
    }


def _structured_trade_date(structured: dict[str, Any], now: datetime) -> str:
    trade_time = str(structured.get("trade_time") or "").strip()
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", trade_time)
    if match:
        return "-".join(match.groups())
    return now.date().isoformat()


def _parse_side(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("卖出", "减仓", "清仓", "sell")):
        return "SELL"
    if any(token in lowered for token in ("买入", "加仓", "补仓", "buy")):
        return "BUY"
    raise ValueError("trade side is missing")


def _parse_symbol(text: str) -> str:
    for upper_match in re.finditer(r"\b([A-Z]{1,6}(?:\.[A-Z]{1,4})?)\b", text):
        token = upper_match.group(1).upper()
        if token not in {"BUY", "SELL", "PUT", "CALL"}:
            return token
    numeric_match = re.search(r"\b(\d{5,6})(?:\.(SH|SZ|HK))?\b", text, re.IGNORECASE)
    if numeric_match:
        suffix = numeric_match.group(2)
        if suffix:
            return f"{numeric_match.group(1)}.{suffix.upper()}"
        return numeric_match.group(1)
    raise ValueError("trade symbol is missing")


def _parse_quantity(text: str, symbol: str) -> int:
    quantity_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:股|shares?|手)", text, re.IGNORECASE)
    if quantity_match:
        return int(float(quantity_match.group(1)))
    after_symbol = text[text.find(symbol) + len(symbol):] if symbol in text else text
    numbers = re.findall(r"\d+(?:\.\d+)?", after_symbol)
    if numbers:
        return int(float(numbers[0]))
    raise ValueError("trade quantity is missing")


def _parse_price(text: str, quantity: int) -> float:
    explicit = re.search(r"(?:@|价格|成本价|price)\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if explicit:
        return float(explicit.group(1))
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", text)]
    candidates = [item for item in numbers if int(item) != quantity or "." in str(item)]
    if candidates:
        return float(candidates[-1])
    raise ValueError("trade price is missing")


def _trade_source_from_pending(pending: dict[str, Any]) -> str:
    source_type = str(pending.get("source_type") or "")
    if "broker" in source_type:
        return "broker_wechat"
    if source_type in {"ocr", "image_ocr"}:
        return "ocr"
    return "manual"


def _position_rows_from_pending(pending: dict[str, Any]) -> list[dict[str, Any]]:
    payload = pending.get("action_payload") or {}
    if not isinstance(payload, dict):
        raise ValueError("position snapshot payload must be an object")
    source_policy = payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else {}
    positions = payload.get("positions")
    if isinstance(positions, list):
        return [
            {**dict(item), "source_policy": {**source_policy, **(item.get("source_policy") or {})}}
            for item in positions
            if isinstance(item, dict)
        ]
    text = str(
        payload.get("normalized_text")
        or payload.get("ocr_text")
        or payload.get("image_text")
        or pending.get("normalized_summary", {}).get("body")
        or ""
    ).strip()
    return [{**item, "source_policy": source_policy} for item in parse_position_snapshot_rows(text)]


def _position_snapshot_payload_from_row(
    *,
    tenant_id: str,
    position: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    symbol = str(position.get("symbol") or "").upper().strip()
    if not symbol:
        raise ValueError("position row symbol is missing")
    quantity = int(float(position.get("quantity") or 0))
    if quantity <= 0:
        raise ValueError(f"position quantity is invalid for {symbol}")
    average_cost = position.get("average_cost")
    average_cost_float = float(average_cost) if average_cost is not None else None
    total_cost = round(average_cost_float * quantity, 2) if average_cost_float is not None else None
    market = str(position.get("market") or _infer_market_exchange(symbol)[0])
    exchange = str(position.get("exchange") or _infer_market_exchange(symbol)[1])
    source_guard = _position_source_guard(position)
    source_as_of = _position_source_as_of(position, now)
    return {
        "tenant_id": tenant_id,
        "symbol": symbol,
        "provider_symbol": str(position.get("provider_symbol") or symbol),
        "market": market,
        "exchange": exchange,
        "stock_name": position.get("stock_name"),
        "total_quantity": quantity,
        "average_cost": average_cost_float,
        "total_cost": total_cost,
        "snapshot_date": now.date().isoformat(),
        "computed_from_event_ids": [],
        "source_type": source_guard["source_type"],
        "source_tier": source_guard["source_tier"],
        "source_actionability": source_guard["actionability"],
        "source_as_of": source_as_of,
        "source_lineage": source_guard["source_lineage"],
        "created_at": now.isoformat(),
    }


def _position_source_guard(position: dict[str, Any]) -> dict[str, Any]:
    raw_policy = position.get("source_policy") or {}
    if not isinstance(raw_policy, dict):
        raw_policy = {}
    source_type = str(raw_policy.get("source_type") or position.get("source_type") or "ocr")
    source_tier = str(raw_policy.get("source_tier") or "user_confirmed")
    actionability = str(raw_policy.get("actionability") or "analysis_only")
    if actionability == "blocked":
        raise ValueError("blocked source cannot be written to holdings")
    return {
        "source_type": source_type,
        "source_tier": source_tier,
        "actionability": actionability,
        "source_lineage": {
            "source_type": source_type,
            "source_tier": source_tier,
            "actionability": actionability,
            "confidence": raw_policy.get("confidence"),
            "quality_reasons": raw_policy.get("quality_reasons") or [],
            "fact_write_allowed": bool(raw_policy.get("fact_write_allowed", True)),
            "trade_action_allowed": bool(raw_policy.get("trade_action_allowed", False)),
            "raw_line": position.get("raw_line"),
            "requires_symbol_review": bool(position.get("requires_symbol_review")),
        },
    }


def _position_source_as_of(position: dict[str, Any], now: datetime) -> str:
    raw_policy = position.get("source_policy") or {}
    if isinstance(raw_policy, dict):
        value = raw_policy.get("as_of")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return now.isoformat()


def _infer_market_exchange(symbol: str) -> tuple[str, str]:
    upper = symbol.upper()
    if upper.endswith(".HK") or (upper.isdigit() and len(upper) == 5):
        return "HK", "HKEX"
    if upper.endswith(".SH") or (upper.isdigit() and upper.startswith(("60", "68"))):
        return "CN", "SSE"
    if upper.endswith(".SZ") or (upper.isdigit() and upper.startswith(("00", "30"))):
        return "CN", "SZSE"
    return "US", "NASDAQ"


def _build_position_snapshot(
    *,
    tenant_id: str,
    symbol: str,
    events: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    quantity = 0
    total_cost = 0.0
    warnings: list[str] = []
    market = "US"
    exchange = "NASDAQ"
    provider_symbol = symbol
    computed_ids: list[str] = []

    for event in events:
        side = str(event.get("side") or "").upper()
        event_qty = int(float(event.get("quantity") or 0))
        price = float(event.get("price") or 0)
        market = str(event.get("market") or market)
        exchange = str(event.get("exchange") or exchange)
        provider_symbol = str(event.get("provider_symbol") or provider_symbol)
        if event.get("id"):
            computed_ids.append(str(event["id"]))
        if side == "BUY":
            quantity += event_qty
            total_cost += price * event_qty
        elif side == "SELL":
            if quantity <= 0 or event_qty > quantity:
                warnings.append("negative_position")
                quantity = max(quantity - event_qty, 0)
                total_cost = 0.0
            else:
                average_cost = total_cost / quantity if quantity else 0.0
                quantity -= event_qty
                total_cost -= average_cost * event_qty

    total_cost = round(max(total_cost, 0.0), 2)
    average_cost = round(total_cost / quantity, 6) if quantity > 0 else None
    return {
        "tenant_id": tenant_id,
        "symbol": symbol,
        "provider_symbol": provider_symbol,
        "market": market,
        "exchange": exchange,
        "stock_name": None,
        "total_quantity": quantity,
        "average_cost": average_cost,
        "total_cost": total_cost,
        "snapshot_date": now.date().isoformat(),
        "computed_from_event_ids": computed_ids[-1000:],
        "created_at": now.isoformat(),
        "warnings": sorted(set(warnings)),
    }


def _artifact_type_for_job(job_type: str) -> str:
    mapping = {
        "confirmed_sell_put_draft_finalize": "sell_put_trade_draft",
        "confirmed_discipline_rule_save": "discipline_rule",
        "confirmed_broker_conflict_reconcile": "broker_conflict_resolution",
        "confirmed_portfolio_view_refresh": "portfolio_view_change",
        "confirmed_action_commit": "confirmed_action",
    }
    return mapping.get(job_type, "confirmed_action")


def _artifact_execution_note(job_type: str) -> str:
    if job_type == "confirmed_sell_put_draft_finalize":
        return "Sell Put draft accepted; this never places an order automatically."
    if job_type == "confirmed_discipline_rule_save":
        return "Discipline rule accepted and stored for downstream rule tooling."
    if job_type == "confirmed_broker_conflict_reconcile":
        return "Broker conflict resolution accepted for downstream reconciliation."
    if job_type == "confirmed_portfolio_view_refresh":
        return "Portfolio view change accepted for downstream refresh."
    return "Confirmed action accepted for downstream processing."


def _artifact_payload(
    *,
    tenant_id: str,
    job: dict[str, Any],
    artifact_type: str,
    now: datetime,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    config = _job_config(job)
    pending = _pending_action(config)
    pending_id = str(pending.get("id") or job["id"])
    artifact_key = f"post-confirmation:{artifact_type}:{pending_id}"
    metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    return {
        "tenant_id": tenant_id,
        "artifact_key": artifact_key,
        "artifact_type": artifact_type,
        "artifact_status": "ready",
        "visibility": "tenant",
        "storage_backend": "inline_metadata",
        "storage_path": f"inline://{artifact_key}",
        "mime_type": "application/json",
        "content_hash": hashlib.sha256(metadata_json.encode("utf-8")).hexdigest(),
        "source_lineage": [
            {
                "job_run_id": str(job["id"]),
                "pending_action_id": pending.get("id"),
                "post_decision": config.get("post_decision"),
            }
        ],
        "artifact_metadata": metadata,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }


def _confirmation_event_payload(
    *,
    tenant_id: str,
    pending_action_id: str,
    confirmation_session_id: str | None,
    event_type: str,
    event_payload: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "pending_action_id": pending_action_id,
        "confirmation_session_id": confirmation_session_id,
        "event_type": event_type,
        "actor_type": "runtime",
        "actor_ref": "post-confirmation-worker",
        "event_payload": event_payload,
        "created_at": now.isoformat(),
    }


def _receipt_delivery_envelope(
    job: dict[str, Any],
    result: dict[str, Any],
    *,
    success: bool,
    now: datetime,
    error: str | None,
) -> DeliveryEnvelope | None:
    config = _job_config(job)
    routing = config.get("routing") or {}
    confirmation = _confirmation(config)
    tenant_id = str(job.get("tenant_id") or routing.get("tenant_id") or "")
    channel_binding_id = routing.get("channel_binding_id") or confirmation.get("channel_binding_id")
    openclaw_account_id = routing.get("openclaw_account_id")
    if not tenant_id or not channel_binding_id or not openclaw_account_id:
        return None

    content = _receipt_content(job, result, success=success, error=error)
    return DeliveryEnvelope(
        tenant_id=tenant_id,
        channel_binding_id=str(channel_binding_id),
        openclaw_account_id=str(openclaw_account_id),
        content_type="task_update",
        content=content,
        dedupe_key=f"{tenant_id}:post-confirmation-receipt:{job['id']}:{'success' if success else 'failed'}",
        target_conversation=routing.get("target_conversation"),
        context_token=routing.get("context_token"),
        priority="high",
        confirmation_session_id=confirmation.get("session_id"),
        data_snapshot_refs=[str(result["snapshot_id"])] if result.get("snapshot_id") else [],
    )


def _receipt_content(
    job: dict[str, Any],
    result: dict[str, Any],
    *,
    success: bool,
    error: str | None,
) -> dict[str, Any]:
    job_type = str(job.get("job_type") or "confirmed_action_commit")
    config = _job_config(job)
    pending = _pending_action(config)
    pending_id = pending.get("id")
    if not success:
        text = (
            "这次确认已收到，但后台处理暂时失败。当前没有改动持仓，也没有下单。"
            "系统已保留这条确认，可稍后通过微信重试；必要时可在确认中心查看最新状态。"
        )
        return {
            "title": "处理暂时失败",
            "text": text,
            "status": "failed_retryable",
            "job_type": job_type,
            "pending_action_id": pending_id,
            "error_summary": (error or "")[:240],
        }

    if job_type == "confirmed_trade_recalculate_holdings":
        symbol = result.get("symbol") or "该标的"
        quantity = result.get("position_quantity")
        text = f"已记录交易并刷新持仓：{symbol}"
        if quantity is not None:
            text += f" 当前持仓 {quantity} 股"
        text += "。这只是持仓系统记录，不会自动下单。"
        title = "交易已记录"
    elif job_type == "confirmed_position_snapshot_import":
        count = result.get("positions_count") or 0
        symbols = result.get("symbols") or []
        symbol_text = "、".join(symbols[:6]) if isinstance(symbols, list) else ""
        text = f"已根据确认的截图识别结果写入持仓系统，共 {count} 个标的"
        if symbol_text:
            text += f"：{symbol_text}"
        review_count = int(result.get("requires_symbol_review_count") or 0)
        if review_count:
            text += f"。其中 {review_count} 个标的只有名称没有代码，已标记为需补代码，暂不作为交易草稿依据"
        text += "。这只是持仓记录，不会自动下单。"
        title = "持仓截图已写入"
    elif job_type == "confirmed_sell_put_draft_finalize":
        text = "已生成 Sell Put 草稿并保存为候选记录。不会自动下单；请在 WebApp 或交易软件中复核行情、现金占用和风险后再操作。"
        title = "Sell Put 草稿已生成"
    elif job_type == "confirmed_discipline_rule_save":
        text = "已保存交易纪律规则。后续记录操作或生成候选时，系统会用这条规则提醒你保持纪律。"
        title = "交易纪律已保存"
    elif job_type == "confirmation_rebuild_request":
        text = (
            "已收到修改要求。本次原确认没有改动持仓，也没有下单。"
            "请通过微信重新发送修正后的内容；必要时可在确认中心查看最新状态。"
        )
        title = "修改要求已记录"
    elif job_type == "confirmed_broker_conflict_reconcile":
        text = "已记录券商数据冲突处理方案，后台会按确认内容继续修复资产数据。"
        title = "数据修复已开始"
    elif job_type == "confirmed_portfolio_view_refresh":
        text = "已记录资产视图调整，后台会刷新你的展示视图。"
        title = "资产视图已更新"
    else:
        text = "已按确认内容完成后台处理。涉及交易的内容只记录或生成草稿，不会自动下单。"
        title = "处理完成"

    return {
        "title": title,
        "text": text,
        "status": "completed",
        "job_type": job_type,
        "pending_action_id": pending_id,
        "result": result,
    }


def create_post_confirmation_worker_from_env() -> PostConfirmationJobWorker:
    import os

    database_url = os.getenv("DATABASE_URL") or os.getenv("GBRAIN_DATABASE_URL")
    repository_backend = os.getenv("OPENCLAW_POST_CONFIRMATION_REPOSITORY", "").strip().lower()
    if database_url and repository_backend == "postgres":
        from openclaw.gateway.outbox import PostgresOutboxRepository

        return PostConfirmationJobWorker(
            PostgresPostConfirmationWorkerRepository(database_url),
            receipt_outbox=DeliveryOutboxService(PostgresOutboxRepository(database_url)),
        )

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    from supabase import create_client

    client = create_client(supabase_url, supabase_key)
    from openclaw.gateway.outbox import SupabaseOutboxRepository

    return PostConfirmationJobWorker(
        SupabasePostConfirmationWorkerRepository(client),
        receipt_outbox=DeliveryOutboxService(SupabaseOutboxRepository(client)),
    )


async def run_worker_loop(
    worker: PostConfirmationJobWorker,
    *,
    once: bool = False,
    poll_interval_seconds: float = 5.0,
    limit: int = 20,
) -> None:
    while True:
        stats = await worker.process_once(limit=limit)
        logger.info("Post-confirmation worker stats: %s", stats)
        if once:
            return
        await asyncio.sleep(poll_interval_seconds)


def _main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Run post-confirmation job worker")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("POST_CONFIRMATION_WORKER_BATCH_LIMIT", "20")),
        help="Maximum jobs to process per batch",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.getenv("POST_CONFIRMATION_WORKER_POLL_INTERVAL_SECONDS", "5")),
        help="Polling interval in seconds",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    worker = create_post_confirmation_worker_from_env()
    asyncio.run(
        run_worker_loop(
            worker,
            once=args.once,
            poll_interval_seconds=args.poll_interval,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    _main()
