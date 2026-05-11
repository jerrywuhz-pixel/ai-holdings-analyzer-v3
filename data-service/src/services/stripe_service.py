"""
Stripe 支付服务

提供 Stripe Checkout Session 创建、Webhook 处理和客户门户等能力。
stripe 为可选依赖，未安装时所有方法将抛出 RuntimeError。

参考 longbridge.py 的可选依赖模式：
    try:
        import stripe
        _HAS_STRIPE = True
    except ImportError:
        _HAS_STRIPE = False
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# 可选依赖
# ---------------------------------------------------------------------------
try:
    import stripe

    _HAS_STRIPE = True
except ImportError:
    _HAS_STRIPE = False


# ---------------------------------------------------------------------------
# Supabase 可选依赖
# ---------------------------------------------------------------------------
try:
    from supabase import create_client

    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------
def _get_supabase_client() -> Optional[Any]:
    """尝试从环境变量创建 Supabase 客户端，失败时返回 None。"""
    if not SUPABASE_AVAILABLE:
        return None

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None

    try:
        return create_client(url, key)
    except Exception:
        return None


def _execute_sync(builder: Any) -> Any:
    """执行同步 Supabase 查询（需在 asyncio.to_thread 中调用）。"""
    return builder.execute()


# ---------------------------------------------------------------------------
# StripeService
# ---------------------------------------------------------------------------
class StripeService:
    """
    Stripe 支付服务。

    封装 Stripe Checkout Session、Webhook 事件处理和客户门户。
    stripe 未安装时，所有方法将抛出 RuntimeError("stripe SDK not installed")。
    """

    def __init__(self):
        self._available = _HAS_STRIPE
        if not self._available:
            return

        self._api_key = os.getenv("STRIPE_SECRET_KEY")
        self._webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

        if self._api_key:
            stripe.api_key = self._api_key

    # ------------------------------------------------------------------
    # Checkout Session
    # ------------------------------------------------------------------
    async def create_checkout_session(
        self,
        tenant_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> Dict[str, Any]:
        """
        创建 Stripe Checkout Session 用于套餐升级订阅。

        Args:
            tenant_id:  租户 ID（存入 metadata 用于 Webhook 关联）
            price_id:   Stripe Price ID
            success_url: 支付成功回调 URL
            cancel_url:  支付取消回调 URL

        Returns:
            {"session_id": "cs_xxx", "url": "https://checkout.stripe.com/..."}

        Raises:
            RuntimeError: stripe SDK 未安装或未配置
        """
        if not self._available:
            raise RuntimeError("stripe SDK not installed")
        if not self._api_key:
            raise RuntimeError("stripe API key not configured")

        # 查找或创建 Stripe Customer
        customer_id = await self._get_or_create_customer(tenant_id)

        session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"tenant_id": tenant_id},
        )

        return {
            "session_id": session.id,
            "url": session.url,
        }

    async def create_addon_session(
        self,
        tenant_id: str,
        pack_name: str,
        success_url: str,
        cancel_url: str,
    ) -> Dict[str, Any]:
        """
        创建 Checkout Session 用于用量包购买。

        Args:
            tenant_id:  租户 ID
            pack_name:  用量包名称，如 'ai_analysis_pack'
            success_url: 支付成功回调 URL
            cancel_url:  支付取消回调 URL

        Returns:
            {"session_id": "cs_xxx", "url": "https://checkout.stripe.com/..."}

        Raises:
            RuntimeError: stripe SDK 未安装或未配置
            ValueError:   用量包未找到或无 Stripe Price ID
        """
        if not self._available:
            raise RuntimeError("stripe SDK not installed")
        if not self._api_key:
            raise RuntimeError("stripe API key not configured")

        # 从 addon_packs 表获取 Stripe Price ID
        price_id = await self._get_addon_price_id(pack_name)
        if not price_id:
            raise ValueError(
                f"Addon pack '{pack_name}' not found or has no Stripe Price ID"
            )

        customer_id = await self._get_or_create_customer(tenant_id)

        session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            mode="payment",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "tenant_id": tenant_id,
                "addon_pack_name": pack_name,
            },
        )

        return {
            "session_id": session.id,
            "url": session.url,
        }

    # ------------------------------------------------------------------
    # Webhook 处理
    # ------------------------------------------------------------------
    async def handle_webhook(
        self, payload: bytes, sig_header: str
    ) -> Dict[str, Any]:
        """
        处理 Stripe Webhook 事件。

        支持的事件类型：
            - checkout.session.completed: 订阅/用量包支付成功
            - customer.subscription.updated: 订阅更新（升降级）
            - customer.subscription.deleted: 订阅取消

        Args:
            payload:     原始请求体
            sig_header:  Stripe-Signature 请求头

        Returns:
            {"processed": True, "event_type": "checkout.session.completed"}

        Raises:
            RuntimeError: stripe SDK 未安装
            ValueError:   签名验证失败或事件处理异常
        """
        if not self._available:
            raise RuntimeError("stripe SDK not installed")
        if not self._webhook_secret:
            raise ValueError("Stripe webhook secret not configured")

        # 验证签名
        try:
            event = await asyncio.to_thread(
                stripe.Webhook.construct_event,
                payload,
                sig_header,
                self._webhook_secret,
            )
        except stripe.error.SignatureVerificationError as exc:
            raise ValueError(f"Invalid signature: {exc}") from exc
        except Exception as exc:
            raise ValueError(f"Webhook construction failed: {exc}") from exc

        event_type = event["type"]

        try:
            if event_type == "checkout.session.completed":
                await self._handle_checkout_completed(event)
            elif event_type == "customer.subscription.updated":
                await self._handle_subscription_updated(event)
            elif event_type == "customer.subscription.deleted":
                await self._handle_subscription_deleted(event)
            else:
                # 未处理的事件类型，记录但不报错
                pass
        except Exception as exc:
            raise ValueError(
                f"Failed to process {event_type} event: {exc}"
            ) from exc

        return {"processed": True, "event_type": event_type}

    # ------------------------------------------------------------------
    # 客户门户
    # ------------------------------------------------------------------
    async def create_customer_portal_session(
        self, tenant_id: str, return_url: str
    ) -> Dict[str, Any]:
        """
        创建 Stripe Customer Portal Session，用于管理订阅。

        Args:
            tenant_id:  租户 ID
            return_url: 退出门户后的返回 URL

        Returns:
            {"url": "https://billing.stripe.com/..."}

        Raises:
            RuntimeError: stripe SDK 未安装或用户无 Stripe Customer ID
        """
        if not self._available:
            raise RuntimeError("stripe SDK not installed")
        if not self._api_key:
            raise RuntimeError("stripe API key not configured")

        customer_id = await self._get_stripe_customer_id(tenant_id)
        if not customer_id:
            raise RuntimeError(
                f"No Stripe customer ID found for tenant {tenant_id}"
            )

        session = await asyncio.to_thread(
            stripe.billing_portal.Session.create,
            customer=customer_id,
            return_url=return_url,
        )

        return {"url": session.url}

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    async def _get_or_create_customer(self, tenant_id: str) -> str:
        """获取或创建 Stripe Customer ID。"""
        # 先查 subscriptions 表
        existing = await self._get_stripe_customer_id(tenant_id)
        if existing:
            return existing

        # 创建新 Customer
        customer = await asyncio.to_thread(
            stripe.Customer.create,
            metadata={"tenant_id": tenant_id},
        )

        # 记录到 subscriptions 表
        client = _get_supabase_client()
        if client is not None:
            try:
                # 尝试更新已有订阅记录
                resp = await asyncio.to_thread(
                    _execute_sync,
                    client.table("subscriptions")
                    .select("id")
                    .eq("tenant_id", tenant_id)
                    .maybe_single(),
                )
                if resp.data:
                    await asyncio.to_thread(
                        _execute_sync,
                        client.table("subscriptions")
                        .update({"stripe_customer_id": customer.id})
                        .eq("tenant_id", tenant_id),
                    )
                else:
                    # 创建默认订阅记录
                    await asyncio.to_thread(
                        _execute_sync,
                        client.table("subscriptions").insert(
                            {
                                "tenant_id": tenant_id,
                                "plan": "free",
                                "status": "active",
                                "stripe_customer_id": customer.id,
                                "payment_method": "stripe",
                            }
                        ),
                    )
            except Exception:
                pass

        return customer.id

    async def _get_stripe_customer_id(self, tenant_id: str) -> Optional[str]:
        """从 subscriptions 表获取 Stripe Customer ID。"""
        client = _get_supabase_client()
        if client is None:
            return None

        try:
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("subscriptions")
                .select("stripe_customer_id")
                .eq("tenant_id", tenant_id)
                .maybe_single(),
            )
            if resp.data and resp.data.get("stripe_customer_id"):
                return resp.data["stripe_customer_id"]
        except Exception:
            pass

        return None

    async def _get_addon_price_id(self, pack_name: str) -> Optional[str]:
        """从 addon_packs 表获取 Stripe Price ID。"""
        client = _get_supabase_client()
        if client is None:
            return None

        try:
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("addon_packs")
                .select("price_stripe_id")
                .eq("name", pack_name)
                .maybe_single(),
            )
            if resp.data:
                return resp.data.get("price_stripe_id")
        except Exception:
            pass

        return None

    async def _handle_checkout_completed(self, event: Dict[str, Any]) -> None:
        """处理 checkout.session.completed 事件。"""
        session = event["data"]["object"]
        metadata = session.get("metadata", {})
        tenant_id = metadata.get("tenant_id")
        mode = session.get("mode")  # subscription / payment

        if not tenant_id:
            return

        client = _get_supabase_client()
        if client is None:
            return

        if mode == "subscription":
            # 订阅支付成功，更新 subscriptions 表
            subscription_id = session.get("subscription")
            customer_id = session.get("customer")
            # 从 line_items 获取 price_id
            line_items = session.get("line_items", {}).get("data", [])
            price_id = line_items[0]["price"]["id"] if line_items else None

            # 根据 price_id 确定 plan（简化处理：从 metadata 或 price 映射）
            plan = metadata.get("plan", "basic")

            try:
                resp = await asyncio.to_thread(
                    _execute_sync,
                    client.table("subscriptions")
                    .select("id")
                    .eq("tenant_id", tenant_id)
                    .maybe_single(),
                )
                update_data = {
                    "plan": plan,
                    "status": "active",
                    "stripe_subscription_id": subscription_id,
                    "stripe_customer_id": customer_id,
                    "stripe_price_id": price_id,
                    "payment_method": "stripe",
                    "current_period_start": session.get("created"),
                }

                if resp.data:
                    await asyncio.to_thread(
                        _execute_sync,
                        client.table("subscriptions")
                        .update(update_data)
                        .eq("tenant_id", tenant_id),
                    )
                else:
                    update_data["tenant_id"] = tenant_id
                    await asyncio.to_thread(
                        _execute_sync,
                        client.table("subscriptions").insert(update_data),
                    )

                # 同步更新 users.plan
                await asyncio.to_thread(
                    _execute_sync,
                    client.table("users").update({"plan": plan}).eq("id", tenant_id),
                )
            except Exception:
                pass

        elif mode == "payment":
            # 用量包支付成功，创建 user_addon_packs 记录
            pack_name = metadata.get("addon_pack_name")
            if not pack_name:
                return

            try:
                # 获取用量包信息
                pack_resp = await asyncio.to_thread(
                    _execute_sync,
                    client.table("addon_packs")
                    .select("id, quota_amount, validity_days")
                    .eq("name", pack_name)
                    .maybe_single(),
                )
                if not pack_resp.data:
                    return

                pack = pack_resp.data
                from datetime import datetime, timedelta, timezone

                now = datetime.now(timezone.utc)
                expires_at = now + timedelta(days=pack["validity_days"])

                await asyncio.to_thread(
                    _execute_sync,
                    client.table("user_addon_packs").insert(
                        {
                            "tenant_id": tenant_id,
                            "addon_pack_id": pack["id"],
                            "remaining_quota": pack["quota_amount"],
                            "expires_at": expires_at.isoformat(),
                            "stripe_session_id": session.get("id"),
                        }
                    ),
                )
            except Exception:
                pass

    async def _handle_subscription_updated(self, event: Dict[str, Any]) -> None:
        """处理 customer.subscription.updated 事件。"""
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")
        status = subscription.get("status")

        client = _get_supabase_client()
        if client is None:
            return

        try:
            # 通过 stripe_customer_id 找到 tenant
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("subscriptions")
                .select("tenant_id")
                .eq("stripe_customer_id", customer_id)
                .maybe_single(),
            )
            if not resp.data:
                return

            tenant_id = resp.data["tenant_id"]
            update_data = {"status": status}

            # 如果取消，设置 cancel_at_period_end
            if status == "active" and subscription.get("cancel_at_period_end"):
                update_data["cancel_at_period_end"] = True
            elif status == "active":
                update_data["cancel_at_period_end"] = False

            await asyncio.to_thread(
                _execute_sync,
                client.table("subscriptions")
                .update(update_data)
                .eq("tenant_id", tenant_id),
            )
        except Exception:
            pass

    async def _handle_subscription_deleted(self, event: Dict[str, Any]) -> None:
        """处理 customer.subscription.deleted 事件。"""
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")

        client = _get_supabase_client()
        if client is None:
            return

        try:
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("subscriptions")
                .select("tenant_id")
                .eq("stripe_customer_id", customer_id)
                .maybe_single(),
            )
            if not resp.data:
                return

            tenant_id = resp.data["tenant_id"]

            # 将订阅降级为 free
            await asyncio.to_thread(
                _execute_sync,
                client.table("subscriptions")
                .update({"plan": "free", "status": "canceled"})
                .eq("tenant_id", tenant_id),
            )

            # 同步更新 users.plan
            await asyncio.to_thread(
                _execute_sync,
                client.table("users").update({"plan": "free"}).eq("id", tenant_id),
            )
        except Exception:
            pass
