from datetime import datetime, timedelta, timezone

import pytest

from openclaw.gateway.confirmation_center import (
    ConfirmationCenterService,
    HIGH_ATTENTION_TTL_MINUTES,
    InMemoryConfirmationRepository,
    LOW_ATTENTION_TTL_HOURS,
    RoutingContext,
    build_confirmation_deep_link,
    classify_high_attention_text,
    classify_image_text_candidate,
    interpret_voice_transcript,
    parse_confirmation_command,
)


class FailingDispatcher:
    async def dispatch(self, **_: object) -> None:
        raise RuntimeError("queue temporarily unavailable")


def test_parse_confirmation_command_variants() -> None:
    command = parse_confirmation_command("确认 CFM1234")
    assert command is not None
    assert command.action == "confirm"
    assert command.session_hint == "CFM1234"

    reject = parse_confirmation_command("取消 #abc123")
    assert reject is not None
    assert reject.action == "reject"
    assert reject.session_hint == "abc123"

    revise = parse_confirmation_command("修改 CFM9988 改成买入 AAPL 10 股")
    assert revise is not None
    assert revise.action == "revise"
    assert revise.session_hint == "CFM9988"
    assert revise.revision_text == "改成买入 AAPL 10 股"


def test_build_confirmation_deep_link() -> None:
    link = build_confirmation_deep_link(
        "https://app.example.com",
        "tenant-1",
        "session-1",
        "CFM123456",
        pending_action_id="pending-1",
    )
    assert link == (
        "https://app.example.com/confirmations/resolve"
        "?tenant_id=tenant-1&session_id=session-1&session_token=CFM123456"
        "&channel=wechat&pending_action_id=pending-1"
    )


def test_interpret_voice_transcript_boundaries() -> None:
    low_confidence = interpret_voice_transcript("买入腾讯 100 股", confidence=0.5)
    assert low_confidence.mode == "pending_action"
    assert low_confidence.reason == "low_confidence_asr"
    assert low_confidence.candidate is not None
    assert low_confidence.candidate.action_type == "asr_correction"
    assert low_confidence.candidate.object_type == "voice_input_review"
    assert low_confidence.candidate.action_payload["confidence"] == 0.5

    decision = interpret_voice_transcript("确认 CFM778899", confidence=0.92)
    assert decision.mode == "decision"
    assert decision.parsed_command is not None
    assert decision.parsed_command.action == "confirm"

    trade = interpret_voice_transcript("买入 AAPL 10 股 180", confidence=0.95)
    assert trade.mode == "pending_action"
    assert trade.candidate is not None
    assert trade.candidate.object_type == "trade_event_input"


def test_classify_image_text_candidate_supports_ocr_and_image_text_fields() -> None:
    trade_candidate = classify_image_text_candidate(
        "买入 AAPL 10 股 180",
        ocr_confidence=0.83,
        media_id="media-1",
        metadata={"source": "camera"},
        source_field="image_text",
    )
    assert trade_candidate is not None
    assert trade_candidate.action_type == "trade_input"
    assert trade_candidate.source_type == "image_ocr"
    assert trade_candidate.action_payload["image_text"] == "买入 AAPL 10 股 180"
    assert trade_candidate.action_payload["media_id"] == "media-1"
    assert "确认前不会改动持仓，也不会下单" in trade_candidate.normalized_summary["risk_note"]

    generic_candidate = classify_image_text_candidate(
        "这是我刚拍的持仓截图",
        ocr_confidence=0.6,
        source_field="ocr_text",
    )
    assert generic_candidate is not None
    assert generic_candidate.action_type == "ocr_correction"
    assert generic_candidate.action_payload["ocr_text"] == "这是我刚拍的持仓截图"
    assert generic_candidate.normalized_summary["title"] == "待确认图片识别内容"


