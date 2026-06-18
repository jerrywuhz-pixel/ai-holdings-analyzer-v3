"""
Standalone outbox worker entrypoint.

The worker is intentionally transport-agnostic: the reliable state machine
lives in outbox.py, while this module wires an environment-selected sender.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import httpx

from openclaw.gateway.outbox import (
    DeliveryOutboxService,
    DeliveryOutboxWorker,
    InMemoryOutboxRepository,
    LoggingDeliverySender,
    SupabaseOutboxRepository,
)

logger = logging.getLogger(__name__)


class DisabledDeliverySender:
    async def send(self, delivery: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError(
            "delivery sender is disabled; set OPENCLAW_DELIVERY_MODE=webhook "
            "and OPENCLAW_DELIVERY_WEBHOOK_URL to enable real delivery"
        )


class WebhookDeliverySender:
    def __init__(
        self,
        url: str,
        *,
        secret: str | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        self._secret = secret
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def send(self, delivery: dict[str, Any]) -> dict[str, Any]:
        outbound_payload = self._build_payload(delivery)
        body = json.dumps(outbound_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = self._build_headers(delivery, body)

        async with httpx.AsyncClient(timeout=self._timeout_seconds, transport=self._transport) as client:
            response = await client.post(self._url, content=body, headers=headers)
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                payload = {"text": response.text[:500]}
            return {"status_code": response.status_code, "response": payload}

    def _build_payload(self, delivery: dict[str, Any]) -> dict[str, Any]:
        content = delivery.get("content") or {}
        if not isinstance(content, dict):
            content = {"text": str(content)}

        return {
            "delivery_id": delivery.get("id"),
            "tenant_id": delivery.get("tenant_id"),
            "channel": "openclaw-weixin",
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
            "confirmation_session_id": delivery.get("confirmation_session_id"),
            "source_run_id": delivery.get("source_run_id"),
        }

    def _build_headers(self, delivery: dict[str, Any], body: bytes) -> dict[str, str]:
        delivery_id = str(delivery.get("id") or "")
        headers = {
            "Content-Type": "application/json",
            "X-OpenClaw-Delivery-Id": delivery_id,
        }
        if not self._secret:
            return headers

        timestamp = str(int(time.time()))
        signed_payload = f"{timestamp}.".encode("utf-8") + body
        signature = hmac.new(
            self._secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        headers.update(
            {
                "X-OpenClaw-Delivery-Timestamp": timestamp,
                "X-OpenClaw-Delivery-Signature": f"v1={signature}",
                # Kept for older local claw plugins while they migrate to HMAC verification.
                "X-OpenClaw-Delivery-Secret": self._secret,
            }
        )
        return headers


def create_outbox_worker_from_env() -> DeliveryOutboxWorker:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if supabase_url and supabase_key:
        from supabase import create_client

        repository = SupabaseOutboxRepository(create_client(supabase_url, supabase_key))
    else:
        logger.warning("Supabase not configured; outbox worker will use in-memory repository")
        repository = InMemoryOutboxRepository()

    mode = os.getenv("OPENCLAW_DELIVERY_MODE", "disabled").strip().lower()
    if mode == "webhook":
        webhook_url = os.getenv("OPENCLAW_DELIVERY_WEBHOOK_URL")
        if not webhook_url:
            raise RuntimeError("OPENCLAW_DELIVERY_WEBHOOK_URL is required when OPENCLAW_DELIVERY_MODE=webhook")
        sender = WebhookDeliverySender(
            webhook_url,
            secret=os.getenv("OPENCLAW_DELIVERY_WEBHOOK_SECRET"),
            timeout_seconds=float(os.getenv("OPENCLAW_DELIVERY_TIMEOUT_SECONDS", "10")),
        )
    elif mode == "log":
        sender = LoggingDeliverySender()
    else:
        sender = DisabledDeliverySender()

    return DeliveryOutboxWorker(DeliveryOutboxService(repository), sender)


async def run_worker_loop(
    worker: DeliveryOutboxWorker,
    *,
    limit: int,
    poll_interval_seconds: float,
    once: bool,
) -> None:
    while True:
        stats = await worker.process_ready(limit=limit)
        logger.info(
            "outbox worker tick scanned=%s delivered=%s retrying=%s failed=%s expired=%s",
            stats.scanned,
            stats.delivered,
            stats.retrying,
            stats.failed,
            stats.expired,
        )
        if once:
            return
        await asyncio.sleep(poll_interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenClaw delivery outbox worker")
    parser.add_argument("--once", action="store_true", help="process one batch then exit")
    parser.add_argument("--limit", type=int, default=int(os.getenv("OPENCLAW_OUTBOX_WORKER_LIMIT", "50")))
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.getenv("OPENCLAW_OUTBOX_WORKER_POLL_INTERVAL_SECONDS", "2")),
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    args = parse_args()
    worker = create_outbox_worker_from_env()
    asyncio.run(
        run_worker_loop(
            worker,
            limit=args.limit,
            poll_interval_seconds=args.poll_interval,
            once=args.once,
        )
    )


if __name__ == "__main__":
    main()
