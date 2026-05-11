from fastapi import FastAPI
from fastapi.testclient import TestClient

from openclaw.gateway.confirmation_center import (
    ConfirmationCenterService,
    InMemoryConfirmationRepository,
)
from openclaw.gateway.outbox import DeliveryOutboxService, InMemoryOutboxRepository
from openclaw.gateway.routers.openclaw_gateway import router


def build_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.confirmation_service = ConfirmationCenterService(
        InMemoryConfirmationRepository(),
        webapp_base_url="https://app.example.com",
    )
    app.state.outbox_service = DeliveryOutboxService(InMemoryOutboxRepository())
    return TestClient(app)


def build_test_client_with_repository() -> tuple[
    TestClient,
    InMemoryConfirmationRepository,
    InMemoryOutboxRepository,
]:
    app = FastAPI()
    app.include_router(router)
    repository = InMemoryConfirmationRepository()
    outbox_repository = InMemoryOutboxRepository()
    app.state.confirmation_service = ConfirmationCenterService(
        repository,
        webapp_base_url="https://app.example.com",
    )
    app.state.outbox_service = DeliveryOutboxService(outbox_repository)
    return TestClient(app), repository, outbox_repository


def test_text_trade_input_returns_confirmation_required() -> None:
    client = build_test_client()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-1",
                "channel_binding_id": "binding-1",
                "openclaw_account_id": "bot-1",
            },
            "message": {
                "type": "text",
                "text": "买入 AAPL 10 股 180",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "confirmation_required"
    assert data["session_token"].startswith("CFM")
    assert "确认页面链接" in data["reply_text"]
    assert "不会下单" in data["reply_text"]


def test_voice_confirm_command_consumes_latest_session() -> None:
    client = build_test_client()
    first = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-1",
                "channel_binding_id": "binding-1",
                "openclaw_account_id": "bot-1",
            },
            "message": {
                "type": "text",
                "text": "买入 NVDA 5 股 900",
            },
        },
    )
    session_token = first.json()["session_token"]

    second = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-1",
                "channel_binding_id": "binding-1",
                "openclaw_account_id": "bot-1",
            },
            "message": {
                "type": "voice",
                "transcript": f"确认 {session_token}",
                "transcript_confidence": 0.99,
            },
        },
    )
    assert second.status_code == 200
    data = second.json()
    assert data["result_type"] == "decision_received"
    assert data["decision"] == "confirmed"


def test_wechat_duplicate_confirm_is_idempotent() -> None:
    client, repository, _ = build_test_client_with_repository()
    first = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-duplicate",
                "channel_binding_id": "binding-duplicate",
                "openclaw_account_id": "bot-duplicate",
            },
            "message": {
                "type": "text",
                "text": "买入 AMD 2 股 130",
            },
        },
    )
    session_token = first.json()["session_token"]

    confirmed = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-duplicate",
                "channel_binding_id": "binding-duplicate",
                "openclaw_account_id": "bot-duplicate",
            },
            "message": {
                "type": "text",
                "text": f"确认 {session_token}",
            },
        },
    )
    duplicate = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-duplicate",
                "channel_binding_id": "binding-duplicate",
                "openclaw_account_id": "bot-duplicate",
            },
            "message": {
                "type": "text",
                "text": f"确认 {session_token}",
            },
        },
    )

    assert confirmed.status_code == 200
    assert duplicate.status_code == 200
    assert confirmed.json()["decision"] == "confirmed"
    assert duplicate.json()["decision"] == "already_confirmed"
    assert "不会重复" in duplicate.json()["reply_text"]
    assert repository.events[-1]["event_type"] == "duplicate_ignored"


def test_low_confidence_voice_creates_confirmation_candidate() -> None:
    client, repository, _ = build_test_client_with_repository()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-voice",
                "channel_binding_id": "binding-voice",
                "openclaw_account_id": "bot-voice",
            },
            "message": {
                "type": "voice",
                "transcript": "以后不要提醒我中概股",
                "transcript_confidence": 0.41,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "confirmation_required"
    assert "不会改动持仓，也不会下单" in data["reply_text"]

    pending_action = repository.pending_actions[data["pending_action_id"]]
    assert pending_action["tenant_id"] == "tenant-voice"
    assert pending_action["action_type"] == "asr_correction"
    assert pending_action["action_payload"]["confidence"] == 0.41


def test_image_ocr_candidate_creates_confirmation_and_preserves_tenant() -> None:
    client, repository, outbox_repository = build_test_client_with_repository()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-image",
                "channel_binding_id": "binding-image",
                "openclaw_account_id": "bot-image",
            },
            "message": {
                "type": "image",
                "image_text": "买入 BABA 5 股 88",
                "ocr_confidence": 0.87,
                "media_id": "wx-media-1",
                "metadata": {"source": "album"},
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "confirmation_required"
    assert "tenant_id=tenant-image" in data["webapp_deep_link"]
    assert "不会改动持仓，也不会下单" in data["reply_text"]

    pending_action = repository.pending_actions[data["pending_action_id"]]
    assert pending_action["tenant_id"] == "tenant-image"
    assert pending_action["source_type"] == "image_ocr"
    assert pending_action["action_payload"]["image_text"] == "买入 BABA 5 股 88"
    assert pending_action["action_payload"]["media_id"] == "wx-media-1"

    records = list(outbox_repository._records.values())
    assert len(records) == 1
    assert records[0]["tenant_id"] == "tenant-image"


def test_low_confidence_image_ocr_routes_to_confirmation_review_center() -> None:
    client, repository, outbox_repository = build_test_client_with_repository()
    response = client.post(
        "/api/openclaw/wechat/messages",
        json={
            "routing": {
                "tenant_id": "tenant-image-low-confidence",
                "channel_binding_id": "binding-image-low-confidence",
                "openclaw_account_id": "bot-image-low-confidence",
                "target_conversation": "conversation-image-low-confidence",
            },
            "message": {
                "type": "image",
                "ocr_text": "买入 AAPL 10 股 180",
                "ocr_confidence": 0.33,
                "media_id": "wx-media-low-confidence",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["result_type"] == "confirmation_required"
    assert "待确认图片识别内容已放入确认中心" in data["reply_text"]
    assert "不会改动持仓，也不会下单" in data["reply_text"]
    assert "tenant_id=tenant-image-low-confidence" in data["webapp_deep_link"]

    pending_action = repository.pending_actions[data["pending_action_id"]]
    assert pending_action["tenant_id"] == "tenant-image-low-confidence"
    assert pending_action["action_type"] == "ocr_correction"
    assert pending_action["action_payload"]["ocr_text"] == "买入 AAPL 10 股 180"
    assert pending_action["action_payload"]["ocr_confidence"] == 0.33
    assert "识别把握不高" in pending_action["normalized_summary"]["risk_note"]

    records = list(outbox_repository._records.values())
    assert len(records) == 1
    assert records[0]["tenant_id"] == "tenant-image-low-confidence"
    assert records[0]["target_conversation"] == "conversation-image-low-confidence"
    assert records[0]["content"]["title"] == "待确认图片识别内容"
