import pytest

from services.hermes import delivery
from services.hermes.delivery import HermesDeliveryProcessor


@pytest.mark.asyncio
async def test_process_ready_cancels_suppressed_system_delivery(monkeypatch):
    cancelled = []

    monkeypatch.setattr(
        delivery,
        "_load_ready_deliveries",
        lambda _database_url, _limit: [
            {
                "id": "delivery-system",
                "content_type": "system_message",
                "attempt_count": 0,
            }
        ],
    )
    monkeypatch.setattr(
        delivery,
        "_mark_cancelled",
        lambda _database_url, delivery_id, reason: cancelled.append((delivery_id, reason)),
    )

    async def fail_send(_self, _record):
        raise AssertionError("suppressed deliveries must not call the webhook sender")

    monkeypatch.setattr(HermesDeliveryProcessor, "_send", fail_send)

    result = await HermesDeliveryProcessor(database_url="postgresql://example").process_ready()

    assert result["ok"] is True
    assert result["scanned"] == 1
    assert result["suppressed"] == 1
    assert result["delivered"] == 0
    assert cancelled == [("delivery-system", "suppressed_delivery_content_type:system_message")]


def test_mark_failed_records_retry_event(monkeypatch):
    updates = []
    events = []

    monkeypatch.setattr(
        delivery,
        "_update_delivery",
        lambda _database_url, delivery_id, payload: updates.append((delivery_id, payload)),
    )
    monkeypatch.setattr(
        delivery,
        "_insert_message_event",
        lambda _database_url, delivery_id, event_type, payload: events.append((delivery_id, event_type, payload)),
    )

    status = delivery._mark_failed(
        "postgresql://example",
        {"id": "delivery-retry", "attempt_count": 0},
        "wechat gateway timeout",
    )

    assert status == "retrying"
    assert updates[0][0] == "delivery-retry"
    assert updates[0][1]["status"] == "retrying"
    assert updates[0][1]["attempt_count"] == 1
    assert events == [
        (
            "delivery-retry",
            "failed",
            {
                "status": "retrying",
                "attempt_count": 1,
                "error": "wechat gateway timeout",
                "next_retry_at": updates[0][1]["next_retry_at"].isoformat(),
            },
        )
    ]


def test_hermes_suppressed_delivery_env_extends_default(monkeypatch):
    monkeypatch.setenv("HERMES_WECHAT_SUPPRESSED_DELIVERY_CONTENT_TYPES", "portfolio_cron_update, broker_sync_planner")

    assert delivery._is_suppressed_delivery({"content_type": "portfolio_cron_update"}) is True
    assert delivery._is_suppressed_delivery({"content_type": "system_message"}) is True
    assert delivery._is_suppressed_delivery({"content_type": "alert_notification"}) is False
