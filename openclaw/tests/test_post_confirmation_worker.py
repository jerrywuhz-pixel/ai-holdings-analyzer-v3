from datetime import datetime, timezone

import pytest

from openclaw.gateway.confirmation_center import (
    ConfirmationCenterService,
    InMemoryConfirmationRepository,
    RoutingContext,
    classify_high_attention_text,
    classify_image_text_candidate,
    parse_confirmation_command,
)
from openclaw.gateway.confirmation_dispatcher import (
    ConfirmationPostDecisionDispatcher,
    InMemoryPostConfirmationTaskRepository,
)
from openclaw.gateway.outbox import (
    DeliveryOutboxService,
    DeliveryOutboxWorker,
    InMemoryOutboxRepository,
)
from openclaw.gateway.post_confirmation_worker import (
    InMemoryPostConfirmationWorkerRepository,
    PostConfirmationJobWorker,
)


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, delivery: dict) -> dict:
        self.sent.append(delivery)
        return {"provider_message_id": f"msg-{delivery['id']}"}


@pytest.mark.asyncio
async def test_worker_commits_trade_and_refreshes_position_snapshot() -> None:
    confirmation_repository = InMemoryConfirmationRepository()
    task_repository = InMemoryPostConfirmationTaskRepository()
    service = ConfirmationCenterService(
        confirmation_repository,
        webapp_base_url="https://app.example.com",
        post_decision_dispatcher=ConfirmationPostDecisionDispatcher(
            task_repository,
            now_provider=lambda: datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc),
        ),
        now_provider=lambda: datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc),
    )
    context = RoutingContext(
        tenant_id="tenant-worker",
        channel_binding_id="binding-worker",
        openclaw_account_id="bot-worker",
    )
    pending = classify_high_attention_text(
        "买入 AAPL 10 股 180",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    assert pending is not None
    created = await service.create_pending_confirmation(context, pending)
    await service.submit_decision(context, parse_confirmation_command(f"确认 {created.session_token}"))

    worker_repository = InMemoryPostConfirmationWorkerRepository(
        jobs=task_repository.tasks,
        pending_actions=confirmation_repository.pending_actions,
        confirmation_events=confirmation_repository.events,
    )
    worker = PostConfirmationJobWorker(
        worker_repository,
        now_provider=lambda: datetime(2026, 5, 10, 2, 1, tzinfo=timezone.utc),
    )

    stats = await worker.process_once()

    assert stats.scanned == 1
    assert stats.succeeded == 1
    assert next(iter(task_repository.tasks.values()))["status"] == "SUCCESS"
    assert confirmation_repository.pending_actions[created.pending_action_id]["status"] == "committed"
    assert len(worker_repository.trade_events) == 1
    trade = worker_repository.trade_events[0]
    assert trade["side"] == "BUY"
    assert trade["symbol"] == "AAPL"
    assert trade["quantity"] == 10
    assert trade["price"] == 180.0
    snapshot = next(iter(worker_repository.position_snapshots.values()))
    assert snapshot["symbol"] == "AAPL"
    assert snapshot["total_quantity"] == 10
    assert snapshot["average_cost"] == 180.0
    assert confirmation_repository.events[-1]["event_type"] == "commit_succeeded"

    second_stats = await worker.process_once()
    assert second_stats.scanned == 0
    assert len(worker_repository.trade_events) == 1


@pytest.mark.asyncio
async def test_worker_commits_structured_broker_trade_without_reparsing_text() -> None:
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc)
    confirmation_repository = InMemoryConfirmationRepository()
    task_repository = InMemoryPostConfirmationTaskRepository()
    service = ConfirmationCenterService(
        confirmation_repository,
        webapp_base_url="https://app.example.com",
        post_decision_dispatcher=ConfirmationPostDecisionDispatcher(
            task_repository,
            now_provider=lambda: now,
        ),
        now_provider=lambda: now,
    )
    context = RoutingContext(
        tenant_id="tenant-broker-worker",
        channel_binding_id="binding-broker-worker",
        openclaw_account_id="bot-broker-worker",
    )
    pending = classify_high_attention_text(
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
        ),
        source_type="message_text",
        source_surface="wechat",
    )
    assert pending is not None
    assert pending.source_type == "broker_wechat"
    created = await service.create_pending_confirmation(context, pending)
    await service.submit_decision(context, parse_confirmation_command(f"确认 {created.session_token}"))

    worker_repository = InMemoryPostConfirmationWorkerRepository(
        jobs=task_repository.tasks,
        pending_actions=confirmation_repository.pending_actions,
        confirmation_events=confirmation_repository.events,
    )
    worker = PostConfirmationJobWorker(
        worker_repository,
        now_provider=lambda: now,
    )

    stats = await worker.process_once()

    assert stats.succeeded == 1
    trade = worker_repository.trade_events[0]
    assert trade["source"] == "broker_wechat"
    assert trade["symbol"] == "600519.SH"
    assert trade["stock_name"] == "贵州茅台"
    assert trade["quantity"] == 100
    assert trade["price"] == 1680.0
    assert trade["broker_message_fingerprint"]
    snapshot = worker_repository.position_snapshots[("tenant-broker-worker", "600519.SH", "2026-05-10")]
    assert snapshot["total_quantity"] == 100
    assert snapshot["average_cost"] == 1680.0