def test_low_confidence_ocr_trade_text_stays_in_review_center() -> None:
    candidate = classify_image_text_candidate(
        "买入 AAPL 10 股 180",
        ocr_confidence=0.41,
        media_id="media-low-confidence",
        metadata={"source": "forward"},
        source_field="ocr_text",
    )
    assert candidate is not None
    assert candidate.action_type == "ocr_correction"
    assert candidate.object_type == "image_input_review"
    assert candidate.action_payload["ocr_text"] == "买入 AAPL 10 股 180"
    assert candidate.action_payload["ocr_confidence"] == 0.41
    assert candidate.action_payload["media_id"] == "media-low-confidence"
    assert "识别把握不高" in candidate.normalized_summary["risk_note"]
    assert "不会改动持仓，也不会下单" in candidate.normalized_summary["risk_note"]


@pytest.mark.asyncio
async def test_confirmation_service_creates_and_confirms_pending_action() -> None:
    repository = InMemoryConfirmationRepository()
    service = ConfirmationCenterService(
        repository,
        webapp_base_url="https://app.example.com",
    )
    context = RoutingContext(
        tenant_id="tenant-1",
        channel_binding_id="binding-1",
        openclaw_account_id="bot-1",
    )
    pending = classify_high_attention_text(
        "买入 AAPL 10 股 180",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    assert pending is not None

    created = await service.create_pending_confirmation(context, pending)
    assert created.session_token.startswith("CFM")
    action_payload = repository.pending_actions[created.pending_action_id]
    assert action_payload["status"] == "awaiting_confirmation"
    assert action_payload["source_surface"] == "wechat"
    assert action_payload["actionability_cap"] == "trade_draft"
    assert "actionability_level" not in action_payload
    assert repository.sessions[created.confirmation_session_id]["channel"] == "openclaw_wechat"

    result = await service.submit_decision(
        context,
        parse_confirmation_command(f"确认 {created.session_token}") or None,
    )
    assert result.outcome == "confirmed"
    assert "不会自动下单" in result.reply_text
    assert repository.pending_actions[created.pending_action_id]["status"] == "confirmed"
    assert repository.sessions[created.confirmation_session_id]["session_status"] == "consumed"
    assert repository.events[-1]["event_type"] == "confirmed"
    assert repository.events[-1]["actor_type"] == "user"
    assert repository.events[-1]["event_payload"]["post_decision"] == "commit_or_recalculate"

    duplicate = await service.submit_decision(
        context,
        parse_confirmation_command(f"确认 {created.session_token}") or None,
    )
    assert duplicate.outcome == "already_confirmed"
    assert duplicate.status == "confirmed"
    assert repository.events[-1]["event_type"] == "duplicate_ignored"
    assert repository.events[-1]["event_payload"]["requested_action"] == "confirm"


@pytest.mark.asyncio
async def test_confirmation_service_uses_ttl_by_confirmation_strength() -> None:
    now = datetime(2026, 5, 10, 1, 0, tzinfo=timezone.utc)
    repository = InMemoryConfirmationRepository()
    service = ConfirmationCenterService(
        repository,
        webapp_base_url="https://app.example.com",
        now_provider=lambda: now,
    )
    context = RoutingContext(
        tenant_id="tenant-ttl",
        channel_binding_id="binding-ttl",
        openclaw_account_id="bot-ttl",
    )

    high_risk = classify_high_attention_text(
        "买入 AAPL 10 股 180",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    low_risk = classify_high_attention_text(
        "以后不要提醒我中概股",
        source_type="message_trade_input",
        source_surface="wechat",
    )

    assert high_risk is not None
    assert low_risk is not None

    high_created = await service.create_pending_confirmation(context, high_risk)
    low_created = await service.create_pending_confirmation(context, low_risk)

    assert high_created.expires_at == now + timedelta(minutes=HIGH_ATTENTION_TTL_MINUTES)
    assert low_created.expires_at == now + timedelta(hours=LOW_ATTENTION_TTL_HOURS)


@pytest.mark.asyncio
async def test_confirmation_service_rejects_instead_of_writing_facts() -> None:
    repository = InMemoryConfirmationRepository()
    service = ConfirmationCenterService(
        repository,
        webapp_base_url="https://app.example.com",
        now_provider=lambda: datetime(2026, 5, 10, 1, 0, tzinfo=timezone.utc),
    )
    context = RoutingContext(
        tenant_id="tenant-2",
        channel_binding_id="binding-2",
        openclaw_account_id="bot-2",
    )
    pending = classify_high_attention_text(
        "以后不要提醒我中概股",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    assert pending is not None
    created = await service.create_pending_confirmation(context, pending)

    result = await service.submit_decision(
        context,
        parse_confirmation_command(f"取消 {created.session_token}") or None,
    )
    assert result.outcome == "rejected"
    assert "没有改动持仓" in result.reply_text
    assert "没有下单" in result.reply_text
    assert "WebApp 确认中心" in result.reply_text
    assert repository.pending_actions[created.pending_action_id]["status"] == "rejected"


@pytest.mark.asyncio
async def test_confirmation_service_expires_and_records_event() -> None:
    current = datetime(2026, 5, 10, 1, 0, tzinfo=timezone.utc)
    repository = InMemoryConfirmationRepository()
    service = ConfirmationCenterService(
        repository,
        webapp_base_url="https://app.example.com",
        now_provider=lambda: current,
    )
    context = RoutingContext(
        tenant_id="tenant-expired",
        channel_binding_id="binding-expired",
        openclaw_account_id="bot-expired",
    )
    pending = classify_high_attention_text(
        "买入 MSFT 3 股 410",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    assert pending is not None
    pending.expires_at = current - timedelta(minutes=1)
    created = await service.create_pending_confirmation(context, pending)

    result = await service.submit_decision(
        context,
        parse_confirmation_command(f"确认 {created.session_token}") or None,
    )

    assert result.outcome == "expired"
    assert result.status == "expired"
    assert "没有改动持仓" in result.reply_text
    assert "没有下单" in result.reply_text
    assert "WebApp 确认中心" in result.reply_text
    assert repository.pending_actions[created.pending_action_id]["status"] == "expired"
    assert repository.sessions[created.confirmation_session_id]["session_status"] == "expired"
    assert repository.events[-1]["event_type"] == "expired"

    duplicate = await service.submit_decision(
        context,
        parse_confirmation_command(f"确认 {created.session_token}") or None,
    )
    assert duplicate.outcome == "already_expired"
    assert repository.events[-1]["event_type"] == "duplicate_ignored"


@pytest.mark.asyncio
async def test_confirmation_service_normalizes_legacy_openclaw_channel() -> None:
    repository = InMemoryConfirmationRepository()
    service = ConfirmationCenterService(
        repository,
        webapp_base_url="https://app.example.com",
    )
    context = RoutingContext(
        tenant_id="tenant-3",
        channel_binding_id="binding-3",
        openclaw_account_id="bot-3",
        channel="openclaw-weixin",
    )
    pending = classify_high_attention_text(
        "卖出 TSLA 1 股 220",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    assert pending is not None

    created = await service.create_pending_confirmation(context, pending)

    assert repository.sessions[created.confirmation_session_id]["channel"] == "openclaw_wechat"


@pytest.mark.asyncio
async def test_confirmation_service_returns_retryable_copy_when_dispatch_fails() -> None:
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc)
    repository = InMemoryConfirmationRepository()
    service = ConfirmationCenterService(
        repository,
        webapp_base_url="https://app.example.com",
        post_decision_dispatcher=FailingDispatcher(),
        now_provider=lambda: now,
    )
    context = RoutingContext(
        tenant_id="tenant-dispatch-fail",
        channel_binding_id="binding-dispatch-fail",
        openclaw_account_id="bot-dispatch-fail",
    )
    pending = classify_high_attention_text(
        "买入 AAPL 10 股 180",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    assert pending is not None
    created = await service.create_pending_confirmation(context, pending)

    result = await service.submit_decision(
        context,
        parse_confirmation_command(f"确认 {created.session_token}") or None,
    )

    assert result.outcome == "confirmed"
    assert result.status == "failed_retryable"
    assert "没有改动持仓" in result.reply_text
    assert "没有下单" in result.reply_text
    assert "WebApp 确认中心" in result.reply_text
    assert repository.pending_actions[created.pending_action_id]["status"] == "failed_retryable"
    assert repository.events[-1]["event_type"] == "commit_failed"
