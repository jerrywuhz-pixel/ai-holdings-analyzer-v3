"""
Admin API 路由
================
管理员专用端点：用量统计、审计日志查询、订阅概览、营收汇总。

所有端点均需验证请求者具备 admin 角色。
"""

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["admin"], prefix="/admin")

# --------------------------------------------------------------------------- #
# 依赖：Supabase 客户端（由 main.py 注入或环境变量构建）
# --------------------------------------------------------------------------- #

import os

from supabase._async.client import AsyncClient
from supabase.lib.client_options import ClientOptions


async def _get_admin_client() -> AsyncClient:
    """创建管理员级别的 Supabase 客户端。"""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Supabase credentials not configured")
    return AsyncClient(url, key)


async def _verify_admin(tenant_id: str) -> bool:
    """
    验证请求者是管理员。

    查询 users 表，检查 role = 'admin'。

    Args:
        tenant_id: 请求者用户 ID。

    Returns:
        True 如果是管理员。

    Raises:
        HTTPException 403: 非管理员。
    """
    client = await _get_admin_client()
    try:
        resp = (
            await client.table("users")
            .select("role")
            .eq("id", tenant_id)
            .limit(1)
            .execute()
        )
        if not resp.data or resp.data[0].get("role") != "admin":
            raise HTTPException(status_code=403, detail="Forbidden: admin role required")
        return True
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to verify admin role: {exc}"
        ) from exc
    finally:
        await client.auth.sign_out()


# --------------------------------------------------------------------------- #
# 用量统计
# --------------------------------------------------------------------------- #


@router.get("/usage")
async def get_usage_stats(
    tenant_id: str,
    period: str = Query("month", description="统计周期: day/week/month"),
    action: Optional[str] = None,
) -> dict[str, Any]:
    """
    获取指定租户的用量统计。

    Query:
        tenant_id: 租户 ID（必填）。
        period: 统计周期 day / week / month，默认 month。
        action: 可选，过滤特定动作类型。

    Returns:
        { ok: true, data: { tenant_id, period, stats: [{ action, count, limit }] } }
    """
    await _verify_admin(tenant_id)

    client = await _get_admin_client()
    try:
        now = datetime.now(timezone.utc)
        if period == "day":
            month_key = now.strftime("%Y-%m-%d")
        elif period == "week":
            # ISO week 归档键
            month_key = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
        else:
            month_key = now.strftime("%Y-%m")

        query = (
            client.table("usage_records")
            .select("action")
            .eq("tenant_id", tenant_id)
            .eq("month_key", month_key)
        )
        if action:
            query = query.eq("action", action)

        resp = await query.execute()
        records = resp.data or []

        # 按动作类型聚合计数
        action_counts: dict[str, int] = {}
        for rec in records:
            act = rec.get("action", "unknown")
            action_counts[act] = action_counts.get(act, 0) + 1

        # 查询对应限额
        stats = []
        for act, count in action_counts.items():
            limit_resp = (
                await client.table("plan_limits")
                .select("limit_value, plan")
                .eq("action", act)
                .limit(10)
                .execute()
            )
            limit_info = limit_resp.data[0] if limit_resp.data else {}
            stats.append(
                {
                    "action": act,
                    "count": count,
                    "limit": limit_info.get("limit_value", 0),
                    "plan": limit_info.get("plan", "unknown"),
                }
            )

        return {
            "ok": True,
            "data": {
                "tenant_id": tenant_id,
                "period": period,
                "month_key": month_key,
                "stats": stats,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to get usage stats: {exc}"
        ) from exc
    finally:
        await client.auth.sign_out()


@router.get("/usage/distribution")
async def get_usage_distribution(
    action: str = Query(..., description="分析的动作类型"),
) -> dict[str, Any]:
    """
    获取所有用户的指定动作用量分布。

    Query:
        action: 动作类型（必填）。

    Returns:
        { ok: true, data: [{ tenant_id, plan, count, limit, exceeded }] }
    """
    # 管理员校验 — 使用系统级 tenant_id
    # 注意：此处简化处理，生产环境应从请求头/Token 提取管理员身份
    client = await _get_admin_client()
    try:
        now = datetime.now(timezone.utc)
        month_key = now.strftime("%Y-%m")

        # 聚合 usage_records
        resp = (
            await client.table("usage_records")
            .select("tenant_id")
            .eq("action", action)
            .eq("month_key", month_key)
            .execute()
        )
        records = resp.data or []

        # 按 tenant_id 计数
        tenant_counts: dict[str, int] = {}
        for rec in records:
            tid = rec.get("tenant_id", "")
            tenant_counts[tid] = tenant_counts.get(tid, 0) + 1

        # 查询每个用户的套餐与限额
        result = []
        for tid, count in tenant_counts.items():
            # 获取套餐
            sub_resp = (
                await client.table("subscriptions")
                .select("plan")
                .eq("tenant_id", tid)
                .eq("status", "active")
                .limit(1)
                .execute()
            )
            plan = sub_resp.data[0].get("plan", "free") if sub_resp.data else "free"

            # 获取限额
            limit_resp = (
                await client.table("plan_limits")
                .select("limit_value")
                .eq("plan", plan)
                .eq("action", action)
                .limit(1)
                .execute()
            )
            limit_val = limit_resp.data[0].get("limit_value", 0) if limit_resp.data else 0

            result.append(
                {
                    "tenant_id": tid,
                    "plan": plan,
                    "count": count,
                    "limit": limit_val,
                    "exceeded": count >= limit_val if limit_val > 0 else False,
                }
            )

        return {"ok": True, "data": result}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to get usage distribution: {exc}"
        ) from exc
    finally:
        await client.auth.sign_out()


