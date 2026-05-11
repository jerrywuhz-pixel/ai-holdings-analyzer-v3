"""
Tests for DeliveryManager — 推送投递可靠性管理器

测试 DeliveryManager 各方法的正确行为，包括：
- 创建 delivery（字段校验、幂等性）
- 状态流转（mark_sent / mark_delivered / mark_failed / mark_abandoned）
- mark_failed 的不同失败类型（default / delivery_error / timeout）
- 查询方法（get_pending_retries / get_abandonable_deliveries）
- _generate_idempotency_key 确定性
"""
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

# Add project root to sys.path for openclaw imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Mock supabase before importing openclaw modules that depend on it
if "supabase" not in sys.modules:
    _mock_supabase = MagicMock()
    _mock_supabase.Client = MagicMock
    _mock_supabase.create_client = MagicMock()
    sys.modules["supabase"] = _mock_supabase

from openclaw.gateway.delivery_manager import (
    DeliveryManager,
    DeliveryValidationError,
    _generate_idempotency_key,
)


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def mock_client():
    """Create a fresh mock Supabase client for each test."""
    return MagicMock()


@pytest.fixture
def delivery_manager(mock_client):
    """Create a DeliveryManager with mock client."""
    return DeliveryManager(client=mock_client)


# ------------------------------------------------------------------ #
# create_delivery — success & validation
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_create_delivery_success(delivery_manager, mock_client):
    """create_delivery with all required fields inserts record and returns delivery_id."""
    mock_execute = MagicMock(return_value=MagicMock(data=[{"id": "delivery-uuid"}]))
    mock_client.table.return_value.insert.return_value.execute = mock_execute

    result = await delivery_manager.create_delivery(
        job_run_id="job-uuid",
        tenant_id="tenant-123",
        channel="wechat_claw",
        content={"text": "今日复盘报告", "delivery_key": "dk-001"},
        context_token="ctx-token-abc",
        target_conversation="conv-xyz",
    )

    assert result == "delivery-uuid"
    insert_call = mock_client.table.return_value.insert.call_args
    payload = insert_call[0][0]
    assert payload["status"] == "PENDING"
    assert payload["job_run_id"] == "job-uuid"
    assert payload["tenant_id"] == "tenant-123"
    assert payload["channel"] == "wechat_claw"
    assert payload["context_token"] == "ctx-token-abc"
    assert payload["target_conversation"] == "conv-xyz"
    assert payload["delivery_key"] == "dk-001"
    assert "idempotency_key" in payload


@pytest.mark.asyncio
async def test_create_delivery_missing_context_token(delivery_manager):
    """create_delivery raises DeliveryValidationError when context_token is missing."""
    with pytest.raises(DeliveryValidationError, match="context_token"):
        await delivery_manager.create_delivery(
            job_run_id="job-uuid",
            tenant_id="tenant-123",
            channel="wechat_claw",
            content={"delivery_key": "dk-001"},
            context_token=None,
            target_conversation="conv-xyz",
        )


@pytest.mark.asyncio
async def test_create_delivery_missing_target_conversation(delivery_manager):
    """create_delivery raises DeliveryValidationError when target_conversation is missing."""
    with pytest.raises(DeliveryValidationError, match="target_conversation"):
        await delivery_manager.create_delivery(
            job_run_id="job-uuid",
            tenant_id="tenant-123",
            channel="wechat_claw",
            content={"delivery_key": "dk-001"},
            context_token="ctx-token",
            target_conversation=None,
        )


@pytest.mark.asyncio
async def test_create_delivery_missing_content(delivery_manager):
    """create_delivery raises DeliveryValidationError when content is empty."""
    with pytest.raises(DeliveryValidationError, match="content"):
        await delivery_manager.create_delivery(
            job_run_id="job-uuid",
            tenant_id="tenant-123",
            channel="wechat_claw",
            content={},
            context_token="ctx-token",
            target_conversation="conv-xyz",
        )


@pytest.mark.asyncio
async def test_create_delivery_missing_delivery_key(delivery_manager):
    """create_delivery raises DeliveryValidationError when content has no delivery_key or analysis_id."""
    with pytest.raises(DeliveryValidationError, match="delivery_key"):
        await delivery_manager.create_delivery(
            job_run_id="job-uuid",
            tenant_id="tenant-123",
            channel="wechat_claw",
            content={"text": "report"},  # no delivery_key, no analysis_id
            context_token="ctx-token",
            target_conversation="conv-xyz",
        )


# ------------------------------------------------------------------ #
# create_delivery — idempotency
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_create_delivery_idempotency(delivery_manager, mock_client):
    """Duplicate insert with 'unique' in error returns existing record id."""
    # insert raises constraint violation
    mock_client.table.return_value.insert.return_value.execute.side_effect = Exception(
        "duplicate key value violates unique constraint"
    )
    # _find_by_idempotency_key select chain returns existing record
    mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute = MagicMock(
        return_value=MagicMock(data=[{"id": "existing-id", "status": "PENDING"}])
    )

    result = await delivery_manager.create_delivery(
        job_run_id="job-uuid",
        tenant_id="tenant-123",
        channel="wechat_claw",
        content={"delivery_key": "dk-001"},
        context_token="ctx-token",
        target_conversation="conv-xyz",
    )

    assert result == "existing-id"


