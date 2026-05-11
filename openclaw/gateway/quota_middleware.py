"""
Skill 配额检查中间件
========================
在 Skill 执行前检查用户套餐配额，超配额时返回升级提示。

与 GatewayDataMiddleware 的底层配额检查（quota_tracking 表）不同，
本中间件聚焦于 Skill 级别的月度配额管控，基于 plan_limits 与
usage_records 表实现按套餐、按动作类型的精细额度校验。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 数据类
# --------------------------------------------------------------------------- #


@dataclass
class QuotaCheckResult:
    """配额检查结果。"""

    allowed: bool
    plan: str
    action: str
    used: int
    limit: int
    remaining: int
    upgrade_message: str = ""


# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

# Skill → quota action 映射
SKILL_ACTION_MAP: dict[str, Optional[str]] = {
    "trade-input": "trade_write",
    "broker-parse": "trade_write",
    "position-aggregate": "data_read",
    "daily-analysis": "ai_analysis",
    "daily-review": "ai_analysis",
    "opportunity-hunter": "ai_analysis",
    "weekly-report": "ai_analysis",
    "profit-taking": "ai_analysis",
    "heartbeat": None,  # heartbeat 免费，不检查配额
}

# 套餐升级建议
UPGRADE_SUGGESTIONS: dict[tuple[str, str], str] = {
    ("free", "ai_analysis"): "升级标准版(29元/月)获取每日200次AI分析",
    ("free", "trade_write"): "升级标准版解除交易记录限制",
    ("free", "max_positions"): "升级标准版解除持仓数量限制",
    ("free", "data_read"): "升级标准版获取更多数据读取额度",
    ("basic", "ai_analysis"): "升级专业版(99元/月)获取无限AI分析",
    ("basic", "data_read"): "升级专业版获取深度数据源",
    ("basic", "trade_write"): "升级专业版获取无限交易记录",
}

# 默认配额（兜底，plan_limits 表无记录时使用）
DEFAULT_LIMITS: dict[str, dict[str, int]] = {
    "free": {
        "ai_analysis": 10,
        "trade_write": 5,
        "data_read": 50,
        "max_positions": 10,
    },
    "basic": {
        "ai_analysis": 200,
        "trade_write": 50,
        "data_read": 500,
        "max_positions": 100,
    },
    "pro": {
        "ai_analysis": -1,  # -1 表示无限制
        "trade_write": -1,
        "data_read": -1,
        "max_positions": -1,
    },
}


# --------------------------------------------------------------------------- #
# 中间件主体
# --------------------------------------------------------------------------- #


class SkillQuotaMiddleware:
    """
    OpenClaw Skill 配额检查中间件。

    在 Skill 执行前检查用户套餐配额，超配额时返回升级提示。
    工作流程：
    1. 根据 SKILL_ACTION_MAP 获取 Skill 对应的 quota action
    2. 查询用户当前套餐
    3. 从 plan_limits 表获取套餐限额（兜底 DEFAULT_LIMITS）
    4. 从 usage_records 表统计当月用量
    5. 查询 addon_packs 获取额外额度
    6. 比较用量与限额，生成 QuotaCheckResult
    """

    def __init__(self, supabase_client=None) -> None:
        """
        Args:
            supabase_client: Supabase 异步客户端实例（需具备 service_role 权限
                以读取所有租户的 plan_limits / usage_records）。
        """
        self._client = supabase_client

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #

    async def check_skill_quota(
        self, tenant_id: str, skill_name: str
    ) -> QuotaCheckResult:
        """
        检查租户是否被允许执行指定 Skill。

        Args:
            tenant_id: 租户 ID。
            skill_name: Skill 标识名，如 ``daily-analysis``。

        Returns:
            :class:`QuotaCheckResult` 包含是否允许、当前用量、限额等。
        """
        action = SKILL_ACTION_MAP.get(skill_name)
        if action is None:
            # 无配额映射的 Skill 免费放行
            return QuotaCheckResult(
                allowed=True, plan="", action="", used=0, limit=0, remaining=0
            )

        if self._client is None:
            # 无数据库连接时降级放行
            logger.warning("No Supabase client, allowing skill %s for %s", skill_name, tenant_id)
            return QuotaCheckResult(
                allowed=True, plan="unknown", action=action, used=0, limit=0, remaining=0
            )

        # 1. 获取用户套餐
        plan = await self._get_user_plan(tenant_id)

        # 2. 获取套餐限额
        limit = await self._get_plan_limit(plan, action)

        # 3. 获取当月用量
        used = await self._get_current_usage(tenant_id, action)

        # 4. 获取 addon 额度
        addon_extra = await self._get_addon_extra(tenant_id, action)
        effective_limit = limit + addon_extra if limit != -1 else -1

        # 5. 判断是否超限
        if effective_limit == -1:
            # 无限制
            return QuotaCheckResult(
                allowed=True,
                plan=plan,
                action=action,
                used=used,
                limit=-1,
                remaining=-1,
            )

        remaining = max(effective_limit - used, 0)
        allowed = used < effective_limit

        upgrade_message = ""
        if not allowed:
            upgrade_message = self._get_upgrade_message(plan, action)

        return QuotaCheckResult(
            allowed=allowed,
            plan=plan,
            action=action,
            used=used,
            limit=effective_limit,
            remaining=remaining,
            upgrade_message=upgrade_message,
        )

    async def record_skill_usage(
        self, tenant_id: str, skill_name: str
    ) -> None:
        """
        记录 Skill 使用一次。

        向 ``usage_records`` 表插入一条记录，含当月归档键。

        Args:
            tenant_id: 租户 ID。
            skill_name: Skill 标识名。
        """
        action = SKILL_ACTION_MAP.get(skill_name)
        if action is None:
            return

        if self._client is None:
            return

        now = datetime.now(timezone.utc)
        month_key = now.strftime("%Y-%m")

        payload = {
            "tenant_id": tenant_id,
            "action": action,
            "skill_name": skill_name,
            "month_key": month_key,
            "created_at": now.isoformat(),
        }

        try:
            await self._client.table("usage_records").insert(payload).execute()
        except Exception as exc:
            logger.warning(
                "Failed to record usage for %s/%s: %s", tenant_id, skill_name, exc
            )

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    async def _get_user_plan(self, tenant_id: str) -> str:
        """从 subscriptions 表获取用户套餐，默认 free。"""
        try:
            resp = (
                await self._client.table("subscriptions")
                .select("plan")
                .eq("tenant_id", tenant_id)
                .eq("status", "active")
                .limit(1)
                .execute()
            )
            if resp.data:
                return resp.data[0].get("plan", "free")
        except Exception as exc:
            logger.warning("Failed to get plan for %s: %s", tenant_id, exc)
        return "free"

    async def _get_plan_limit(self, plan: str, action: str) -> int:
        """
        从 plan_limits 表获取套餐限额。

        无记录时回退到 DEFAULT_LIMITS，再无则默认 0（禁止）。
        """
        try:
            resp = (
                await self._client.table("plan_limits")
                .select("limit_value")
                .eq("plan", plan)
                .eq("action", action)
                .limit(1)
                .execute()
            )
            if resp.data:
                return resp.data[0].get("limit_value", 0)
        except Exception as exc:
            logger.warning("Failed to get plan limit for %s/%s: %s", plan, action, exc)

        # 兜底到硬编码默认值
        return DEFAULT_LIMITS.get(plan, {}).get(action, 0)

    async def _get_current_usage(self, tenant_id: str, action: str) -> int:
        """从 usage_records 统计当月用量。"""
        now = datetime.now(timezone.utc)
        month_key = now.strftime("%Y-%m")

        try:
            resp = (
                await self._client.table("usage_records")
                .select("id", count="exact")
                .eq("tenant_id", tenant_id)
                .eq("action", action)
                .eq("month_key", month_key)
                .execute()
            )
            return resp.count if resp.count is not None else len(resp.data or [])
        except Exception as exc:
            logger.warning("Failed to get usage for %s/%s: %s", tenant_id, action, exc)
            return 0

    async def _get_addon_extra(self, tenant_id: str, action: str) -> int:
        """从 addon_packs 获取额外额度。"""
        try:
            resp = (
                await self._client.table("addon_packs")
                .select("extra_quota")
                .eq("tenant_id", tenant_id)
                .eq("action", action)
                .eq("status", "active")
                .execute()
            )
            if resp.data:
                return sum(row.get("extra_quota", 0) for row in resp.data)
        except Exception as exc:
            logger.warning("Failed to get addon for %s/%s: %s", tenant_id, action, exc)
        return 0

    def _get_upgrade_message(self, plan: str, action: str) -> str:
        """生成升级建议消息。"""
        return UPGRADE_SUGGESTIONS.get((plan, action), "升级套餐获取更多额度")