@pytest.mark.asyncio
async def test_worker_imports_confirmed_position_screenshot_snapshot() -> None:
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc)
    confirmation_repository = InMemoryConfirmationRepository()
    task_repository = InMemoryPostConfirmationTaskRepository()
    service = ConfirmationCenterService(
        confirmation_repository,
        webapp_base_url="https://app.example.com",
        post_decision_dispatcher=ConfirmationPostDecisionDispatcher(
            task_repository,
            now_provider=lambda: now,
        ),
        now_provider=lambda: now,
    )
    context = RoutingContext(
        tenant_id="tenant-position-worker",
        channel_binding_id="binding-position-worker",
        openclaw_account_id="bot-position-worker",
        target_conversation="conversation-position-worker",
    )
    pending = classify_image_text_candidate(
        "持仓 数量 成本\nAAPL 苹果 10 180.25\nNVDA 英伟达 2 900",
        ocr_confidence=0.91,
        media_id="media-position-worker",
    )
    assert pending is not None
    created = await service.create_pending_confirmation(context, pending)
    await service.submit_decision(context, parse_confirmation_command(f"确认 {created.session_token}"))

    outbox_repository = InMemoryOutboxRepository()
    outbox_service = DeliveryOutboxService(outbox_repository, now_provider=lambda: now)
    worker_repository = InMemoryPostConfirmationWorkerRepository(
        jobs=task_repository.tasks,
        pending_actions=confirmation_repository.pending_actions,
        confirmation_events=confirmation_repository.events,
    )
    worker = PostConfirmationJobWorker(
        worker_repository,
        receipt_outbox=outbox_service,
        now_provider=lambda: now,
    )

    stats = await worker.process_once()
    ready = await outbox_repository.list_retry_ready(now, limit=10)

    assert stats.succeeded == 1
    assert stats.receipts_queued == 1
    assert next(iter(task_repository.tasks.values()))["job_type"] == "confirmed_position_snapshot_import"
    assert confirmation_repository.pending_actions[created.pending_action_id]["status"] == "committed"
    assert len(worker_repository.trade_events) == 0
    assert len(worker_repository.position_snapshots) == 2
    aapl = worker_repository.position_snapshots[("tenant-position-worker", "AAPL", "2026-05-10")]
    assert aapl["total_quantity"] == 10
    assert aapl["average_cost"] == 180.25
    assert aapl["total_cost"] == 1802.5
    assert aapl["source_type"] == "ocr"
    assert aapl["source_tier"] == "user_confirmed"
    assert aapl["source_actionability"] == "analysis_only"
    assert aapl["source_lineage"]["fact_write_allowed"] is True
    assert aapl["source_lineage"]["trade_action_allowed"] is False
    assert ready[0]["content"]["title"] == "持仓截图已写入"
    assert "不会自动下单" in ready[0]["content"]["text"]