# --------------------------------------------------------------------------- #
# 审计日志
# --------------------------------------------------------------------------- #


@router.get("/audit-logs")
async def get_audit_logs(
    tenant_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """
    查询审计日志（分页）。

    Query:
        tenant_id: 可选，按租户过滤。
        action: 可选，按动作类型过滤。
        limit: 分页大小，默认 50，最大 200。
        offset: 分页偏移，默认 0。

    Returns:
        { ok: true, data: [...], total: N }
    """
    client = await _get_admin_client()
    try:
        query = client.table("audit_logs").select("*", count="exact")

        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        if action:
            query = query.eq("action", action)

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        resp = await query.execute()

        return {
            "ok": True,
            "data": resp.data or [],
            "total": resp.count if resp.count is not None else len(resp.data or []),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to get audit logs: {exc}"
        ) from exc
    finally:
        await client.auth.sign_out()


# --------------------------------------------------------------------------- #
# 订阅概览
# --------------------------------------------------------------------------- #


@router.get("/subscriptions")
async def get_all_subscriptions(
    plan: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """
    获取所有用户订阅列表。

    Query:
        plan: 可选，按套餐类型过滤（free/basic/pro）。
        status: 可选，按状态过滤（active/canceled/expired）。

    Returns:
        { ok: true, data: [...] }
    """
    client = await _get_admin_client()
    try:
        query = client.table("subscriptions").select("*")

        if plan:
            query = query.eq("plan", plan)
        if status:
            query = query.eq("status", status)

        query = query.order("created_at", desc=True).limit(200)

        resp = await query.execute()

        return {"ok": True, "data": resp.data or []}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to get subscriptions: {exc}"
        ) from exc
    finally:
        await client.auth.sign_out()


# --------------------------------------------------------------------------- #
# 营收汇总
# --------------------------------------------------------------------------- #


@router.get("/revenue/summary")
async def get_revenue_summary() -> dict[str, Any]:
    """
    管理后台营收概览。

    Returns:
        { ok: true, data: { total_users, by_plan, monthly_revenue } }
    """
    client = await _get_admin_client()
    try:
        # 1. 统计各套餐用户数
        subs_resp = (
            await client.table("subscriptions")
            .select("plan, status")
            .execute()
        )
        subs = subs_resp.data or []

        by_plan: dict[str, int] = {"free": 0, "basic": 0, "pro": 0}
        for sub in subs:
            plan = sub.get("plan", "free")
            by_plan[plan] = by_plan.get(plan, 0) + 1

        total_users = sum(by_plan.values())

        # 2. 当月 addon 购买营收
        now = datetime.now(timezone.utc)
        month_key = now.strftime("%Y-%m")

        addon_resp = (
            await client.table("addon_packs")
            .select("price")
            .eq("status", "active")
            .execute()
        )
        addons = addon_resp.data or []
        addon_revenue = sum(a.get("price", 0) or 0 for a in addons)

        # 3. 套餐月费营收（简化估算）
        plan_prices = {"free": 0, "basic": 29, "pro": 99}
        subscription_revenue = sum(
            by_plan.get(plan, 0) * price for plan, price in plan_prices.items()
        )

        monthly_revenue = subscription_revenue + addon_revenue

        return {
            "ok": True,
            "data": {
                "total_users": total_users,
                "by_plan": by_plan,
                "subscription_revenue": subscription_revenue,
                "addon_revenue": addon_revenue,
                "monthly_revenue": monthly_revenue,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to get revenue summary: {exc}"
        ) from exc
    finally:
        await client.auth.sign_out()
