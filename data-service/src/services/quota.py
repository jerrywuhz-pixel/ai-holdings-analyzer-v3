"""
配额检查服务

为 data-service 层提供统一的配额检查与用量记录能力：
- check_quota: 检查租户是否允许执行某操作
- record_usage: 记录一次用量事件
- get_usage_summary: 获取租户用量汇总

所有 Supabase 操作使用 asyncio.to_thread() 包装，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 可选依赖
# ---------------------------------------------------------------------------
try:
    from supabase import create_client

    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass
class QuotaResult:
    """配额检查结果。"""

    allowed: bool
    plan: str
    action: str
    used: int
    limit: int
    remaining: int
    message: str = ""


# ---------------------------------------------------------------------------
# 常量：内置套餐限制（数据库不可用时的降级兜底）
# ---------------------------------------------------------------------------
_PLAN_LIMITS_FALLBACK: Dict[str, Dict[str, int]] = {
    "free": {
        "max_positions": 5,
        "max_trades": 50,
        "daily_ai_calls": 10,
        "data_sources": 1,
        "push_notifications": 0,
        "watchlist": 5,
        "webapp": 0,
    },
    "basic": {
        "max_positions": 999999,
        "max_trades": 999999,
        "daily_ai_calls": 200,
        "data_sources": 2,
        "push_notifications": 1,
        "watchlist": 999999,
        "webapp": 1,
    },
    "pro": {
        "max_positions": 999999,
        "max_trades": 999999,
        "daily_ai_calls": 999999,
        "data_sources": 999,
        "push_notifications": 2,
        "watchlist": 999999,
        "webapp": 2,
    },
    "enterprise": {
        "max_positions": 999999,
        "max_trades": 999999,
        "daily_ai_calls": 999999,
        "data_sources": 999,
        "push_notifications": 2,
        "watchlist": 999999,
        "webapp": 2,
    },
}


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
# QuotaService
# ---------------------------------------------------------------------------
class QuotaService:
    """
    配额检查服务。

    优先从 plan_limits 表和 usage_records 表查询实时配额，
    Supabase 不可用时降级到内置常量。
    """

    def __init__(self, supabase_client: Optional[Any] = None):
        self._client = supabase_client

    def _ensure_client(self) -> Optional[Any]:
        """惰性获取 Supabase 客户端。"""
        if self._client is None:
            self._client = _get_supabase_client()
        return self._client

    # ------------------------------------------------------------------
    # 核心方法
    # ------------------------------------------------------------------
    async def check_quota(self, tenant_id: str, action: str) -> QuotaResult:
        """
        检查租户是否允许执行某操作。

        检查流程：
            1. 获取用户当前套餐（subscriptions > users.plan 降级）
            2. 查询当前周期用量（usage_records 表）
            3. 对比 plan_limits 中的限制
            4. 检查 user_addon_packs 是否有额外额度
            5. 返回 QuotaResult

        Args:
            tenant_id: 租户 ID
            action:    操作类型，如 'daily_ai_calls'

        Returns:
            QuotaResult 含 allowed / used / limit / remaining 等字段
        """
        # 1. 获取套餐
        plan = await self._get_plan(tenant_id)

        # 2. 获取限制
        limit = await self._get_limit(plan, action)

        # 3. 获取当前周期用量
        used = await self._get_usage_count(tenant_id, action)

        # 4. 检查用量包额外额度
        addon_remaining = await self._get_addon_remaining(tenant_id, action)

        # 5. 综合判断
        effective_limit = limit + addon_remaining
        remaining = max(0, effective_limit - used)
        allowed = used < effective_limit

        message = ""
        if not allowed:
            message = (
                f"Quota exceeded for '{action}': "
                f"used {used}/{effective_limit} (plan: {limit}, addon: {addon_remaining})"
            )

        return QuotaResult(
            allowed=allowed,
            plan=plan,
            action=action,
            used=used,
            limit=limit,
            remaining=remaining,
            message=message,
        )

    async def record_usage(
        self,
        tenant_id: str,
        action: str,
        quantity: int = 1,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        记录一次用量事件。

        同时写入 usage_records 表和递减 user_addon_packs 剩余额度，
        并更新 quota_tracking 计数器。

        Args:
            tenant_id: 租户 ID
            action:    操作类型
            quantity:  用量数量，默认 1
            metadata:  附加元数据，可选
        """
        client = self._ensure_client()
        if client is None:
            # 数据库不可用时静默跳过（不阻塞业务主流程）
            return

        try:
            # 1. 插入 usage_records
            record = {
                "tenant_id": tenant_id,
                "action": action,
                "quantity": quantity,
                "metadata": metadata or {},
            }
            await asyncio.to_thread(
                _execute_sync,
                client.table("usage_records").insert(record),
            )
        except Exception:
            # 记录失败不阻塞业务
            pass

        try:
            # 2. 更新 quota_tracking 计数器
            await self._increment_quota_tracking(client, tenant_id, action, quantity)
        except Exception:
            pass

        try:
            # 3. 递减 user_addon_packs 剩余额度
            await self._decrement_addon_quota(client, tenant_id, action, quantity)
        except Exception:
            pass

    async def get_usage_summary(self, tenant_id: str) -> dict:
        """
        获取租户用量汇总。

        Returns:
            {
                "plan": "free",
                "subscription_status": "active",
                "actions": {
                    "daily_ai_calls": {"used": 5, "limit": 10, "remaining": 5, "addon_remaining": 0},
                    ...
                }
            }
        """
        plan = await self._get_plan(tenant_id)
        sub_status = await self._get_subscription_status(tenant_id)

        actions = [
            "daily_ai_calls",
            "max_positions",
            "max_trades",
            "data_sources",
            "push_notifications",
            "watchlist",
            "webapp",
        ]

        summary: Dict[str, Any] = {
            "plan": plan,
            "subscription_status": sub_status,
            "actions": {},
        }

        for action in actions:
            limit = await self._get_limit(plan, action)
            used = await self._get_usage_count(tenant_id, action)
            addon_remaining = await self._get_addon_remaining(tenant_id, action)

            summary["actions"][action] = {
                "used": used,
                "limit": limit,
                "remaining": max(0, limit + addon_remaining - used),
                "addon_remaining": addon_remaining,
            }

        return summary

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    async def _get_plan(self, tenant_id: str) -> str:
        """获取用户当前套餐，优先从 subscriptions 表，降级到 users.plan。"""
        client = self._ensure_client()
        if client is None:
            return "free"

        # 优先从 subscriptions 表获取
        try:
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("subscriptions")
                .select("plan,status")
                .eq("tenant_id", tenant_id)
                .maybe_single(),
            )
            if resp.data and resp.data.get("status") == "active":
                return resp.data["plan"]
        except Exception:
            pass

        # 降级到 users.plan
        try:
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("users").select("plan").eq("id", tenant_id).maybe_single(),
            )
            if resp.data:
                return resp.data["plan"]
        except Exception:
            pass

        return "free"

    async def _get_subscription_status(self, tenant_id: str) -> str:
        """获取用户订阅状态。"""
        client = self._ensure_client()
        if client is None:
            return "active"

        try:
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("subscriptions")
                .select("status")
                .eq("tenant_id", tenant_id)
                .maybe_single(),
            )
            if resp.data:
                return resp.data["status"]
        except Exception:
            pass

        return "active"

    async def _get_limit(self, plan: str, action: str) -> int:
        """获取指定套餐的指定操作限制，优先查数据库，降级到内置常量。"""
        client = self._ensure_client()
        if client is not None:
            try:
                resp = await asyncio.to_thread(
                    _execute_sync,
                    client.table("plan_limits")
                    .select("limit_value")
                    .eq("plan", plan)
                    .eq("action", action)
                    .maybe_single(),
                )
                if resp.data:
                    return resp.data["limit_value"]
            except Exception:
                pass

        # 降级到内置常量
        return _PLAN_LIMITS_FALLBACK.get(plan, _PLAN_LIMITS_FALLBACK["free"]).get(
            action, 0
        )

    async def _get_usage_count(self, tenant_id: str, action: str) -> int:
        """获取当前周期的用量计数（从 usage_records 表统计）。"""
        client = self._ensure_client()
        if client is None:
            return 0

        try:
            # 查询当月该 action 的总用量
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("usage_records")
                .select("quantity")
                .eq("tenant_id", tenant_id)
                .eq("action", action)
                .gte("created_at", month_start),
            )
            if resp.data:
                return sum(row.get("quantity", 1) for row in resp.data)
        except Exception:
            pass

        return 0

    async def _get_addon_remaining(self, tenant_id: str, action: str) -> int:
        """获取用户用量包中该 action 的剩余总额度。"""
        client = self._ensure_client()
        if client is None:
            return 0

        try:
            now_iso = datetime.now(timezone.utc).isoformat()

            # 查询该用户未过期的、对应 action 的用量包剩余额度
            # 需要关联 addon_packs 表获取 quota_action
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("user_addon_packs")
                .select("remaining_quota, addon_packs(quota_action)")
                .eq("tenant_id", tenant_id)
                .gt("expires_at", now_iso)
                .gt("remaining_quota", 0),
            )

            total = 0
            if resp.data:
                for row in resp.data:
                    pack = row.get("addon_packs")
                    if pack and pack.get("quota_action") == action:
                        total += row.get("remaining_quota", 0)
            return total
        except Exception:
            return 0

    async def _increment_quota_tracking(
        self, client: Any, tenant_id: str, action: str, quantity: int
    ) -> None:
        """更新 quota_tracking 计数器。"""
        # action -> quota_tracking column 映射
        column_map = {
            "trade_write": "daily_writes",
            "data_read": "daily_reads",
            "daily_ai_calls": "daily_ai_calls",
            "ai_analysis": "daily_ai_calls",
        }

        column = column_map.get(action)
        if column is None:
            return

        # 尝试 upsert：先尝试更新，若无记录则插入
        # TODO: 使用 Supabase RPC 或原始 SQL 实现原子递增，消除竞态条件
        try:
            # 检查记录是否存在并读取当前值
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("quota_tracking")
                .select(f"id, {column}")
                .eq("tenant_id", tenant_id)
                .maybe_single(),
            )

            if resp.data:
                # 更新已有记录：累加而非覆盖
                current = resp.data.get(column) or 0
                await asyncio.to_thread(
                    _execute_sync,
                    client.table("quota_tracking")
                    .update({column: current + quantity})
                    .eq("tenant_id", tenant_id),
                )
            else:
                # 插入新记录
                await asyncio.to_thread(
                    _execute_sync,
                    client.table("quota_tracking")
                    .insert({"tenant_id": tenant_id, column: quantity}),
                )
        except Exception:
            pass

    async def _decrement_addon_quota(
        self, client: Any, tenant_id: str, action: str, quantity: int
    ) -> None:
        """递减用户用量包剩余额度。"""
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            # 查询未过期的、有剩余额度的用量包
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("user_addon_packs")
                .select("id, remaining_quota, addon_packs(quota_action)")
                .eq("tenant_id", tenant_id)
                .gt("expires_at", now_iso)
                .gt("remaining_quota", 0)
                .order("expires_at")  # 先用过期最早的
            )

            if not resp.data:
                return

            remaining_qty = quantity
            for row in resp.data:
                pack = row.get("addon_packs")
                if not pack or pack.get("quota_action") != action:
                    continue

                if remaining_qty <= 0:
                    break

                pack_id = row["id"]
                current_remaining = row["remaining_quota"]
                decrement = min(remaining_qty, current_remaining)

                await asyncio.to_thread(
                    _execute_sync,
                    client.table("user_addon_packs")
                    .update({"remaining_quota": current_remaining - decrement})
                    .eq("id", pack_id),
                )

                remaining_qty -= decrement
        except Exception:
            pass
