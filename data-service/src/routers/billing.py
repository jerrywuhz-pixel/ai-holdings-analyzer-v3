"""
计费 API 路由

提供 Stripe Checkout、用量包购买、Webhook 回调、订阅查询和用量汇总等端点。
"""

import asyncio
import inspect
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from services.quota import QuotaService
from services.stripe_service import StripeService

try:
    from supabase import create_client

    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

router = APIRouter(tags=["billing"])

# 全局服务实例
_quota_service = QuotaService()
_stripe_service = StripeService()
_supabase_auth_client: Optional[Any] = None
_supabase_auth_config: Optional[tuple[str, str]] = None


# ---------- Pydantic 模型 ----------


class CheckoutRequest(BaseModel):
    """Stripe Checkout 请求体。"""

    tenant_id: str = Field(..., description="租户 ID")
    price_id: str = Field(..., description="Stripe Price ID")
    success_url: str = Field(..., description="支付成功回调 URL")
    cancel_url: str = Field(..., description="支付取消回调 URL")


class AddonRequest(BaseModel):
    """用量包购买请求体。"""

    tenant_id: str = Field(..., description="租户 ID")
    pack_name: str = Field(..., description="用量包名称，如 ai_analysis_pack")
    success_url: str = Field(..., description="支付成功回调 URL")
    cancel_url: str = Field(..., description="支付取消回调 URL")


class PortalRequest(BaseModel):
    """客户门户请求体。"""

    tenant_id: str = Field(..., description="租户 ID")
    return_url: str = Field(..., description="退出门户后的返回 URL")


class QuotaCheckRequest(BaseModel):
    """配额检查请求体。"""

    tenant_id: str = Field(..., description="租户 ID")
    action: str = Field(..., description="操作类型，如 daily_ai_calls")


class UsageRecordRequest(BaseModel):
    """用量记录请求体。"""

    tenant_id: str = Field(..., description="租户 ID")
    action: str = Field(..., description="操作类型")
    quantity: int = Field(1, ge=1, description="用量数量")
    metadata: Optional[dict] = Field(None, description="附加元数据")


# ---------- 鉴权辅助 ----------


def _auth_http_exception(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"ok": False, "message": message})


def _get_supabase_auth_client() -> Optional[Any]:
    global _supabase_auth_client, _supabase_auth_config

    if not SUPABASE_AVAILABLE:
        return None

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None

    config = (url, key)
    if _supabase_auth_client is not None and _supabase_auth_config == config:
        return _supabase_auth_client

    try:
        _supabase_auth_client = create_client(url, key)
        _supabase_auth_config = config
    except Exception:
        _supabase_auth_client = None
        _supabase_auth_config = None

    return _supabase_auth_client


async def _call_supabase_get_user(get_user: Any, token: str) -> Any:
    attempts = [((token,), {}), ((), {"jwt": token})]
    last_exc: Optional[TypeError] = None

    for args, kwargs in attempts:
        try:
            if inspect.iscoroutinefunction(get_user):
                return await get_user(*args, **kwargs)
            return await asyncio.to_thread(get_user, *args, **kwargs)
        except TypeError as exc:
            last_exc = exc

    raise RuntimeError("Supabase auth.get_user signature is unsupported") from last_exc


def _extract_user_id(user_response: Any) -> Optional[str]:
    user = getattr(user_response, "user", None)
    if user is None and isinstance(user_response, dict):
        user = user_response.get("user")

    if isinstance(user, dict):
        return user.get("id")

    return getattr(user, "id", None)


async def _authenticate_bearer_token(token: str) -> str:
    client = _get_supabase_auth_client()
    if client is None:
        raise _auth_http_exception(
            status_code=503,
            message="Supabase auth is not configured",
        )

    auth_client = getattr(client, "auth", None)
    get_user = getattr(auth_client, "get_user", None)
    if get_user is None:
        raise _auth_http_exception(
            status_code=503,
            message="Supabase auth client is unavailable",
        )

    try:
        user_response = await _call_supabase_get_user(get_user, token)
    except HTTPException:
        raise
    except Exception as exc:
        raise _auth_http_exception(
            status_code=401,
            message=f"Invalid or expired bearer token: {exc}",
        )

    tenant_id = _extract_user_id(user_response)
    if not tenant_id:
        raise _auth_http_exception(
            status_code=401,
            message="Invalid or expired bearer token",
        )
    return tenant_id


def _ensure_tenant_match(authenticated_tenant_id: str, requested_tenant_id: str) -> None:
    if requested_tenant_id != authenticated_tenant_id:
        raise _auth_http_exception(
            status_code=403,
            message="tenant_id does not match authenticated user",
        )


async def get_authenticated_tenant_id(
    authorization: Optional[str] = Header(default=None),
) -> str:
    if not authorization:
        raise _auth_http_exception(
            status_code=401,
            message="Missing Authorization header",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _auth_http_exception(
            status_code=401,
            message="Authorization header must use Bearer token",
        )

    return await _authenticate_bearer_token(token.strip())


# ---------- 路由 ----------


@router.post("/billing/checkout")
async def create_checkout(
    request: CheckoutRequest,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
) -> dict[str, Any]:
    """
    创建 Stripe Checkout Session 用于套餐升级订阅。

    Body:
        tenant_id, price_id, success_url, cancel_url

    Returns:
        {"ok": true, "data": {"session_id": "cs_xxx", "url": "..."}}
    """
    try:
        _ensure_tenant_match(authenticated_tenant_id, request.tenant_id)
        result = await _stripe_service.create_checkout_session(
            tenant_id=authenticated_tenant_id,
            price_id=request.price_id,
            success_url=request.success_url,
            cancel_url=request.cancel_url,
        )
        return {"ok": True, "data": result}
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "message": str(exc)},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to create checkout session: {exc}"},
        )


