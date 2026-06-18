"""
WeChat / OpenClaw ingress router for P0 confirmation-safe interactions.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import urllib.parse
from datetime import datetime
from typing import Any, Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from openclaw.gateway.confirmation_center import (
    ConfirmationCenterService,
    PendingActionInput,
    RoutingContext,
    classify_high_attention_text,
    classify_image_text_candidate,
    interpret_voice_transcript,
    parse_confirmation_command,
)
from openclaw.gateway.conversation_memory import (
    ConversationMemoryService,
    safe_content_from_message,
)
from openclaw.gateway.image_vision import extract_image_text_from_metadata
from openclaw.gateway.model_dialogue import (
    ModelDialogueResult,
    generate_openclaw_reply,
    is_deep_research_request,
)
from openclaw.gateway.outbox import DeliveryEnvelope, DeliveryOutboxService
from openclaw.gateway.webhook_security import check_rate_limit

router = APIRouter(prefix="/api/openclaw", tags=["openclaw-gateway"])
logger = logging.getLogger(__name__)

QUOTE_KEYWORDS = (
    "实时行情",
    "行情",
    "报价",
    "股价",
    "quote",
    "price",
)
PORTFOLIO_MARKET_KEYWORDS = (
    "持仓",
    "仓位",
    "组合",
    "盈亏",
    "行情分析",
    "今天的行情",
    "市场怎么看",
    "我的股票",
)
REALTIME_SEARCH_KEYWORDS = (
    "实时搜索",
    "联网搜索",
    "搜索一下",
    "搜一下",
    "查一下最新",
    "最新消息",
    "相关新闻",
    "新闻",
    "web search",
    "search web",
)
QUOTE_SYMBOL_RE = re.compile(
    r"(?<![A-Z0-9])(?:SH|SZ|HK)?[A-Z]{1,6}\d{0,5}(?![A-Z0-9])|(?<!\d)\d{6}(?!\d)"
)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _wechat_skip_confirmation_center() -> bool:
    return _env_bool("OPENCLAW_WECHAT_SKIP_CONFIRMATION_CENTER", True)


class RoutingPayload(BaseModel):
    tenant_id: str
    channel_binding_id: Optional[str] = None
    openclaw_account_id: Optional[str] = None
    channel: str = "openclaw_wechat"
    session_space: Optional[str] = None
    context_token: Optional[str] = None
    target_conversation: Optional[str] = None
    quiet_hours: Optional[dict[str, Any]] = None
    timezone: str = "Asia/Shanghai"


class MessagePayload(BaseModel):
    id: Optional[str] = None
    type: Literal["text", "voice", "image", "event"]
    text: Optional[str] = None
    transcript: Optional[str] = None
    transcript_confidence: Optional[float] = None
    ocr_text: Optional[str] = None
    image_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    media_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpenClawIngressRequest(BaseModel):
    routing: RoutingPayload
    message: MessagePayload


def _confirmation_service(request: Request) -> ConfirmationCenterService:
    service = getattr(request.app.state, "confirmation_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="confirmation service unavailable")
    return service


def _outbox_service(request: Request) -> DeliveryOutboxService | None:
    return getattr(request.app.state, "outbox_service", None)


def _conversation_memory_service(request: Request) -> ConversationMemoryService | None:
    return getattr(request.app.state, "conversation_memory_service", None)


@router.post("/wechat/messages")
async def ingest_wechat_message(
    payload: OpenClawIngressRequest,
    request: Request,
) -> dict[str, Any]:
    ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(ip, max_requests=120, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many ingress requests")

    context = RoutingContext(
        tenant_id=payload.routing.tenant_id,
        channel_binding_id=payload.routing.channel_binding_id,
        openclaw_account_id=payload.routing.openclaw_account_id,
        context_token=payload.routing.context_token,
        target_conversation=payload.routing.target_conversation,
        channel=payload.routing.channel,
        session_space=payload.routing.session_space,
        timezone_name=payload.routing.timezone,
        quiet_hours=payload.routing.quiet_hours,
    )
    service = _confirmation_service(request)
    outbox = _outbox_service(request)
    conversation_memory = _conversation_memory_service(request)

    if payload.message.type == "text":
        return await _handle_text_message(service, outbox, conversation_memory, context, payload.message)
    if payload.message.type == "voice":
        return await _handle_voice_message(service, outbox, conversation_memory, context, payload.message)
    if payload.message.type == "image":
        return await _handle_image_message(service, outbox, conversation_memory, context, payload.message)

    return {
        "result_type": "ignored",
        "reply_text": "这类消息目前只做接收，当前没有改动持仓，也没有下单。",
    }


async def _handle_text_message(
    service: ConfirmationCenterService,
    outbox: DeliveryOutboxService | None,
    conversation_memory: ConversationMemoryService | None,
    context: RoutingContext,
    message: MessagePayload,
) -> dict[str, Any]:
    text = message.text or ""
    conversation_context = await _safe_conversation_context(conversation_memory, context)
    await _safe_append_user_message(
        conversation_memory,
        context,
        content=safe_content_from_message(text=text),
        content_type="text",
        message_id=message.id,
        raw_payload=message.metadata,
    )
    command = parse_confirmation_command(text)
    if command is not None:
        result = await service.submit_decision(context, command)
        response = {
            "result_type": "decision_received",
            "decision": result.outcome,
            "pending_action_id": result.pending_action_id,
            "confirmation_session_id": result.confirmation_session_id,
            "status": result.status,
            "reply_text": result.reply_text,
            "webapp_deep_link": result.deep_link,
        }
        await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
        return response

    candidate = classify_high_attention_text(
        text,
        source_type="message_trade_input",
        source_surface="wechat",
    )
    if candidate is None:
        quote_symbol = _extract_realtime_quote_symbol(text)
        if quote_symbol:
            quote_payload = await _fetch_realtime_quote(quote_symbol)
            response = _market_quote_response(quote_symbol, quote_payload)
            await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
            return response

        portfolio_response = await _portfolio_market_response(context, text)
        if portfolio_response is not None:
            await _safe_append_assistant_reply(conversation_memory, context, portfolio_response["reply_text"])
            return portfolio_response

        search_response = await _realtime_search_response(text)
        if search_response is not None:
            await _safe_append_assistant_reply(conversation_memory, context, search_response["reply_text"])
            return search_response

        model_result = await generate_openclaw_reply(
            text,
            context=context,
            route="deep" if is_deep_research_request(text) else "light",
            conversation_context=conversation_context,
        )
        response = _model_response(model_result)
        await _safe_append_assistant_reply(
            conversation_memory,
            context,
            response["reply_text"],
            result=model_result,
        )
        return response

    if _wechat_skip_confirmation_center():
        response = _readonly_acknowledgement_response(candidate)
        await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
        return response

    created = await _create_pending_confirmation_safely(service, context, candidate)
    if created is None:
        response = _confirmation_unavailable_response(candidate)
        await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
        return response
    await _enqueue_confirmation_prompt(outbox, context, candidate, created)
    response = _confirmation_response(created, candidate.normalized_summary["title"])
    await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
    return response


async def _handle_voice_message(
    service: ConfirmationCenterService,
    outbox: DeliveryOutboxService | None,
    conversation_memory: ConversationMemoryService | None,
    context: RoutingContext,
    message: MessagePayload,
) -> dict[str, Any]:
    transcript = message.transcript or message.text or ""
    conversation_context = await _safe_conversation_context(conversation_memory, context)
    await _safe_append_user_message(
        conversation_memory,
        context,
        content=safe_content_from_message(transcript=transcript),
        content_type="voice",
        message_id=message.id,
        raw_payload=message.metadata,
    )
    interpretation = interpret_voice_transcript(
        transcript,
        confidence=message.transcript_confidence,
    )
    if interpretation.mode == "decision" and interpretation.parsed_command is not None:
        result = await service.submit_decision(context, interpretation.parsed_command)
        response = {
            "result_type": "decision_received",
            "decision": result.outcome,
            "pending_action_id": result.pending_action_id,
            "confirmation_session_id": result.confirmation_session_id,
            "status": result.status,
            "reply_text": result.reply_text,
            "webapp_deep_link": result.deep_link,
        }
        await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
        return response

    if interpretation.mode == "pending_action" and interpretation.candidate is not None:
        if _wechat_skip_confirmation_center():
            response = _readonly_acknowledgement_response(interpretation.candidate)
            await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
            return response

        created = await _create_pending_confirmation_safely(service, context, interpretation.candidate)
        if created is None:
            response = _confirmation_unavailable_response(interpretation.candidate)
            await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
            return response
        await _enqueue_confirmation_prompt(
            outbox,
            context,
            interpretation.candidate,
            created,
        )
        response = _confirmation_response(created, interpretation.candidate.normalized_summary["title"])
        await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
        return response

    model_result = await generate_openclaw_reply(
        transcript,
        context=context,
        route="deep" if is_deep_research_request(transcript) else "light",
        conversation_context=conversation_context,
    )
    response = _model_response(model_result)
    await _safe_append_assistant_reply(
        conversation_memory,
        context,
        response["reply_text"],
        result=model_result,
    )
    return response


async def _handle_image_message(
    service: ConfirmationCenterService,
    outbox: DeliveryOutboxService | None,
    conversation_memory: ConversationMemoryService | None,
    context: RoutingContext,
    message: MessagePayload,
) -> dict[str, Any]:
    extracted_text = message.ocr_text or message.image_text or ""
    source_field = "ocr_text" if message.ocr_text else "image_text"
    vision_positions: list[dict[str, Any]] | None = None
    metadata = dict(message.metadata)
    if not extracted_text:
        vision = await extract_image_text_from_metadata(metadata)
        if vision is not None:
            if vision.error:
                logger.warning("image vision extraction failed: %s", vision.error)
            extracted_text = vision.ocr_text
            vision_positions = vision.positions
            if vision.confidence is not None and message.ocr_confidence is None:
                message.ocr_confidence = vision.confidence
            metadata.update(
                {
                    "vision_provider": vision.provider,
                    "vision_model": vision.model,
                    "vision_response_id": vision.response_id,
                    "vision_error": vision.error,
                }
            )
            source_field = "ocr_text"
    await _safe_append_user_message(
        conversation_memory,
        context,
        content=safe_content_from_message(
            image_text=extracted_text,
            media_id=message.media_id,
        ),
        content_type="image",
        message_id=message.id,
        raw_payload=metadata,
    )
    candidate = classify_image_text_candidate(
        extracted_text,
        ocr_confidence=message.ocr_confidence,
        media_id=message.media_id,
        metadata=metadata,
        positions=vision_positions,
        source_field=source_field,
        source_surface="wechat",
    )
    if candidate is None:
        response = _image_unrecognized_response(metadata, message)
        await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
        return response
    if _wechat_skip_confirmation_center():
        response = _readonly_acknowledgement_response(candidate)
        await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
        return response

    created = await _create_pending_confirmation_safely(service, context, candidate)
    if created is None:
        response = _confirmation_unavailable_response(candidate)
        await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
        return response
    await _enqueue_confirmation_prompt(outbox, context, candidate, created)
    response = _confirmation_response(created, candidate.normalized_summary["title"])
    await _safe_append_assistant_reply(conversation_memory, context, response["reply_text"])
    return response


def _image_unrecognized_response(metadata: dict[str, Any], message: MessagePayload) -> dict[str, Any]:
    media_download = metadata.get("media_download")
    vision_error = str(metadata.get("vision_error") or "").strip()
    reason = "暂时没有拿到可确认的文字内容"
    if isinstance(media_download, dict):
        status = str(media_download.get("status") or "").strip()
        error = str(media_download.get("error") or "").strip()
        if status == "failed":
            reason = f"图片下载失败{f'：{error}' if error else ''}"
        elif status == "missing_media_reference":
            reason = "只收到图片标识，但没有拿到可下载的图片内容"
    if vision_error:
        if vision_error.startswith("missing_"):
            reason = "图片识别服务暂未配置完成"
        elif "image_vision_disabled" in vision_error:
            reason = "图片识别服务当前被关闭"
        else:
            reason = f"图片识别服务调用失败：{vision_error}"
    elif not any(
        isinstance(metadata.get(key), str) and str(metadata.get(key)).strip()
        for key in ("image_data_url", "image_url", "media_url")
    ) and message.media_id:
        reason = "只收到图片标识，但没有拿到可下载的图片内容"
    return {
        "result_type": "image_unrecognized",
        "reply_text": f"这张图片处理失败：{reason}。当前没有改动持仓，也没有下单。",
    }


async def _safe_conversation_context(
    conversation_memory: ConversationMemoryService | None,
    context: RoutingContext,
) -> str | None:
    if conversation_memory is None:
        return None
    try:
        conversation_context = await conversation_memory.context_for_model(context)
        rendered = conversation_context.render_for_prompt()
        return rendered or None
    except Exception as exc:  # pragma: no cover - repository failures vary by deployment
        logger.warning("conversation context unavailable: tenant=%s error=%s", context.tenant_id, exc)
        return None


async def _safe_append_user_message(
    conversation_memory: ConversationMemoryService | None,
    context: RoutingContext,
    *,
    content: str,
    content_type: str,
    message_id: str | None,
    raw_payload: dict[str, Any] | None,
) -> None:
    if conversation_memory is None:
        return
    try:
        await conversation_memory.append_user_message(
            context,
            content=content,
            content_type=content_type,
            message_id=message_id,
            raw_payload=raw_payload,
        )
    except Exception as exc:  # pragma: no cover - repository failures vary by deployment
        logger.warning("conversation user turn write failed: tenant=%s error=%s", context.tenant_id, exc)


async def _safe_append_assistant_reply(
    conversation_memory: ConversationMemoryService | None,
    context: RoutingContext,
    content: str,
    *,
    result: ModelDialogueResult | None = None,
) -> None:
    if conversation_memory is None:
        return
    try:
        await conversation_memory.append_assistant_reply(
            context,
            content=content,
            result=result,
        )
    except Exception as exc:  # pragma: no cover - repository failures vary by deployment
        logger.warning("conversation assistant turn write failed: tenant=%s error=%s", context.tenant_id, exc)


async def _create_pending_confirmation_safely(
    service: ConfirmationCenterService,
    context: RoutingContext,
    candidate: PendingActionInput,
) -> Any | None:
    try:
        return await service.create_pending_confirmation(context, candidate)
    except Exception as exc:  # pragma: no cover - exact database errors vary by environment
        logger.exception(
            "confirmation center write failed: tenant=%s action=%s object=%s error=%s",
            context.tenant_id,
            candidate.action_type,
            candidate.object_type,
            exc,
        )
        return None


async def _enqueue_confirmation_prompt(
    outbox: DeliveryOutboxService | None,
    context: RoutingContext,
    candidate: PendingActionInput,
    created: Any,
) -> None:
    if outbox is None or not context.channel_binding_id or not context.openclaw_account_id:
        return

    envelope = DeliveryEnvelope(
        tenant_id=context.tenant_id,
        channel_binding_id=context.channel_binding_id,
        openclaw_account_id=context.openclaw_account_id,
        content_type="confirmation_card",
        dedupe_key=f"{context.tenant_id}:{candidate.action_type}:{created.confirmation_session_id}",
        target_conversation=context.target_conversation,
        context_token=context.context_token,
        priority="high" if candidate.risk_level == "high" else "normal",
        confirmation_session_id=created.confirmation_session_id,
        content={
            "title": candidate.normalized_summary.get("title"),
            "body": candidate.normalized_summary.get("body"),
            "command_hint": created.command_hint,
            "reject_hint": f"取消 {created.session_token}",
            "deep_link": created.deep_link,
            "expires_at": created.expires_at.isoformat(),
            "risk_note": candidate.normalized_summary.get("risk_note"),
        },
    )
    await outbox.enqueue(envelope, quiet_hours=context.quiet_hours)


def _confirmation_response(created: Any, title: str) -> dict[str, Any]:
    return {
        "result_type": "confirmation_required",
        "pending_action_id": created.pending_action_id,
        "confirmation_session_id": created.confirmation_session_id,
        "session_token": created.session_token,
        "status": created.status,
        "webapp_deep_link": created.deep_link,
        "reply_text": (
            f"{title}已放入确认中心。回复“{created.command_hint}”即可继续，"
            f"也可以打开确认页面链接查看详情；两边看到的是同一条确认事项。"
            "确认前不会改动持仓，也不会下单。"
        ),
        "expires_at": created.expires_at.isoformat(),
    }


def _confirmation_unavailable_response(candidate: PendingActionInput) -> dict[str, Any]:
    title = candidate.normalized_summary.get("title") or "待确认事项"
    return {
        "result_type": "confirmation_unavailable",
        "model_stub": True,
        "reply_text": (
            f"我识别到这是需要确认的操作：{title}。"
            "但确认中心暂时没有保存成功，所以我没有记录持仓、没有生成有效草稿，也没有下单。"
            "请稍后在微信重试；也可以到确认中心查看服务恢复后的状态。"
        ),
    }


def _readonly_acknowledgement_response(candidate: PendingActionInput) -> dict[str, Any]:
    title = str(candidate.normalized_summary.get("title") or "这条待处理事项")
    return {
        "result_type": "readonly_ack",
        "reply_text": (
            f"我已识别到你要【{title}】。目前 Hermes 处于只读模式："
            "我会直接回执，不会改动持仓，也不会下单；"
            "当前不会经过确认中心。"
        ),
    }


def _model_response(result: ModelDialogueResult) -> dict[str, Any]:
    return {
        "result_type": "query_routed" if result.stub else "model_reply",
        "model_route": result.route,
        "model_provider": result.provider,
        "model": result.model,
        "model_response_id": result.response_id,
        "model_stub": result.stub,
        "model_error": result.error,
        "reply_text": result.reply_text,
    }


def _extract_realtime_quote_symbol(text: str) -> str | None:
    lowered = text.lower()
    if not any(keyword.lower() in lowered for keyword in QUOTE_KEYWORDS):
        return None
    for raw_symbol in QUOTE_SYMBOL_RE.findall(text.upper()):
        symbol = _normalize_quote_symbol(raw_symbol)
        if symbol:
            return symbol
    return None


def _normalize_quote_symbol(raw_symbol: str) -> str | None:
    symbol = raw_symbol.strip().upper()
    if not symbol:
        return None
    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith(("5", "6", "9")):
            return f"SH{symbol}"
        if symbol.startswith(("0", "1", "2", "3")):
            return f"SZ{symbol}"
    return symbol


async def _fetch_realtime_quote(symbol: str) -> dict[str, Any]:
    base_url = _data_service_base_url()
    timeout = float(os.getenv("OPENCLAW_DATA_SERVICE_TIMEOUT_SECONDS", "10"))
    url = f"{base_url}/api/quote/{urllib.parse.quote(symbol)}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params={"max_age_seconds": 60})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
    if not isinstance(payload, dict):
        return {"ok": False, "message": "quote response is not a JSON object"}
    if not payload.get("ok"):
        return {"ok": False, "message": _quote_error_message(payload)}
    return payload


def _market_quote_response(symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("ok") or not isinstance(payload.get("data"), dict):
        message = payload.get("message") or payload.get("error") or "data-service 没有返回可用行情"
        return {
            "result_type": "market_quote_unavailable",
            "symbol": symbol,
            "reply_text": (
                f"{symbol} 实时行情暂时不可用：{message}。"
                "我不会用过期或低可信数据替代实时价格；可以稍后重试，或先查看持仓和风险框架。"
            ),
        }

    quote = payload["data"]
    price = _format_quote_number(quote.get("price"))
    change = _format_quote_number(quote.get("change"), signed=True)
    change_rate = _format_quote_number(quote.get("change_rate"), signed=True)
    currency = str(quote.get("currency") or "").strip()
    source = _quote_source_label(quote)
    freshness = quote.get("freshness_seconds")
    freshness_note = f"，约 {int(freshness)} 秒前" if isinstance(freshness, (int, float)) else ""
    actionability = str(quote.get("quote_actionability") or "")
    action_note = "；该行情只用于分析，不作为下单确认价格" if actionability == "analysis_only" else ""
    reply = f"{quote.get('symbol') or symbol} 实时行情：{price} {currency}".strip()
    if change != "--" or change_rate != "--":
        reply += f"，涨跌 {change} / {change_rate}%"
    reply += f"（来源：{source}{freshness_note}{action_note}）。当前不会改动持仓，也不会下单。"
    return {
        "result_type": "market_quote",
        "symbol": quote.get("symbol") or symbol,
        "source": quote.get("source"),
        "source_tier": quote.get("source_tier"),
        "freshness_status": quote.get("freshness_status"),
        "quote_actionability": actionability,
        "reply_text": reply,
    }


async def _portfolio_market_response(context: RoutingContext, text: str) -> dict[str, Any] | None:
    if not _looks_like_portfolio_market_question(text):
        return None

    positions_payload = await _fetch_portfolio_positions(context.tenant_id)
    if not positions_payload.get("ok"):
        logger.warning(
            "portfolio market context unavailable: tenant=%s error=%s",
            context.tenant_id,
            positions_payload.get("message"),
        )
        return None

    positions = _portfolio_equity_positions(positions_payload)
    if not positions:
        return {
            "result_type": "portfolio_market_context",
            "portfolio_positions_count": 0,
            "reply_text": "我查了当前持仓系统，还没有可分析的股票持仓快照。当前不会改动持仓，也不会下单。",
        }

    symbols = _top_position_symbols(positions)
    quotes_payload = await _fetch_batch_quotes(symbols)
    quote_map = _quote_data_map(quotes_payload)
    failed_symbols = list(quotes_payload.get("failed") or []) if isinstance(quotes_payload, dict) else []

    reply_text = _render_portfolio_market_reply(
        positions=positions,
        quote_map=quote_map,
        failed_symbols=failed_symbols,
        positions_payload=positions_payload,
    )
    return {
        "result_type": "portfolio_market_context",
        "portfolio_positions_count": len(positions),
        "quoted_symbols": list(quote_map.keys()),
        "failed_symbols": failed_symbols,
        "reply_text": reply_text,
    }


def _looks_like_portfolio_market_question(text: str) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in PORTFOLIO_MARKET_KEYWORDS)


async def _realtime_search_response(text: str) -> dict[str, Any] | None:
    query = _extract_realtime_search_query(text)
    if query is None:
        return None

    payload = await _fetch_realtime_search(query)
    if not payload.get("ok"):
        message = payload.get("message") or "搜索工具没有返回结果"
        return {
            "result_type": "realtime_search_unavailable",
            "query": query,
            "reply_text": (
                f"我识别到你要实时搜索“{query}”，但当前 MiniMax 搜索工具暂时不可用：{message}。"
                "这次不会编造搜索结果；你可以稍后重试，或先让我基于已有持仓和行情数据做分析。"
            ),
        }

    results = _normalize_search_results(payload)
    if not results:
        return {
            "result_type": "realtime_search",
            "query": query,
            "results_count": 0,
            "reply_text": f"我实时搜索了“{query}”，但暂时没有拿到可引用的结果。当前不会改动持仓，也不会下单。",
        }

    return {
        "result_type": "realtime_search",
        "query": query,
        "results_count": len(results),
        "reply_text": _render_realtime_search_reply(query, results),
    }


def _extract_realtime_search_query(text: str) -> str | None:
    normalized = text.strip()
    lowered = normalized.lower()
    if not any(keyword.lower() in lowered for keyword in REALTIME_SEARCH_KEYWORDS):
        return None

    query = re.sub(
        r"^(帮我|给我|请|麻烦)?\s*(实时搜索|联网搜索|搜索一下|搜一下|查一下最新|查一下|搜索|搜|看看最新|看看)\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip(" ：:，,。")
    query = re.sub(r"(的)?(最新消息|相关新闻|新闻)$", "", query).strip(" ：:，,。")
    return query or normalized


async def _fetch_realtime_search(query: str) -> dict[str, Any]:
    mmx_payload = await _run_mmx_search(query)
    if mmx_payload.get("ok"):
        mmx_payload.setdefault("source", "minimax")
        return mmx_payload

    ftshare_payload = await _run_ftshare_news_search(query)
    if ftshare_payload.get("ok"):
        ftshare_payload.setdefault("source", "ftshare")
        return ftshare_payload

    mmx_message = mmx_payload.get("message") or "MiniMax search failed"
    ftshare_message = ftshare_payload.get("message") or "FTShare news search failed"
    return {"ok": False, "message": f"MiniMax: {mmx_message}; FTShare: {ftshare_message}"}


async def _run_mmx_search(query: str) -> dict[str, Any]:
    cli = os.getenv("MMX_CLI_PATH") or shutil.which("mmx")
    if not cli:
        return {"ok": False, "message": "mmx CLI not found"}

    timeout = float(os.getenv("OPENCLAW_REALTIME_SEARCH_TIMEOUT_SECONDS", "20"))
    command = [cli, "search", "query", "--q", query, "--output", "json", "--quiet"]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        return {"ok": False, "message": "mmx search timed out"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}

    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        return {"ok": False, "message": stderr_text or stdout_text or f"mmx exited with {process.returncode}"}
    if not stdout_text:
        return {"ok": True, "data": []}
    try:
        return {"ok": True, "data": json.loads(stdout_text)}
    except json.JSONDecodeError:
        return {"ok": True, "data": stdout_text}


async def _run_ftshare_news_search(query: str) -> dict[str, Any]:
    skill_dir = (
        os.getenv("FTSHARE_MARKET_DATA_SKILL_DIR")
        or os.getenv("OPENCLAW_FTSHARE_MARKET_DATA_SKILL_DIR")
        or "/app/openclaw/skills/ftshare-market-data"
    )
    run_py = os.path.join(skill_dir, "run.py")
    if not os.path.exists(run_py):
        local_run_py = os.path.join(os.getcwd(), "openclaw", "skills", "ftshare-market-data", "run.py")
        if os.path.exists(local_run_py):
            run_py = local_run_py
        else:
            return {"ok": False, "message": f"FTShare skill not found: {run_py}"}

    python_bin = os.getenv("OPENCLAW_PYTHON_BIN") or shutil.which("python3") or shutil.which("python") or "python3"
    timeout = float(os.getenv("OPENCLAW_REALTIME_SEARCH_TIMEOUT_SECONDS", "20"))
    command = [python_bin, run_py, "semantic-search-news", "--query", query, "--limit", "5"]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        return {"ok": False, "message": "FTShare news search timed out"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}

    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        return {"ok": False, "message": stderr_text or stdout_text or f"FTShare exited with {process.returncode}"}
    if not stdout_text:
        return {"ok": True, "source": "ftshare", "data": []}
    try:
        return {"ok": True, "source": "ftshare", "data": json.loads(stdout_text)}
    except json.JSONDecodeError:
        return {"ok": True, "source": "ftshare", "data": stdout_text}


def _normalize_search_results(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw = payload.get("data")
    candidates: Any = raw
    if isinstance(raw, dict):
        for key in ("results", "items", "data", "search_results", "records", "list"):
            if isinstance(raw.get(key), list):
                candidates = raw[key]
                break
    if isinstance(candidates, str):
        return [{"title": "MiniMax 搜索结果", "snippet": candidates[:600], "url": ""}]
    if not isinstance(candidates, list):
        return []

    results: list[dict[str, str]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or item.get("headline") or "").strip()
        snippet = str(item.get("snippet") or item.get("summary") or item.get("content") or item.get("description") or "").strip()
        url = str(item.get("url") or item.get("link") or item.get("source_url") or item.get("article_url") or "").strip()
        source = str(item.get("source") or item.get("source_site") or item.get("media_name") or "").strip()
        published_at = str(item.get("published_at") or item.get("publish_time") or item.get("date") or "").strip()
        if not title and not snippet:
            continue
        results.append(
            {
                "title": title or url or "搜索结果",
                "snippet": snippet,
                "url": url,
                "source": source,
                "published_at": published_at,
            }
        )
    return results


def _render_realtime_search_reply(query: str, results: list[dict[str, str]]) -> str:
    lines = [f"我实时搜索了“{query}”，先给你可核对的摘要："]
    for index, result in enumerate(results[:5], start=1):
        title = result["title"]
        snippet = result["snippet"]
        url = result["url"]
        line = f"{index}. {title}"
        source_note = " / ".join(part for part in (result.get("source"), result.get("published_at")) if part)
        if source_note:
            line += f"（{source_note}）"
        if snippet:
            line += f"：{snippet[:180]}"
        if url:
            line += f"\n{url}"
        lines.append(line)
    lines.append("这些结果只作为外部参考；涉及持仓、交易记录或规则变更会进入后续合规落地环节，不会自动下单。")
    return "\n".join(lines)


async def _fetch_portfolio_positions(tenant_id: str) -> dict[str, Any]:
    base_url = _data_service_base_url()
    timeout = float(os.getenv("OPENCLAW_DATA_SERVICE_TIMEOUT_SECONDS", "10"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base_url}/api/v3/portfolio/positions", params={"tenant_id": tenant_id})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
    if not isinstance(payload, dict):
        return {"ok": False, "message": "positions response is not a JSON object"}
    return payload


async def _fetch_batch_quotes(symbols: list[str]) -> dict[str, Any]:
    if not symbols:
        return {"ok": True, "data": {}, "failed": []}
    base_url = _data_service_base_url()
    timeout = float(os.getenv("OPENCLAW_DATA_SERVICE_TIMEOUT_SECONDS", "10"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url}/api/quote/batch",
                json={"symbols": symbols},
                params={"max_age_seconds": 60},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {"ok": False, "data": {}, "failed": symbols, "message": str(exc)}
    if not isinstance(payload, dict):
        return {"ok": False, "data": {}, "failed": symbols, "message": "batch quote response is not a JSON object"}
    return payload


def _portfolio_equity_positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    rows = data.get("equity_positions")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("symbol")]


def _top_position_symbols(positions: list[dict[str, Any]], *, limit: int = 10) -> list[str]:
    sorted_positions = sorted(
        positions,
        key=lambda row: abs(_to_float(row.get("base_market_value") or row.get("market_value") or row.get("cost_basis"))),
        reverse=True,
    )
    symbols: list[str] = []
    for row in sorted_positions:
        symbol = _normalize_quote_symbol(str(row.get("symbol") or ""))
        if symbol and symbol not in symbols:
            symbols.append(symbol)
        if len(symbols) >= limit:
            break
    return symbols


def _quote_data_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {}
    return {str(symbol): quote for symbol, quote in data.items() if isinstance(quote, dict)}


def _render_portfolio_market_reply(
    *,
    positions: list[dict[str, Any]],
    quote_map: dict[str, dict[str, Any]],
    failed_symbols: list[str],
    positions_payload: dict[str, Any],
) -> str:
    lines = ["我先按当前持仓系统里的快照和实时行情源做一个只读检查："]
    lines.append(f"持仓快照：股票 {len(positions)} 个标的。")

    actionable_quotes = [
        quote
        for quote in quote_map.values()
        if str(quote.get("quote_actionability") or "") in {"analysis_only", "trade_candidate"}
    ]
    blocked_quotes = [
        quote
        for quote in quote_map.values()
        if str(quote.get("quote_actionability") or "") not in {"analysis_only", "trade_candidate"}
    ]

    if actionable_quotes:
        lines.append("可用于分析的行情：")
        for quote in actionable_quotes[:6]:
            symbol = str(quote.get("symbol") or "").strip()
            price = _format_quote_number(quote.get("price"))
            change_rate = _format_quote_number(quote.get("change_rate"), signed=True)
            currency = str(quote.get("currency") or "").strip()
            source = _quote_source_label(quote)
            lines.append(f"- {symbol}: {price} {currency}, {change_rate}%, {source}")
    else:
        lines.append("这次没有拿到可用于分析的实时行情。")

    if blocked_quotes or failed_symbols:
        unavailable = [str(quote.get("symbol") or symbol) for symbol, quote in quote_map.items() if quote in blocked_quotes]
        unavailable.extend(str(symbol) for symbol in failed_symbols)
        if unavailable:
            lines.append(f"暂不可用/过期的行情：{', '.join(dict.fromkeys(unavailable))}。")

    largest = _largest_position_line(positions, quote_map)
    if largest:
        lines.append(largest)

    freshness = _portfolio_freshness_note(positions_payload)
    if freshness:
        lines.append(f"持仓快照时间：{freshness}。")
    lines.append("当前回复只做分析参考，不会改动持仓，也不会下单。")
    return "\n".join(lines)


def _largest_position_line(positions: list[dict[str, Any]], quote_map: dict[str, dict[str, Any]]) -> str | None:
    if not positions:
        return None
    largest = max(
        positions,
        key=lambda row: abs(_to_float(row.get("base_market_value") or row.get("market_value") or row.get("cost_basis"))),
    )
    symbol = str(largest.get("symbol") or "").strip()
    name = str(largest.get("name") or "").strip()
    value = _format_quote_number(largest.get("base_market_value") or largest.get("market_value") or largest.get("cost_basis"))
    quote = quote_map.get(_normalize_quote_symbol(symbol) or symbol) or quote_map.get(symbol)
    quote_note = ""
    if quote:
        quote_note = f"，当前涨跌 { _format_quote_number(quote.get('change_rate'), signed=True) }%"
    return f"最大持仓观察：{name or symbol} 市值约 {value}{quote_note}。"


def _portfolio_freshness_note(payload: dict[str, Any]) -> str | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    freshness = data.get("freshness") if isinstance(data, dict) else None
    if not isinstance(freshness, dict):
        return None
    as_of = freshness.get("as_of") or freshness.get("received_at")
    age = freshness.get("age_seconds")
    if as_of and isinstance(age, (int, float)):
        return f"{as_of}，约 {int(age)} 秒前"
    if as_of:
        return str(as_of)
    return None


def _data_service_base_url() -> str:
    return (
        os.getenv("OPENCLAW_DATA_SERVICE_URL")
        or os.getenv("DATA_SERVICE_URL")
        or "http://data-service:8000"
    ).rstrip("/")


def _quote_error_message(payload: dict[str, Any]) -> str:
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("error") or detail)
    if isinstance(detail, str):
        return detail
    return str(payload.get("message") or payload.get("error") or "unknown quote error")


def _format_quote_number(value: Any, *, signed: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if signed and number > 0:
        return f"+{number:.2f}"
    return f"{number:.2f}"


def _quote_source_label(quote: dict[str, Any]) -> str:
    source = str(quote.get("source") or quote.get("source_key") or "").lower()
    if source:
        return source
    if quote.get("source_fallback"):
        return "fallback"
    return str(quote.get("source") or quote.get("source_key") or "data-service")


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
