"""
WeChat / OpenClaw ingress router for P0 confirmation-safe interactions.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from openclaw.gateway.confirmation_center import (
    ConfirmationCenterService,
    RoutingContext,
    classify_high_attention_text,
    classify_image_text_candidate,
    interpret_voice_transcript,
    parse_confirmation_command,
)
from openclaw.gateway.outbox import DeliveryEnvelope, DeliveryOutboxService
from openclaw.gateway.webhook_security import check_rate_limit

router = APIRouter(prefix="/api/openclaw", tags=["openclaw-gateway"])


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
        return {
            "result_type": "query_routed",
            "reply_text": "已收到，我会按普通问题继续处理。当前没有改动持仓，也没有下单。",
        }

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

    return {
        "result_type": "query_routed",
        "reply_text": "这段语音已按普通问题继续处理。当前没有改动持仓，也没有下单。",
    }


async def _handle_image_message(
    service: ConfirmationCenterService,
    outbox: DeliveryOutboxService | None,
    context: RoutingContext,
    message: MessagePayload,
) -> dict[str, Any]:
    extracted_text = message.ocr_text or message.image_text or ""
    source_field = "ocr_text" if message.ocr_text else "image_text"
    candidate = classify_image_text_candidate(
        extracted_text,
        ocr_confidence=message.ocr_confidence,
        media_id=message.media_id,
        metadata=message.metadata,
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
