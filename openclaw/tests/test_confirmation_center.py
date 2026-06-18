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
    parse_broker_trade_message,
    parse_position_snapshot_rows,
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


def test_parse_broker_trade_message_supports_v2_huatai_template() -> None:
    parsed = parse_broker_trade_message(
        "\n".join(
            [
                "【华泰证券】您的委托已成交",
                "证券名称：贵州茅台",
                "证券代码：600519",
                "委托方向：买入",
                "成交数量：100股",
                "成交价格：1680.00元",
                "成交时间：14:32:18",
                "委托编号：12345678",
            ]
        )
    )

    assert parsed is not None
    assert parsed["broker"] == "huatai"
    assert parsed["side"] == "BUY"
    assert parsed["symbol"] == "600519.SH"
    assert parsed["stock_name"] == "贵州茅台"
    assert parsed["quantity"] == 100
    assert parsed["price"] == 1680.00
    assert parsed["order_no"] == "12345678"
    assert parsed["fingerprint"]


def test_classify_high_attention_text_prioritizes_broker_parse_over_generic_trade() -> None:
    candidate = classify_high_attention_text(
        "\n".join(
            [
                "【富途牛牛】成交通知",
                "方向：BUY",
                "代码：AAPL",
                "名称：Apple Inc.",
                "数量：50股",
                "价格：$190.00",
                "时间：2024-01-15 14:32:18 EST",
            ]
        ),
        source_type="message_text",
        source_surface="wechat",
    )

    assert candidate is not None
    assert candidate.action_type == "trade_input"
    assert candidate.source_type == "broker_wechat"
    assert candidate.action_payload["structured_trade"]["broker"] == "futu"
    assert candidate.action_payload["structured_trade"]["symbol"] == "AAPL"
    assert candidate.action_payload["structured_trade"]["quantity"] == 50
    assert candidate.action_payload["structured_trade"]["price"] == 190.0
    assert candidate.normalized_summary["title"] == "待确认富途牛牛成交提醒"


def test_sell_put_analysis_request_stays_in_dialogue_lane() -> None:
    candidate = classify_high_attention_text(
        "帮我分析一下 TSLA 的 Sell Put 候选排序",
        source_type="message_text",
        source_surface="wechat",
    )

    assert candidate is None


def test_explicit_sell_put_draft_requires_confirmation() -> None:
    candidate = classify_high_attention_text(
        "帮我生成 TSLA Sell Put 草稿，准备卖出 100P",
        source_type="message_text",
        source_surface="wechat",
    )

    assert candidate is not None
    assert candidate.action_type == "trade_draft_ack"
    assert candidate.object_type == "sell_put_trade_draft"


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
    assert trade_candidate.source_type == "ocr"
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


def test_classify_image_text_candidate_detects_position_screenshot_rows() -> None:
    candidate = classify_image_text_candidate(
        "持仓 数量 成本\nAAPL 苹果 10 180.25\nNVDA 英伟达 2 900",
        ocr_confidence=0.91,
        media_id="position-media-1",
        source_field="ocr_text",
    )

    assert candidate is not None
    assert candidate.object_type == "position_snapshot_input"
    assert candidate.action_type == "position_snapshot_input"
    assert candidate.action_scope == "fact_record"
    assert candidate.source_type == "ocr"
    assert candidate.action_payload["positions"][0]["symbol"] == "AAPL"
    assert candidate.action_payload["positions"][0]["quantity"] == 10
    assert candidate.action_payload["positions"][0]["average_cost"] == 180.25
    assert candidate.action_payload["positions"][1]["symbol"] == "NVDA"
    assert candidate.action_payload["source_policy"]["source_tier"] == "user_confirmed"
    assert candidate.action_payload["source_policy"]["actionability"] == "analysis_only"
    assert candidate.action_payload["source_policy"]["fact_write_allowed"] is True
    assert candidate.normalized_summary["title"] == "待确认持仓截图导入"


