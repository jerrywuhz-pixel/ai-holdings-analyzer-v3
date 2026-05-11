"""
OpenClaw Gateway — 小程序专用数据端点

桥接小程序数据契约与 Supabase 表结构，
聚合 GatewayDataMiddleware + MemoryMiddleware。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["miniprogram"])


# ── 认证依赖 ──────────────────────────────────────────────────

def _extract_tenant_id(request: Request) -> str:
    """从 JWT 中提取 tenant_id"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token")

    token = auth_header[7:]
    try:
        import jwt as pyjwt

        jwt_secret = request.app.state.jwt_secret if hasattr(request.app.state, "jwt_secret") else "dev-secret-change-in-production"
        payload = pyjwt.decode(token, jwt_secret, algorithms=["HS256"])
        tenant_id = payload.get("sub") or payload.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=401, detail="Invalid token: missing tenant_id")
        return tenant_id
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


# ── 数据转换适配器 ─────────────────────────────────────────────

def miniprogram_position_to_trade_event(pos: dict) -> dict:
    """小程序 position → Supabase trade_events 格式"""
    return {
        "local_id": pos.get("id", ""),
        "symbol": pos.get("symbol") or pos.get("providerSymbol", ""),
        "stock_name": pos.get("name", ""),
        "market": pos.get("market", "A"),
        "exchange": pos.get("exchange", ""),
        "side": pos.get("side", "BUY"),
        "price": float(pos.get("costPrice") or pos.get("price") or 0),
        "quantity": int(pos.get("quantity") or 0),
        "trade_amount": float(pos.get("tradeAmount") or pos.get("trade_amount") or 0),
        "trade_date": pos.get("tradeDate") or pos.get("trade_date", ""),
        "source": pos.get("source", "manual"),
        "strategy_tag": pos.get("strategyTag") or pos.get("strategy_tag", ""),
        "note": pos.get("note", ""),
    }


def trade_event_to_miniprogram_position(event: dict) -> dict:
    """Supabase trade_events → 小程序 position 格式"""
    return {
        "id": event.get("local_id") or event.get("id", ""),
        "symbol": event.get("symbol", ""),
        "providerSymbol": event.get("symbol", ""),
        "name": event.get("stock_name", ""),
        "market": event.get("market", "A"),
        "exchange": event.get("exchange", ""),
        "costPrice": float(event.get("price") or 0),
        "quantity": int(event.get("quantity") or 0),
        "tradeAmount": float(event.get("trade_amount") or 0),
        "tradeDate": event.get("trade_date", ""),
        "note": event.get("note", ""),
        "side": event.get("side", "BUY"),
        "source": event.get("source", "gateway"),
        "strategyTag": event.get("strategy_tag", ""),
        "createdAt": event.get("created_at", ""),
        "updatedAt": event.get("updated_at", ""),
    }


# ── 端点 ──────────────────────────────────────────────────────

