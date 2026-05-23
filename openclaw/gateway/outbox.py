"""
Delivery / outbox abstraction for OpenClaw P0.

All proactive or asynchronous user-facing messages should be queued here first,
then delivered by a sender/worker.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)

RETRY_SCHEDULE_SECONDS = (30, 300, 1800)


@dataclass
class DeliveryEnvelope:
    tenant_id: str
    channel_binding_id: str
    openclaw_account_id: str
    content_type: str
    content: dict[str, Any]
    dedupe_key: str
    target_conversation: str | None = None
    context_token: str | None = None
    priority: str = "normal"
    confirmation_session_id: str | None = None
    source_run_id: str | None = None
    data_snapshot_refs: list[str] | None = None
    asset_source_refs: list[str] | None = None


@dataclass
class DeliveryQueueResult:
    delivery_id: str
    status: str
    next_retry_at: datetime | None
    content_snapshot_hash: str
    dedupe_key: str
    held_reason: str | None = None


@dataclass
class DeliveryWorkerStats:
    scanned: int = 0
    delivered: int = 0
    retrying: int = 0
    failed: int = 0
    expired: int = 0


class CompensationHook(Protocol):
    async def handle(self, event_type: str, payload: dict[str, Any]) -> None:
        ...


class DeliverySender(Protocol):
    async def send(self, delivery: dict[str, Any]) -> dict[str, Any] | None:
        ...


class OutboxRepository(Protocol):
    async def create_or_get(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    async def update(self, delivery_id: str, updates: dict[str, Any]) -> None:
        ...

    async def get(self, delivery_id: str) -> dict[str, Any] | None:
        ...

    async def list_retry_ready(self, now: datetime, limit: int = 50) -> list[dict[str, Any]]:
        ...


class SlidingWindowRateLimiter:
    def __init__(self, max_events: int, window_seconds: int) -> None:
        self._max_events = max_events
        self._window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}

    def allow(self, key: str, now: datetime) -> bool:
        current = now.timestamp()
        window_start = current - self._window_seconds
        timestamps = [ts for ts in self._events.get(key, []) if ts > window_start]
        if len(timestamps) >= self._max_events:
            self._events[key] = timestamps
            return False
        timestamps.append(current)
        self._events[key] = timestamps
        return True


class InMemoryOutboxRepository:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._dedupe_index: dict[str, str] = {}

    async def create_or_get(self, payload: dict[str, Any]) -> dict[str, Any]:
        existing_id = self._dedupe_index.get(payload["dedupe_key"])
        if existing_id and existing_id in self._records:
            return dict(self._records[existing_id])
        self._records[payload["id"]] = dict(payload)
        self._dedupe_index[payload["dedupe_key"]] = payload["id"]
        return dict(payload)

    async def update(self, delivery_id: str, updates: dict[str, Any]) -> None:
        self._records[delivery_id].update(updates)

    async def get(self, delivery_id: str) -> dict[str, Any] | None:
        record = self._records.get(delivery_id)
        return dict(record) if record else None

    async def list_retry_ready(self, now: datetime, limit: int = 50) -> list[dict[str, Any]]:
        ready: list[dict[str, Any]] = []
        for record in self._records.values():
            if record["status"] not in {"retrying", "pending"}:
                continue
            next_retry_at = _parse_dt(record.get("next_retry_at"))
            if next_retry_at is None or next_retry_at <= now:
                ready.append(dict(record))
        ready.sort(key=lambda item: str(item.get("next_retry_at") or item["created_at"]))
        return ready[:limit]


class SupabaseOutboxRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def create_or_get(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _insert() -> dict[str, Any]:
            try:
                response = self._client.table("delivery_outbox").insert(payload).execute()
                return response.data[0] if response.data else payload
            except Exception as exc:
                message = str(exc).lower()
                if "duplicate" not in message and "unique" not in message and "23505" not in message:
                    raise
                lookup = (
                    self._client.table("delivery_outbox")
                    .select("*")
                    .eq("dedupe_key", payload["dedupe_key"])
                    .limit(1)
                    .execute()
                )
                if lookup.data:
                    return lookup.data[0]
                raise

        return await asyncio.to_thread(_insert)

    async def update(self, delivery_id: str, updates: dict[str, Any]) -> None:
        def _update() -> None:
            self._client.table("delivery_outbox").update(updates).eq("id", delivery_id).execute()

        await asyncio.to_thread(_update)

    async def get(self, delivery_id: str) -> dict[str, Any] | None:
        def _query() -> list[dict[str, Any]]:
            response = self._client.table("delivery_outbox").select("*").eq("id", delivery_id).limit(1).execute()
            return response.data or []

        rows = await asyncio.to_thread(_query)
        return rows[0] if rows else None

    async def list_retry_ready(self, now: datetime, limit: int = 50) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            response = (
                self._client.table("delivery_outbox")
                .select("*")
                .in_("status", ["retrying", "pending"])
                .lte("next_retry_at", now.isoformat())
                .order("next_retry_at", desc=False)
                .limit(limit)
                .execute()
            )
            return response.data or []

        return await asyncio.to_thread(_query)


class PostgresOutboxRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def create_or_get(self, payload: dict[str, Any]) -> dict[str, Any]:
        from psycopg import connect, sql
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb

        columns = [
            "id",
            "tenant_id",
            "channel_binding_id",
            "openclaw_account_id",
            "content_type",
            "content",
            "content_snapshot_hash",
            "priority",
            "dedupe_key",
            "status",
            "attempt_count",
            "next_retry_at",
            "target_conversation",
            "context_token",
            "confirmation_session_id",
            "source_run_id",
            "asset_source_refs",
            "data_snapshot_refs",
            "held_reason",
            "created_at",
            "updated_at",
        ]

        def _value(column: str) -> Any:
            value = payload.get(column)
            if column in {"content", "asset_source_refs", "data_snapshot_refs"}:
                return Jsonb(value if value is not None else ([] if column.endswith("_refs") else {}))
            return value

        def _insert() -> dict[str, Any]:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    query = sql.SQL(
                        """
                        INSERT INTO public.delivery_outbox ({columns})
                        VALUES ({placeholders})
                        ON CONFLICT (tenant_id, dedupe_key) DO NOTHING
                        RETURNING *
                        """
                    ).format(
                        columns=sql.SQL(", ").join(sql.Identifier(column) for column in columns),
                        placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                    )
                    cur.execute(query, [_value(column) for column in columns])
                    row = cur.fetchone()
                    if row:
                        return dict(row)
                    cur.execute(
                        """
                        SELECT *
                        FROM public.delivery_outbox
                        WHERE tenant_id = %s AND dedupe_key = %s
                        LIMIT 1
                        """,
                        [payload["tenant_id"], payload["dedupe_key"]],
                    )
                    existing = cur.fetchone()
                    if not existing:
                        raise RuntimeError("delivery_outbox insert conflict but existing row was not found")
                    return dict(existing)

        return await asyncio.to_thread(_insert)

    async def update(self, delivery_id: str, updates: dict[str, Any]) -> None:
        from psycopg import connect, sql
        from psycopg.types.json import Jsonb

        normalized: list[Any] = []
        for value in updates.values():
            if isinstance(value, (dict, list)):
                normalized.append(Jsonb(value))
            else:
                normalized.append(value)

        def _update() -> None:
            with connect(self._database_url) as conn:
                with conn.cursor() as cur:
                    query = sql.SQL("UPDATE public.delivery_outbox SET {updates} WHERE id = %s").format(
                        updates=sql.SQL(", ").join(
                            sql.SQL("{} = {}").format(sql.Identifier(column), sql.Placeholder())
                            for column in updates
                        )
                    )
                    cur.execute(query, [*normalized, delivery_id])

        await asyncio.to_thread(_update)

    async def get(self, delivery_id: str) -> dict[str, Any] | None:
        from psycopg import connect
        from psycopg.rows import dict_row

        def _query() -> dict[str, Any] | None:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM public.delivery_outbox WHERE id = %s LIMIT 1", [delivery_id])
                    row = cur.fetchone()
                    return dict(row) if row else None

        return await asyncio.to_thread(_query)

    async def list_retry_ready(self, now: datetime, limit: int = 50) -> list[dict[str, Any]]:
        from psycopg import connect
        from psycopg.rows import dict_row

        def _query() -> list[dict[str, Any]]:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT *
                        FROM public.delivery_outbox
                        WHERE status IN ('retrying', 'pending')
                          AND (next_retry_at IS NULL OR next_retry_at <= %s)
                        ORDER BY next_retry_at ASC NULLS FIRST, created_at ASC
                        LIMIT %s
                        """,
                        [now, limit],
                    )
                    return [dict(row) for row in cur.fetchall()]

        return await asyncio.to_thread(_query)


