from datetime import datetime, timezone
import json

import httpx
import pytest

from openclaw.gateway.outbox import (
    DeliveryEnvelope,
    DeliveryOutboxService,
    DeliveryOutboxWorker,
    InMemoryOutboxRepository,
    SlidingWindowRateLimiter,
    is_within_quiet_hours,
)
from openclaw.gateway.outbox_worker import WebhookDeliverySender


class RecordingHook:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def handle(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


class RecordingSender:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.sent: list[dict] = []

    async def send(self, delivery: dict) -> dict:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("wechat gateway timeout")
        self.sent.append(delivery)
        return {"provider_message_id": f"msg-{delivery['id']}"}


def test_quiet_hours_window_crosses_midnight() -> None:
    now = datetime(2026, 5, 10, 23, 30, tzinfo=timezone.utc)
    next_retry_at = is_within_quiet_hours(
        now,
        {"start": "22:00", "end": "08:00"},
    )
    assert next_retry_at == datetime(2026, 5, 11, 8, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_outbox_holds_normal_priority_during_quiet_hours() -> None:
    repository = InMemoryOutboxRepository()
    service = DeliveryOutboxService(
        repository,
        now_provider=lambda: datetime(2026, 5, 10, 23, 30, tzinfo=timezone.utc),
    )
    result = await service.enqueue(
        DeliveryEnvelope(
            tenant_id="tenant-1",
            channel_binding_id="binding-1",
            openclaw_account_id="bot-1",
            content_type="task_update",
            content={"text": "summary"},
            dedupe_key="tenant-1:daily:1",
        ),
        quiet_hours={"start": "22:00", "end": "08:00"},
    )
    assert result.status == "pending"
    assert result.held_reason == "quiet_hours"
    assert result.next_retry_at == datetime(2026, 5, 11, 8, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_outbox_rate_limit_and_retry_hooks() -> None:
    repository = InMemoryOutboxRepository()
    hook = RecordingHook()
    service = DeliveryOutboxService(
        repository,
        rate_limiter=SlidingWindowRateLimiter(max_events=1, window_seconds=60),
        hooks=[hook],
        now_provider=lambda: datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc),
    )

    first = await service.enqueue(
        DeliveryEnvelope(
            tenant_id="tenant-1",
            channel_binding_id="binding-1",
            openclaw_account_id="bot-1",
            content_type="task_update",
            content={"text": "first"},
            dedupe_key="tenant-1:first",
        )
    )
    assert first.status == "pending"

    second = await service.enqueue(
        DeliveryEnvelope(
            tenant_id="tenant-1",
            channel_binding_id="binding-1",
            openclaw_account_id="bot-1",
            content_type="task_update",
            content={"text": "second"},
            dedupe_key="tenant-1:second",
        )
    )
    assert second.status == "retrying"
    assert second.held_reason == "rate_limited"

    retry = await service.mark_failed(second.delivery_id, "gateway timeout")
    assert retry.status == "retrying"
    assert retry.next_retry_at == datetime(2026, 5, 10, 9, 0, 30, tzinfo=timezone.utc)
    assert hook.events[0][0] == "delivery_retry_scheduled"


@pytest.mark.asyncio
async def test_outbox_abandons_after_max_retries() -> None:
    repository = InMemoryOutboxRepository()
    hook = RecordingHook()
    service = DeliveryOutboxService(
        repository,
        hooks=[hook],
        now_provider=lambda: datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc),
    )
    created = await service.enqueue(
        DeliveryEnvelope(
            tenant_id="tenant-1",
            channel_binding_id="binding-2",
            openclaw_account_id="bot-1",
            content_type="confirmation_card",
            content={"text": "confirm me"},
            dedupe_key="tenant-1:confirm",
            confirmation_session_id="session-1",
        )
    )
    await service.mark_failed(created.delivery_id, "attempt 1")
    await service.mark_failed(created.delivery_id, "attempt 2")
    await service.mark_failed(created.delivery_id, "attempt 3")
    final = await service.mark_failed(created.delivery_id, "attempt 4")
    assert final.status == "failed"
    assert hook.events[-1][0] == "delivery_abandoned"


@pytest.mark.asyncio
async def test_outbox_worker_delivers_retry_ready_message() -> None:
    repository = InMemoryOutboxRepository()
    hook = RecordingHook()
    service = DeliveryOutboxService(
        repository,
        hooks=[hook],
        now_provider=lambda: datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc),
    )
    created = await service.enqueue(
        DeliveryEnvelope(
            tenant_id="tenant-1",
            channel_binding_id="binding-1",
            openclaw_account_id="bot-1",
            content_type="confirmation_card",
            content={"text": "请确认", "command_hint": "确认 CFM123456"},
            dedupe_key="tenant-1:confirm:worker",
            confirmation_session_id="session-worker-1",
            target_conversation="conversation-1",
        )
    )
    sender = RecordingSender()
    worker = DeliveryOutboxWorker(
        service,
        sender,
        now_provider=lambda: datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc),
    )

    stats = await worker.process_ready()

    assert stats.scanned == 1
    assert stats.delivered == 1
    assert sender.sent[0]["id"] == created.delivery_id
    assert (await repository.get(created.delivery_id))["status"] == "delivered"
    assert hook.events[-1][0] == "delivery_delivered"


