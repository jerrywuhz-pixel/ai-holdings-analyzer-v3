"""
Billing Router 单元测试

覆盖 Stripe Checkout、用量包、Webhook、配额检查和用量记录等端点。
"""

import httpx
import pytest
from fastapi import FastAPI
from unittest.mock import AsyncMock, patch

import routers.billing as billing_module
from routers.billing import router as billing_router
from services.quota import QuotaResult


# ---------------------------------------------------------------------------
# 测试应用
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """创建包含 billing router 的 FastAPI 测试应用。"""
    _app = FastAPI()
    _app.include_router(billing_router, prefix="/api")
    return _app


@pytest.fixture
def client(app):
    """创建 httpx AsyncClient。"""
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def mock_bearer_auth(monkeypatch):
    """默认将 Bearer token 解析为固定租户，避免依赖真实 Supabase。"""

    async def _fake_authenticate(token: str) -> str:
        if token == "test-token":
            return "t1"
        if token == "tenant-2-token":
            return "t2"
        raise billing_module._auth_http_exception(401, "Invalid or expired bearer token")

    monkeypatch.setattr(billing_module, "_authenticate_bearer_token", _fake_authenticate)


def auth_headers(token: str = "test-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# POST /api/billing/checkout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_stripe_unavailable(client):
    """Stripe SDK 不可用时 POST /billing/checkout → 503。"""
    with patch(
        "routers.billing._stripe_service.create_checkout_session",
        new_callable=AsyncMock,
        side_effect=RuntimeError("stripe SDK not installed"),
    ):
        response = await client.post(
            "/api/billing/checkout",
            json={
                "tenant_id": "t1",
                "price_id": "price_abc",
                "success_url": "https://example.com/success",
                "cancel_url": "https://example.com/cancel",
            },
            headers=auth_headers(),
        )

    assert response.status_code == 503
    data = response.json()
    assert data["detail"]["ok"] is False
    assert "stripe SDK not installed" in data["detail"]["message"]


@pytest.mark.asyncio
async def test_checkout_rejects_body_tenant_mismatch(client):
    """认证租户与 body tenant_id 不一致时拒绝请求。"""
    with patch(
        "routers.billing._stripe_service.create_checkout_session",
        new_callable=AsyncMock,
    ) as mock_checkout:
        response = await client.post(
            "/api/billing/checkout",
            json={
                "tenant_id": "other-tenant",
                "price_id": "price_abc",
                "success_url": "https://example.com/success",
                "cancel_url": "https://example.com/cancel",
            },
            headers=auth_headers(),
        )

    assert response.status_code == 403
    data = response.json()
    assert data["detail"]["ok"] is False
    assert "tenant_id does not match authenticated user" in data["detail"]["message"]
    mock_checkout.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /api/billing/addon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_addon_pack_not_found(client):
    """用量包不存在时 POST /billing/addon → 400 ValueError。"""
    with patch(
        "routers.billing._stripe_service.create_addon_session",
        new_callable=AsyncMock,
        side_effect=ValueError("Addon pack 'nonexistent_pack' not found or has no Stripe Price ID"),
    ):
        response = await client.post(
            "/api/billing/addon",
            json={
                "tenant_id": "t1",
                "pack_name": "nonexistent_pack",
                "success_url": "https://example.com/success",
                "cancel_url": "https://example.com/cancel",
            },
            headers=auth_headers(),
        )

    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["ok"] is False
    assert "not found" in data["detail"]["message"]


# ---------------------------------------------------------------------------
# POST /api/billing/webhook/stripe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_missing_signature(client):
    """无 Stripe-Signature 头时 POST /billing/webhook/stripe → 400。"""
    response = await client.post(
        "/api/billing/webhook/stripe",
        content=b'{"type": "checkout.session.completed"}',
        headers={},
    )

    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["ok"] is False
    assert "Missing Stripe-Signature" in data["detail"]["message"]


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quota_check_requires_authorization_header(client):
    """非 webhook 端点缺少 Authorization 头时返回 401。"""
    response = await client.post(
        "/api/billing/quota/check",
        json={
            "tenant_id": "t1",
            "action": "daily_ai_calls",
        },
    )

    assert response.status_code == 401
    data = response.json()
    assert data["detail"]["ok"] is False
    assert "Missing Authorization header" in data["detail"]["message"]


@pytest.mark.asyncio
async def test_subscription_rejects_path_tenant_mismatch(client):
    """认证租户与 path tenant_id 不一致时拒绝请求。"""
    with patch(
        "routers.billing._quota_service.get_usage_summary",
        new_callable=AsyncMock,
    ) as mock_summary:
        response = await client.get(
            "/api/billing/subscription/other-tenant",
            headers=auth_headers(),
        )

    assert response.status_code == 403
    data = response.json()
    assert data["detail"]["ok"] is False
    assert "tenant_id does not match authenticated user" in data["detail"]["message"]
    mock_summary.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /api/billing/quota/check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quota_check_success(client):
    """配额检查成功 → 200，返回 allowed/plan/used/limit/remaining。"""
    mock_result = QuotaResult(
        allowed=True,
        plan="free",
        action="daily_ai_calls",
        used=5,
        limit=10,
        remaining=5,
        message="",
    )

    with patch(
        "routers.billing._quota_service.check_quota",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        response = await client.post(
            "/api/billing/quota/check",
            json={
                "tenant_id": "t1",
                "action": "daily_ai_calls",
            },
            headers=auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["allowed"] is True
    assert data["data"]["plan"] == "free"
    assert data["data"]["action"] == "daily_ai_calls"
    assert data["data"]["used"] == 5
    assert data["data"]["limit"] == 10
    assert data["data"]["remaining"] == 5
    assert data["data"]["message"] == ""


# ---------------------------------------------------------------------------
# POST /api/billing/quota/record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_record_success(client):
    """用量记录成功 → 200。"""
    with patch(
        "routers.billing._quota_service.record_usage",
        new_callable=AsyncMock,
    ) as mock_record:
        response = await client.post(
            "/api/billing/quota/record",
            json={
                "tenant_id": "t1",
                "action": "daily_ai_calls",
                "quantity": 2,
                "metadata": {"source": "test"},
            },
            headers=auth_headers(),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["message"] == "Usage recorded"

    # 验证 record_usage 被正确调用
    mock_record.assert_awaited_once_with(
        tenant_id="t1",
        action="daily_ai_calls",
        quantity=2,
        metadata={"source": "test"},
    )