def create_outbox_repository_from_env(supabase_client: Any | None = None) -> OutboxRepository:
    repository_mode = os.getenv("OPENCLAW_OUTBOX_REPOSITORY", "postgres").strip().lower()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url and repository_mode in {"postgres", "direct_postgres", "auto"}:
        return PostgresOutboxRepository(database_url)
    if supabase_client is not None:
        return SupabaseOutboxRepository(supabase_client)
    return InMemoryOutboxRepository()


class DeliveryOutboxService:
    def __init__(
        self,
        repository: OutboxRepository,
        *,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        hooks: list[CompensationHook] | None = None,
        now_provider: callable | None = None,
    ) -> None:
        self._repository = repository
        self._rate_limiter = rate_limiter or SlidingWindowRateLimiter(max_events=10, window_seconds=60)
        self._hooks = hooks or []
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def enqueue(
        self,
        envelope: DeliveryEnvelope,
        *,
        quiet_hours: dict[str, Any] | None = None,
    ) -> DeliveryQueueResult:
        if envelope.content_type == "confirmation_card" and not envelope.confirmation_session_id:
            raise ValueError("confirmation_card delivery requires confirmation_session_id")

        now = self._now_provider()
        delivery_id = str(uuid.uuid4())
        snapshot_hash = _content_hash(envelope.content)
        status = "pending"
        next_retry_at: datetime | None = now
        held_reason: str | None = None

        quiet_match = quiet_hours and is_within_quiet_hours(now, quiet_hours)
        if quiet_match and envelope.priority != "high":
            status = "pending"
            next_retry_at = quiet_match
            held_reason = "quiet_hours"
        elif not self._rate_limiter.allow(envelope.channel_binding_id, now):
            status = "retrying"
            next_retry_at = now + timedelta(seconds=RETRY_SCHEDULE_SECONDS[0])
            held_reason = "rate_limited"

        payload = {
            "id": delivery_id,
            "tenant_id": envelope.tenant_id,
            "channel_binding_id": envelope.channel_binding_id,
            "openclaw_account_id": envelope.openclaw_account_id,
            "content_type": envelope.content_type,
            "content": envelope.content,
            "content_snapshot_hash": snapshot_hash,
            "priority": envelope.priority,
            "dedupe_key": envelope.dedupe_key,
            "status": status,
            "attempt_count": 0,
            "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
            "target_conversation": envelope.target_conversation,
            "context_token": envelope.context_token,
            "confirmation_session_id": envelope.confirmation_session_id,
            "source_run_id": envelope.source_run_id,
            "asset_source_refs": envelope.asset_source_refs or [],
            "data_snapshot_refs": envelope.data_snapshot_refs or [],
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "held_reason": held_reason,
        }

        record = await self._repository.create_or_get(payload)
        return DeliveryQueueResult(
            delivery_id=str(record["id"]),
            status=str(record.get("status", status)),
            next_retry_at=_parse_dt(record.get("next_retry_at")),
            content_snapshot_hash=str(record.get("content_snapshot_hash", snapshot_hash)),
            dedupe_key=str(record.get("dedupe_key", envelope.dedupe_key)),
            held_reason=record.get("held_reason"),
        )

    async def mark_sending(self, delivery_id: str) -> None:
        await self._repository.update(
            delivery_id,
            {
                "status": "sending",
                "updated_at": self._now_provider().isoformat(),
            },
        )

    async def mark_delivered(self, delivery_id: str) -> None:
        now = self._now_provider()
        await self._repository.update(
            delivery_id,
            {
                "status": "delivered",
                "delivered_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "held_reason": None,
            },
        )
        await self._emit(
            "delivery_delivered",
            {
                "delivery_id": delivery_id,
                "status": "delivered",
                "delivered_at": now.isoformat(),
            },
        )

    async def mark_expired(self, delivery_id: str, reason: str = "expired_before_delivery") -> DeliveryQueueResult:
        now = self._now_provider()
        existing = await self._repository.get(delivery_id)
        if existing is None:
            raise KeyError(f"Unknown delivery_id: {delivery_id}")

        await self._repository.update(
            delivery_id,
            {
                "status": "expired",
                "last_error": reason,
                "next_retry_at": None,
                "updated_at": now.isoformat(),
                "held_reason": None,
            },
        )
        await self._emit(
            "delivery_expired",
            {
                "delivery_id": delivery_id,
                "status": "expired",
                "reason": reason,
            },
        )
        return DeliveryQueueResult(
            delivery_id=delivery_id,
            status="expired",
            next_retry_at=None,
            content_snapshot_hash=str(existing["content_snapshot_hash"]),
            dedupe_key=str(existing["dedupe_key"]),
            held_reason=None,
        )

    async def mark_failed(self, delivery_id: str, error: str) -> DeliveryQueueResult:
        now = self._now_provider()
        existing = await self._repository.get(delivery_id)
        if existing is None:
            raise KeyError(f"Unknown delivery_id: {delivery_id}")

        attempt_count = int(existing.get("attempt_count") or 0) + 1
        retry_delay = _retry_delay_for_attempt(attempt_count)
        if retry_delay is None:
            status = "failed"
            next_retry_at = None
            event_type = "delivery_abandoned"
        else:
            status = "retrying"
            next_retry_at = now + timedelta(seconds=retry_delay)
            event_type = "delivery_retry_scheduled"

        updates = {
            "status": status,
            "attempt_count": attempt_count,
            "last_error": error,
            "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
            "updated_at": now.isoformat(),
        }
        await self._repository.update(delivery_id, updates)

        payload = {
            "delivery_id": delivery_id,
            "status": status,
            "attempt_count": attempt_count,
            "error": error,
            "next_retry_at": updates["next_retry_at"],
        }
        await self._emit(event_type, payload)

        return DeliveryQueueResult(
            delivery_id=delivery_id,
            status=status,
            next_retry_at=next_retry_at,
            content_snapshot_hash=str(existing["content_snapshot_hash"]),
            dedupe_key=str(existing["dedupe_key"]),
            held_reason=None,
        )

    async def retry_ready(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return await self._repository.list_retry_ready(self._now_provider(), limit=limit)

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        for hook in self._hooks:
            await hook.handle(event_type, payload)


class DeliveryOutboxWorker:
    def __init__(
        self,
        outbox: DeliveryOutboxService,
        sender: DeliverySender,
        *,
        now_provider: callable | None = None,
    ) -> None:
        self._outbox = outbox
        self._sender = sender
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def process_ready(self, *, limit: int = 50) -> DeliveryWorkerStats:
        records = await self._outbox.retry_ready(limit=limit)
        stats = DeliveryWorkerStats(scanned=len(records))

        for record in records:
            delivery_id = str(record["id"])
            if self._is_expired(record):
                await self._outbox.mark_expired(delivery_id)
                stats.expired += 1
                continue

            await self._outbox.mark_sending(delivery_id)
            try:
                await self._sender.send(record)
            except Exception as exc:
                result = await self._outbox.mark_failed(delivery_id, str(exc))
                if result.status == "failed":
                    stats.failed += 1
                else:
                    stats.retrying += 1
                continue

            await self._outbox.mark_delivered(delivery_id)
            stats.delivered += 1

        return stats

    def _is_expired(self, record: dict[str, Any]) -> bool:
        expires_at = _parse_dt(record.get("expires_at"))
        return expires_at is not None and expires_at <= self._now_provider()


class LoggingDeliverySender:
    async def send(self, delivery: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "Dry-run delivery: id=%s tenant=%s content_type=%s target=%s",
            delivery.get("id"),
            delivery.get("tenant_id"),
            delivery.get("content_type"),
            delivery.get("target_conversation") or delivery.get("openclaw_account_id"),
        )
        return {"mode": "dry_run"}


def is_within_quiet_hours(now: datetime, quiet_hours: dict[str, Any]) -> datetime | None:
    start = quiet_hours.get("start")
    end = quiet_hours.get("end")
    if not start or not end:
        return None

    start_hour, start_minute = _parse_hhmm(start)
    end_hour, end_minute = _parse_hhmm(end)
    local_now = now
    start_dt = local_now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end_dt = local_now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)

    crosses_midnight = start_dt >= end_dt
    if crosses_midnight:
        if local_now >= start_dt:
            return end_dt + timedelta(days=1)
        if local_now < end_dt:
            return end_dt
        return None

    if start_dt <= local_now < end_dt:
        return end_dt
    return None


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.split(":", 1)
    return int(hour_text), int(minute_text)


def _content_hash(content: dict[str, Any]) -> str:
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _retry_delay_for_attempt(attempt_count: int) -> int | None:
    if attempt_count <= len(RETRY_SCHEDULE_SECONDS):
        return RETRY_SCHEDULE_SECONDS[attempt_count - 1]
    return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
