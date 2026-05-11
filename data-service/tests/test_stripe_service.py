"""
StripeService 单元测试

覆盖 Stripe SDK 不可用时的 RuntimeError 以及 mock SDK 可用时的正常路径。
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from services.stripe_service import StripeService


# ---------------------------------------------------------------------------
# SDK 不可用时的 RuntimeError 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unavailable_without_sdk():
    """_HAS_STRIPE=False 时 create_checkout_session 抛出 RuntimeError。"""
    svc = StripeService()
    with pytest.raises(RuntimeError, match="stripe SDK not installed"):
        await svc.create_checkout_session(
            tenant_id="t1",
            price_id="price_123",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )


@pytest.mark.asyncio
async def test_addon_session_unavailable():
    """_HAS_STRIPE=False 时 create_addon_session 抛出 RuntimeError。"""
    svc = StripeService()
    with pytest.raises(RuntimeError, match="stripe SDK not installed"):
        await svc.create_addon_session(
            tenant_id="t1",
            pack_name="ai_analysis_pack",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )


@pytest.mark.asyncio
async def test_webhook_unavailable():
    """_HAS_STRIPE=False 时 handle_webhook 抛出 RuntimeError。"""
    svc = StripeService()
    with pytest.raises(RuntimeError, match="stripe SDK not installed"):
        await svc.handle_webhook(
            payload=b'{"type": "test"}',
            sig_header="sig_header_value",
        )


@pytest.mark.asyncio
async def test_portal_unavailable():
    """_HAS_STRIPE=False 时 create_customer_portal_session 抛出 RuntimeError。"""
    svc = StripeService()
    with pytest.raises(RuntimeError, match="stripe SDK not installed"):
        await svc.create_customer_portal_session(
            tenant_id="t1",
            return_url="https://example.com/return",
        )


# ---------------------------------------------------------------------------
# SDK 可用 + mock stripe 模块
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_available_with_mock():
    """patch _HAS_STRIPE=True + mock stripe 模块 → 正常返回 session_id 和 url。"""
    mock_stripe = MagicMock()

    # mock checkout.Session.create 返回值
    mock_session = MagicMock()
    mock_session.id = "cs_test_123"
    mock_session.url = "https://checkout.stripe.com/test"
    mock_stripe.checkout.Session.create.return_value = mock_session

    with patch("services.stripe_service._HAS_STRIPE", True), \
         patch("services.stripe_service.stripe", mock_stripe, create=True), \
         patch.dict("os.environ", {"STRIPE_SECRET_KEY": "sk_test_123"}), \
         patch.object(StripeService, "_get_or_create_customer", new_callable=AsyncMock, return_value="cus_test_456"):

        svc = StripeService()
        result = await svc.create_checkout_session(
            tenant_id="t1",
            price_id="price_abc",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

    assert result["session_id"] == "cs_test_123"
    assert result["url"] == "https://checkout.stripe.com/test"

    # 验证 stripe.checkout.Session.create 被正确调用
    mock_stripe.checkout.Session.create.assert_called_once_with(
        mode="subscription",
        customer="cus_test_456",
        line_items=[{"price": "price_abc", "quantity": 1}],
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel",
        metadata={"tenant_id": "t1"},
    )


@pytest.mark.asyncio
async def test_checkout_no_api_key():
    """_HAS_STRIPE=True 但无 STRIPE_SECRET_KEY 环境变量 → RuntimeError。"""
    mock_stripe = MagicMock()

    with patch("services.stripe_service._HAS_STRIPE", True), \
         patch("services.stripe_service.stripe", mock_stripe, create=True), \
         patch.dict("os.environ", {}, clear=False):

        # 移除 STRIPE_SECRET_KEY（如果存在）
        import os
        key = "STRIPE_SECRET_KEY"
        original = os.environ.pop(key, None)
        try:
            svc = StripeService()
            with pytest.raises(RuntimeError, match="stripe API key not configured"):
                await svc.create_checkout_session(
                    tenant_id="t1",
                    price_id="price_abc",
                    success_url="https://example.com/success",
                    cancel_url="https://example.com/cancel",
                )
        finally:
            if original is not None:
                os.environ[key] = original
