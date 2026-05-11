"""
QuotaService 单元测试

覆盖配额检查、用量记录、用量汇总及内部降级逻辑。
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from services.quota import QuotaService, QuotaResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def quota_no_client():
    """无 Supabase 客户端的 QuotaService 实例（降级到内置常量）。"""
    svc = QuotaService(supabase_client=None)
    # 确保 _ensure_client 也拿不到客户端
    with patch.object(svc, "_ensure_client", return_value=None):
        yield svc


@pytest.fixture
def quota_with_mock_client():
    """有 mock Supabase 客户端的 QuotaService 实例。"""
    mock_client = MagicMock()
    svc = QuotaService(supabase_client=mock_client)
    return svc, mock_client


# ---------------------------------------------------------------------------
# Supabase 查询链辅助工具
# ---------------------------------------------------------------------------


def _build_chain(final_data):
    """
    构建 mock Supabase 查询链：
        client.table(...).select(...).eq(...).maybe_single().execute() → {data: ...}
    """
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.gt.return_value = chain
    chain.order.return_value = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = MagicMock(data=final_data)
    return chain


# ---------------------------------------------------------------------------
# check_quota
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_quota_free_plan_allowed(quota_no_client):
    """free plan + daily_ai_calls 用量 < 限制 → allowed=True。"""
    svc = quota_no_client

    # free plan 的 daily_ai_calls 限制为 10，用量为 5
    with patch.object(svc, "_get_plan", new_callable=AsyncMock, return_value="free"):
        with patch.object(svc, "_get_usage_count", new_callable=AsyncMock, return_value=5):
            with patch.object(svc, "_get_addon_remaining", new_callable=AsyncMock, return_value=0):
                result = await svc.check_quota("tenant-1", "daily_ai_calls")

    assert isinstance(result, QuotaResult)
    assert result.allowed is True
    assert result.plan == "free"
    assert result.action == "daily_ai_calls"
    assert result.used == 5
    assert result.limit == 10
    assert result.remaining == 5
    assert result.message == ""


@pytest.mark.asyncio
async def test_check_quota_free_plan_exceeded(quota_no_client):
    """free plan + daily_ai_calls 用量 >= 限制 → allowed=False，message 非空。"""
    svc = quota_no_client

    with patch.object(svc, "_get_plan", new_callable=AsyncMock, return_value="free"):
        with patch.object(svc, "_get_usage_count", new_callable=AsyncMock, return_value=10):
            with patch.object(svc, "_get_addon_remaining", new_callable=AsyncMock, return_value=0):
                result = await svc.check_quota("tenant-1", "daily_ai_calls")

    assert result.allowed is False
    assert result.plan == "free"
    assert result.used == 10
    assert result.limit == 10
    assert result.remaining == 0
    assert "Quota exceeded" in result.message
    assert "daily_ai_calls" in result.message


@pytest.mark.asyncio
async def test_check_quota_with_addon_remaining():
    """即使基础配额已用完，addon 额度仍有剩余 → allowed=True。"""
    svc = QuotaService(supabase_client=None)

    with patch.object(svc, "_ensure_client", return_value=None):
        with patch.object(svc, "_get_plan", new_callable=AsyncMock, return_value="free"):
            with patch.object(svc, "_get_usage_count", new_callable=AsyncMock, return_value=12):
                with patch.object(
                    svc, "_get_addon_remaining", new_callable=AsyncMock, return_value=5
                ):
                    result = await svc.check_quota("tenant-1", "daily_ai_calls")

    # free plan limit=10 + addon=5 = effective_limit=15, used=12 < 15 → allowed
    assert result.allowed is True
    assert result.limit == 10
    assert result.remaining == 3  # 15 - 12 = 3


# ---------------------------------------------------------------------------
# record_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_usage_no_client_silent():
    """无 Supabase 客户端时 record_usage 静默跳过，不抛异常。"""
    svc = QuotaService(supabase_client=None)

    with patch.object(svc, "_ensure_client", return_value=None):
        # 应正常返回，不抛异常
        await svc.record_usage("tenant-1", "daily_ai_calls", quantity=1)


@pytest.mark.asyncio
async def test_record_usage_inserts_usage_record():
    """有 Supabase 客户端时，验证 usage_records 表的 insert 调用。"""
    mock_client = MagicMock()
    svc = QuotaService(supabase_client=mock_client)

    # 构建 insert 链
    insert_chain = MagicMock()
    mock_client.table.return_value = insert_chain
    insert_chain.insert.return_value = insert_chain
    insert_chain.update.return_value = insert_chain
    insert_chain.select.return_value = insert_chain
    insert_chain.eq.return_value = insert_chain
    insert_chain.maybe_single.return_value = insert_chain

    # execute 对于不同的调用返回不同结果
    # 1. usage_records insert
    # 2. quota_tracking select (检查是否存在)
    # 3. quota_tracking insert/update
    # 4. user_addon_packs select + update
    insert_chain.execute.side_effect = [
        MagicMock(data=None),           # usage_records insert
        MagicMock(data=None),           # quota_tracking select (不存在)
        MagicMock(data=None),           # quota_tracking insert
        MagicMock(data=[]),             # user_addon_packs select (无 addon)
    ]

    await svc.record_usage("tenant-1", "daily_ai_calls", quantity=2, metadata={"source": "test"})

    # 验证 table("usage_records").insert() 被调用，且 payload 包含正确字段
    first_call_args = mock_client.table.call_args_list
    assert any(call[0][0] == "usage_records" for call in first_call_args)

    # 找到 usage_records 的 insert 调用
    insert_calls = insert_chain.insert.call_args_list
    assert len(insert_calls) >= 1
    # 第一条 insert 应该是 usage_records 的
    insert_payload = insert_calls[0][0][0]
    assert insert_payload["tenant_id"] == "tenant-1"
    assert insert_payload["action"] == "daily_ai_calls"
    assert insert_payload["quantity"] == 2
    assert insert_payload["metadata"] == {"source": "test"}


# ---------------------------------------------------------------------------
# get_usage_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_usage_summary_no_client():
    """无 Supabase 客户端时返回 free plan 汇总，所有 action 的 used=0。"""
    svc = QuotaService(supabase_client=None)

    with patch.object(svc, "_ensure_client", return_value=None):
        summary = await svc.get_usage_summary("tenant-1")

    assert summary["plan"] == "free"
    assert summary["subscription_status"] == "active"
    assert "actions" in summary

    # 验证所有 7 个 action 都存在
    expected_actions = [
        "daily_ai_calls", "max_positions", "max_trades",
        "data_sources", "push_notifications", "watchlist", "webapp",
    ]
    for action in expected_actions:
        assert action in summary["actions"]
        assert summary["actions"][action]["used"] == 0
        assert summary["actions"][action]["addon_remaining"] == 0
        # limit 应来自内置常量
        from services.quota import _PLAN_LIMITS_FALLBACK
        assert summary["actions"][action]["limit"] == _PLAN_LIMITS_FALLBACK["free"][action]


# ---------------------------------------------------------------------------
# _get_plan 降级逻辑
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_plan_from_subscriptions():
    """Supabase subscriptions 表返回 active pro 订阅 → 返回 'pro'。"""
    mock_client = MagicMock()
    svc = QuotaService(supabase_client=mock_client)

    chain = _build_chain({"plan": "pro", "status": "active"})
    mock_client.table.return_value = chain

    result = await svc._get_plan("tenant-1")

    assert result == "pro"
    mock_client.table.assert_called_with("subscriptions")


@pytest.mark.asyncio
async def test_get_plan_fallback_to_users():
    """subscriptions 查询失败，降级到 users 表获取 plan。"""
    mock_client = MagicMock()
    svc = QuotaService(supabase_client=mock_client)

    # subscriptions 查询链：抛异常
    sub_chain = MagicMock()
    sub_chain.select.return_value = sub_chain
    sub_chain.eq.return_value = sub_chain
    sub_chain.maybe_single.return_value = sub_chain
    sub_chain.execute.side_effect = Exception("subscriptions table error")

    # users 查询链：正常返回
    users_chain = MagicMock()
    users_chain.select.return_value = users_chain
    users_chain.eq.return_value = users_chain
    users_chain.maybe_single.return_value = users_chain
    users_chain.execute.return_value = MagicMock(data={"plan": "basic"})

    mock_client.table.side_effect = [sub_chain, users_chain]

    result = await svc._get_plan("tenant-1")

    assert result == "basic"


@pytest.mark.asyncio
async def test_get_plan_default_free():
    """subscriptions 和 users 查询都失败 → 返回默认 'free'。"""
    mock_client = MagicMock()
    svc = QuotaService(supabase_client=mock_client)

    # 两次查询都抛异常
    error_chain = MagicMock()
    error_chain.select.return_value = error_chain
    error_chain.eq.return_value = error_chain
    error_chain.maybe_single.return_value = error_chain
    error_chain.execute.side_effect = Exception("db error")

    mock_client.table.return_value = error_chain

    result = await svc._get_plan("tenant-1")

    assert result == "free"