# ------------------------------------------------------------------ #
# mark_sent
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_mark_sent(delivery_manager, mock_client):
    """mark_sent sets status=SENT and sent_at."""
    mock_client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

    await delivery_manager.mark_sent("delivery-123")

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["status"] == "SENT"
    assert "sent_at" in payload


# ------------------------------------------------------------------ #
# mark_delivered
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_mark_delivered(delivery_manager, mock_client):
    """mark_delivered sets status=DELIVERED."""
    mock_client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

    await delivery_manager.mark_delivered("delivery-456")

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["status"] == "DELIVERED"


# ------------------------------------------------------------------ #
# mark_failed — different failure types
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_mark_failed_default(delivery_manager, mock_client):
    """mark_failed with default params sets status=FAILED and increments retry_count."""
    # Mock select chain: returns retry_count=1
    mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute = MagicMock(
        return_value=MagicMock(data=[{"retry_count": 1}])
    )
    # Mock update chain
    mock_client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

    await delivery_manager.mark_failed("delivery-789", "push failed")

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["status"] == "FAILED"
    assert payload["retry_count"] == 2  # 1 + 1
    assert payload["error_message"] == "push failed"


@pytest.mark.asyncio
async def test_mark_failed_delivery_error(delivery_manager, mock_client):
    """mark_failed with is_delivery_error=True sets status=DELIVERY_FAILED."""
    mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute = MagicMock(
        return_value=MagicMock(data=[{"retry_count": 0}])
    )
    mock_client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

    await delivery_manager.mark_failed("delivery-err", "channel error", is_delivery_error=True)

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["status"] == "DELIVERY_FAILED"
    assert payload["retry_count"] == 1


@pytest.mark.asyncio
async def test_mark_failed_timeout(delivery_manager, mock_client):
    """mark_failed with is_timeout=True sets status=DELIVERY_TIMEOUT."""
    mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute = MagicMock(
        return_value=MagicMock(data=[{"retry_count": 0}])
    )
    mock_client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

    await delivery_manager.mark_failed("delivery-timeout", "timed out", is_timeout=True)

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["status"] == "DELIVERY_TIMEOUT"
    assert payload["retry_count"] == 1


# ------------------------------------------------------------------ #
# mark_abandoned
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_mark_abandoned(delivery_manager, mock_client):
    """mark_abandoned sets status=ABANDONED."""
    mock_client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

    await delivery_manager.mark_abandoned("delivery-abandon")

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["status"] == "ABANDONED"
    assert payload["error_message"] == "Delivery abandoned after max retries"


# ------------------------------------------------------------------ #
# get_pending_retries
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_get_pending_retries(delivery_manager, mock_client):
    """get_pending_retries returns list of retryable failed deliveries."""
    retry_list = [
        {"id": "d1", "status": "FAILED", "retry_count": 1},
        {"id": "d2", "status": "DELIVERY_FAILED", "retry_count": 2},
    ]
    mock_client.table.return_value.select.return_value.in_.return_value.lt.return_value.order.return_value.limit.return_value.execute = MagicMock(
        return_value=MagicMock(data=retry_list)
    )

    result = await delivery_manager.get_pending_retries(limit=50)

    assert len(result) == 2
    assert result[0]["id"] == "d1"
    assert result[1]["id"] == "d2"


# ------------------------------------------------------------------ #
# get_abandonable_deliveries
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_get_abandonable_deliveries(delivery_manager, mock_client):
    """get_abandonable_deliveries returns list of deliveries past max retries."""
    abandonable = [
        {"id": "d3", "status": "FAILED", "retry_count": 3},
    ]
    mock_client.table.return_value.select.return_value.in_.return_value.gte.return_value.execute = MagicMock(
        return_value=MagicMock(data=abandonable)
    )

    result = await delivery_manager.get_abandonable_deliveries()

    assert len(result) == 1
    assert result[0]["id"] == "d3"


# ------------------------------------------------------------------ #
# _generate_idempotency_key
# ------------------------------------------------------------------ #


def test_generate_idempotency_key_deterministic():
    """Same inputs always produce the same idempotency key."""
    key1 = _generate_idempotency_key("tenant-abc", "dk-001")
    key2 = _generate_idempotency_key("tenant-abc", "dk-001")
    assert key1 == key2


def test_generate_idempotency_key_different_inputs():
    """Different inputs produce different idempotency keys."""
    key1 = _generate_idempotency_key("tenant-abc", "dk-001")
    key2 = _generate_idempotency_key("tenant-xyz", "dk-001")
    key3 = _generate_idempotency_key("tenant-abc", "dk-002")
    assert key1 != key2
    assert key1 != key3
    assert key2 != key3