@router.post("/billing/addon")
async def create_addon_checkout(
    request: AddonRequest,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
) -> dict[str, Any]:
    """
    创建 Stripe Checkout Session 用于用量包购买。

    Body:
        tenant_id, pack_name, success_url, cancel_url

    Returns:
        {"ok": true, "data": {"session_id": "cs_xxx", "url": "..."}}
    """
    try:
        _ensure_tenant_match(authenticated_tenant_id, request.tenant_id)
        result = await _stripe_service.create_addon_session(
            tenant_id=authenticated_tenant_id,
            pack_name=request.pack_name,
            success_url=request.success_url,
            cancel_url=request.cancel_url,
        )
        return {"ok": True, "data": result}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "message": str(exc)},
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "message": str(exc)},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to create addon session: {exc}"},
        )


@router.post("/billing/webhook/stripe")
async def stripe_webhook(request: Request) -> dict[str, Any]:
    """
    处理 Stripe Webhook 事件。

    注意：使用原始请求体进行签名验证，不通过 Pydantic 解析。

    Headers:
        Stripe-Signature: 签名头

    Returns:
        {"ok": true, "data": {"processed": true, "event_type": "..."}}
    """
    # 获取原始请求体（用于签名验证）
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    if not sig_header:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "message": "Missing Stripe-Signature header"},
        )

    try:
        result = await _stripe_service.handle_webhook(
            payload=payload,
            sig_header=sig_header,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "message": str(exc)},
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "message": str(exc)},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Webhook processing failed: {exc}"},
        )


@router.post("/billing/portal")
async def create_portal_session(
    request: PortalRequest,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
) -> dict[str, Any]:
    """
    创建 Stripe Customer Portal Session，用于管理订阅。

    Body:
        tenant_id, return_url

    Returns:
        {"ok": true, "data": {"url": "https://billing.stripe.com/..."}}
    """
    try:
        _ensure_tenant_match(authenticated_tenant_id, request.tenant_id)
        result = await _stripe_service.create_customer_portal_session(
            tenant_id=authenticated_tenant_id,
            return_url=request.return_url,
        )
        return {"ok": True, "data": result}
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "message": str(exc)},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to create portal session: {exc}"},
        )


@router.get("/billing/subscription/{tenant_id}")
async def get_subscription(
    tenant_id: str,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
) -> dict[str, Any]:
    """
    获取用户当前订阅信息。

    Path:
        tenant_id: 租户 ID

    Returns:
        {"ok": true, "data": {"plan": "pro", "status": "active", ...}}
    """
    try:
        _ensure_tenant_match(authenticated_tenant_id, tenant_id)
        summary = await _quota_service.get_usage_summary(authenticated_tenant_id)
        return {
            "ok": True,
            "data": {
                "plan": summary["plan"],
                "subscription_status": summary["subscription_status"],
                "actions": summary["actions"],
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "message": f"Failed to get subscription for {tenant_id}: {exc}",
            },
        )


@router.get("/billing/usage/{tenant_id}")
async def get_usage(
    tenant_id: str,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
) -> dict[str, Any]:
    """
    获取用户用量汇总。

    Path:
        tenant_id: 租户 ID

    Returns:
        {"ok": true, "data": {"plan": "free", "actions": {...}}}
    """
    try:
        _ensure_tenant_match(authenticated_tenant_id, tenant_id)
        summary = await _quota_service.get_usage_summary(authenticated_tenant_id)
        return {"ok": True, "data": summary}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "message": f"Failed to get usage for {tenant_id}: {exc}",
            },
        )


@router.post("/billing/quota/check")
async def check_quota(
    request: QuotaCheckRequest,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
) -> dict[str, Any]:
    """
    检查配额是否允许。

    Body:
        tenant_id, action

    Returns:
        {"ok": true, "data": {"allowed": true, "plan": "free", "used": 5, "limit": 10, "remaining": 5}}
    """
    try:
        _ensure_tenant_match(authenticated_tenant_id, request.tenant_id)
        result = await _quota_service.check_quota(
            tenant_id=authenticated_tenant_id,
            action=request.action,
        )
        return {
            "ok": True,
            "data": {
                "allowed": result.allowed,
                "plan": result.plan,
                "action": result.action,
                "used": result.used,
                "limit": result.limit,
                "remaining": result.remaining,
                "message": result.message,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Quota check failed: {exc}"},
        )


@router.post("/billing/quota/record")
async def record_usage(
    request: UsageRecordRequest,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
) -> dict[str, Any]:
    """
    记录一次用量事件。

    Body:
        tenant_id, action, quantity, metadata

    Returns:
        {"ok": true, "message": "Usage recorded"}
    """
    try:
        _ensure_tenant_match(authenticated_tenant_id, request.tenant_id)
        await _quota_service.record_usage(
            tenant_id=authenticated_tenant_id,
            action=request.action,
            quantity=request.quantity,
            metadata=request.metadata,
        )
        return {"ok": True, "message": "Usage recorded"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to record usage: {exc}"},
        )
