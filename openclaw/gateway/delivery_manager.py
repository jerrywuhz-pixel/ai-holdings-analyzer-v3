"""
DeliveryManager — 推送投递可靠性管理器

管理 delivery_runs 记录的完整生命周期：
  PENDING → SENT → DELIVERED
         ↘ FAILED / DELIVERY_FAILED / DELIVERY_TIMEOUT → (retry) → SENT → DELIVERED
                                                        ↘ ABANDONED

核心职责：
1. 创建 delivery 记录时验证必填字段（context_token, target_conversation, delivery_key, content）
2. 生成幂等性 idempotency_key 防止重复投递
3. 提供状态流转方法（mark_sent / mark_delivered / mark_failed / mark_abandoned）
4. 支持失败 delivery 的重试查询

所有 Supabase 操作均通过 ``asyncio.to_thread()`` 包装。
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _get_supabase_client() -> Any:
    """
    从环境变量创建同步 Supabase 客户端。

    环境变量:
        SUPABASE_URL:               Supabase Project URL
        SUPABASE_SERVICE_ROLE_KEY:  service_role JWT（可绕过 RLS）
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables are required."
        )
    from supabase import create_client

    return create_client(url, key)


class DeliveryValidationError(Exception):
    """delivery 记录创建前校验失败。"""
    pass


