from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

JsonDict = dict[str, Any]
RETRY_SCHEDULE_SECONDS = (30, 300, 1800)
DEFAULT_SUPPRESSED_CONTENT_TYPES = {"confirmation_card", "task_update", "system", "system_message"}


@dataclass(frozen=True)
class DeliveryProcessStats:
    scanned: int = 0
    delivered: int = 0
    retrying: int = 0
    failed: int = 0
    expired: int = 0
    suppressed: int = 0

    def model_dump(self) -> JsonDict:
        return {
            "scanned": self.scanned,
            "delivered": self.delivered,
            "retrying": self.retrying,
            "failed": self.failed,
            "expired": self.expired,
            "suppressed": self.suppressed,
        }


class HermesDeliveryProcessor:
    def __init__(
        self,
        *,
        database_url: str = "",
        webhook_url: str = "",
        webhook_secret: str = "",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._database_url = database_url or os.getenv("DATABASE_URL", "").strip()
        self._webhook_url = (
            webhook_url
            or os.getenv("HERMES_DELIVERY_WEBHOOK_URL", "").strip()
            or os.getenv("OPENCLAW_DELIVERY_WEBHOOK_URL", "").strip()
            or "http://webapp:3000/api/hermes/delivery/wechat"
        )
        self._webhook_secret = (
            webhook_secret
            or os.getenv("HERMES_DELIVERY_WEBHOOK_SECRET", "").strip()
            or os.getenv("OPENCLAW_DELIVERY_WEBHOOK_SECRET", "").strip()
        )
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> "HermesDeliveryProcessor":
        return cls(
            timeout_seconds=float(os.getenv("HERMES_DELIVERY_TIMEOUT_SECONDS", os.getenv("OPENCLAW_DELIVERY_TIMEOUT_SECONDS", "10"))),
        )

    async def process_ready(self, *, limit: int = 50, dry_run: bool = False) -> JsonDict:
        if not self._database_url:
            return {"ok": False, "status": "skipped", "reason": "database_url_not_configured"}
        records = await asyncio.to_thread(_load_ready_deliveries, self._database_url, limit)
        stats = DeliveryProcessStats(scanned=len(records))
        details: list[JsonDict] = []

        for record in records:
            delivery_id = str(record.get("id") or "")
            if _is_suppressed_delivery(record):
                await asyncio.to_thread(_mark_cancelled, self._database_url, delivery_id, _suppressed_reason(record))
                stats = _stats(stats, suppressed=1)
                details.append({"delivery_id": delivery_id, "status": "cancelled", "reason": _suppressed_reason(record)})
                continue
            if _is_expired(record):
                await asyncio.to_thread(_mark_expired, self._database_url, delivery_id)
                stats = _stats(stats, expired=1)
                continue
            if dry_run:
                details.append({"delivery_id": delivery_id, "status": "dry_run"})
                continue
            await asyncio.to_thread(_mark_sending, self._database_url, delivery_id)
            try:
                response = await self._send(record)
                await asyncio.to_thread(_mark_delivered, self._database_url, delivery_id, response)
                stats = _stats(stats, delivered=1)
            except Exception as exc:
                failed_status = await asyncio.to_thread(_mark_failed, self._database_url, record, str(exc))
                if failed_status == "failed":
                    stats = _stats(stats, failed=1)
                else:
                    stats = _stats(stats, retrying=1)
                details.append({"delivery_id": delivery_id, "error": str(exc), "status": failed_status})

        return {"ok": True, "status": "ok", **stats.model_dump(), "details": details[:20]}

    async def _send(self, delivery: JsonDict) -> JsonDict:
        payload = _delivery_payload(delivery)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = _delivery_headers(self._webhook_secret, body)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(self._webhook_url, content=body, headers=headers)
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                return {"text": response.text[:500], "status_code": response.status_code}


def _load_ready_deliveries(database_url: str, limit: int) -> list[JsonDict]:
    import psycopg
    from psycopg.rows import dict_row

    now = datetime.now(timezone.utc)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM public.delivery_outbox
            WHERE status IN ('pending', 'retrying')
              AND (next_retry_at IS NULL OR next_retry_at <= %(now)s)
            ORDER BY next_retry_at ASC NULLS FIRST, created_at ASC
            LIMIT %(limit)s
            """,
            {"now": now, "limit": limit},
        ).fetchall()
        return [dict(row) for row in rows]


def _delivery_payload(delivery: JsonDict) -> JsonDict:
    content = delivery.get("content") if isinstance(delivery.get("content"), dict) else {"text": str(delivery.get("content") or "")}
    return {
        "delivery_id": delivery.get("id"),
        "tenant_id": delivery.get("tenant_id"),
        "channel": "hermes-wechat",
        "recipient": {
            "openclaw_account_id": delivery.get("openclaw_account_id"),
            "target_conversation": delivery.get("target_conversation"),
            "context_token": delivery.get("context_token"),
            "channel_binding_id": delivery.get("channel_binding_id"),
        },
        "message": {
            "content_type": delivery.get("content_type"),
            "content": content,
        },
        "dedupe_key": delivery.get("dedupe_key"),
        "content_snapshot_hash": delivery.get("content_snapshot_hash"),
        "priority": delivery.get("priority") or "normal",
        "source_run_id": delivery.get("source_run_id"),
    }


def _delivery_headers(secret: str, body: bytes) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if not secret:
        return headers
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.".encode("utf-8") + body
    signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    headers.update(
        {
            "X-Hermes-Delivery-Timestamp": timestamp,
            "X-Hermes-Delivery-Signature": f"v1={signature}",
            "X-Hermes-Delivery-Secret": secret,
        }
    )
    return headers


def _mark_sending(database_url: str, delivery_id: str) -> None:
    _update_delivery(database_url, delivery_id, {"status": "sending", "last_attempt_at": datetime.now(timezone.utc)})
    _insert_message_event(database_url, delivery_id, "sending", {"status": "sending"})


def _mark_delivered(database_url: str, delivery_id: str, response: JsonDict) -> None:
    now = datetime.now(timezone.utc)
    _update_delivery(
        database_url,
        delivery_id,
        {
            "status": "delivered",
            "delivered_at": now,
            "last_error": None,
            "held_reason": None,
            "content_summary": {"delivery_response": response},
        },
    )
    _insert_message_event(database_url, delivery_id, "delivered", {"status": "delivered", "response": response})


def _mark_expired(database_url: str, delivery_id: str) -> None:
    _update_delivery(
        database_url,
        delivery_id,
        {"status": "expired", "last_error": "expired_before_delivery", "next_retry_at": None, "held_reason": None},
    )
    _insert_message_event(database_url, delivery_id, "expired", {"status": "expired", "reason": "expired_before_delivery"})


def _mark_cancelled(database_url: str, delivery_id: str, reason: str) -> None:
    _update_delivery(
        database_url,
        delivery_id,
        {"status": "cancelled", "last_error": reason, "next_retry_at": None, "held_reason": None},
    )
    _insert_message_event(database_url, delivery_id, "failed", {"status": "cancelled", "reason": reason})


def _mark_failed(database_url: str, delivery: JsonDict, error: str) -> str:
    attempt_count = int(delivery.get("attempt_count") or 0) + 1
    retry_delay = _retry_delay_for_attempt(attempt_count)
    if retry_delay is None:
        status = "failed"
        next_retry_at = None
    else:
        status = "retrying"
        next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=retry_delay)
    _update_delivery(
        database_url,
        str(delivery.get("id")),
        {
            "status": status,
            "attempt_count": attempt_count,
            "last_error": error,
            "next_retry_at": next_retry_at,
        },
    )
    _insert_message_event(
        database_url,
        str(delivery.get("id")),
        "failed",
        {
            "status": status,
            "attempt_count": attempt_count,
            "error": error,
            "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
        },
    )
    return status


def _update_delivery(database_url: str, delivery_id: str, updates: JsonDict) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    updates = {**updates, "updated_at": datetime.now(timezone.utc)}
    json_columns = {"content", "content_summary", "asset_source_refs", "data_snapshot_refs"}
    columns = tuple(updates.keys())
    assignments = ", ".join(f"{column} = %s" for column in columns)
    values = [Jsonb(updates[column]) if column in json_columns else updates[column] for column in columns]
    values.append(delivery_id)
    with psycopg.connect(database_url) as conn:
        conn.execute(f"UPDATE public.delivery_outbox SET {assignments} WHERE id = %s", values)
        conn.commit()


def _retry_delay_for_attempt(attempt_count: int) -> int | None:
    index = attempt_count - 1
    if index >= len(RETRY_SCHEDULE_SECONDS):
        return None
    return RETRY_SCHEDULE_SECONDS[index]


def _suppressed_content_types() -> set[str]:
    configured: set[str] = set()
    for name in (
        "HERMES_WECHAT_SUPPRESSED_DELIVERY_CONTENT_TYPES",
        "HERMES_SUPPRESSED_DELIVERY_CONTENT_TYPES",
        "OPENCLAW_WECHAT_SUPPRESSED_DELIVERY_CONTENT_TYPES",
    ):
        configured.update(_parse_content_types(os.getenv(name, "")))
    if not configured and (
        _env_bool("HERMES_SKIP_SYSTEM_DELIVERIES") or _env_bool("OPENCLAW_SKIP_GATEWAY_SYSTEM_DELIVERIES")
    ):
        configured.update(DEFAULT_SUPPRESSED_CONTENT_TYPES)
    return set(DEFAULT_SUPPRESSED_CONTENT_TYPES) | configured


def _parse_content_types(raw_value: str) -> set[str]:
    return {item.strip().lower() for item in raw_value.split(",") if item.strip()}


def _env_bool(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _is_suppressed_delivery(record: JsonDict) -> bool:
    content_type = str(record.get("content_type") or "").strip().lower()
    return bool(content_type and content_type in _suppressed_content_types())


def _suppressed_reason(record: JsonDict) -> str:
    return f"suppressed_delivery_content_type:{record.get('content_type')}"


def _insert_message_event(database_url: str, delivery_id: str, event_type: str, payload: JsonDict) -> None:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    if not delivery_id:
        return
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT id, tenant_id, channel_binding_id
            FROM public.delivery_outbox
            WHERE id = %s
            LIMIT 1
            """,
            (delivery_id,),
        ).fetchone()
        if not row:
            return
        conn.execute(
            """
            INSERT INTO public.message_events (
              tenant_id, delivery_outbox_id, channel_binding_id, event_type, event_payload
            )
            VALUES (%s, %s, %s, %s::public.message_event_type, %s)
            """,
            (
                row["tenant_id"],
                row["id"],
                row.get("channel_binding_id"),
                event_type,
                Jsonb(payload),
            ),
        )
        conn.commit()


def _is_expired(record: JsonDict) -> bool:
    expires_at = _parse_datetime(record.get("expires_at"))
    return expires_at is not None and expires_at <= datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _stats(stats: DeliveryProcessStats, **delta: int) -> DeliveryProcessStats:
    values = stats.model_dump()
    for key, amount in delta.items():
        values[key] += amount
    return DeliveryProcessStats(**values)