@pytest.mark.asyncio
async def test_outbox_worker_schedules_retry_when_sender_fails() -> None:
    repository = InMemoryOutboxRepository()
    hook = RecordingHook()
    service = DeliveryOutboxService(
        repository,
        hooks=[hook],
        now_provider=lambda: datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc),
    )
    created = await service.enqueue(
        DeliveryEnvelope(
            tenant_id="tenant-1",
            channel_binding_id="binding-1",
            openclaw_account_id="bot-1",
            content_type="task_update",
            content={"text": "任务完成"},
            dedupe_key="tenant-1:task:worker",
        )
    )
    worker = DeliveryOutboxWorker(
        service,
        RecordingSender(fail_times=1),
        now_provider=lambda: datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc),
    )

    stats = await worker.process_ready()
    record = await repository.get(created.delivery_id)

    assert stats.retrying == 1
    assert record["status"] == "retrying"
    assert record["attempt_count"] == 1
    assert record["last_error"] == "wechat gateway timeout"
    assert hook.events[-1][0] == "delivery_retry_scheduled"


@pytest.mark.asyncio
async def test_outbox_worker_expires_old_message_without_sending() -> None:
    repository = InMemoryOutboxRepository()
    hook = RecordingHook()
    service = DeliveryOutboxService(
        repository,
        hooks=[hook],
        now_provider=lambda: datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc),
    )
    created = await service.enqueue(
        DeliveryEnvelope(
            tenant_id="tenant-1",
            channel_binding_id="binding-1",
            openclaw_account_id="bot-1",
            content_type="task_update",
            content={"text": "过期消息"},
            dedupe_key="tenant-1:expired:worker",
        )
    )
    await repository.update(
        created.delivery_id,
        {"expires_at": datetime(2026, 5, 10, 8, 59, tzinfo=timezone.utc).isoformat()},
    )
    sender = RecordingSender()
    worker = DeliveryOutboxWorker(
        service,
        sender,
        now_provider=lambda: datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc),
    )

    stats = await worker.process_ready()
    record = await repository.get(created.delivery_id)

    assert stats.expired == 1
    assert sender.sent == []
    assert record["status"] == "expired"
    assert hook.events[-1][0] == "delivery_expired"


@pytest.mark.asyncio
async def test_webhook_delivery_sender_sends_signed_claw_payload() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"provider_message_id": "wx-msg-1"})

    sender = WebhookDeliverySender(
        "https://claw.example/send",
        secret="test-secret",
        transport=httpx.MockTransport(handler),
    )

    result = await sender.send(
        {
            "id": "delivery-1",
            "tenant_id": "tenant-1",
            "channel_binding_id": "binding-1",
            "openclaw_account_id": "bot-1",
            "target_conversation": "conv-1",
            "context_token": "ctx-1",
            "content_type": "confirmation_card",
            "content": {"text": "请确认", "command_hint": "确认 CFM123"},
            "dedupe_key": "tenant-1:confirm:1",
            "content_snapshot_hash": "hash-1",
            "priority": "high",
            "confirmation_session_id": "session-1",
        }
    )

    assert result["status_code"] == 200
    payload = captured["payload"]
    assert payload["delivery_id"] == "delivery-1"
    assert payload["channel"] == "openclaw-weixin"
    assert payload["recipient"]["openclaw_account_id"] == "bot-1"
    assert payload["recipient"]["target_conversation"] == "conv-1"
    assert payload["message"]["content_type"] == "confirmation_card"
    assert payload["message"]["content"]["command_hint"] == "确认 CFM123"

    headers = captured["headers"]
    assert headers["x-openclaw-delivery-id"] == "delivery-1"
    assert headers["x-openclaw-delivery-secret"] == "test-secret"
    assert headers["x-openclaw-delivery-signature"].startswith("v1=")
    assert headers["x-openclaw-delivery-timestamp"]