@router.get("/portfolio/bootstrap")
async def portfolio_bootstrap(request: Request, tenant_id: str = Depends(_extract_tenant_id)):
    """
    初始化拉取所有用户数据 + gbrain 记忆上下文。

    使用 GatewayDataMiddleware.read_with_context() 一次获取。
    """
    middleware = request.app.state.gateway_middleware

    # 读取交易事件
    trade_events = await middleware.read("trade_events", tenant_id)

    # 读取复盘笔记
    review_notes_raw = await middleware.read("review_notes", tenant_id)
    review_notes = {}
    for note in (review_notes_raw or []):
        key = note.get("note_key", "")
        if key:
            review_notes[key] = note.get("note_value", {})

    # 读取自选股
    watchlist_raw = await middleware.read("watchlist_items", tenant_id)

    # 读取 gbrain 记忆上下文
    brain_context = None
    if hasattr(middleware, "_memory_middleware") and middleware._memory_middleware:
        try:
            brain_context = await middleware._memory_middleware.on_skill_invoke(
                skill_name="position-aggregate",
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.warning("[Miniprogram] Brain context retrieval failed: %s", e)

    return {
        "positions": [trade_event_to_miniprogram_position(e) for e in (trade_events or [])],
        "review_notes": review_notes,
        "watchlist": watchlist_raw or [],
        "brain_context": brain_context,
    }


@router.post("/portfolio/trade-events")
async def sync_trade_events(request: Request, tenant_id: str = Depends(_extract_tenant_id)):
    """
    增量同步交易事件。

    处理流程：
    1. 逐条 upsert trade_events
    2. 触发 position_snapshot 重算
    3. 自动触发 MemoryMiddleware.on_skill_complete
    """
    body = await request.json()
    events = body.get("events", [])

    if not events:
        return {"ok": True, "synced": 0}

    middleware = request.app.state.gateway_middleware
    synced = 0
    errors = []

    for event_data in events:
        # 删除标记
        if event_data.get("_deleted"):
            try:
                local_id = event_data.get("id", "")
                existing = await middleware.read(
                    "trade_events", tenant_id,
                    query={"local_id": local_id},
                )
                for record in (existing or []):
                    await middleware.delete("trade_events", tenant_id, record["id"])
                synced += 1
            except Exception as e:
                errors.append({"id": event_data.get("id"), "error": str(e)})
            continue

        # upsert
        try:
            trade_event = miniprogram_position_to_trade_event(event_data)
            trade_event["tenant_id"] = tenant_id

            # 检查是否已存在
            existing = await middleware.read(
                "trade_events", tenant_id,
                query={"local_id": trade_event["local_id"]},
            )

            if existing:
                record_id = existing[0]["id"]
                await middleware.update("trade_events", tenant_id, record_id, trade_event)
            else:
                await middleware.write("trade_events", tenant_id, trade_event)

            synced += 1
        except Exception as e:
            errors.append({"id": event_data.get("id"), "error": str(e)})

    # 记忆中间件由 write() 的 on_skill_complete 钩子自动触发

    return {"ok": True, "synced": synced, "errors": errors}


@router.post("/portfolio/watchlist")
async def sync_watchlist(request: Request, tenant_id: str = Depends(_extract_tenant_id)):
    """同步自选股"""
    body = await request.json()
    items = body.get("items", [])

    middleware = request.app.state.gateway_middleware
    synced = 0

    for item_data in items:
        if item_data.get("_deleted"):
            try:
                existing = await middleware.read(
                    "watchlist_items", tenant_id,
                    query={"local_id": item_data.get("id", "")},
                )
                for record in (existing or []):
                    await middleware.delete("watchlist_items", tenant_id, record["id"])
                synced += 1
            except Exception:
                pass
            continue

        try:
            watchlist_item = {
                "local_id": item_data.get("id", ""),
                "symbol": item_data.get("symbol", ""),
                "provider_symbol": item_data.get("providerSymbol", item_data.get("symbol", "")),
                "market": item_data.get("market", "A"),
                "exchange": item_data.get("exchange", ""),
                "stock_name": item_data.get("name") or item_data.get("stock_name", ""),
                "investment_thesis": item_data.get("investmentThesis", ""),
                "strike_zone": item_data.get("strikeZone") or item_data.get("strike_zone"),
            }

            existing = await middleware.read(
                "watchlist_items", tenant_id,
                query={"local_id": watchlist_item["local_id"]},
            )

            if existing:
                await middleware.update("watchlist_items", tenant_id, existing[0]["id"], watchlist_item)
            else:
                await middleware.write("watchlist_items", tenant_id, watchlist_item)

            synced += 1
        except Exception:
            pass

    return {"ok": True, "synced": synced}


@router.post("/portfolio/review-notes")
async def sync_review_notes(request: Request, tenant_id: str = Depends(_extract_tenant_id)):
    """同步复盘笔记"""
    body = await request.json()
    notes = body.get("notes", {})

    middleware = request.app.state.gateway_middleware
    synced = 0

    for key, value in (notes or {}).items():
        try:
            existing = await middleware.read(
                "review_notes", tenant_id,
                query={"note_key": key},
            )

            note_data = {"note_key": key, "note_value": value}

            if existing:
                await middleware.update("review_notes", tenant_id, existing[0]["id"], note_data)
            else:
                await middleware.write("review_notes", tenant_id, note_data)

            synced += 1
        except Exception:
            pass

    return {"ok": True, "synced": synced}


@router.get("/analysis/{symbol}")
async def get_analysis(symbol: str, request: Request, tenant_id: str = Depends(_extract_tenant_id)):
    """
    获取个股分析 + gbrain 记忆上下文。

    优先从 daily_analysis 表读取今日分析，
    如无记录则返回 gbrain 上下文供前端展示。
    """
    middleware = request.app.state.gateway_middleware

    # 读取今日分析
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    analysis_records = await middleware.read(
        "daily_analysis", tenant_id,
        query={"analysis_date": today},
    )

    result = {
        "symbol": symbol,
        "analysis_date": today,
    }

    if analysis_records:
        result["data"] = analysis_records[0]
        result["source"] = "daily_analysis"

    # 读取 gbrain 记忆上下文
    if hasattr(middleware, "_memory_middleware") and middleware._memory_middleware:
        try:
            brain_context = await middleware._memory_middleware.on_skill_invoke(
                skill_name="daily-analysis",
                tenant_id=tenant_id,
            )
            if brain_context:
                result["brain_context"] = brain_context
        except Exception as e:
            logger.warning("[Miniprogram] Analysis brain context failed: %s", e)

    return result


@router.get("/portfolio/profit-taking")
async def get_profit_taking_plans(request: Request, tenant_id: str = Depends(_extract_tenant_id)):
    """读取最近的止盈行动计划。"""
    middleware = request.app.state.gateway_middleware
    plans = await middleware.read("profit_taking_plans", tenant_id)
    plans = sorted(
        plans or [],
        key=lambda row: (row.get("plan_date", ""), row.get("created_at", "")),
        reverse=True,
    )
    return {
        "ok": True,
        "plans": plans[:50],
    }


@router.get("/brain/context")
async def get_brain_context(
    request: Request,
    skill: str = "daily-analysis",
    symbol: Optional[str] = None,
    tenant_id: str = Depends(_extract_tenant_id),
):
    """获取 gbrain 记忆上下文"""
    middleware = request.app.state.gateway_middleware

    if not hasattr(middleware, "_memory_middleware") or not middleware._memory_middleware:
        return {"brain_context": None}

    try:
        brain_context = await middleware._memory_middleware.on_skill_invoke(
            skill_name=skill,
            tenant_id=tenant_id,
        )
        return {"brain_context": brain_context}
    except Exception as e:
        logger.warning("[Miniprogram] Brain context failed: %s", e)
        return {"brain_context": None}