@pytest.mark.asyncio
async def test_full_confirmation_flow_queues_and_delivers_trade_receipt() -> None:
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc)
    confirmation_repository = InMemoryConfirmationRepository()
    task_repository = InMemoryPostConfirmationTaskRepository()
    service = ConfirmationCenterService(
        confirmation_repository,
        webapp_base_url="https://app.example.com",
        post_decision_dispatcher=ConfirmationPostDecisionDispatcher(
            task_repository,
            now_provider=lambda: now,
        ),
        now_provider=lambda: now,
    )
    context = RoutingContext(
        tenant_id="tenant-full-flow",
        channel_binding_id="binding-full-flow",
        openclaw_account_id="bot-full-flow",
        target_conversation="conversation-full-flow",
    )
    pending = classify_high_attention_text(
        "买入 AAPL 10 股 180",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    assert pending is not None
    created = await service.create_pending_confirmation(context, pending)
    decision = await service.submit_decision(context, parse_confirmation_command(f"确认 {created.session_token}"))
    assert decision.status == "committing"

    outbox_repository = InMemoryOutboxRepository()
    outbox_service = DeliveryOutboxService(outbox_repository, now_provider=lambda: now)
    worker_repository = InMemoryPostConfirmationWorkerRepository(
        jobs=task_repository.tasks,
        pending_actions=confirmation_repository.pending_actions,
        confirmation_events=confirmation_repository.events,
    )
    post_worker = PostConfirmationJobWorker(
        worker_repository,
        receipt_outbox=outbox_service,
        now_provider=lambda: now,
    )

    post_stats = await post_worker.process_once()
    ready = await outbox_repository.list_retry_ready(now, limit=10)

    assert post_stats.succeeded == 1
    assert post_stats.receipts_queued == 1
    assert len(ready) == 1
    assert ready[0]["content_type"] == "task_update"
    assert ready[0]["content"]["title"] == "交易已记录"
    assert "不会自动下单" in ready[0]["content"]["text"]

    sender = RecordingSender()
    outbox_worker = DeliveryOutboxWorker(outbox_service, sender, now_provider=lambda: now)
    delivery_stats = await outbox_worker.process_ready()

    assert delivery_stats.delivered == 1
    assert sender.sent[0]["target_conversation"] == "conversation-full-flow"
    assert sender.sent[0]["content"]["status"] == "completed"


@pytest.mark.asyncio
async def test_worker_finalizes_sell_put_as_artifact_without_order_execution() -> None:
    confirmation_repository = InMemoryConfirmationRepository()
    task_repository = InMemoryPostConfirmationTaskRepository()
    service = ConfirmationCenterService(
        confirmation_repository,
        webapp_base_url="https://app.example.com",
        post_decision_dispatcher=ConfirmationPostDecisionDispatcher(task_repository),
    )
    context = RoutingContext(
        tenant_id="tenant-sellput-worker",
        channel_binding_id="binding-sellput-worker",
        openclaw_account_id="bot-sellput-worker",
    )
    pending = classify_high_attention_text(
        "生成 NVDA Sell Put 草稿，30 delta，45 DTE",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    assert pending is not None
    created = await service.create_pending_confirmation(context, pending)
    await service.submit_decision(context, parse_confirmation_command(f"确认 {created.session_token}"))

    worker_repository = InMemoryPostConfirmationWorkerRepository(
        jobs=task_repository.tasks,
        pending_actions=confirmation_repository.pending_actions,
        confirmation_events=confirmation_repository.events,
    )
    worker = PostConfirmationJobWorker(worker_repository)

    stats = await worker.process_once()

    assert stats.succeeded == 1
    assert confirmation_repository.pending_actions[created.pending_action_id]["status"] == "committed"
    artifact = next(iter(worker_repository.artifacts.values()))
    assert artifact["artifact_type"] == "sell_put_trade_draft"
    assert artifact["artifact_metadata"]["requires_manual_order"] is True
    assert artifact["artifact_metadata"]["draft_only"] is True
    assert artifact["artifact_metadata"]["human_confirm_required"] is True
    assert artifact["artifact_metadata"]["auto_order_allowed"] is False
    assert "never places an order" in artifact["artifact_metadata"]["execution_note"]


@pytest.mark.asyncio
async def test_worker_records_rebuild_request_without_marking_pending_committed() -> None:
    confirmation_repository = InMemoryConfirmationRepository()
    task_repository = InMemoryPostConfirmationTaskRepository()
    service = ConfirmationCenterService(
        confirmation_repository,
        webapp_base_url="https://app.example.com",
        post_decision_dispatcher=ConfirmationPostDecisionDispatcher(task_repository),
    )
    context = RoutingContext(
        tenant_id="tenant-rebuild-worker",
        channel_binding_id="binding-rebuild-worker",
        openclaw_account_id="bot-rebuild-worker",
    )
    pending = classify_high_attention_text(
        "买入 AAPL 10 股 180",
        source_type="message_trade_input",
        source_surface="wechat",
    )
    assert pending is not None
    created = await service.create_pending_confirmation(context, pending)
    await service.submit_decision(
        context,
        parse_confirmation_command(f"修改 {created.session_token} 改成买入 AAPL 5 股 180"),
    )

    worker_repository = InMemoryPostConfirmationWorkerRepository(
        jobs=task_repository.tasks,
        pending_actions=confirmation_repository.pending_actions,
        confirmation_events=confirmation_repository.events,
    )
    worker = PostConfirmationJobWorker(worker_repository)

    stats = await worker.process_once()

    assert stats.succeeded == 1
    assert confirmation_repository.pending_actions[created.pending_action_id]["status"] == "revoked"
    artifact = next(iter(worker_repository.artifacts.values()))
    assert artifact["artifact_type"] == "confirmation_rebuild_request"
    assert artifact["artifact_metadata"]["revision_text"] == "改成买入 AAPL 5 股 180"


@pytest.mark.asyncio
async def test_worker_marks_trade_job_retryable_when_payload_is_not_parseable() -> None:
    job_id = "job-invalid"
    pending_action_id = "pending-invalid"
    jobs = {
        job_id: {
            "id": job_id,
            "tenant_id": "tenant-invalid",
            "job_type": "confirmed_trade_recalculate_holdings",
            "status": "PENDING",
            "config": {
                "dedupe_key": "confirmation:invalid",
                "post_decision": "commit_or_recalculate",
                "pending_action": {
                    "id": pending_action_id,
                    "action_payload": {"normalized_text": "只是一句无法解析的话"},
                    "normalized_summary": {},
                    "source_type": "message_trade_input",
                },
                "confirmation": {"session_id": "session-invalid"},
            },
        }
    }
    pending_actions = {pending_action_id: {"id": pending_action_id, "status": "committing"}}
    events: list[dict] = []
    repository = InMemoryPostConfirmationWorkerRepository(
        jobs=jobs,
        pending_actions=pending_actions,
        confirmation_events=events,
    )
    worker = PostConfirmationJobWorker(repository)

    stats = await worker.process_once()

    assert stats.failed == 1
    assert jobs[job_id]["status"] == "FAILED"
    assert pending_actions[pending_action_id]["status"] == "failed_retryable"
    assert events[-1]["event_type"] == "commit_failed"


@pytest.mark.asyncio
async def test_worker_queues_failure_receipt_for_retryable_processing_error() -> None:
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc)
    job_id = "job-invalid-receipt"
    pending_action_id = "pending-invalid-receipt"
    jobs = {
        job_id: {
            "id": job_id,
            "tenant_id": "tenant-invalid-receipt",
            "job_type": "confirmed_trade_recalculate_holdings",
            "status": "PENDING",
            "config": {
                "dedupe_key": "confirmation:invalid-receipt",
                "post_decision": "commit_or_recalculate",
                "pending_action": {
                    "id": pending_action_id,
                    "action_payload": {"normalized_text": "只是一句无法解析的话"},
                    "normalized_summary": {},
                    "source_type": "message_trade_input",
                },
                "confirmation": {
                    "session_id": "session-invalid-receipt",
                    "channel_binding_id": "binding-invalid-receipt",
                },
                "routing": {
                    "tenant_id": "tenant-invalid-receipt",
                    "channel_binding_id": "binding-invalid-receipt",
                    "openclaw_account_id": "bot-invalid-receipt",
                },
            },
        }
    }
    pending_actions = {pending_action_id: {"id": pending_action_id, "status": "committing"}}
    events: list[dict] = []
    outbox_repository = InMemoryOutboxRepository()
    outbox_service = DeliveryOutboxService(outbox_repository, now_provider=lambda: now)
    repository = InMemoryPostConfirmationWorkerRepository(
        jobs=jobs,
        pending_actions=pending_actions,
        confirmation_events=events,
    )
    worker = PostConfirmationJobWorker(
        repository,
        receipt_outbox=outbox_service,
        now_provider=lambda: now,
    )

    stats = await worker.process_once()
    ready = await outbox_repository.list_retry_ready(now, limit=10)

    assert stats.failed == 1
    assert stats.receipts_queued == 1
    assert ready[0]["content"]["title"] == "处理暂时失败"
    assert ready[0]["content"]["status"] == "failed_retryable"
    assert "没有改动持仓" in ready[0]["content"]["text"]
    assert "没有下单" in ready[0]["content"]["text"]
    assert "WebApp 确认中心" in ready[0]["content"]["text"]


@pytest.mark.asyncio
async def test_worker_rejects_trade_processing_without_confirmation_guard() -> None:
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc)
    job_id = "job-missing-guard"
    pending_action_id = "pending-missing-guard"
    jobs = {
        job_id: {
            "id": job_id,
            "tenant_id": "tenant-missing-guard",
            "job_type": "confirmed_trade_recalculate_holdings",
            "status": "PENDING",
            "config": {
                "dedupe_key": "confirmation:missing-guard",
                "post_decision": "commit_or_recalculate",
                "decision_command": {"action": "confirm"},
                "pending_action": {
                    "id": pending_action_id,
                    "action_payload": {"normalized_text": "买入 AAPL 10 股 180"},
                    "normalized_summary": {},
                    "source_type": "message_trade_input",
                },
                "confirmation": {"session_id": "session-missing-guard"},
                "routing": {
                    "tenant_id": "tenant-missing-guard",
                    "channel_binding_id": "binding-missing-guard",
                    "openclaw_account_id": "bot-missing-guard",
                },
            },
        }
    }
    pending_actions = {pending_action_id: {"id": pending_action_id, "status": "committing"}}
    repository = InMemoryPostConfirmationWorkerRepository(
        jobs=jobs,
        pending_actions=pending_actions,
        confirmation_events=[],
    )
    worker = PostConfirmationJobWorker(repository, now_provider=lambda: now)

    stats = await worker.process_once()

    assert stats.failed == 1
    assert jobs[job_id]["status"] == "FAILED"
    assert pending_actions[pending_action_id]["status"] == "failed_retryable"
    assert repository.trade_events == []
    assert repository.confirmation_events[-1]["event_type"] == "commit_failed"
