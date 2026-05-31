"""
WeChat / OpenClaw ingress router for P0 confirmation-safe interactions.
"""
from __future__ import annotations

import logging
import os
import re
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
QUOTE_SYMBOL_RE = re.compile(r"(?<![A-Z0-9])(?:SH|SZ|HK)?[A-Z]{1,6}\d{0,5}(?![A-Z0-9])|(?<!\d)\d{6}(?!\d)")


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

    if payload.message.type == "text":
        return await _handle_text_message(service, outbox, context, payload.message)
    if payload.message.type == "voice":
        return await _handle_voice_message(service, outbox, context, payload.message)
    if payload.message.type == "image":
        return await _handle_image_message(service, outbox, context, payload.message)

    return {
        "result_type": "ignored",
        "reply_text": "这类消息目前只做接收，当前没有改动持仓，也没有下单。",
    }


async def _handle_text_message(
    service: ConfirmationCenterService,
    outbox: DeliveryOutboxService | None,
    context: RoutingContext,
    message: MessagePayload,
) -> dict[str, Any]:
    text = message.text or ""
    command = parse_confirmation_command(text)
    if command is not None:
        result = await service.submit_decision(context, command)
        return {
            "result_type": "decision_received",
            "decision": result.outcome,
            "pending_action_id": result.pending_action_id,
            "confirmation_session_id": result.confirmation_session_id,
            "status": result.status,
            "reply_text": result.reply_text,
            "webapp_deep_link": result.deep_link,
        }

    candidate = classify_high_attention_text(
        text,
        source_type="message_trade_input",
        source_surface="wechat",
    )
    if candidate is None:
        quote_symbol = _extract_realtime_quote_symbol(text)
        if quote_symbol:
            quote_payload = await _fetch_realtime_quote(quote_symbol)
            return _market_quote_response(quote_symbol, quote_payload)

        model_result = await generate_openclaw_reply(
            text,
            context=context,
            route="deep" if is_deep_research_request(text) else "light",
        )
        return _model_response(model_result)

    created = await service.create_pending_confirmation(context, candidate)
    await _enqueue_confirmation_prompt(outbox, context, candidate, created)
    return _confirmation_response(created, candidate.normalized_summary["title"])


async def _handle_voice_message(
    service: ConfirmationCenterService,
    outbox: DeliveryOutboxService | None,
    context: RoutingContext,
    message: MessagePayload,
) -> dict[str, Any]:
    transcript = message.transcript or message.text or ""
    interpretation = interpret_voice_transcript(
        transcript,
        confidence=message.transcript_confidence,
    )
    if interpretation.mode == "decision" and interpretation.parsed_command is not None:
        result = await service.submit_decision(context, interpretation.parsed_command)
        return {
            "result_type": "decision_received",
            "decision": result.outcome,
            "pending_action_id": result.pending_action_id,
            "confirmation_session_id": result.confirmation_session_id,
            "status": result.status,
            "reply_text": result.reply_text,
            "webapp_deep_link": result.deep_link,
        }

    if interpretation.mode == "pending_action" and interpretation.candidate is not None:
        created = await service.create_pending_confirmation(context, interpretation.candidate)
        await _enqueue_confirmation_prompt(
            outbox,
            context,
            interpretation.candidate,
            created,
        )
        return _confirmation_response(created, interpretation.candidate.normalized_summary["title"])

    model_result = await generate_openclaw_reply(
        transcript,
        context=context,
        route="deep" if is_deep_research_request(transcript) else "light",
    )
    return _model_response(model_result)


async def _handle_image_message(
    service: ConfirmationCenterService,
    outbox: DeliveryOutboxService | None,
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
        return {
            "result_type": "query_routed",
            "reply_text": "这张图片里暂时没有拿到可确认的文字内容。当前没有改动持仓，也没有下单。",
        }
    created = await service.create_pending_confirmation(context, candidate)
    await _enqueue_confirmation_prompt(outbox, context, candidate, created)
    return _confirmation_response(created, candidate.normalized_summary["title"])


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
            f"也可以打开确认页面链接查看详情。确认前不会改动持仓，也不会下单。"
        ),
        "expires_at": created.expires_at.isoformat(),
    }


