from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Literal, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from services.hermes.domain_tools import DomainToolError, DomainToolsFacade, domain_tool_manifest
from services.hermes.alerts import HermesAlertCenter, HermesAlertEvaluator
from services.hermes.delivery import HermesDeliveryProcessor
from services.hermes.ima_archive import HermesImaArchiveService
from services.hermes.stock_analysis import MAX_REPORT_MODULE_CHARS, StockAnalysisPersistence
from services.hermes.watchlist import HermesWatchlistService

router = APIRouter(prefix="/hermes", tags=["hermes"])
logger = logging.getLogger(__name__)

QUOTE_KEYWORDS = (
    "实时行情",
    "行情",
    "报价",
    "股价",
    "quote",
    "price",
)
QUOTE_SYMBOL_RE = re.compile(
    r"(?<![A-Z0-9])(?:SH|SZ|HK)?[A-Z]{1,6}\d{0,5}(?![A-Z0-9])|(?<!\d)\d{6}(?!\d)"
)
POSITION_KEYWORDS = ("持仓", "仓位", "组合", "portfolio", "positions", "position", "我的股票", "我的账户")
SELL_PUT_KEYWORDS = ("sell put", "卖put", "卖 put", "现金担保", "covered put")
STOCK_ANALYSIS_KEYWORDS = (
    "分析",
    "怎么看",
    "看下",
    "看一下",
    "要不要",
    "止盈",
    "止损",
    "值得买吗",
    "值不值得",
    "复核",
)
PUBLIC_URL_RE = re.compile(r"https?://[^\s<>'\"，。；、！？）)】]+", re.IGNORECASE)
REFERENCE_SEARCH_KEYWORDS = (
    "搜索",
    "搜一下",
    "网上查",
    "网页资料",
    "公开资料",
    "公众号",
    "小红书",
    "文章",
    "新闻",
    "news",
    "search",
)
USER_FACING_RECOVERY_TEXT = "系统处理暂时受阻，请稍后重试。当前没有改动持仓，也不会下单。"
INTERNAL_STATUS_TEXT_PATTERNS = (
    re.compile(r"gateway\s+shutting\s+down", re.IGNORECASE),
    re.compile(r"current\s+task\s+will\s+be\s+interrupted", re.IGNORECASE),
    re.compile(r"not\s+accepting\s+another\s+turn", re.IGNORECASE),
    re.compile(r"compacting\s+context", re.IGNORECASE),
    re.compile(r"context\s+compaction", re.IGNORECASE),
    re.compile(r"preflight\s+compression", re.IGNORECASE),
    re.compile(r"compression\s+summary\s+failed", re.IGNORECASE),
    re.compile(r"fallback\s+context\s+marker", re.IGNORECASE),
    re.compile(r"\b\d{4,}[,\d]*\s+tokens?\b", re.IGNORECASE),
    re.compile(r"connection\s+error", re.IGNORECASE),
    re.compile(r"provider\s+returned\s+an\s+empty\s+response", re.IGNORECASE),
)


class DomainToolInvokeRequest(BaseModel):
    tool: str = Field(..., min_length=1)
    tenant_id: Optional[str] = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None


class HermesRoutingPayload(BaseModel):
    tenant_id: str
    channel_binding_id: Optional[str] = None
    channel_account_id: Optional[str] = None
    openclaw_account_id: Optional[str] = None
    channel: str = "hermes_wechat"
    session_space: Optional[str] = None
    context_token: Optional[str] = None
    target_conversation: Optional[str] = None
    quiet_hours: Optional[dict[str, Any]] = None
    timezone: str = "Asia/Shanghai"


class HermesMessagePayload(BaseModel):
    id: Optional[str] = None
    type: Literal["text", "voice", "image", "event"]
    text: Optional[str] = None
    transcript: Optional[str] = None
    transcript_confidence: Optional[float] = None
    ocr_text: Optional[str] = None
    image_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    media_id: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HermesWechatIngressRequest(BaseModel):
    routing: HermesRoutingPayload
    message: HermesMessagePayload


class HermesWechatAnalysisArtifactRequest(BaseModel):
    routing: HermesRoutingPayload
    message: HermesMessagePayload
    hermes_result: dict[str, Any] = Field(default_factory=dict)
    reply_text: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HermesAlertEvaluateRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    dry_run: bool = False


class HermesAlertCenterRunRequest(BaseModel):
    cycle: Literal["premarket", "intraday", "postmarket"]
    limit: int = Field(default=50, ge=1, le=200)
    dry_run: bool = False


class HermesDeliveryProcessRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    dry_run: bool = False


class HermesImaArchiveRequest(BaseModel):
    source: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    content_markdown: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    tenant_id: Optional[str] = None
    prompt: Optional[str] = None
    result_type: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HermesWechatTraceRequest(BaseModel):
    tenant_id: Optional[str] = None
    channel_binding_id: Optional[str] = None
    channel_account_id: Optional[str] = None
    openclaw_account_id: Optional[str] = None
    message_id: Optional[str] = None
    message_text: Optional[str] = None
    window_minutes: int = Field(default=120, ge=5, le=1440)
    limit: int = Field(default=8, ge=1, le=50)


_domain_tools_facade: DomainToolsFacade | None = None


def _domain_tools() -> DomainToolsFacade:
    global _domain_tools_facade
    if _domain_tools_facade is None:
        _domain_tools_facade = DomainToolsFacade()
    return _domain_tools_facade


def _verify_internal_request(request: Request) -> None:
    expected = os.getenv("HERMES_DOMAIN_TOOLS_KEY") or os.getenv("HERMES_INTERNAL_TOKEN", "")
    if not expected:
        return
    supplied = (
        request.headers.get("X-Hermes-Domain-Tools-Key")
        or request.headers.get("X-Hermes-Internal-Token")
        or request.headers.get("X-OpenClaw-Skill-Key")
    )
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail={"ok": False, "message": "invalid Hermes internal key"})


@router.get("/domain-tools")
async def list_domain_tools(request: Request) -> dict[str, Any]:
    _verify_internal_request(request)
    return {"ok": True, "runtime": "hermes", "tools": domain_tool_manifest()}


@router.post("/domain-tools/invoke")
async def invoke_domain_tool(payload: DomainToolInvokeRequest, request: Request) -> dict[str, Any]:
    _verify_internal_request(request)
    arguments = dict(payload.arguments)
    if payload.tenant_id and "tenant_id" not in arguments:
        arguments["tenant_id"] = payload.tenant_id
    try:
        result = await _domain_tools().invoke(payload.tool, arguments)
        return {"ok": result.get("ok", False), "runtime": "hermes", "result": result, "run_id": payload.run_id}
    except DomainToolError as exc:
        return {
            "ok": False,
            "runtime": "hermes",
            "run_id": payload.run_id,
            "result": {
                "tool": payload.tool,
                "ok": False,
                "status": "error",
                "error": str(exc),
            },
        }
    except httpx.HTTPStatusError as exc:
        logger.warning("Hermes domain tool upstream HTTP error: %s", exc)
        return {
            "ok": False,
            "runtime": "hermes",
            "run_id": payload.run_id,
            "result": {
                "tool": payload.tool,
                "ok": False,
                "status": "upstream_error",
                "error": str(exc),
                "upstream_status_code": exc.response.status_code,
            },
        }
    except Exception as exc:
        logger.exception("Hermes domain tool invocation failed")
        return {
            "ok": False,
            "runtime": "hermes",
            "run_id": payload.run_id,
            "result": {
                "tool": payload.tool,
                "ok": False,
                "status": "error",
                "error": str(exc),
            },
        }


