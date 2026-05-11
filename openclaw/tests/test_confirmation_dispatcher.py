from datetime import datetime, timezone

import pytest

from openclaw.gateway.confirmation_center import (
    ConfirmationCenterService,
    InMemoryConfirmationRepository,
    RoutingContext,
    classify_high_attention_text,
    parse_confirmation_command,
)
from openclaw.gateway.confirmation_dispatcher import (
    ConfirmationPostDecisionDispatcher,
    InMemoryPostConfirmationTaskRepository,
)


@pytest.mark.asyncio
async def test_confirmed_trade_enqueues_holdings_recalculation_once() -> None:
    confirmation_repository = InMemoryConfirmationRepository()
    task_repository = InMemoryPostConfirmationTaskRepository()
    dispatcher = ConfirmationPostDecisionDispatcher(
        task_repository,
        now_provider=lambda: datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc),
    )
    service = ConfirmationCenterService(
        confirmation_repository,
        webapp_base_url="https://app.example.com",
        post_decision_dispatcher=dispatcher,
        now_provider=lambda: datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc),
    )
    context = RoutingContext(
        tenant_id="tenant-dispatch",
        channel_binding_id="binding-dispatch",
        openclaw_account_id="bot-dispatch",
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
        parse_confirmation_command(f"确认 {created.session_token}"),
    )

    assert result.outcome == "confirmed"
    assert result.status == "committing"
    assert confirmation_repository.pending_actions[created.pending_action_id]["status"] == "committing"
    assert len(task_repository.tasks) == 1
    task = next(iter(task_repository.tasks.values()))
    assert task["tenant_id"] == "tenant-dispatch"
    assert task["job_type"] == "confirmed_trade_recalculate_holdings"
    assert task["status"] == "PENDING"
    assert task["runtime_target"] == "domain_worker"
    assert task["timeout_seconds"] == 300
    assert task["config"]["post_decision"] == "commit_or_recalculate"
    assert task["config"]["pending_action"]["id"] == created.pending_action_id
    assert task["config"]["confirmation"]["session_id"] == created.confirmation_session_id
    assert task["config"]["execution_guard"]["confirmation_record_required"] is True
    assert task["config"]["execution_guard"]["human_confirm_required"] is True
    assert task["config"]["execution_guard"]["draft_only"] is True
    assert task["config"]["execution_guard"]["auto_order_allowed"] is False

    duplicate = await service.submit_decision(
        context,
        parse_confirmation_command(f"确认 {created.session_token}"),
    )
    assert duplicate.outcome == "already_confirmed"
    assert len(task_repository.tasks) == 1


@pytest.mark.asyncio
async def test_confirmed_sell_put_uses_deep_task_timeout() -> None:
    confirmation_repository = InMemoryConfirmationRepository()
    task_repository = InMemoryPostConfirmationTaskRepository()
    service = ConfirmationCenterService(
        confirmation_repository,
        webapp_base_url="https://app.example.com",
        post_decision_dispatcher=ConfirmationPostDecisionDispatcher(task_repository),
    )
    context = RoutingContext(
        tenant_id="tenant-sellput",
        channel_binding_id="binding-sellput",
        openclaw_account_id="bot-sellput",
    )
    pending = classify_high_attention_text(
        "生成 NVDA Sell Put 草稿，30 delta，45 DTE",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    assert pending is not None
    created = await service.create_pending_confirmation(context, pending)

    result = await service.submit_decision(
        context,
        parse_confirmation_command(f"确认 {created.session_token}"),
    )

    assert result.status == "committing"
    task = next(iter(task_repository.tasks.values()))
    assert task["job_type"] == "confirmed_sell_put_draft_finalize"
    assert task["timeout_seconds"] == 1800
    assert task["config"]["task_category"] == "deep"
    assert task["config"]["execution_guard"]["draft_only"] is True
    assert task["config"]["execution_guard"]["human_confirm_required"] is True
    assert task["config"]["execution_guard"]["auto_order_allowed"] is False


@pytest.mark.asyncio
async def test_revise_enqueues_rebuild_request_without_fact_commit() -> None:
    confirmation_repository = InMemoryConfirmationRepository()
    task_repository = InMemoryPostConfirmationTaskRepository()
    service = ConfirmationCenterService(
        confirmation_repository,
        webapp_base_url="https://app.example.com",
        post_decision_dispatcher=ConfirmationPostDecisionDispatcher(task_repository),
    )
    context = RoutingContext(
        tenant_id="tenant-revise",
        channel_binding_id="binding-revise",
        openclaw_account_id="bot-revise",
    )
    pending = classify_high_attention_text(
        "卖出 TSLA 1 股 220",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    assert pending is not None
    created = await service.create_pending_confirmation(context, pending)

    result = await service.submit_decision(
        context,
        parse_confirmation_command(f"修改 {created.session_token} 改成卖出 TSLA 2 股 220"),
    )

    assert result.outcome == "rebuild_required"
    assert result.status == "revoked"
    assert confirmation_repository.pending_actions[created.pending_action_id]["status"] == "revoked"
    assert len(task_repository.tasks) == 1
    task = next(iter(task_repository.tasks.values()))
    assert task["job_type"] == "confirmation_rebuild_request"
    assert task["config"]["post_decision"] == "rebuild_confirmation_required"
    assert task["config"]["decision_command"]["revision_text"] == "改成卖出 TSLA 2 股 220"
    assert task["config"]["execution_guard"]["fact_write_allowed"] is False
    assert task["config"]["execution_guard"]["human_confirm_required"] is True


@pytest.mark.asyncio
async def test_reject_does_not_enqueue_post_confirmation_task() -> None:
    confirmation_repository = InMemoryConfirmationRepository()
    task_repository = InMemoryPostConfirmationTaskRepository()
    service = ConfirmationCenterService(
        confirmation_repository,
        webapp_base_url="https://app.example.com",
        post_decision_dispatcher=ConfirmationPostDecisionDispatcher(task_repository),
    )
    context = RoutingContext(
        tenant_id="tenant-reject",
        channel_binding_id="binding-reject",
        openclaw_account_id="bot-reject",
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
        parse_confirmation_command(f"取消 {created.session_token}"),
    )

    assert result.outcome == "rejected"
    assert task_repository.tasks == {}