def _model_response(result: ModelDialogueResult) -> dict[str, Any]:
    return {
        "result_type": "model_route_unavailable" if result.stub else "model_reply",
        "model_route": result.route,
        "model_provider": result.provider,
        "model": result.model,
        "model_response_id": result.response_id,
        "model_stub": result.stub,
        "model_error": result.error,
        "reply_text": result.reply_text,
    }


def _extract_realtime_quote_symbol(text: str) -> str | None:
    normalized = text.strip()
    if not normalized:
        return None
    if not any(keyword.lower() in normalized.lower() for keyword in QUOTE_KEYWORDS):
        return None

    for match in QUOTE_SYMBOL_RE.finditer(normalized.upper()):
        symbol = match.group(0)
        if symbol in {"US", "HK", "CN", "ETF", "QUOTE", "PRICE"}:
            continue
        if symbol.isdigit() and len(symbol) == 6:
            if symbol.startswith("6"):
                return f"SH{symbol}"
            if symbol.startswith(("0", "3")):
                return f"SZ{symbol}"
        return symbol
    return None


async def _fetch_realtime_quote(symbol: str) -> dict[str, Any]:
    base_url = (
        os.getenv("OPENCLAW_DATA_SERVICE_URL")
        or os.getenv("DATA_SERVICE_URL")
        or "http://data-service:8000"
    ).rstrip("/")
    query = urllib.parse.urlencode(
        {
            "source": "futu",
            "require_fresh": "true",
            "max_age_seconds": os.getenv("OPENCLAW_REALTIME_QUOTE_MAX_AGE_SECONDS", "60"),
        }
    )
    url = f"{base_url}/api/quote/{urllib.parse.quote(symbol)}?{query}"
    timeout = float(os.getenv("OPENCLAW_DATA_SERVICE_TIMEOUT_SECONDS", "10"))
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url)
        try:
            payload = response.json()
        except ValueError:
            payload = {"ok": False, "message": response.text[:240]}
        if response.status_code >= 400:
            return {
                "ok": False,
                "status_code": response.status_code,
                "message": _quote_error_message(payload),
            }
        return payload if isinstance(payload, dict) else {"ok": False, "message": "行情服务返回格式异常"}


def _market_quote_response(symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("ok") or not isinstance(payload.get("data"), dict):
        message = payload.get("message") or "实时行情源暂时不可用"
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
    freshness_text = f"，约 {freshness}s 前更新" if isinstance(freshness, (int, float)) else ""
    actionability = str(quote.get("quote_actionability") or "")

    reply = f"{quote.get('symbol') or symbol} 实时行情：{price} {currency}".strip()
    if change != "-":
        reply += f"，涨跌 {change}"
    if change_rate != "-":
        reply += f"（{change_rate}%）"
    reply += f"。来源：{source}{freshness_text}。"
    if actionability != "trade_draft":
        reply += "当前数据未达到交易草稿级新鲜度，只作为观察参考。"

    return {
        "result_type": "market_quote",
        "symbol": quote.get("symbol") or symbol,
        "source": quote.get("source"),
        "source_tier": quote.get("source_tier"),
        "freshness_status": quote.get("freshness_status"),
        "quote_actionability": actionability,
        "reply_text": reply,
    }


def _quote_error_message(payload: dict[str, Any]) -> str:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or "实时行情源暂时不可用")
    return str(payload.get("message") or detail or "实时行情源暂时不可用")


def _format_quote_number(value: Any, *, signed: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    prefix = "+" if signed and number > 0 else ""
    return f"{prefix}{number:.2f}"


def _quote_source_label(quote: dict[str, Any]) -> str:
    source = str(quote.get("source") or quote.get("source_key") or "").lower()
    if source == "futu" or "futu" in source:
        return "Futu OpenD"
    return str(quote.get("source") or quote.get("source_key") or "data-service")