@router.post("/wechat/messages")
async def ingest_wechat_message(
    payload: HermesWechatIngressRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    _verify_internal_request(request)
    result = await _build_wechat_message_response(payload, background_tasks)
    _schedule_ima_archive(
        background_tasks,
        source="wechat_user_reply",
        title=_archive_title_from_result(result, fallback="Hermes 用户回复"),
        content_markdown=result.get("reply_text"),
        payload=result,
        tenant_id=payload.routing.tenant_id,
        prompt=_message_text(payload.message),
        result_type=result.get("result_type"),
        metadata={
            "channel": payload.routing.channel,
            "message_id": payload.message.id,
            "message_type": payload.message.type,
        },
    )
    return result


async def _build_wechat_message_response(
    payload: HermesWechatIngressRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    text = _message_text(payload.message)
    if payload.message.type == "event":
        return _reply("ignored", "这类事件已收到，当前没有改动持仓，也没有下单。", intent={"name": "event"})

    reference_url = _extract_first_url(text)
    if reference_url:
        text_without_url = _strip_urls(text)
        analysis_symbol = _extract_analysis_symbol(text_without_url)
        if analysis_symbol:
            return await _reference_reply_with_timeout(
                routing=payload.routing,
                prompt=text,
                background_tasks=background_tasks,
                content_type="stock_analysis_reference_result",
                intent={"name": "stock_analysis_with_web_reference", "symbol": analysis_symbol, "url": reference_url},
                work=lambda: _stock_analysis_with_web_reference_reply(
                    symbol=analysis_symbol,
                    tenant_id=payload.routing.tenant_id,
                    prompt=text,
                    url=reference_url,
                ),
            )
        return await _reference_reply_with_timeout(
            routing=payload.routing,
            prompt=text,
            background_tasks=background_tasks,
            content_type="web_reference_result",
            intent={"name": "web_reference_read", "url": reference_url},
            work=lambda: _web_reference_reply(payload.routing.tenant_id, text, reference_url),
        )

    if _looks_like_social_signal_query(text):
        analysis_symbol = _extract_analysis_symbol(text)
        if analysis_symbol:
            return await _stock_analysis_with_social_context_reply(
                analysis_symbol,
                payload.routing.tenant_id,
                text,
            )

    if _looks_like_reference_search(text):
        analysis_symbol = _extract_analysis_symbol(text)
        search_query = _reference_search_query(text, symbol=analysis_symbol)
        if analysis_symbol:
            return await _reference_reply_with_timeout(
                routing=payload.routing,
                prompt=text,
                background_tasks=background_tasks,
                content_type="stock_analysis_reference_result",
                intent={"name": "stock_analysis_with_search_reference", "symbol": analysis_symbol, "query": search_query},
                work=lambda: _stock_analysis_with_search_reference_reply(
                    symbol=analysis_symbol,
                    tenant_id=payload.routing.tenant_id,
                    prompt=text,
                    query=search_query,
                ),
            )
        return await _reference_reply_with_timeout(
            routing=payload.routing,
            prompt=text,
            background_tasks=background_tasks,
            content_type="web_reference_search_result",
            intent={"name": "web_reference_search", "query": search_query},
            work=lambda: _web_reference_search_reply(payload.routing.tenant_id, text, search_query),
        )

    if _looks_like_watchlist_query(text):
        return await _watchlist_query_reply(payload.routing.tenant_id)

    archive_symbol = _extract_archive_watch_symbol(text)
    if archive_symbol:
        return await _archive_watch_reply(payload.routing.tenant_id, archive_symbol)

    watch_command = _parse_watch_command(text)
    if watch_command:
        return await _watch_command_reply(payload.routing.tenant_id, watch_command)

    quote_symbol = _extract_quote_symbol(text)
    if quote_symbol:
        return await _quote_reply(quote_symbol, payload.routing.tenant_id)

    analysis_symbol = _extract_analysis_symbol(text)
    if analysis_symbol:
        return await _stock_analysis_reply(analysis_symbol, payload.routing.tenant_id, text)

    if _looks_like_positions_query(text):
        return await _positions_reply(payload.routing.tenant_id)

    if _looks_like_sell_put_request(text):
        return await _sell_put_draft_reply(text, payload.routing.tenant_id)

    if payload.message.type == "image":
        extracted = payload.message.ocr_text or payload.message.image_text or text
        if extracted.strip():
            return _reply(
                "image_received",
                f"已收到截图识别内容：{extracted.strip()[:300]}\n我会把它作为只读线索处理，不会直接改动持仓或下单。",
                intent={"name": "image_note"},
                safety={"mode": "read_only", "writes_fact_store": False, "places_orders": False},
            )
        return _reply(
            "image_received",
            "已收到截图。当前没有可用识别文本，我不会改动持仓或下单。",
            intent={"name": "image_note"},
            safety={"mode": "read_only", "writes_fact_store": False, "places_orders": False},
        )

    if payload.message.type == "voice":
        if text:
            return _reply(
                "voice_received",
                f"已收到语音内容：{text[:300]}\n当前仅做记录和只读回复，不会直接改动持仓或下单。",
                intent={"name": "voice_note"},
                safety={"mode": "read_only", "writes_fact_store": False, "places_orders": False},
            )
        return _reply(
            "voice_received",
            "已收到语音消息。当前没有可用转写文本，我不会改动持仓或下单。",
            intent={"name": "voice_note"},
            safety={"mode": "read_only", "writes_fact_store": False, "places_orders": False},
        )

    if _looks_like_trade_input(text):
        return _reply(
            "readonly_acknowledgement",
            "已收到你的持仓/交易描述。本阶段 Hermes 只做只读分析和草稿提示，不会直接写入事实库或自动下单。",
            intent={"name": "trade_note"},
            safety={"mode": "read_only_trade_draft_only", "writes_fact_store": False, "places_orders": False},
        )

    return _reply(
        "hermes_reply",
        "Hermes 已收到请求。你可以直接问“我的持仓怎么样”或“NVDA 行情”，我会通过只读工具查询真实数据；涉及交易时只给分析和草稿，不会自动下单。",
        intent={"name": "general_help"},
        safety={"mode": "read_only", "writes_fact_store": False, "places_orders": False},
    )


@router.post("/wechat/analysis-artifacts")
async def persist_wechat_analysis_artifact(payload: HermesWechatAnalysisArtifactRequest, request: Request) -> dict[str, Any]:
    _verify_internal_request(request)
    hermes_result = payload.hermes_result if isinstance(payload.hermes_result, dict) else {}
    existing_persistence = _existing_persistence(hermes_result)
    if existing_persistence.get("status") == "saved":
        return {
            "ok": True,
            "runtime": "hermes",
            "result_type": "analysis_artifact_persist",
            "persistence": {"status": "skipped", "reason": "already_saved", "existing": existing_persistence},
        }

    reply_text = (payload.reply_text or _reply_text_from_result(hermes_result)).strip()
    symbol = _analysis_symbol_from_result(hermes_result, reply_text, _message_text(payload.message))
    if not symbol:
        return {
            "ok": True,
            "runtime": "hermes",
            "result_type": "analysis_artifact_persist",
            "persistence": {"status": "skipped", "reason": "symbol_not_detected"},
        }

    analysis = _external_analysis_payload(
        symbol=symbol,
        reply_text=reply_text,
        hermes_result=hermes_result,
        prompt=_message_text(payload.message),
    )
    context = {
        "schema_version": "wechat_analysis_context_p1",
        "tenant_id": payload.routing.tenant_id,
        "symbol": symbol,
        "prompt": _message_text(payload.message),
        "channel_binding_id": payload.routing.channel_binding_id,
        "channel_account_id": payload.routing.channel_account_id,
        "openclaw_account_id": payload.routing.openclaw_account_id,
        "context_token": payload.routing.context_token,
        "target_conversation": payload.routing.target_conversation,
        "source_refs": [{"source": "hermes-wechat", "ref": payload.message.id or "wechat-message"}],
        "hermes_result": _compact_jsonish(hermes_result, max_chars=12000),
        "metadata": payload.metadata,
    }
    persistence = await StockAnalysisPersistence.from_env().save(
        tenant_id=payload.routing.tenant_id,
        symbol=symbol,
        analysis=analysis,
        context=context,
        entry_surface="wechat",
        create_alert_drafts=True,
    )
    return {
        "ok": True,
        "runtime": "hermes",
        "result_type": "analysis_artifact_persist",
        "symbol": symbol,
        "persistence": persistence,
    }


@router.post("/alerts/evaluate")
async def evaluate_alerts(payload: HermesAlertEvaluateRequest, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    _verify_internal_request(request)

    async def quote_reader(symbol: str, tenant_id: str) -> dict[str, Any]:
        return await _invoke_tool("market.quote", {"symbol": symbol}, tenant_id=tenant_id)

    result = await HermesAlertEvaluator.from_env(quote_reader=quote_reader).evaluate(
        limit=payload.limit,
        dry_run=payload.dry_run,
    )
    response = {"ok": bool(result.get("ok")), "runtime": "hermes", "result_type": "alert_evaluation", **result}
    _schedule_ima_archive(
        background_tasks,
        source="scheduled_analysis",
        title="Hermes 价格提醒评估",
        content_markdown=_markdown_from_payload(response),
        payload=response,
        result_type="alert_evaluation",
        metadata={"dry_run": payload.dry_run, "limit": payload.limit},
    )
    return response


@router.post("/alert-center/run")
async def run_alert_center(payload: HermesAlertCenterRunRequest, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    _verify_internal_request(request)

    if payload.cycle == "intraday":
        async def quote_reader(symbol: str, tenant_id: str) -> dict[str, Any]:
            return await _invoke_tool("market.quote", {"symbol": symbol}, tenant_id=tenant_id)

        result = await HermesAlertEvaluator.from_env(quote_reader=quote_reader).evaluate(
            limit=payload.limit,
            dry_run=payload.dry_run,
        )
    elif payload.cycle == "premarket":
        result = await HermesAlertCenter.from_env().run_premarket(limit=payload.limit, dry_run=payload.dry_run)
    else:
        result = await HermesAlertCenter.from_env().run_postmarket(limit=payload.limit, dry_run=payload.dry_run)

    response = {"ok": bool(result.get("ok")), "runtime": "hermes", "result_type": "alert_center_run", **result}
    _schedule_ima_archive(
        background_tasks,
        source="scheduled_analysis",
        title=f"Hermes {payload.cycle} 定时分析",
        content_markdown=_markdown_from_payload(response),
        payload=response,
        result_type="alert_center_run",
        metadata={"cycle": payload.cycle, "dry_run": payload.dry_run, "limit": payload.limit},
    )
    return response


@router.post("/delivery/process-ready")
async def process_ready_deliveries(payload: HermesDeliveryProcessRequest, request: Request) -> dict[str, Any]:
    _verify_internal_request(request)
    result = await HermesDeliveryProcessor.from_env().process_ready(limit=payload.limit, dry_run=payload.dry_run)
    return {"ok": bool(result.get("ok")), "runtime": "hermes", "result_type": "delivery_process_ready", **result}


@router.post("/ima/archive")
async def archive_ima_markdown(payload: HermesImaArchiveRequest, request: Request) -> dict[str, Any]:
    _verify_internal_request(request)
    result = await HermesImaArchiveService.from_env().archive(
        source=payload.source,
        title=payload.title,
        content_markdown=payload.content_markdown,
        payload=payload.payload,
        tenant_id=payload.tenant_id,
        prompt=payload.prompt,
        result_type=payload.result_type,
        metadata=payload.metadata,
    )
    return {"ok": result.get("status") in {"saved", "synced"}, "runtime": "hermes", "result_type": "ima_archive", "archive": result}


@router.post("/wechat/trace")
async def trace_wechat_message(payload: HermesWechatTraceRequest, request: Request) -> dict[str, Any]:
    _verify_internal_request(request)
    trace = _build_wechat_trace(payload)
    return {"ok": True, "runtime": "hermes", "result_type": "wechat_trace", **trace}


@router.post("/openclaw/wechat/messages")
async def legacy_openclaw_wechat_alias(
    payload: HermesWechatIngressRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Compatibility alias for old bridge callers; runtime is still Hermes."""

    result = await ingest_wechat_message(payload, request, background_tasks)
    result["legacy_alias"] = "/api/openclaw/wechat/messages"
    return result


def _message_text(message: HermesMessagePayload) -> str:
    return (message.text or message.transcript or message.ocr_text or message.image_text or "").strip()


def _reply(result_type: str, reply_text: str, **extra: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "runtime": "hermes",
        "result_type": result_type,
        "reply_text": _sanitize_user_facing_reply_text(reply_text),
        **extra,
    }


def _sanitize_user_facing_reply_text(reply_text: str) -> str:
    text = str(reply_text or "").strip()
    if not text:
        return USER_FACING_RECOVERY_TEXT

    text = re.sub(
        r"(搜索资料暂时不可用，未作为事实依据)[：:][^\n。]*",
        r"\1",
        text,
    )
    text = re.sub(
        r"(链接资料暂时读不到，未作为事实依据)[：:][^\n。]*",
        r"\1",
        text,
    )
    text = (
        text.replace("reference_only", "参考资料")
        .replace("analysis_only", "仅分析")
        .replace("trade_draft", "交易草稿")
    )

    kept_lines: list[str] = []
    dropped_internal_line = False
    for line in text.splitlines():
        if _is_internal_status_text(line):
            dropped_internal_line = True
            continue
        kept_lines.append(line)

    cleaned = "\n".join(kept_lines).strip()
    if cleaned:
        return cleaned
    return USER_FACING_RECOVERY_TEXT if dropped_internal_line else text


def _is_internal_status_text(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in INTERNAL_STATUS_TEXT_PATTERNS)


def _schedule_ima_archive(
    background_tasks: BackgroundTasks,
    *,
    source: str,
    title: str,
    content_markdown: str | None,
    payload: dict[str, Any],
    tenant_id: str | None = None,
    prompt: str | None = None,
    result_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    background_tasks.add_task(
        _archive_ima_background,
        source,
        title,
        content_markdown,
        payload,
        tenant_id,
        prompt,
        result_type,
        metadata or {},
    )


async def _archive_ima_background(
    source: str,
    title: str,
    content_markdown: str | None,
    payload: dict[str, Any],
    tenant_id: str | None,
    prompt: str | None,
    result_type: str | None,
    metadata: dict[str, Any],
) -> None:
    result = await HermesImaArchiveService.from_env().archive(
        source=source,
        title=title,
        content_markdown=content_markdown,
        payload=payload,
        tenant_id=tenant_id,
        prompt=prompt,
        result_type=result_type,
        metadata=metadata,
    )
    if result.get("status") not in {"skipped", "saved", "synced"}:
        logger.warning("Hermes IMA archive failed: %s", result)


def _archive_title_from_result(result: dict[str, Any], *, fallback: str) -> str:
    intent = result.get("intent") if isinstance(result.get("intent"), dict) else {}
    symbol = intent.get("symbol") if isinstance(intent, dict) else None
    result_type = str(result.get("result_type") or fallback)
    if symbol:
        return f"{result_type} {symbol}"
    return result_type


def _markdown_from_payload(payload: dict[str, Any]) -> str:
    lines = []
    title = payload.get("result_type") or "Hermes output"
    lines.append(f"## {title}")
    if "ok" in payload:
        lines.append(f"- ok: {payload.get('ok')}")
    if payload.get("cycle"):
        lines.append(f"- cycle: {payload.get('cycle')}")
    if payload.get("status"):
        lines.append(f"- status: {payload.get('status')}")
    reply_text = payload.get("reply_text")
    if reply_text:
        lines.extend(["", str(reply_text)])
    return "\n".join(lines).strip()


def _build_wechat_trace(payload: HermesWechatTraceRequest) -> dict[str, Any]:
    db_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or ""
    if not db_url:
        return {
            "trace_status": "UNKNOWN",
            "db_available": False,
            "reason": "DATABASE_URL_missing",
            "stages": [_trace_stage("input", "unknown", "DB trace skipped because DATABASE_URL is not configured", [])],
        }

    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:  # noqa: BLE001 - trace must explain missing optional driver
        return {
            "trace_status": "UNKNOWN",
            "db_available": False,
            "reason": f"psycopg_unavailable: {exc}",
            "stages": [_trace_stage("input", "unknown", "DB trace skipped because psycopg is unavailable", [])],
        }

    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=payload.window_minutes)
    stages: list[dict[str, Any]] = []
    meta = {
        "tenant_id": payload.tenant_id,
        "channel_binding_id": payload.channel_binding_id,
        "channel_account_id": payload.channel_account_id or payload.openclaw_account_id,
        "message_id": payload.message_id,
        "message_text_preview": (payload.message_text or "")[:120],
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
    }

    try:
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            binding_rows = _trace_bindings(conn, payload, limit=payload.limit)
            stages.append(
                _trace_stage(
                    "binding",
                    "pass" if binding_rows else "gap",
                    f"{len(binding_rows)} matching WeChat binding row(s)",
                    binding_rows,
                )
            )

            receipt_rows = _trace_recent_table(
                conn,
                table_name="wechat_clawbot_message_receipts",
                timestamp_column="processed_at",
                start=start,
                end=end,
                limit=payload.limit,
                columns="id::text, credential_id::text, message_key, processed_at",
            )
            stages.append(
                _trace_stage(
                    "bridge_receipt",
                    "pass" if receipt_rows else "gap",
                    f"{len(receipt_rows)} bridge receipt row(s) in window",
                    receipt_rows,
                )
            )

            agent_rows = _trace_agent_runs(conn, payload, start=start, end=end, limit=payload.limit)
            stages.append(
                _trace_stage(
                    "hermes_ingress",
                    "pass" if agent_rows else "gap",
                    f"{len(agent_rows)} WeChat agent run row(s) in window",
                    agent_rows,
                )
            )

            artifact_rows = _trace_artifacts(conn, payload, limit=payload.limit)
            stages.append(
                _trace_stage(
                    "analysis_persistence",
                    "pass" if artifact_rows else "unknown",
                    f"{len(artifact_rows)} recent analysis artifact/signal row(s)",
                    artifact_rows,
                )
            )

            delivery_rows = _trace_deliveries(conn, payload, start=start, end=end, limit=payload.limit)
            delivery_status = "pass" if any(str(row.get("status")) == "delivered" for row in delivery_rows) else "gap"
            stages.append(
                _trace_stage(
                    "delivery",
                    delivery_status if delivery_rows else "gap",
                    f"{len(delivery_rows)} delivery row(s) in window",
                    delivery_rows,
                )
            )

            event_rows = _trace_message_events(conn, payload, start=start, end=end, limit=payload.limit)
            stages.append(
                _trace_stage(
                    "message_events",
                    "pass" if event_rows else "unknown",
                    f"{len(event_rows)} message event row(s) in window",
                    event_rows,
                )
            )
    except Exception as exc:  # noqa: BLE001 - diagnostics should return structured failure
        logger.warning("Hermes WeChat trace failed: %s", exc)
        return {
            "trace_status": "UNKNOWN",
            "db_available": False,
            "reason": str(exc),
            "input": meta,
            "stages": [_trace_stage("db", "unknown", f"DB trace failed: {exc}", [])],
        }

    return {
        "trace_status": _classify_trace(stages),
        "db_available": True,
        "input": meta,
        "stages": stages,
    }


def _trace_stage(name: str, status: str, detail: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail, "rows": _json_ready(rows)}


def _table_exists(conn: Any, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) AS table_name", (f"public.{table_name}",))
        row = cur.fetchone()
    return bool(row and row.get("table_name"))


def _trace_bindings(conn: Any, payload: HermesWechatTraceRequest, *, limit: int) -> list[dict[str, Any]]:
    if not _table_exists(conn, "channel_bindings"):
        return []
    where = ["channel IN ('hermes_wechat', 'openclaw_wechat')"]
    params: list[Any] = []
    if payload.tenant_id:
        where.append("tenant_id::text = %s")
        params.append(payload.tenant_id)
    if payload.channel_binding_id:
        where.append("id::text = %s")
        params.append(payload.channel_binding_id)
    account_id = payload.channel_account_id or payload.openclaw_account_id
    if account_id:
        where.append(
            "(openclaw_account_id = %s OR channel_user_ref = %s "
            "OR coalesce(to_jsonb(channel_bindings)->>'channel_account_id', '') = %s "
            "OR binding_metadata::text ILIKE %s)"
        )
        params.extend([account_id, account_id, account_id, f"%{account_id}%"])
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id::text, tenant_id::text, channel::text, binding_status::text,
                   openclaw_account_id, channel_user_ref, account_label, is_primary,
                   bound_at, last_seen_at, updated_at
            FROM public.channel_bindings
            WHERE {' AND '.join(where)}
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def _trace_recent_table(
    conn: Any,
    *,
    table_name: str,
    timestamp_column: str,
    start: datetime,
    end: datetime,
    limit: int,
    columns: str,
) -> list[dict[str, Any]]:
    if not _table_exists(conn, table_name):
        return []
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {columns}
            FROM public.{table_name}
            WHERE {timestamp_column} BETWEEN %s AND %s
            ORDER BY {timestamp_column} DESC
            LIMIT %s
            """,
            (start, end, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def _trace_agent_runs(
    conn: Any,
    payload: HermesWechatTraceRequest,
    *,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    if not _table_exists(conn, "agent_runs"):
        return []
    where = ["entry_surface = 'wechat'", "created_at BETWEEN %s AND %s"]
    params: list[Any] = [start, end]
    if payload.tenant_id:
        where.append("tenant_id::text = %s")
        params.append(payload.tenant_id)
    if payload.channel_binding_id:
        where.append("channel_binding_id::text = %s")
        params.append(payload.channel_binding_id)
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id::text, tenant_id::text, channel_binding_id::text, trigger::text,
                   entry_surface, intent, actionability_cap::text, status::text,
                   created_at, completed_at
            FROM public.agent_runs
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def _trace_artifacts(conn: Any, payload: HermesWechatTraceRequest, *, limit: int) -> list[dict[str, Any]]:
    if not _table_exists(conn, "artifact_registry"):
        return []
    where = ["artifact_type::text ILIKE %s"]
    params: list[Any] = ["%analysis%"]
    if payload.tenant_id:
        where.append("tenant_id::text = %s")
        params.append(payload.tenant_id)
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id::text, tenant_id::text, source_run_id::text, artifact_key,
                   artifact_type::text, artifact_status::text, created_at
            FROM public.artifact_registry
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def _trace_deliveries(
    conn: Any,
    payload: HermesWechatTraceRequest,
    *,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    if not _table_exists(conn, "delivery_outbox"):
        return []
    where = ["created_at BETWEEN %s AND %s"]
    params: list[Any] = [start, end]
    if payload.tenant_id:
        where.append("tenant_id::text = %s")
        params.append(payload.tenant_id)
    if payload.channel_binding_id:
        where.append("channel_binding_id::text = %s")
        params.append(payload.channel_binding_id)
    account_id = payload.channel_account_id or payload.openclaw_account_id
    if account_id:
        where.append("(openclaw_account_id = %s OR context_token = %s OR target_conversation = %s)")
        params.extend([account_id, account_id, account_id])
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id::text, tenant_id::text, channel_binding_id::text,
                   source_run_id::text, content_type, status::text, attempt_count,
                   last_error, target_conversation, context_token, created_at,
                   delivered_at, updated_at
            FROM public.delivery_outbox
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def _trace_message_events(
    conn: Any,
    payload: HermesWechatTraceRequest,
    *,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    if not _table_exists(conn, "message_events"):
        return []
    where = ["occurred_at BETWEEN %s AND %s"]
    params: list[Any] = [start, end]
    if payload.tenant_id:
        where.append("tenant_id::text = %s")
        params.append(payload.tenant_id)
    if payload.channel_binding_id:
        where.append("channel_binding_id::text = %s")
        params.append(payload.channel_binding_id)
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id::text, tenant_id::text, delivery_outbox_id::text,
                   channel_binding_id::text, event_type::text, event_payload,
                   occurred_at
            FROM public.message_events
            WHERE {' AND '.join(where)}
            ORDER BY occurred_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def _classify_trace(stages: list[dict[str, Any]]) -> str:
    statuses = {stage["name"]: stage["status"] for stage in stages}
    if statuses.get("bridge_receipt") == "pass" and statuses.get("hermes_ingress") == "pass" and statuses.get("delivery") == "pass":
        return "ARRIVED_ANALYZED_DELIVERED"
    if statuses.get("bridge_receipt") == "pass" and statuses.get("hermes_ingress") == "pass":
        return "ARRIVED_ANALYZED_DELIVERY_GAP"
    if statuses.get("binding") == "pass" and statuses.get("bridge_receipt") != "pass":
        return "BOUND_NO_RECEIPT"
    if statuses.get("binding") != "pass":
        return "NO_BINDING_PROOF"
    return "PARTIAL"


def _json_ready(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _sha256_json(value: Any) -> str:
    raw = json.dumps(_json_ready(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _reference_async_enabled() -> bool:
    return _env_bool("HERMES_REFERENCE_ASYNC_ENABLED", default=True)


def _reference_async_threshold_seconds() -> float:
    raw = os.getenv("HERMES_REFERENCE_ASYNC_THRESHOLD_SECONDS", "12")
    try:
        value = float(raw)
    except ValueError:
        value = 12.0
    return max(0.1, min(30.0, value))


def _extract_quote_symbol(text: str) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    if not any(keyword in lowered or keyword in text for keyword in QUOTE_KEYWORDS):
        return None
    matches = [match.group(0).upper() for match in QUOTE_SYMBOL_RE.finditer(text.upper())]
    for candidate in matches:
        if candidate in {"QUOTE", "PRICE"}:
            continue
        return _normalize_symbol(candidate)
    return None


def _normalize_symbol(symbol: str) -> str:
    if symbol.isdigit() and len(symbol) == 6:
        return f"SH{symbol}" if symbol.startswith("6") else f"SZ{symbol}"
    return symbol


async def _quote_reply(symbol: str, tenant_id: str) -> dict[str, Any]:
    result = await _invoke_tool("market.quote", {"symbol": symbol}, tenant_id=tenant_id)
    if not result.get("ok"):
        return _tool_error_reply("market_quote_error", f"{symbol} 行情暂时不可用", result, intent={"name": "market_quote", "symbol": symbol})

    quote = _quote_payload(result)
    price = quote.get("price") or quote.get("last_price") or quote.get("current_price")
    name = quote.get("name") or quote.get("symbol") or quote.get("provider_symbol") or symbol
    currency = quote.get("currency") or ""
    source = quote.get("source") or "unknown"
    change = quote.get("change")
    change_rate = quote.get("change_rate") or quote.get("change_percent")
    change_text = ""
    if change is not None or change_rate is not None:
        change_text = f"，涨跌 {change if change is not None else '-'} / {change_rate if change_rate is not None else '-'}%"
    return _reply(
        "market_quote",
        f"{name}（{symbol}）最新价 {price} {currency}{change_text}。数据源：{source}。",
        intent={"name": "market_quote", "symbol": symbol},
        tool_calls=[_tool_call_summary(result)],
        source_refs=result.get("source_refs") or [],
        quote=quote,
        safety={"mode": "read_only", "writes_fact_store": False, "places_orders": False},
    )


async def _positions_reply(tenant_id: str) -> dict[str, Any]:
    overview_result = await _invoke_tool("portfolio.overview", {"tenant_id": tenant_id}, tenant_id=tenant_id)
    positions_result = await _invoke_tool(
        "broker.positions_read",
        {"tenant_id": tenant_id, "source": "portfolio_read_model"},
        tenant_id=tenant_id,
    )
    if not overview_result.get("ok") and not positions_result.get("ok"):
        return _tool_error_reply(
            "portfolio_positions_error",
            "当前持仓暂时不可用",
            positions_result if positions_result.get("error") else overview_result,
            intent={"name": "portfolio_analysis"},
        )

    overview = overview_result.get("data") if isinstance(overview_result.get("data"), dict) else {}
    data = positions_result.get("data") if isinstance(positions_result.get("data"), dict) else {}
    equities = data.get("equity_positions") if isinstance(data.get("equity_positions"), list) else []
    options = data.get("option_positions") if isinstance(data.get("option_positions"), list) else []
    total = _first_number(overview, "positions_count", "holdings_count") or len(equities) + len(options)
    source_quality = overview.get("source_quality") or data.get("source_quality") or positions_result.get("status") or "unknown"
    top_symbols = _position_symbols([*equities, *options])
    base_currency = str(overview.get("base_currency") or overview.get("currency") or "")
    total_value = _money_text(overview.get("base_total_value") or overview.get("total_value"), base_currency)
    gross_value = _money_text(overview.get("base_gross_market_value") or overview.get("gross_market_value"), base_currency)
    cash = _money_text(overview.get("base_cash") or overview.get("cash"), base_currency)
    buying_power = _money_text(overview.get("base_buying_power") or overview.get("buying_power"), base_currency)
    cash_secured = _money_text(
        overview.get("base_cash_secured_requirement") or overview.get("cash_secured_requirement"),
        base_currency,
    )
    freshness = _freshness_summary(overview.get("freshness") or data.get("freshness"))
    concentration = _top_concentration([*equities, *options], overview)
    risk_lines = _portfolio_risk_lines(
        overview=overview,
        equities=equities,
        options=options,
        source_quality=str(source_quality),
        freshness=freshness,
        concentration=concentration,
    )
    if total:
        symbol_text = f"主要标的：{', '.join(top_symbols)}。" if top_symbols else "主要标的：暂未识别。"
        reply_text = (
            f"组合概览：当前读取到 {total} 条持仓，股票 {len(equities)} 条，期权 {len(options)} 条。\n"
            f"资产：总资产 {total_value}，持仓市值 {gross_value}，现金 {cash}，可用购买力 {buying_power}，现金担保/保证金占用 {cash_secured}。\n"
            f"风险：{'; '.join(risk_lines)}\n"
            f"{symbol_text}\n"
            f"数据：来源质量为{_source_quality_label(source_quality)}；{freshness['text']}。\n"
            "下一步：可以回复“分析 NVDA”看单票，或“设置提醒 NVDA 跌破 110”进入观察。"
        )
    else:
        reply_text = (
            "已查询组合，但当前没有读到 open 持仓。\n"
            f"资产：现金 {cash}，可用购买力 {buying_power}。\n"
            f"数据：来源质量为{_source_quality_label(source_quality)}；{freshness['text']}。\n"
            "如果你确认有持仓，请先检查券商同步或手工持仓导入。"
        )

    return _reply(
        "portfolio_analysis",
        reply_text,
        intent={"name": "portfolio_analysis"},
        tool_calls=[_tool_call_summary(overview_result), _tool_call_summary(positions_result)],
        source_refs=[*(overview_result.get("source_refs") or []), *(positions_result.get("source_refs") or [])],
        portfolio_analysis={
            "total": total,
            "equities": len(equities),
            "options": len(options),
            "source_quality": source_quality,
            "freshness": freshness,
            "overview": overview,
            "symbols": top_symbols,
            "risk_flags": risk_lines,
            "top_concentration": concentration,
        },
        safety={"mode": "read_only", "writes_fact_store": False, "places_orders": False},
    )


async def _watch_command_reply(tenant_id: str, command: dict[str, Any]) -> dict[str, Any]:
    result = await HermesWatchlistService.from_env().add_watch(
        tenant_id=tenant_id,
        symbol=command["symbol"],
        market=command.get("market") or "US",
        thesis=command.get("thesis") or "",
        alert_price=command.get("alert_price"),
        alert_direction=command.get("alert_direction"),
        review_days=command.get("review_days"),
    )
    symbol = command["symbol"]
    if result.get("status") not in {"saved", "ok"}:
        return _reply(
            "watchlist_update_error",
            f"{symbol} 关注项暂时未保存：{result.get('reason') or result.get('status') or 'unknown'}。",
            intent={"name": "watchlist_update", "symbol": symbol},
            safety={"mode": "read_only_watchlist", "writes_fact_store": False, "places_orders": False},
        )

    extras: list[str] = []
    if command.get("alert_price") is not None and command.get("alert_direction"):
        direction_label = "跌破" if command["alert_direction"] == "below" else "突破"
        extras.append(f"{direction_label} {command['alert_price']} 提醒")
    if command.get("review_days"):
        extras.append(f"{command['review_days']} 天后复核")
    tail = f"；已设置：{'、'.join(extras)}" if extras else ""
    return _reply(
        "watchlist_updated",
        f"已把 {symbol} 加入关注清单{tail}。这只是观察和提醒，不会改动持仓或下单。",
        intent={"name": "watchlist_update", "symbol": symbol},
        watchlist=result,
        safety={"mode": "read_only_watchlist", "writes_fact_store": True, "places_orders": False},
    )


async def _watchlist_query_reply(tenant_id: str) -> dict[str, Any]:
    result = await HermesWatchlistService.from_env().list_watch(tenant_id=tenant_id, limit=8)
    items = result.get("items") if isinstance(result.get("items"), list) else []
    if not items:
        text = "当前关注清单为空。可以回复“关注 INTC，跌破 31 提醒我”来添加观察项。"
    else:
        lines = []
        for item in items[:8]:
            symbol = item.get("symbol") or "-"
            thesis = str(item.get("thesis") or "").strip()
            next_review = str(item.get("next_review_at") or "").split("T")[0]
            suffix = f"，复核 {next_review}" if next_review else ""
            lines.append(f"- {symbol}: {thesis[:60]}{suffix}")
        text = "当前关注清单：\n" + "\n".join(lines)
    return _reply(
        "watchlist",
        text,
        intent={"name": "watchlist_query"},
        watchlist=result,
        safety={"mode": "read_only", "writes_fact_store": False, "places_orders": False},
    )


async def _archive_watch_reply(tenant_id: str, symbol: str) -> dict[str, Any]:
    result = await HermesWatchlistService.from_env().archive_watch(tenant_id=tenant_id, symbol=symbol)
    status = result.get("status")
    if status == "archived":
        text = f"已把 {symbol} 从当前观察中归档，并停用对应微信观察提醒。"
    else:
        text = f"没有找到 {symbol} 的活跃关注项。"
    return _reply(
        "watchlist_archived",
        text,
        intent={"name": "watchlist_archive", "symbol": symbol},
        watchlist=result,
        safety={"mode": "read_only_watchlist", "writes_fact_store": True, "places_orders": False},
    )


async def _sell_put_draft_reply(text: str, tenant_id: str) -> dict[str, Any]:
    symbol = _first_symbol(text)
    quote_result: dict[str, Any] | None = None
    if symbol:
        quote_result = await _invoke_tool("market.quote", {"symbol": symbol}, tenant_id=tenant_id)

    tool_calls = [_tool_call_summary(quote_result)] if quote_result else []
    quote_text = ""
    if quote_result and quote_result.get("ok"):
        quote = _quote_payload(quote_result)
        price = quote.get("price") or quote.get("last_price") or quote.get("current_price")
        if price is not None:
            quote_text = f"已读取 {symbol} 最新价 {price}。"

    return _reply(
        "readonly_trade_draft",
        f"{quote_text}Sell Put 属于交易策略，我可以做只读评估和草稿建议，但不会自动下单。请补充到期日、行权价、可接受最大亏损和目标年化，或发“我的持仓”先查看账户上下文。",
        intent={"name": "sell_put_draft", "symbol": symbol},
        tool_calls=tool_calls,
        source_refs=(quote_result or {}).get("source_refs") or [],
        safety={"mode": "read_only_trade_draft_only", "writes_fact_store": False, "places_orders": False},
    )


async def _reference_reply_with_timeout(
    *,
    routing: HermesRoutingPayload,
    prompt: str,
    background_tasks: BackgroundTasks,
    content_type: str,
    intent: dict[str, Any],
    work: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    if not _reference_async_enabled():
        return await work()
    threshold = _reference_async_threshold_seconds()
    try:
        return await asyncio.wait_for(work(), timeout=threshold)
    except asyncio.TimeoutError:
        background_tasks.add_task(
            _complete_reference_async_delivery,
            routing.model_dump(),
            prompt,
            content_type,
            intent,
            work,
        )
        return _reply(
            "web_reference_reading",
            "正在读取这条资料，超过即时回复窗口了。读取完成后我会通过微信推送结果。\n这一步仍然只作为参考资料，不会改动持仓或下单。",
            intent={**intent, "async": True},
            safety={"mode": "reference_only", "writes_fact_store": False, "places_orders": False},
            async_delivery={
                "status": "scheduled",
                "content_type": content_type,
                "threshold_seconds": threshold,
            },
        )


async def _complete_reference_async_delivery(
    routing: dict[str, Any],
    prompt: str,
    content_type: str,
    intent: dict[str, Any],
    work: Callable[[], Awaitable[dict[str, Any]]],
) -> None:
    try:
        result = await work()
    except Exception as exc:  # noqa: BLE001 - background completion must still notify if possible.
        logger.exception("Hermes reference async work failed")
        result = _reply(
            "web_reference_async_error",
            "资料读取任务暂时失败。\n我没有改动持仓，也不会把未读取内容当作事实。",
            intent={**intent, "async": True},
            safety={"mode": "reference_only", "writes_fact_store": False, "places_orders": False},
            internal_error=str(exc),
        )
    queue_result = await asyncio.to_thread(
        _queue_reference_delivery_sync,
        routing,
        prompt,
        content_type,
        result,
    )
    await _archive_ima_background(
        "wechat_async_reply",
        _archive_title_from_result(result, fallback="Hermes 异步资料读取回复"),
        result.get("reply_text"),
        result,
        str(routing.get("tenant_id") or "") or None,
        prompt,
        result.get("result_type"),
        {"content_type": content_type, "intent": intent},
    )
    if queue_result.get("status") != "queued":
        logger.warning("Hermes reference async delivery was not queued: %s", queue_result)
        return
    if _env_bool("HERMES_REFERENCE_ASYNC_DELIVER_IMMEDIATELY"):
        try:
            await HermesDeliveryProcessor.from_env().process_ready(limit=3)
        except Exception as exc:  # noqa: BLE001 - queued outbox remains retryable by the normal worker.
            logger.warning("Hermes reference async immediate delivery failed: %s", exc)


def _queue_reference_delivery_sync(
    routing: dict[str, Any],
    prompt: str,
    content_type: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    database_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or ""
    tenant_id = str(routing.get("tenant_id") or "")
    if not database_url:
        return {"status": "skipped", "reason": "DATABASE_URL_missing"}
    if not tenant_id:
        return {"status": "skipped", "reason": "tenant_id_missing"}

    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    now = datetime.now(timezone.utc)
    reply_text = _reply_text_from_result(result) or "资料读取已完成。"
    content = {
        "title": "资料读取完成",
        "text": reply_text,
        "result_type": result.get("result_type"),
        "intent": result.get("intent"),
        "reference_summary": result.get("reference_summary"),
        "source_refs": result.get("source_refs") or [],
    }
    content_hash = _sha256_json(content)
    dedupe_source = json.dumps(
        {"tenant_id": tenant_id, "prompt": prompt, "content_type": content_type, "intent": result.get("intent") or {}},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    dedupe_key = f"reference-async:{hashlib.sha256(dedupe_source.encode('utf-8')).hexdigest()[:40]}"
    channel_binding_id = str(routing.get("channel_binding_id") or "")
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        binding = conn.execute(
            """
            SELECT id, openclaw_account_id, channel_user_ref, binding_metadata
            FROM public.channel_bindings
            WHERE tenant_id::text = %(tenant_id)s
              AND channel IN ('hermes_wechat', 'openclaw_wechat')
              AND binding_status = 'active'
              AND (%(channel_binding_id)s = '' OR id::text = %(channel_binding_id)s)
            ORDER BY is_primary DESC, last_seen_at DESC NULLS LAST, updated_at DESC
            LIMIT 1
            """,
            {"tenant_id": tenant_id, "channel_binding_id": channel_binding_id},
        ).fetchone()
        if not binding:
            return {"status": "skipped", "reason": "active_binding_missing"}
        binding_metadata = binding.get("binding_metadata") if isinstance(binding.get("binding_metadata"), dict) else {}
        row = conn.execute(
            """
            INSERT INTO public.delivery_outbox (
              tenant_id, channel_binding_id, openclaw_account_id,
              content_type, content, content_snapshot_hash, content_summary, priority,
              dedupe_key, status, attempt_count, next_retry_at, target_conversation,
              context_token, data_snapshot_refs, expires_at
            )
            VALUES (
              %(tenant_id)s, %(channel_binding_id)s, %(openclaw_account_id)s,
              %(content_type)s, %(content)s, %(content_snapshot_hash)s, %(content_summary)s, 'normal',
              %(dedupe_key)s, 'pending', 0, %(next_retry_at)s, %(target_conversation)s,
              %(context_token)s, %(data_snapshot_refs)s, %(expires_at)s
            )
            ON CONFLICT (tenant_id, dedupe_key) DO NOTHING
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "channel_binding_id": binding.get("id"),
                "openclaw_account_id": binding.get("openclaw_account_id"),
                "content_type": content_type,
                "content": Jsonb(content),
                "content_snapshot_hash": content_hash,
                "content_summary": Jsonb(
                    {
                        "title": content["title"],
                        "result_type": result.get("result_type"),
                        "prompt": prompt[:160],
                    }
                ),
                "dedupe_key": dedupe_key,
                "next_retry_at": now,
                "target_conversation": binding.get("channel_user_ref") or routing.get("target_conversation"),
                "context_token": routing.get("context_token") or binding_metadata.get("context_token"),
                "data_snapshot_refs": Jsonb(result.get("source_refs") or []),
                "expires_at": now + timedelta(hours=6),
            },
        ).fetchone()
        conn.commit()
    return {"status": "queued" if row else "duplicate", "delivery_id": str(row.get("id")) if row else None}


async def _web_reference_search_reply(tenant_id: str, prompt: str, query: str) -> dict[str, Any]:
    result = await _invoke_tool(
        "reference.web.search",
        {
            "query": query,
            "tenant_id": tenant_id,
            "prompt": prompt,
            "entry_surface": "wechat",
            "limit": 5,
            "read_top": True,
        },
        tenant_id=tenant_id,
    )
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    read_result = data.get("read_result") if isinstance(data.get("read_result"), dict) else None
    if not result.get("ok"):
        failed = result.get("failed") if isinstance(result.get("failed"), dict) else {}
        return _reply(
            "web_reference_search_error",
            "搜索源暂时不可用。\n我没有改动持仓，也不会把未验证搜索结果当作交易事实。",
            intent={"name": "web_reference_search", "query": query},
            tool_calls=[_tool_call_summary(result)],
            source_refs=result.get("source_refs") or [],
            search_results=items,
            internal_failure=failed or {"status": result.get("status"), "error": result.get("error")},
            safety={"mode": "reference_only", "writes_fact_store": False, "places_orders": False},
        )

    lines = [f"搜索：{query}"]
    if items:
        for index, item in enumerate(items[:3], start=1):
            title = str(item.get("title") or item.get("url") or "网页资料")
            snippet = str(item.get("snippet") or "").strip()
            suffix = f" - {snippet[:80]}" if snippet else ""
            lines.append(f"{index}. {title[:80]}{suffix}")
    else:
        lines.append("未找到可用公开网页结果。")
    read_summary = _read_summary_from_search_result(read_result)
    if read_summary.get("summary"):
        lines.append("")
        lines.append(f"已读取首条：{read_summary.get('title') or '网页资料'}")
        lines.append(str(read_summary["summary"])[:500])
    lines.append("")
    lines.append("以上只是参考资料，不会改动持仓或下单。")
    return _reply(
        "web_reference_search",
        "\n".join(lines),
        intent={"name": "web_reference_search", "query": query},
        tool_calls=[_tool_call_summary(result)],
        source_refs=result.get("source_refs") or [],
        search_results=items,
        reference_summary=read_summary,
        safety={"mode": "reference_only", "writes_fact_store": _read_persistence_saved(read_result), "places_orders": False},
    )


async def _web_reference_reply(tenant_id: str, prompt: str, url: str) -> dict[str, Any]:
    result = await _invoke_tool(
        "reference.web.read",
        {"url": url, "tenant_id": tenant_id, "prompt": prompt, "entry_surface": "wechat"},
        tenant_id=tenant_id,
    )
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    persistence = data.get("persistence") if isinstance(data.get("persistence"), dict) else {}
    if not result.get("ok"):
        failed = result.get("failed") if isinstance(result.get("failed"), dict) else {}
        return _reply(
            "web_reference_error",
            "这个链接暂时读不到。\n我没有改动持仓，也不会把它当作交易事实。",
            intent={"name": "web_reference_read", "url": url},
            tool_calls=[_tool_call_summary(result)],
            source_refs=result.get("source_refs") or [],
            reference_summary=summary,
            persistence=persistence,
            internal_failure=failed or {"status": result.get("status"), "error": result.get("error")},
            safety={"mode": "reference_only", "writes_fact_store": persistence.get("status") == "saved", "places_orders": False},
        )

    title = summary.get("title") or "网页资料"
    body = summary.get("summary") or "已读取网页，但正文摘要为空。"
    saved_text = "已保存引用快照。" if persistence.get("status") == "saved" else "引用快照暂未保存。"
    return _reply(
        "web_reference",
        f"{title}\n\n{body}\n\n来源：{summary.get('url') or url}\n{saved_text}\n这只是参考资料，不会改动持仓或下单。",
        intent={"name": "web_reference_read", "url": url},
        tool_calls=[_tool_call_summary(result)],
        source_refs=result.get("source_refs") or [],
        reference_summary=summary,
        persistence=persistence,
        safety={"mode": "reference_only", "writes_fact_store": persistence.get("status") == "saved", "places_orders": False},
    )


async def _stock_analysis_with_search_reference_reply(symbol: str, tenant_id: str, prompt: str, query: str) -> dict[str, Any]:
    search_result = await _invoke_tool(
        "reference.web.search",
        {
            "query": query,
            "tenant_id": tenant_id,
            "prompt": prompt,
            "entry_surface": "wechat",
            "limit": 5,
            "read_top": True,
        },
        tenant_id=tenant_id,
    )
    news_context = _news_context_from_search_reference(search_result, symbol)
    analysis = await _stock_analysis_reply(symbol, tenant_id, prompt, news_context=news_context)
    analysis["reference_tool_calls"] = [_tool_call_summary(search_result)]
    analysis["reference_summary"] = news_context
    analysis["source_refs"] = [*(analysis.get("source_refs") or []), *(search_result.get("source_refs") or [])]
    if search_result.get("ok"):
        analysis["reply_text"] = f"{analysis['reply_text']}\n\n已把搜索到的公开网页资料作为参考资料上下文纳入分析：{query}"
    else:
        analysis["reply_text"] = f"{analysis['reply_text']}\n\n搜索资料暂时不可用，未作为事实依据。"
    return analysis


async def _stock_analysis_with_web_reference_reply(symbol: str, tenant_id: str, prompt: str, url: str) -> dict[str, Any]:
    reference_result = await _invoke_tool(
        "reference.web.read",
        {"url": url, "tenant_id": tenant_id, "prompt": prompt, "entry_surface": "wechat"},
        tenant_id=tenant_id,
    )
    news_context = _news_context_from_reference(reference_result, symbol)
    analysis = await _stock_analysis_reply(symbol, tenant_id, prompt, news_context=news_context)
    analysis["reference_tool_calls"] = [_tool_call_summary(reference_result)]
    analysis["reference_summary"] = news_context
    analysis["source_refs"] = [*(analysis.get("source_refs") or []), *(reference_result.get("source_refs") or [])]
    if reference_result.get("ok"):
        analysis["reply_text"] = f"{analysis['reply_text']}\n\n已把链接内容作为参考资料纳入分析：{url}"
    else:
        analysis["reply_text"] = f"{analysis['reply_text']}\n\n链接资料暂时读不到，未作为事实依据。"
    return analysis


async def _stock_analysis_with_social_context_reply(symbol: str, tenant_id: str, prompt: str) -> dict[str, Any]:
    social_result = await _invoke_tool(
        "sentiment.social.snapshot",
        {
            "symbol": symbol,
            "tenant_id": tenant_id,
            "prompt": prompt,
            "entry_surface": "wechat",
            "window": "72h",
            "limit": 20,
        },
        tenant_id=tenant_id,
    )
    social_context = _social_context_from_snapshot(social_result, symbol)
    analysis = await _stock_analysis_reply(symbol, tenant_id, prompt, social_context=social_context)
    analysis["reference_tool_calls"] = [_tool_call_summary(social_result)]
    analysis["social_summary"] = social_context
    analysis["source_refs"] = [*(analysis.get("source_refs") or []), *(social_result.get("source_refs") or [])]
    if social_result.get("ok"):
        analysis["reply_text"] = f"{analysis['reply_text']}\n\n已把有限账号清单里的社媒样本作为弱信号纳入分析。"
    else:
        analysis["reply_text"] = f"{analysis['reply_text']}\n\n社媒账号清单或读取源暂未配置，未纳入社区情绪。"
    return analysis


async def _stock_analysis_reply(
    symbol: str,
    tenant_id: str,
    prompt: str,
    *,
    news_context: dict[str, Any] | None = None,
    social_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    arguments: dict[str, Any] = {"symbol": symbol, "tenant_id": tenant_id, "prompt": prompt, "entry_surface": "wechat"}
    if news_context:
        arguments["news_context"] = news_context
    if social_context:
        arguments["social_context"] = social_context
    result = await _invoke_tool(
        "stock.analysis",
        arguments,
        tenant_id=tenant_id,
    )
    if not result.get("ok"):
        return _tool_error_reply(
            "stock_analysis_error",
            f"{symbol} 分析暂时不可用",
            result,
            intent={"name": "stock_analysis", "symbol": symbol},
        )

    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    report = data.get("report") if isinstance(data.get("report"), dict) else {}
    quality_display = data.get("quality_display") if isinstance(data.get("quality_display"), dict) else {}
    reply_text = data.get("short_reply")
    if not reply_text:
        reply_text = (
            f"{report.get('conclusion') or f'{symbol} 分析已完成'}\n"
            f"数据质量：{_quality_display_summary(quality_display)}。\n"
            f"行动等级：{data.get('actionability_cap') or 'analysis_only'} / {data.get('action_label') or '观察'}。\n"
            f"下一步：{report.get('next_steps') or '可继续让我设置提醒或加入关注。'}"
        )

    return _reply(
        "stock_analysis",
        str(reply_text),
        intent={"name": "stock_analysis", "symbol": symbol},
        tool_calls=[_tool_call_summary(result)],
        source_refs=result.get("source_refs") or [],
        analysis={
            "symbol": data.get("symbol") or symbol,
            "action": data.get("action"),
            "action_label": data.get("action_label"),
            "actionability_cap": data.get("actionability_cap"),
            "score": data.get("score"),
            "quality_display": quality_display,
            "data_quality": data.get("data_quality"),
            "report": report,
            "persistence": data.get("persistence"),
            "report_constraints": data.get("report_constraints"),
        },
        safety={"mode": "read_only_analysis_artifact", "writes_fact_store": False, "places_orders": False},
    )


async def _invoke_tool(tool: str, arguments: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
    tool_args = dict(arguments)
    if tenant_id and "tenant_id" not in tool_args:
        tool_args["tenant_id"] = tenant_id
    try:
        return await _domain_tools().invoke(tool, tool_args)
    except DomainToolError as exc:
        return {"tool": tool, "ok": False, "status": "error", "error": str(exc), "source_refs": []}
    except httpx.HTTPStatusError as exc:
        logger.warning("Hermes WeChat domain tool upstream HTTP error: %s", exc)
        return {
            "tool": tool,
            "ok": False,
            "status": "upstream_error",
            "error": str(exc),
            "upstream_status_code": exc.response.status_code,
            "source_refs": [],
        }
    except Exception as exc:
        logger.exception("Hermes WeChat domain tool invocation failed")
        return {"tool": tool, "ok": False, "status": "error", "error": str(exc), "source_refs": []}


def _tool_error_reply(result_type: str, prefix: str, result: dict[str, Any], *, intent: dict[str, Any]) -> dict[str, Any]:
    return _reply(
        result_type,
        f"{prefix}，请稍后重试。我没有改动持仓，也不会自动下单。",
        intent=intent,
        tool_calls=[_tool_call_summary(result)],
        source_refs=result.get("source_refs") or [],
        internal_failure={"status": result.get("status"), "error": result.get("error")},
        safety={"mode": "read_only", "writes_fact_store": False, "places_orders": False},
    )


def _news_context_from_reference(reference_result: dict[str, Any], symbol: str) -> dict[str, Any]:
    data = reference_result.get("data") if isinstance(reference_result.get("data"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    return {
        "schema_version": "web_reference_news_context_v1",
        "symbol": symbol,
        "reference_only": True,
        "items": [
            {
                "title": summary.get("title"),
                "url": summary.get("url"),
                "summary": summary.get("summary"),
                "content_hash": summary.get("content_hash"),
                "fetched_at": summary.get("fetched_at"),
                "status": summary.get("status"),
                "failed": summary.get("failed"),
            }
        ],
        "source_refs": reference_result.get("source_refs") or [],
    }


def _news_context_from_search_reference(search_result: dict[str, Any], symbol: str) -> dict[str, Any]:
    data = search_result.get("data") if isinstance(search_result.get("data"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    read_result = data.get("read_result") if isinstance(data.get("read_result"), dict) else None
    read_summary = _read_summary_from_search_result(read_result)
    context_items: list[dict[str, Any]] = []
    if read_summary:
        context_items.append(
            {
                "title": read_summary.get("title"),
                "url": read_summary.get("url"),
                "summary": read_summary.get("summary"),
                "content_hash": read_summary.get("content_hash"),
                "fetched_at": read_summary.get("fetched_at"),
                "status": read_summary.get("status"),
                "failed": read_summary.get("failed"),
            }
        )
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        context_items.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "summary": item.get("snippet"),
                "status": "search_result",
            }
        )
    return {
        "schema_version": "web_reference_search_news_context_v1",
        "symbol": symbol,
        "reference_only": True,
        "query": data.get("query"),
        "items": context_items,
        "source_refs": search_result.get("source_refs") or [],
        "failed": search_result.get("failed"),
    }


def _social_context_from_snapshot(social_result: dict[str, Any], symbol: str) -> dict[str, Any]:
    data = social_result.get("data") if isinstance(social_result.get("data"), dict) else {}
    context = data.get("social_context") if isinstance(data.get("social_context"), dict) else {}
    if context:
        return {**context, "symbol": context.get("symbol") or symbol}
    return {
        "schema_version": "social_sentiment_snapshot_v1",
        "status": "not_configured",
        "reason": social_result.get("status") or "social_source_not_configured",
        "symbol": symbol,
        "items": [],
        "accounts": [],
        "themes": [],
        "risk_flags": [],
        "source_refs": social_result.get("source_refs") or [],
    }


def _read_summary_from_search_result(read_result: dict[str, Any] | None) -> dict[str, Any]:
    if not read_result:
        return {}
    data = read_result.get("data") if isinstance(read_result.get("data"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    return summary


def _read_persistence_saved(read_result: dict[str, Any] | None) -> bool:
    if not read_result:
        return False
    data = read_result.get("data") if isinstance(read_result.get("data"), dict) else {}
    persistence = data.get("persistence") if isinstance(data.get("persistence"), dict) else {}
    return persistence.get("status") == "saved"


def _existing_persistence(result: dict[str, Any]) -> dict[str, Any]:
    for container in (result, result.get("analysis"), result.get("data"), result.get("result")):
        if isinstance(container, dict) and isinstance(container.get("persistence"), dict):
            return container["persistence"]
    return {}


def _reply_text_from_result(result: dict[str, Any]) -> str:
    for key in ("reply_text", "replyText", "text", "content"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value
    analysis = result.get("analysis")
    if isinstance(analysis, dict):
        short_reply = analysis.get("short_reply")
        if isinstance(short_reply, str):
            return short_reply
    data = result.get("data")
    if isinstance(data, dict):
        short_reply = data.get("short_reply")
        if isinstance(short_reply, str):
            return short_reply
    return ""


def _analysis_symbol_from_result(result: dict[str, Any], reply_text: str, prompt: str) -> str | None:
    for container in (result.get("analysis"), result.get("data"), result.get("intent"), result.get("result"), result):
        if not isinstance(container, dict):
            continue
        for key in ("symbol", "ticker", "provider_symbol"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_symbol_alias(value)

    text = " ".join([reply_text, prompt]).upper()
    provider_match = re.search(r"\b([A-Z]{1,6})(?:\.(?:US|HK|SH|SZ|NYSE|NASDAQ))\b", text)
    if provider_match:
        return _normalize_symbol_alias(provider_match.group(1))
    if "CIRCLE" in text:
        return "CRCL"
    matches = [match.group(0).upper() for match in QUOTE_SYMBOL_RE.finditer(text)]
    for candidate in matches:
        if candidate not in {"QUOTE", "PRICE", "CIRCLE"}:
            return _normalize_symbol_alias(candidate)
    return None


def _normalize_symbol_alias(symbol: str) -> str:
    normalized = _normalize_symbol(symbol.strip().upper())
    if normalized in {"CIRCLE", "CIRCLE.US"}:
        return "CRCL"
    if normalized.endswith(".US"):
        return normalized[:-3]
    return normalized


def _quality_display_summary(value: dict[str, Any]) -> str:
    if not value:
        return "只能观察 / 新鲜度未知 / 来源 unknown"
    summary = value.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    actionability = value.get("actionability_label") or _quality_actionability_label(value.get("actionability"))
    freshness = value.get("freshness_label") or _quality_freshness_label(value.get("freshness"))
    reason = value.get("degrade_reason_label") or _quality_degrade_reason_label(value.get("degrade_reason"))
    source = value.get("source") or "unknown"
    parts = [str(actionability), str(freshness)]
    if value.get("degrade_reason") and str(reason) not in parts:
        parts.append(str(reason))
    parts.append(f"来源 {source}")
    return " / ".join(parts)


def _external_quality_display(*, hermes_result: dict[str, Any], actionability: str) -> dict[str, Any]:
    existing = _quality_display_from_result(hermes_result)
    if existing:
        return existing
    source = _source_from_result(hermes_result) or "hermes_wechat_result"
    freshness = "unknown"
    degrade_reason = "analysis_only" if actionability != "trade_draft" else None
    return {
        "schema_version": "quality_display_v1",
        "source": source,
        "as_of": None,
        "freshness": freshness,
        "freshness_label": _quality_freshness_label(freshness),
        "actionability": actionability,
        "actionability_label": _quality_actionability_label(actionability),
        "degrade_reason": degrade_reason,
        "degrade_reason_label": _quality_degrade_reason_label(degrade_reason),
        "summary": _quality_display_summary(
            {
                "source": source,
                "freshness": freshness,
                "actionability": actionability,
                "degrade_reason": degrade_reason,
            }
        ),
    }


def _quality_display_from_result(result: dict[str, Any]) -> dict[str, Any]:
    for container in (result.get("analysis"), result.get("data"), result.get("result"), result):
        if isinstance(container, dict) and isinstance(container.get("quality_display"), dict):
            return container["quality_display"]
    return {}


def _source_from_result(result: dict[str, Any]) -> str | None:
    for container in (result.get("analysis"), result.get("data"), result.get("result"), result):
        if not isinstance(container, dict):
            continue
        quality = container.get("quality_display")
        if isinstance(quality, dict) and quality.get("source"):
            return str(quality["source"])
        data_quality = container.get("data_quality")
        if isinstance(data_quality, dict):
            source = data_quality.get("source") or data_quality.get("quote_source")
            if source:
                return str(source)
    return None


def _quality_freshness_label(value: Any) -> str:
    return {
        "fresh": "数据新鲜",
        "degraded": "数据降级",
        "stale": "数据过期",
        "missing": "数据缺失",
        "unknown": "新鲜度未知",
    }.get(str(value or "unknown"), "新鲜度未知")


def _quality_actionability_label(value: Any) -> str:
    return {
        "trade_draft": "可行动",
        "analysis_only": "只能观察",
        "blocked": "不可行动",
    }.get(str(value or "analysis_only"), "只能观察")


def _quality_degrade_reason_label(value: Any) -> str:
    return {
        None: "无降级",
        "quote_unavailable": "行情不可用",
        "data_stale": "数据过期",
        "no_portfolio_context": "无持仓上下文",
        "no_position_context": "无持仓上下文",
        "action_blocked": "纪律或数据阻断",
        "analysis_only": "只能观察",
        "freshness_uncertain": "新鲜度待复核",
    }.get(value, str(value))


def _external_analysis_payload(*, symbol: str, reply_text: str, hermes_result: dict[str, Any], prompt: str) -> dict[str, Any]:
    actionability = _actionability_from_result(hermes_result, reply_text)
    report = _report_from_result(hermes_result, reply_text)
    quality_display = _external_quality_display(hermes_result=hermes_result, actionability=actionability)
    return {
        "schema_version": "wechat_analysis_artifact_p1",
        "symbol": symbol,
        "name": _name_from_result(hermes_result, symbol),
        "market": _market_from_symbol(symbol),
        "action": "watch" if actionability != "blocked" else "data_blocked",
        "action_label": "观察" if actionability != "blocked" else "数据阻断",
        "actionability_cap": actionability,
        "confidence_score": 0.6,
        "score": 55 if actionability != "blocked" else 30,
        "risk_flags": _risk_flags_from_reply(reply_text),
        "watch_conditions": _watch_conditions_from_reply(reply_text, symbol),
        "data_quality": {
            "source": quality_display["source"],
            "persisted_from": "wechat_bridge",
            "quality_display": quality_display,
        },
        "quality_display": quality_display,
        "report": report,
        "short_reply": reply_text[:1800],
        "report_constraints": {"conclusion_first": True, "module_max_chars": MAX_REPORT_MODULE_CHARS},
        "prompt": prompt,
    }


def _actionability_from_result(result: dict[str, Any], reply_text: str) -> str:
    for container in (result.get("analysis"), result.get("data"), result.get("result"), result):
        if isinstance(container, dict):
            value = container.get("actionability_cap") or container.get("actionability") or container.get("actionability_level")
            if value in {"blocked", "analysis_only", "trade_draft", "suggested_action", "info_only"}:
                return str(value)
    lowered = reply_text.lower()
    if "blocked" in lowered:
        return "blocked"
    if "analysis_only" in lowered:
        return "analysis_only"
    return "analysis_only"


def _report_from_result(result: dict[str, Any], reply_text: str) -> dict[str, str]:
    for container in (result.get("analysis"), result.get("data"), result.get("result"), result):
        if isinstance(container, dict) and isinstance(container.get("report"), dict):
            report = container["report"]
            return {
                key: _clip_text(report.get(key) or "")
                for key in ("conclusion", "position", "market", "risk", "discipline", "next_steps")
            }
    return {
        "conclusion": _clip_text(reply_text or "Hermes 微信分析已完成。"),
        "position": _clip_text(_line_matching(reply_text, ("持仓", "观察池")) or "详见 Hermes 微信回复。"),
        "market": _clip_text(_line_matching(reply_text, ("数据源", "收盘价", "盘后价", "Longbridge")) or "详见 Hermes 微信回复。"),
        "risk": _clip_text(_line_matching(reply_text, ("风险", "亏损", "分歧", "波动")) or "需结合数据质量和组合上下文复核。"),
        "discipline": _clip_text("这是微信分析产物持久化，不写入持仓事实，不下券商订单。"),
        "next_steps": _clip_text(_line_matching(reply_text, ("下一步", "观察", "一句话")) or "可继续追问、加入关注或设置提醒。"),
    }


def _name_from_result(result: dict[str, Any], symbol: str) -> str:
    for container in (result.get("analysis"), result.get("data"), result.get("result"), result):
        if isinstance(container, dict):
            value = container.get("name") or container.get("company_name")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "Circle Internet Group" if symbol == "CRCL" else symbol


def _market_from_symbol(symbol: str) -> str:
    if symbol.startswith(("SH", "SZ")):
        return "CN"
    if symbol.startswith("HK"):
        return "HK"
    return "US"


def _risk_flags_from_reply(reply_text: str) -> list[str]:
    flags: list[str] = []
    if "亏损" in reply_text or "PE TTM: -" in reply_text:
        flags.append("盈利口径或估值存在风险")
    if "分歧" in reply_text:
        flags.append("机构目标价分歧较大")
    if "未发现" in reply_text and "持仓" in reply_text:
        flags.append("未匹配到本地持仓上下文")
    return flags


def _watch_conditions_from_reply(reply_text: str, symbol: str) -> list[str]:
    conditions = [f"复核 {symbol} 后续价格和成交量变化"]
    if "目标价" in reply_text:
        conditions.append("跟踪机构目标价和评级变化")
    if "观察池" in reply_text or "未持有" in reply_text:
        conditions.append("如符合纪律，可加入观察池并设置提醒")
    return conditions


def _line_matching(text: str, needles: tuple[str, ...]) -> str:
    for line in text.splitlines():
        if any(needle in line for needle in needles):
            return line.strip()
    return ""


def _clip_text(text: Any) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= MAX_REPORT_MODULE_CHARS:
        return compact
    return compact[: MAX_REPORT_MODULE_CHARS - 1].rstrip() + "…"


def _compact_jsonish(value: Any, *, max_chars: int) -> Any:
    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)[:max_chars]
    if len(rendered) <= max_chars:
        return value
    return {"truncated": True, "text": rendered[:max_chars]}


def _quote_payload(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    if isinstance(data, dict):
        for key in ("quote", "data", "result"):
            nested = data.get(key)
            if isinstance(nested, dict):
                return nested
        return data
    return {}


def _tool_call_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {"tool": "unknown", "ok": False, "status": "not_called"}
    return {
        "tool": result.get("tool"),
        "ok": bool(result.get("ok")),
        "status": result.get("status"),
        "source_refs": result.get("source_refs") or [],
        **({"upstream_status_code": result.get("upstream_status_code")} if result.get("upstream_status_code") else {}),
    }


def _looks_like_positions_query(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered or keyword in text for keyword in POSITION_KEYWORDS)


def _looks_like_sell_put_request(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered or keyword in text for keyword in SELL_PUT_KEYWORDS)


def _looks_like_trade_input(text: str) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in ("买入", "卖出", "加仓", "减仓", "清仓", "sell put", "交易", "成交"))


def _looks_like_watchlist_query(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    has_list = any(keyword in lowered or keyword in text for keyword in ("观察清单", "关注清单", "watchlist", "关注列表", "观察列表"))
    has_query = any(keyword in text for keyword in ("看", "列", "查", "哪些", "有什么")) or "show" in lowered
    return has_list and has_query


def _looks_like_social_signal_query(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    social_keywords = (
        "社媒",
        "社区",
        "舆情",
        "大家怎么看",
        "散户怎么看",
        "雪球",
        "小红书",
        "reddit",
        "twitter",
        "x 上",
        "推特",
    )
    return any(keyword in lowered or keyword in text for keyword in social_keywords)


def _extract_archive_watch_symbol(text: str) -> str | None:
    if not text:
        return None
    if not any(keyword in text for keyword in ("放弃观察", "取消关注", "先放弃", "不看了", "移出关注")):
        return None
    return _first_symbol(text)


def _parse_watch_command(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    lowered = text.lower()
    is_watch = any(keyword in text for keyword in ("加入关注", "关注", "加入观察", "放入观察", "设提醒", "设置提醒", "提醒我"))
    is_review = "复核" in text and any(keyword in text for keyword in ("天后", "明天", "后天", "下周"))
    if not is_watch and not is_review:
        return None

    symbol = _first_symbol(text)
    if not symbol:
        return None

    alert_price = _extract_alert_price(text) if any(keyword in text for keyword in ("跌破", "跌到", "低于", "突破", "高于", "站上")) else None
    alert_direction: str | None = None
    if alert_price is not None:
        alert_direction = "below" if any(keyword in text for keyword in ("跌破", "跌到", "低于")) else "above"

    review_days = _extract_review_days(text)
    thesis = text
    return {
        "symbol": symbol,
        "market": _market_from_symbol(symbol),
        "thesis": thesis[:200],
        "alert_price": alert_price,
        "alert_direction": alert_direction,
        "review_days": review_days,
    }


def _extract_alert_price(text: str) -> float | None:
    candidates = re.findall(r"(?<![A-Z0-9])(\d+(?:\.\d+)?)(?![A-Z0-9])", text.upper())
    for raw in candidates:
        try:
            value = float(raw)
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def _extract_review_days(text: str) -> int | None:
    if "明天" in text:
        return 1
    if "后天" in text:
        return 2
    if "下周" in text:
        return 7
    match = re.search(r"(\d+)\s*天后", text)
    if match:
        return max(1, min(30, int(match.group(1))))
    chinese_days = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}
    match = re.search(r"([一二两三四五六七])天后", text)
    if match:
        return chinese_days.get(match.group(1))
    return None


def _extract_analysis_symbol(text: str) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    if not any(keyword in lowered or keyword in text for keyword in STOCK_ANALYSIS_KEYWORDS):
        return None
    return _first_symbol(text)


def _looks_like_reference_search(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(keyword in lowered or keyword in text for keyword in REFERENCE_SEARCH_KEYWORDS):
        if any(keyword in text for keyword in ("行情", "报价", "股价")) and not any(keyword in text for keyword in ("新闻", "文章", "资料", "搜索", "搜一下")):
            return False
        return True
    return False


def _reference_search_query(text: str, *, symbol: str | None = None) -> str:
    query = _strip_urls(text)
    query = re.sub(r"^(帮我|请|麻烦)?\s*", "", query, flags=re.IGNORECASE).strip()
    query = re.sub(r"^(分析一下|分析|看一下|看下|看看|复核|怎么看)\s*", "", query, flags=re.IGNORECASE).strip()
    query = re.sub(r"^(搜索一下|搜索|搜一下|查一下|网上查|查找)\s*", "", query, flags=re.IGNORECASE).strip()
    query = re.sub(r"^一下\s*", "", query).strip()
    if symbol and _should_remove_symbol_from_search_query(query, symbol):
        normalized = re.escape(symbol)
        query = re.sub(rf"(?<![A-Z0-9]){normalized}(?![A-Z0-9])", " ", query, flags=re.IGNORECASE).strip()
        if symbol.endswith(".US"):
            query = re.sub(rf"(?<![A-Z0-9]){re.escape(symbol[:-3])}(?![A-Z0-9])", " ", query, flags=re.IGNORECASE).strip()
    query = re.sub(r"\s+", " ", query).strip(" ，,。:：")
    query = re.sub(r"^(搜索一下|搜索|搜一下|查一下|网上查|查找)\s*", "", query, flags=re.IGNORECASE).strip()
    query = re.sub(r"(并)?(总结|读一下|看看|分析一下|分析|怎么看)\s*$", "", query).strip()
    return query or text.strip()


def _should_remove_symbol_from_search_query(query: str, symbol: str) -> bool:
    base_symbol = symbol.upper().removesuffix(".US")
    generic = {"NEWS", "LATEST", "SEARCH", "REPORT", "ARTICLE", "STOCK", "PRICE"}
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.]{2,}", query or "")
    for token in tokens:
        normalized = token.upper().removesuffix(".US")
        if normalized != base_symbol and normalized not in generic:
            return True
    return False


def _extract_first_url(text: str) -> str | None:
    if not text:
        return None
    match = PUBLIC_URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;，。；")


def _strip_urls(text: str) -> str:
    return PUBLIC_URL_RE.sub(" ", text or "").strip()


def _first_symbol(text: str) -> str | None:
    matches = [match.group(0).upper() for match in QUOTE_SYMBOL_RE.finditer(text.upper())]
    for candidate in matches:
        if candidate not in {"QUOTE", "PRICE"}:
            return _normalize_symbol(candidate)
    if "circle" in text.lower() or "Circle" in text:
        return "CRCL"
    return None


def _position_symbols(rows: list[dict[str, Any]]) -> list[str]:
    symbols: list[str] = []
    for row in rows[:5]:
        symbol = row.get("symbol") or row.get("provider_symbol")
        if symbol:
            symbols.append(str(symbol))
    return symbols


def _first_number(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip():
            try:
                return int(float(value))
            except ValueError:
                continue
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def _money_text(value: Any, currency: str = "") -> str:
    number = _number(value)
    if number is None:
        return "-"
    suffix = f" {currency}" if currency else ""
    return f"{number:,.2f}{suffix}"


def _freshness_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "unknown", "text": "新鲜度未知"}
    status = str(value.get("status") or "unknown")
    as_of = value.get("as_of")
    as_of_age = value.get("as_of_age_seconds")
    received_age = value.get("received_age_seconds")
    missing = value.get("missing_fields") if isinstance(value.get("missing_fields"), list) else []
    bits = [f"新鲜度{_freshness_label(status)}"]
    if as_of:
        bits.append(f"数据时间 {as_of}")
    if as_of_age is not None:
        bits.append(f"距数据时间约 {_duration_label(as_of_age)}")
    if received_age is not None:
        bits.append(f"距接收时间约 {_duration_label(received_age)}")
    if missing:
        bits.append(f"缺少字段 {', '.join(str(item) for item in missing[:5])}")
    return {
        "status": status,
        "as_of": as_of,
        "as_of_age_seconds": as_of_age,
        "received_age_seconds": received_age,
        "missing_fields": missing,
        "text": "；".join(bits),
    }


def _top_concentration(rows: list[dict[str, Any]], overview: dict[str, Any]) -> dict[str, Any] | None:
    gross = _number(overview.get("base_gross_market_value") or overview.get("gross_market_value"))
    best: dict[str, Any] | None = None
    best_value = 0.0
    for row in rows:
        value = abs(_number(row.get("base_market_value") or row.get("market_value")) or 0.0)
        if value > best_value:
            best_value = value
            best = row
    if not best or best_value <= 0:
        return None
    pct = round(best_value / gross * 100, 1) if gross else None
    return {
        "symbol": best.get("symbol") or best.get("provider_symbol"),
        "market_value": best_value,
        "percentage_of_gross": pct,
    }


def _portfolio_risk_lines(
    *,
    overview: dict[str, Any],
    equities: list[dict[str, Any]],
    options: list[dict[str, Any]],
    source_quality: str,
    freshness: dict[str, Any],
    concentration: dict[str, Any] | None,
) -> list[str]:
    risks: list[str] = []
    if concentration and concentration.get("percentage_of_gross") is not None:
        pct = float(concentration["percentage_of_gross"])
        symbol = concentration.get("symbol") or "单一标的"
        if pct >= 30:
            risks.append(f"{symbol} 集中度 {pct}% 偏高")
        else:
            risks.append(f"最大单票 {symbol} 约 {pct}%")
    if options:
        risks.append(f"有 {len(options)} 条期权持仓，需关注到期日、delta 和保证金")
    cash = _number(overview.get("base_cash") or overview.get("cash"))
    gross = _number(overview.get("base_gross_market_value") or overview.get("gross_market_value"))
    if cash is not None and gross:
        cash_ratio = cash / gross
        if cash_ratio < 0.05:
            risks.append("现金缓冲低于持仓市值 5%")
        else:
            risks.append(f"现金/持仓市值约 {round(cash_ratio * 100, 1)}%")
    if freshness.get("status") not in {"fresh", "ok", "complete"}:
        risks.append(f"数据新鲜度为{_freshness_label(freshness.get('status'))}")
    if source_quality not in {"broker_verified", "user_confirmed"}:
        risks.append(f"来源质量为{_source_quality_label(source_quality)}，行动前需复核")
    if not risks:
        risks.append("未发现需要立刻处理的组合级风险")
    return risks[:5]


def _source_quality_label(value: Any) -> str:
    labels = {
        "broker_verified": "券商已验证",
        "user_confirmed": "用户已确认",
        "manual": "手工录入",
        "public_fallback": "公开数据兜底",
        "stale": "可能过期",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _freshness_label(value: Any) -> str:
    labels = {
        "fresh": "新鲜",
        "ok": "可用",
        "complete": "完整",
        "partial": "部分可用",
        "stale": "可能过期",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _duration_label(value: Any) -> str:
    seconds = _number(value)
    if seconds is None:
        return "未知"
    if seconds < 60:
        return f"{int(seconds)} 秒"
    if seconds < 3600:
        return f"{round(seconds / 60, 1)} 分钟"
    return f"{round(seconds / 3600, 1)} 小时"