def test_parse_position_snapshot_rows_supports_futu_name_only_layout() -> None:
    rows = parse_position_snapshot_rows(
        "\n".join(
            [
                "持仓 证券名称 证券市值 浮动盈亏 盈亏比例 成本价 现价 实际数量 可用数量",
                "盛新锂能 485100.00 -53475.75 -9.93% 53.858 48.510 10000 10000",
                "东山精密 113120.00 5109.20 4.73% 216.022 226.240 500 500",
                "罗博特科 0.00 181958.19 -- 0.000 621.990 0 0",
            ]
        )
    )

    assert len(rows) == 2
    assert rows[0]["stock_name"] == "盛新锂能"
    assert rows[0]["symbol"].startswith("CNNAME_")
    assert rows[0]["market"] == "CN"
    assert rows[0]["exchange"] == "UNKNOWN"
    assert rows[0]["requires_symbol_review"] is True
    assert rows[0]["symbol_confidence"] == "name_only"
    assert rows[0]["quantity"] == 10000
    assert rows[0]["available_quantity"] == 10000
    assert rows[0]["average_cost"] == 53.858
    assert rows[0]["current_price"] == 48.510
    assert rows[0]["market_value"] == 485100.00
    assert rows[0]["unrealized_pnl"] == -53475.75
    assert rows[0]["pnl_ratio"] == -0.0993
    assert rows[1]["stock_name"] == "东山精密"


def test_parse_position_snapshot_rows_supports_name_first_quantity_first_ocr() -> None:
    rows = parse_position_snapshot_rows(
        "\n".join(
            [
                "持仓 数量 成本价 现价 市值 浮动盈亏 盈亏比例",
                "盛新锂能 10000 53.858 48.510 485100.00 -53475.75 -9.93%",
                "东山精密 500 216.022 226.240 113120.00 5109.20 4.73%",
            ]
        )
    )

    assert len(rows) == 2
    assert rows[0]["symbol"].startswith("CNNAME_")
    assert rows[0]["stock_name"] == "盛新锂能"
    assert rows[0]["quantity"] == 10000
    assert rows[0]["average_cost"] == 53.858
    assert rows[0]["current_price"] == 48.510
    assert rows[0]["market_value"] == 485100.00
    assert rows[0]["unrealized_pnl"] == -53475.75
    assert rows[0]["pnl_ratio"] == -0.0993
    assert rows[1]["stock_name"] == "东山精密"
    assert rows[1]["quantity"] == 500


def test_position_screenshot_candidate_marks_name_only_symbols_for_review() -> None:
    candidate = classify_image_text_candidate(
        "\n".join(
            [
                "持仓 证券名称 证券市值 浮动盈亏 盈亏比例 成本价 现价 实际数量 可用数量",
                "盛新锂能 485100.00 -53475.75 -9.93% 53.858 48.510 10000 10000",
            ]
        ),
        ocr_confidence=0.93,
        media_id="position-media-name-only",
    )

    assert candidate is not None
    position = candidate.action_payload["positions"][0]
    assert position["symbol"].startswith("CNNAME_")
    assert position["requires_symbol_review"] is True
    assert "需补证券代码" in candidate.normalized_summary["body"]
    assert "需补代码" in candidate.normalized_summary["risk_note"]


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


def test_low_confidence_position_screenshot_still_creates_position_confirmation() -> None:
    candidate = classify_image_text_candidate(
        "\n".join(
            [
                "持仓 证券名称 证券市值 浮动盈亏 盈亏比例 成本价 现价 实际数量 可用数量",
                "盛新锂能 485100.00 -53475.75 -9.93% 53.858 48.510 10000 10000",
                "东山精密 113120.00 5109.20 4.73% 216.022 226.240 500 500",
            ]
        ),
        ocr_confidence=0.46,
        media_id="position-media-low-confidence",
        source_field="ocr_text",
    )

    assert candidate is not None
    assert candidate.action_type == "position_snapshot_input"
    assert candidate.object_type == "position_snapshot_input"
    assert candidate.action_payload["ocr_confidence"] == 0.46
    assert candidate.action_payload["source_policy"]["confidence"] == 0.46
    assert candidate.normalized_summary["title"] == "待确认持仓截图导入"
    assert "盛新锂能" in candidate.normalized_summary["body"]


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
    assert "确认中心查看最新状态" in result.reply_text
    assert "微信口令仍可用于二次确认" in result.reply_text
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
    assert "确认中心查看最新状态" in result.reply_text
    assert "微信口令仍可用于二次确认" in result.reply_text
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
    assert "确认中心查看最新状态" in result.reply_text
    assert "微信口令仍可用于二次确认" in result.reply_text
    assert repository.pending_actions[created.pending_action_id]["status"] == "failed_retryable"
    assert repository.events[-1]["event_type"] == "commit_failed"