class DeliveryManager:
    """
    管理 delivery_runs 表记录的完整生命周期。

    用法::

        dm = DeliveryManager()
        delivery_id = await dm.create_delivery(
            job_run_id="job-uuid",
            tenant_id="user-uuid",
            channel="wechat_claw",
            content={"text": "今日复盘报告"},
            context_token="ctx-token",
            target_conversation="conv-id",
        )
        await dm.mark_sent(delivery_id)
        await dm.mark_delivered(delivery_id)
    """

    # 最大重试次数（超过后标记 ABANDONED）
    MAX_RETRIES = 3

    def __init__(self, client: Any | None = None) -> None:
        """
        Args:
            client: 可选的同步 Supabase 客户端。若不传入，则从环境变量自动创建。
        """
        self._client = client or _get_supabase_client()

    # ------------------------------------------------------------------ #
    # 创建 delivery
    # ------------------------------------------------------------------ #

    async def create_delivery(
        self,
        job_run_id: str,
        tenant_id: str,
        channel: str,
        content: dict[str, Any],
        context_token: str | None = None,
        target_conversation: str | None = None,
    ) -> str:
        """
        创建 delivery_runs 记录，状态为 PENDING。

        创建前验证必填字段：
        - context_token: 推送所需的会话令牌
        - target_conversation: 推送目标对话 ID
        - delivery_key: 从 content 中提取的业务去重键
        - content: 推送内容不能为空

        Args:
            job_run_id: 关联的 job_runs 记录 UUID。
            tenant_id: 租户 ID。
            channel: 推送渠道，如 'wechat_claw'。
            content: 推送内容字典。
            context_token: OpenClaw 会话 token。
            target_conversation: 微信对话 ID。

        Returns:
            新创建的 delivery_runs 记录 UUID。

        Raises:
            DeliveryValidationError: 必填字段缺失。
            RuntimeError: 数据库写入失败。
        """
        # 字段校验
        errors: list[str] = []
        if not context_token:
            errors.append("context_token is required for delivery")
        if not target_conversation:
            errors.append("target_conversation is required for delivery")
        if not content:
            errors.append("content is required for delivery")

        # delivery_key: 从 content 中提取或生成
        delivery_key = content.get("delivery_key") or content.get("analysis_id")
        if not delivery_key:
            errors.append(
                "delivery_key (or content.analysis_id) is required for delivery"
            )

        if errors:
            raise DeliveryValidationError("; ".join(errors))

        # 生成幂等性 key：tenant_id + delivery_key 的确定性哈希
        idempotency_key = _generate_idempotency_key(tenant_id, delivery_key)

        delivery_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        payload: dict[str, Any] = {
            "id": delivery_id,
            "job_run_id": job_run_id,
            "tenant_id": tenant_id,
            "channel": channel,
            "status": "PENDING",
            "content": content,
            "context_token": context_token,
            "target_conversation": target_conversation,
            "delivery_key": delivery_key,
            "idempotency_key": idempotency_key,
            "created_at": now,
        }

        def _insert() -> dict:
            resp = (
                self._client.table("delivery_runs")
                .insert(payload)
                .execute()
            )
            return resp.data[0] if resp.data else payload

        try:
            record = await asyncio.to_thread(_insert)
            logger.info(
                "Created delivery %s (job=%s, tenant=%s, channel=%s)",
                delivery_id, job_run_id, tenant_id, channel,
            )
            return str(record.get("id", delivery_id))
        except Exception as exc:
            # 唯一约束冲突 → 幂等返回已有记录
            if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
                logger.info(
                    "Delivery already exists for idempotency_key=%s, skipping.",
                    idempotency_key,
                )
                # 查找已有记录
                existing = await self._find_by_idempotency_key(idempotency_key, tenant_id)
                if existing:
                    return str(existing["id"])
            raise RuntimeError(
                f"Failed to create delivery (job={job_run_id}, tenant={tenant_id}): {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # 状态流转方法
    # ------------------------------------------------------------------ #

    async def mark_sent(self, delivery_id: str) -> None:
        """
        将 delivery 状态设置为 SENT，记录 sent_at。

        由推送执行器在消息发送成功后调用。

        Args:
            delivery_id: delivery_runs 记录 UUID。

        Raises:
            RuntimeError: 更新失败。
        """
        now = datetime.now(timezone.utc).isoformat()

        def _update() -> None:
            self._client.table("delivery_runs").update({
                "status": "SENT",
                "sent_at": now,
            }).eq("id", delivery_id).execute()

        try:
            await asyncio.to_thread(_update)
            logger.info("Marked delivery %s as SENT", delivery_id)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to mark delivery '{delivery_id}' as SENT: {exc}"
            ) from exc

    async def mark_delivered(self, delivery_id: str) -> None:
        """
        将 delivery 状态设置为 DELIVERED。

        由回调/确认机制在用户确认收到后调用。

        Args:
            delivery_id: delivery_runs 记录 UUID。

        Raises:
            RuntimeError: 更新失败。
        """
        def _update() -> None:
            self._client.table("delivery_runs").update({
                "status": "DELIVERED",
            }).eq("id", delivery_id).execute()

        try:
            await asyncio.to_thread(_update)
            logger.info("Marked delivery %s as DELIVERED", delivery_id)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to mark delivery '{delivery_id}' as DELIVERED: {exc}"
            ) from exc

    async def mark_failed(
        self,
        delivery_id: str,
        error: str,
        *,
        is_delivery_error: bool = False,
        is_timeout: bool = False,
    ) -> None:
        """
        将 delivery 标记为失败，递增 retry_count。

        根据错误类型选择不同的失败状态：
        - 默认: FAILED
        - is_delivery_error=True: DELIVERY_FAILED（渠道侧失败）
        - is_timeout=True: DELIVERY_TIMEOUT

        Args:
            delivery_id: delivery_runs 记录 UUID。
            error: 错误信息。
            is_delivery_error: 是否为渠道投递失败。
            is_timeout: 是否为投递超时。

        Raises:
            RuntimeError: 更新失败。
        """
        if is_timeout:
            status = "DELIVERY_TIMEOUT"
        elif is_delivery_error:
            status = "DELIVERY_FAILED"
        else:
            status = "FAILED"

        def _update() -> None:
            # 读取当前 retry_count
            # TODO: 使用原子递增（如 Supabase RPC / 原始 SQL）消除读-改-写竞态条件
            resp = (
                self._client.table("delivery_runs")
                .select("retry_count")
                .eq("id", delivery_id)
                .limit(1)
                .execute()
            )
            current_retries = resp.data[0]["retry_count"] if resp.data else 0
            self._client.table("delivery_runs").update({
                "status": status,
                "error_message": error,
                "retry_count": current_retries + 1,
            }).eq("id", delivery_id).execute()

        try:
            await asyncio.to_thread(_update)
            logger.warning(
                "Marked delivery %s as %s: %s", delivery_id, status, error[:200]
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to mark delivery '{delivery_id}' as {status}: {exc}"
            ) from exc

    async def mark_abandoned(self, delivery_id: str) -> None:
        """
        将 delivery 状态设置为 ABANDONED。

        当 retry_count >= MAX_RETRIES 时由 Heartbeat 调用。

        Args:
            delivery_id: delivery_runs 记录 UUID。

        Raises:
            RuntimeError: 更新失败。
        """
        def _update() -> None:
            self._client.table("delivery_runs").update({
                "status": "ABANDONED",
                "error_message": "Delivery abandoned after max retries",
            }).eq("id", delivery_id).execute()

        try:
            await asyncio.to_thread(_update)
            logger.warning("Abandoned delivery %s", delivery_id)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to abandon delivery '{delivery_id}': {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # 查询方法（供 Heartbeat 等使用）
    # ------------------------------------------------------------------ #

    async def get_pending_retries(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        查找可重试的失败 delivery（FAILED 且 retry_count < MAX_RETRIES）。

        Args:
            limit: 返回记录数上限。

        Returns:
            可重试的 delivery 列表，按 created_at 升序（先失败先重试）。
        """
        def _query() -> list:
            # 查询 FAILED / DELIVERY_FAILED 且 retry_count < MAX_RETRIES 的记录
            resp = (
                self._client.table("delivery_runs")
                .select("*")
                .in_("status", ["FAILED", "DELIVERY_FAILED", "DELIVERY_TIMEOUT"])
                .lt("retry_count", self.MAX_RETRIES)
                .order("created_at", desc=False)
                .limit(limit)
                .execute()
            )
            return resp.data or []

        try:
            return await asyncio.to_thread(_query)
        except Exception as exc:
            logger.error("Failed to query pending delivery retries: %s", exc)
            return []

    async def get_abandonable_deliveries(self) -> list[dict[str, Any]]:
        """
        查找应被标记为 ABANDONED 的 delivery（retry_count >= MAX_RETRIES）。

        Returns:
            超过最大重试次数的失败 delivery 列表。
        """
        def _query() -> list:
            resp = (
                self._client.table("delivery_runs")
                .select("id, retry_count, status")
                .in_("status", ["FAILED", "DELIVERY_FAILED", "DELIVERY_TIMEOUT"])
                .gte("retry_count", self.MAX_RETRIES)
                .execute()
            )
            return resp.data or []

        try:
            return await asyncio.to_thread(_query)
        except Exception as exc:
            logger.error("Failed to query abandonable deliveries: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    async def _find_by_idempotency_key(
        self, idempotency_key: str, tenant_id: str
    ) -> dict[str, Any] | None:
        """
        根据 idempotency_key + tenant_id 查找已有 delivery。

        Args:
            idempotency_key: 幂等性键。
            tenant_id: 租户 ID。

        Returns:
            已有记录或 None。
        """
        def _query() -> list:
            resp = (
                self._client.table("delivery_runs")
                .select("id, status")
                .eq("idempotency_key", idempotency_key)
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            return resp.data or []

        try:
            records = await asyncio.to_thread(_query)
            return records[0] if records else None
        except Exception:
            return None


# ====================================================================== #
# 工具函数
# ====================================================================== #

def _generate_idempotency_key(tenant_id: str, delivery_key: str) -> str:
    """
    生成确定性幂等性键。

    基于 tenant_id + delivery_key 生成 UUID v5（命名空间 DNS），
    确保同一租户同一业务键不会重复创建 delivery。

    Args:
        tenant_id: 租户 ID。
        delivery_key: 业务去重键（如 analysis_id）。

    Returns:
        UUID v5 格式的幂等性键。
    """
    import hashlib

    raw = f"{tenant_id}:{delivery_key}"
    hash_hex = hashlib.sha256(raw.encode()).hexdigest()
    # 取前 32 字符作为 UUID 格式
    return str(uuid.UUID(hash_hex[:32]))
