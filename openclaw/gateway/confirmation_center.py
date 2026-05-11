"""
P0 confirmation center helpers for WeChat / OpenClaw ingress.

This module keeps high-attention actions in a controlled state machine:

pending_action -> confirmation_session -> user decision -> later commit

It does not write business facts directly.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import urlencode, urljoin

logger = logging.getLogger(__name__)

HIGH_ATTENTION_TTL_MINUTES = 30
LOW_ATTENTION_TTL_HOURS = 24
LOW_CONFIDENCE_ASR_THRESHOLD = 0.72
LOW_CONFIDENCE_OCR_THRESHOLD = 0.72
NO_FACT_WRITE_TEXT = "当前没有改动持仓，也没有下单。"
WEBAPP_CONFIRMATION_CENTER_HINT = "必要时请去 WebApp 确认中心查看最新状态。"

_ACTION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("confirm", ("确认", "同意", "yes", "ok", "approve")),
    ("reject", ("拒绝", "取消", "不同意", "reject", "cancel", "no")),
    ("revise", ("修改", "修正", "更正", "改成", "revise", "edit")),
    ("status", ("状态", "进度", "查询确认", "status", "check")),
    ("help", ("帮助", "help", "怎么确认", "确认说明")),
)


@dataclass
class RoutingContext:
    tenant_id: str
    channel_binding_id: str | None
    openclaw_account_id: str | None
    context_token: str | None = None
    target_conversation: str | None = None
    channel: str = "openclaw_wechat"
    session_space: str | None = None
    timezone_name: str = "Asia/Shanghai"
    quiet_hours: dict[str, Any] | None = None


@dataclass
class PendingActionInput:
    object_type: str
    action_type: str
    action_scope: str
    source_type: str
    source_surface: str
    risk_level: str
    confirmation_strength: str
    action_payload: dict[str, Any]
    normalized_summary: dict[str, Any]
    actionability_level: str = "trade_draft"
    expires_at: datetime | None = None
    fingerprint_seed: str | None = None
    requires_override: bool = False


@dataclass
class PendingActionResult:
    pending_action_id: str
    confirmation_session_id: str
    session_token: str
    status: str
    command_hint: str
    deep_link: str
    expires_at: datetime


@dataclass
class ConfirmationCommand:
    action: str
    session_hint: str | None
    revision_text: str | None
    raw_text: str
    normalized_text: str
    via: str = "text"


@dataclass
class DecisionResult:
    outcome: str
    pending_action_id: str | None
    confirmation_session_id: str | None
    reply_text: str
    status: str | None = None
    deep_link: str | None = None


@dataclass
class VoiceTranscriptInterpretation:
    mode: str
    reason: str
    normalized_text: str
    parsed_command: ConfirmationCommand | None = None
    candidate: PendingActionInput | None = None


class ConfirmationRepository(Protocol):
    async def create_pending_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    async def create_confirmation_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    async def append_event(self, payload: dict[str, Any]) -> None:
        ...

    async def get_active_session(
        self,
        tenant_id: str,
        *,
        session_hint: str | None = None,
        channel_binding_id: str | None = None,
    ) -> dict[str, Any] | None:
        ...

    async def get_session_by_hint(
        self,
        tenant_id: str,
        *,
        session_hint: str,
        channel_binding_id: str | None = None,
    ) -> dict[str, Any] | None:
        ...

    async def get_pending_action(self, pending_action_id: str) -> dict[str, Any] | None:
        ...

    async def update_pending_action(self, pending_action_id: str, updates: dict[str, Any]) -> None:
        ...

    async def update_confirmation_session(
        self,
        confirmation_session_id: str,
        updates: dict[str, Any],
    ) -> None:
        ...


class PostDecisionDispatcher(Protocol):
    async def dispatch(
        self,
        *,
        context: RoutingContext,
        pending_action: dict[str, Any],
        session: dict[str, Any],
        command: ConfirmationCommand,
        post_decision: str,
    ) -> Any | None:
        ...


def normalize_user_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = cleaned.replace("，", " ").replace("。", " ").replace("：", ":")
    cleaned = cleaned.replace("（", " ").replace("）", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def parse_confirmation_command(text: str, *, via: str = "text") -> ConfirmationCommand | None:
    normalized = normalize_user_text(text)
    lowered = normalized.lower()

    matched_action: str | None = None
    matched_keyword: str | None = None
    for action, keywords in _ACTION_PATTERNS:
        for keyword in keywords:
            check = keyword.lower()
            if lowered == check or lowered.startswith(f"{check} "):
                matched_action = action
                matched_keyword = keyword
                break
        if matched_action:
            break

    if not matched_action or not matched_keyword:
        return None

    remainder = normalized[len(matched_keyword):].strip()
    session_hint = _extract_session_hint(remainder)
    revision_text: str | None = None
    if matched_action == "revise":
        revision_text = _extract_revision_text(remainder, session_hint)

    return ConfirmationCommand(
        action=matched_action,
        session_hint=session_hint,
        revision_text=revision_text,
        raw_text=text,
        normalized_text=normalized,
        via=via,
    )


def build_confirmation_deep_link(
    base_url: str,
    tenant_id: str,
    confirmation_session_id: str,
    session_token: str,
    *,
    pending_action_id: str | None = None,
    channel: str = "wechat",
) -> str:
    root = base_url.rstrip("/") + "/"
    path = urljoin(root, "confirmations/resolve")
    query = {
        "tenant_id": tenant_id,
        "session_id": confirmation_session_id,
        "session_token": session_token,
        "channel": channel,
    }
    if pending_action_id:
        query["pending_action_id"] = pending_action_id
    return f"{path}?{urlencode(query)}"


def classify_high_attention_text(
    text: str,
    *,
    source_type: str,
    source_surface: str,
    confidence: float | None = None,
) -> PendingActionInput | None:
    normalized = normalize_user_text(text)
    lowered = normalized.lower()

    if _looks_like_sell_put(lowered):
        summary = {
            "title": "待确认 Sell Put 草稿",
            "body": normalized,
            "source_type": source_type,
            "risk_note": "只生成交易草稿，不会自动下单；请确认后再用于实际操作。",
        }
        return PendingActionInput(
            object_type="sell_put_trade_draft",
            action_type="trade_draft_ack",
            action_scope="draft_ack",
            source_type=source_type,
            source_surface=source_surface,
            risk_level="high",
            confirmation_strength="high_attention",
            action_payload={
                "raw_text": text,
                "normalized_text": normalized,
                "confidence": confidence,
            },
            normalized_summary=summary,
            fingerprint_seed=f"sell-put:{normalized}",
        )

    if _looks_like_trade_input(lowered):
        summary = {
            "title": "待确认交易录入",
            "body": normalized,
            "source_type": source_type,
            "risk_note": "不会自动下单，也不会立刻改动持仓；确认后才会记录到你的持仓系统。",
        }
        payload = {
            "raw_text": text,
            "normalized_text": normalized,
            "confidence": confidence,
        }
        return PendingActionInput(
            object_type="trade_event_input",
            action_type="trade_input",
            action_scope="fact_record",
            source_type=source_type,
            source_surface=source_surface,
            risk_level="high",
            confirmation_strength="high_attention",
            action_payload=payload,
            normalized_summary=summary,
            fingerprint_seed=f"trade:{normalized}",
        )

    if _looks_like_rule_change(lowered):
        summary = {
            "title": "待确认规则变更",
            "body": normalized,
            "source_type": source_type,
            "risk_note": "确认后才会保存为你的交易纪律设置，并影响后续提醒。",
        }
        return PendingActionInput(
            object_type="discipline_rule_override",
            action_type="rule_override",
            action_scope="rule_exception",
            source_type=source_type,
            source_surface=source_surface,
            risk_level="medium",
            confirmation_strength="structured",
            action_payload={
                "raw_text": text,
                "normalized_text": normalized,
                "confidence": confidence,
            },
            normalized_summary=summary,
            actionability_level="suggested_action",
            fingerprint_seed=f"rule:{normalized}",
        )

    return None


def interpret_voice_transcript(
    transcript: str,
    *,
    confidence: float | None,
) -> VoiceTranscriptInterpretation:
    normalized = normalize_user_text(transcript)
    if not normalized:
        return VoiceTranscriptInterpretation(
            mode="query",
            reason="empty_transcript",
            normalized_text=normalized,
        )

    command = parse_confirmation_command(normalized, via="voice")
    if command is not None:
        return VoiceTranscriptInterpretation(
            mode="decision",
            reason="voice_confirmation_command",
            normalized_text=normalized,
            parsed_command=command,
        )

    if confidence is None or confidence < LOW_CONFIDENCE_ASR_THRESHOLD:
        candidate = build_voice_candidate(
            normalized,
            confidence=confidence,
            raw_transcript=transcript,
        )
        return VoiceTranscriptInterpretation(
            mode="pending_action",
            reason="low_confidence_asr",
            normalized_text=normalized,
            candidate=candidate,
        )

    candidate = classify_high_attention_text(
        normalized,
        source_type="voice_asr",
        source_surface="wechat",
        confidence=confidence,
    )
    if candidate is not None:
        return VoiceTranscriptInterpretation(
            mode="pending_action",
            reason="high_attention_voice_intent",
            normalized_text=normalized,
            candidate=candidate,
        )

    return VoiceTranscriptInterpretation(
        mode="query",
        reason="voice_query_or_low_risk",
        normalized_text=normalized,
    )


def build_voice_candidate(
    normalized_text: str,
    *,
    confidence: float | None,
    raw_transcript: str,
    source_surface: str = "wechat",
) -> PendingActionInput:
    return PendingActionInput(
        object_type="voice_input_review",
        action_type="asr_correction",
        action_scope="source_correction",
        source_type="voice_asr",
        source_surface=source_surface,
        risk_level="high",
        confirmation_strength="high_attention",
        action_payload={
            "raw_transcript": raw_transcript,
            "normalized_text": normalized_text,
            "confidence": confidence,
        },
        normalized_summary={
            "title": "待确认语音内容",
            "body": normalized_text,
            "source_type": "voice_asr",
            "risk_note": "这段语音识别把握不高，请先确认文字是否准确。确认前不会改动持仓，也不会下单。",
        },
        fingerprint_seed=f"voice-low:{normalized_text}",
    )


def build_image_review_candidate(
    normalized_text: str,
    *,
    ocr_confidence: float | None,
    media_id: str | None,
    metadata: dict[str, Any] | None,
    source_field: str,
    raw_text: str,
    source_surface: str = "wechat",
    low_confidence: bool = False,
) -> PendingActionInput:
    payload = {
        source_field: raw_text,
        "normalized_text": normalized_text,
        "ocr_confidence": ocr_confidence,
        "media_id": media_id,
        "metadata": metadata or {},
    }
    if low_confidence:
        risk_note = (
            "这张图片的文字识别把握不高，请先确认文字是否准确。"
            "确认前不会改动持仓，也不会下单。"
        )
    else:
        risk_note = "图片里的文字会先进入确认，确认前不会改动持仓，也不会下单。"

    return PendingActionInput(
        object_type="image_input_review",
        action_type="ocr_correction",
        action_scope="source_correction",
        source_type="image_ocr",
        source_surface=source_surface,
        risk_level="high",
        confirmation_strength="high_attention",
        action_payload=payload,
        normalized_summary={
            "title": "待确认图片识别内容",
            "body": normalized_text,
            "source_type": "image_ocr",
            "risk_note": risk_note,
        },
        fingerprint_seed=f"ocr:{media_id or ''}:{normalized_text}",
    )


def classify_image_text_candidate(
    text: str,
    *,
    ocr_confidence: float | None = None,
    media_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    source_field: str = "ocr_text",
    source_surface: str = "wechat",
) -> PendingActionInput | None:
    normalized = normalize_user_text(text)
    if not normalized:
        return None

    if ocr_confidence is not None and ocr_confidence < LOW_CONFIDENCE_OCR_THRESHOLD:
        return build_image_review_candidate(
            normalized,
            ocr_confidence=ocr_confidence,
            media_id=media_id,
            metadata=metadata,
            source_field=source_field,
            raw_text=text,
            source_surface=source_surface,
            low_confidence=True,
        )

    payload = {
        source_field: text,
        "normalized_text": normalized,
        "ocr_confidence": ocr_confidence,
        "media_id": media_id,
        "metadata": metadata or {},
    }
    candidate = classify_high_attention_text(
        normalized,
        source_type="image_ocr",
        source_surface=source_surface,
        confidence=ocr_confidence,
    )
    if candidate is not None:
        candidate.action_payload.update(payload)
        candidate.normalized_summary["body"] = normalized
        candidate.normalized_summary["risk_note"] = (
            f"{candidate.normalized_summary['risk_note']} 图片里的文字会先进入确认，"
            "确认前不会改动持仓，也不会下单。"
        )
        return candidate

    return build_image_review_candidate(
        normalized,
        ocr_confidence=ocr_confidence,
        media_id=media_id,
        metadata=metadata,
        source_field=source_field,
        raw_text=text,
        source_surface=source_surface,
    )


class InMemoryConfirmationRepository:
    def __init__(self) -> None:
        self.pending_actions: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []

    async def create_pending_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.pending_actions[payload["id"]] = dict(payload)
        return dict(payload)

    async def create_confirmation_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.sessions[payload["id"]] = dict(payload)
        return dict(payload)

    async def append_event(self, payload: dict[str, Any]) -> None:
        self.events.append(dict(payload))

    async def get_active_session(
        self,
        tenant_id: str,
        *,
        session_hint: str | None = None,
        channel_binding_id: str | None = None,
    ) -> dict[str, Any] | None:
        records = [
            record
            for record in self.sessions.values()
            if record["tenant_id"] == tenant_id and record["session_status"] == "active"
        ]
        if channel_binding_id:
            records = [
                record
                for record in records
                if record.get("channel_binding_id") == channel_binding_id
            ]
        if session_hint:
            hint = session_hint.lower()
            for record in records:
                candidates = {
                    str(record["id"]).lower(),
                    str(record["pending_action_id"]).lower(),
                    str(record["session_token"]).lower(),
                }
                if hint in candidates:
                    return dict(record)
            return None
        if not records:
            return None
        records.sort(key=lambda item: item["created_at"], reverse=True)
        return dict(records[0])

    async def get_session_by_hint(
        self,
        tenant_id: str,
        *,
        session_hint: str,
        channel_binding_id: str | None = None,
    ) -> dict[str, Any] | None:
        records = [
            record
            for record in self.sessions.values()
            if record["tenant_id"] == tenant_id
        ]
        if channel_binding_id:
            records = [
                record
                for record in records
                if record.get("channel_binding_id") == channel_binding_id
            ]
        hint = session_hint.lower()
        for record in records:
            candidates = {
                str(record["id"]).lower(),
                str(record["pending_action_id"]).lower(),
                str(record["session_token"]).lower(),
            }
            if hint in candidates:
                return dict(record)
        return None

    async def get_pending_action(self, pending_action_id: str) -> dict[str, Any] | None:
        record = self.pending_actions.get(pending_action_id)
        return dict(record) if record else None

    async def update_pending_action(self, pending_action_id: str, updates: dict[str, Any]) -> None:
        current = self.pending_actions[pending_action_id]
        current.update(updates)

    async def update_confirmation_session(
        self,
        confirmation_session_id: str,
        updates: dict[str, Any],
    ) -> None:
        current = self.sessions[confirmation_session_id]
        current.update(updates)


class SupabaseConfirmationRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def create_pending_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _insert() -> dict[str, Any]:
            response = self._client.table("pending_actions").insert(payload).execute()
            return response.data[0] if response.data else payload

        return await asyncio.to_thread(_insert)

    async def create_confirmation_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _insert() -> dict[str, Any]:
            response = self._client.table("confirmation_sessions").insert(payload).execute()
            return response.data[0] if response.data else payload

        return await asyncio.to_thread(_insert)

    async def append_event(self, payload: dict[str, Any]) -> None:
        def _insert() -> None:
            self._client.table("confirmation_events").insert(payload).execute()

        await asyncio.to_thread(_insert)

    async def get_active_session(
        self,
        tenant_id: str,
        *,
        session_hint: str | None = None,
        channel_binding_id: str | None = None,
    ) -> dict[str, Any] | None:
        def _query() -> list[dict[str, Any]]:
            def _base_query():
                query = (
                    self._client.table("confirmation_sessions")
                    .select("*")
                    .eq("tenant_id", tenant_id)
                    .eq("session_status", "active")
                    .order("created_at", desc=True)
                )
                if channel_binding_id:
                    query = query.eq("channel_binding_id", channel_binding_id)
                return query

            if session_hint:
                hint = session_hint
                fields = ["session_token"]
                if _is_uuid_like(hint):
                    fields.extend(["id", "pending_action_id"])
                for field in fields:
                    response = _base_query().eq(field, hint).limit(1).execute()
                    if response.data:
                        return response.data
                return []
            response = _base_query().limit(1).execute()
            return response.data or []

        rows = await asyncio.to_thread(_query)
        return rows[0] if rows else None

    async def get_session_by_hint(
        self,
        tenant_id: str,
        *,
        session_hint: str,
        channel_binding_id: str | None = None,
    ) -> dict[str, Any] | None:
        def _query() -> list[dict[str, Any]]:
            def _base_query():
                query = (
                    self._client.table("confirmation_sessions")
                    .select("*")
                    .eq("tenant_id", tenant_id)
                    .order("created_at", desc=True)
                )
                if channel_binding_id:
                    query = query.eq("channel_binding_id", channel_binding_id)
                return query

            fields = ["session_token"]
            if _is_uuid_like(session_hint):
                fields.extend(["id", "pending_action_id"])
            for field in fields:
                response = _base_query().eq(field, session_hint).limit(1).execute()
                if response.data:
                    return response.data
            return []

        rows = await asyncio.to_thread(_query)
        return rows[0] if rows else None

    async def get_pending_action(self, pending_action_id: str) -> dict[str, Any] | None:
        def _query() -> list[dict[str, Any]]:
            response = self._client.table("pending_actions").select("*").eq("id", pending_action_id).limit(1).execute()
            return response.data or []

        rows = await asyncio.to_thread(_query)
        return rows[0] if rows else None

    async def update_pending_action(self, pending_action_id: str, updates: dict[str, Any]) -> None:
        def _update() -> None:
            self._client.table("pending_actions").update(updates).eq("id", pending_action_id).execute()

        await asyncio.to_thread(_update)

    async def update_confirmation_session(
        self,
        confirmation_session_id: str,
        updates: dict[str, Any],
    ) -> None:
        def _update() -> None:
            self._client.table("confirmation_sessions").update(updates).eq("id", confirmation_session_id).execute()

        await asyncio.to_thread(_update)


class ConfirmationCenterService:
    def __init__(
        self,
        repository: ConfirmationRepository,
        *,
        webapp_base_url: str,
        post_decision_dispatcher: PostDecisionDispatcher | None = None,
        now_provider: callable | None = None,
    ) -> None:
        self._repository = repository
        self._webapp_base_url = webapp_base_url
        self._post_decision_dispatcher = post_decision_dispatcher
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def create_pending_confirmation(
        self,
        context: RoutingContext,
        pending: PendingActionInput,
    ) -> PendingActionResult:
        now = self._now_provider()
        expires_at = pending.expires_at or _default_expiry(now, pending.confirmation_strength)
        pending_action_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        session_token = _short_session_token(session_id)
        fingerprint = _fingerprint(
            context.tenant_id,
            pending.fingerprint_seed
            or json.dumps(pending.action_payload, ensure_ascii=False, sort_keys=True),
        )

        pending_payload = {
            "id": pending_action_id,
            "tenant_id": context.tenant_id,
            "channel_binding_id": context.channel_binding_id,
            "source_run_id": None,
            "source_agent_role": "openclaw-gateway",
            "action_type": pending.action_type,
            "action_scope": pending.action_scope,
            "target_entity_type": pending.object_type,
            "target_entity_id": None,
            "source_type": pending.source_type,
            "action_payload": pending.action_payload,
            "normalized_summary": pending.normalized_summary,
            "rule_check_ref": None,
            "risk_review_ref": None,
            "requires_override": pending.requires_override,
            "confirmation_strength": pending.confirmation_strength,
            "status": "awaiting_confirmation",
            "fingerprint": fingerprint,
            "version": 1,
            "expires_at": expires_at.isoformat(),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "source_surface": pending.source_surface,
            "risk_level": pending.risk_level,
            "actionability_cap": pending.actionability_level,
        }
        await self._repository.create_pending_action(pending_payload)

        session_payload = {
            "id": session_id,
            "pending_action_id": pending_action_id,
            "tenant_id": context.tenant_id,
            "channel": _normalize_db_channel(context.channel),
            "channel_binding_id": context.channel_binding_id,
            "session_status": "active",
            "session_token": session_token,
            "presented_version": 1,
            "decision_deadline": expires_at.isoformat(),
            "created_at": now.isoformat(),
        }
        await self._repository.create_confirmation_session(session_payload)

        await self._repository.append_event(
            _event_payload(
                tenant_id=context.tenant_id,
                pending_action_id=pending_action_id,
                confirmation_session_id=session_id,
                event_type="created",
                payload={"source_surface": pending.source_surface},
                now=now,
            )
        )
        await self._repository.append_event(
            _event_payload(
                tenant_id=context.tenant_id,
                pending_action_id=pending_action_id,
                confirmation_session_id=session_id,
                event_type="presented",
                payload={"channel": context.channel, "db_channel": _normalize_db_channel(context.channel)},
                now=now,
            )
        )

        deep_link = build_confirmation_deep_link(
            self._webapp_base_url,
            context.tenant_id,
            session_id,
            session_token,
            pending_action_id=pending_action_id,
            channel="wechat",
        )
        return PendingActionResult(
            pending_action_id=pending_action_id,
            confirmation_session_id=session_id,
            session_token=session_token,
            status="awaiting_confirmation",
            command_hint=f"确认 {session_token}",
            deep_link=deep_link,
            expires_at=expires_at,
        )

    async def submit_decision(
        self,
        context: RoutingContext,
        command: ConfirmationCommand,
    ) -> DecisionResult:
        if command.action == "help":
            return DecisionResult(
                outcome="help",
                pending_action_id=None,
                confirmation_session_id=None,
                reply_text=(
                    "你可以回复“确认 会话码”继续，回复“取消 会话码”放弃，"
                    "或回复“修改 会话码 新内容”重新提交。确认前不会改动持仓，也不会下单。"
                ),
            )

        session = await self._repository.get_active_session(
            context.tenant_id,
            session_hint=command.session_hint,
            channel_binding_id=context.channel_binding_id,
        )
        if session is None:
            if command.session_hint:
                handled_session = await self._repository.get_session_by_hint(
                    context.tenant_id,
                    session_hint=command.session_hint,
                    channel_binding_id=context.channel_binding_id,
                )
                if handled_session is not None:
                    return await self._handled_session_result(context, command, handled_session)
            return DecisionResult(
                outcome="not_found",
                pending_action_id=None,
                confirmation_session_id=None,
                reply_text=_reply_with_no_fact_write(
                    "没找到这条待确认事项。你可以重试最新一条确认消息。",
                    include_webapp_hint=True,
                ),
            )

        now = self._now_provider()
        deadline = _parse_dt(session.get("decision_deadline"))
        if deadline is not None and now > deadline:
            await self._repository.update_confirmation_session(
                str(session["id"]),
                {
                    "session_status": "expired",
                    "consumed_at": now.isoformat(),
                },
            )
            await self._repository.update_pending_action(
                str(session["pending_action_id"]),
                {
                    "status": "expired",
                    "updated_at": now.isoformat(),
                },
            )
            await self._repository.append_event(
                _event_payload(
                    tenant_id=context.tenant_id,
                    pending_action_id=str(session["pending_action_id"]),
                    confirmation_session_id=str(session["id"]),
                    event_type="expired",
                    payload={"via": command.via, "requested_action": command.action},
                    now=now,
                )
            )
            return DecisionResult(
                outcome="expired",
                pending_action_id=str(session["pending_action_id"]),
                confirmation_session_id=str(session["id"]),
                reply_text=_reply_with_no_fact_write(
                    "这条确认已经过期，需要重新发起。",
                    include_webapp_hint=True,
                ),
                status="expired",
            )

        pending_action_id = str(session["pending_action_id"])
        session_id = str(session["id"])

        if command.action == "status":
            return DecisionResult(
                outcome="status",
                pending_action_id=pending_action_id,
                confirmation_session_id=session_id,
                reply_text=(
                    "这条确认还有效。你可以直接回复“确认 {code}”，"
                    "也可以打开确认页面链接继续处理。确认前不会改动持仓，也不会下单。"
                ).format(code=session["session_token"]),
                status="active",
            )

        if command.action == "reject":
            await self._repository.update_pending_action(
                pending_action_id,
                {
                    "status": "rejected",
                    "updated_at": now.isoformat(),
                },
            )
            await self._repository.update_confirmation_session(
                session_id,
                {
                    "session_status": "consumed",
                    "consumed_at": now.isoformat(),
                    "cancel_reason": "user_rejected",
                },
            )
            await self._repository.append_event(
                _event_payload(
                    tenant_id=context.tenant_id,
                    pending_action_id=pending_action_id,
                    confirmation_session_id=session_id,
                    event_type="rejected",
                    payload={"via": command.via, "post_decision": "no_business_fact_write"},
                    now=now,
                    actor_type="user",
                    actor_ref=context.channel_binding_id or context.openclaw_account_id,
                )
            )
            return DecisionResult(
                outcome="rejected",
                pending_action_id=pending_action_id,
                confirmation_session_id=session_id,
                reply_text=_reply_with_no_fact_write(
                    "已取消这次确认。",
                    include_webapp_hint=True,
                ),
                status="rejected",
            )

        if command.action == "revise":
            post_decision = "rebuild_confirmation_required"
            await self._repository.update_pending_action(
                pending_action_id,
                {
                    "status": "revoked",
                    "updated_at": now.isoformat(),
                },
            )
            await self._repository.update_confirmation_session(
                session_id,
                {
                    "session_status": "cancelled",
                    "consumed_at": now.isoformat(),
                    "cancel_reason": "revise_requested",
                },
            )
            await self._repository.append_event(
                _event_payload(
                    tenant_id=context.tenant_id,
                    pending_action_id=pending_action_id,
                    confirmation_session_id=session_id,
                    event_type="modified",
                    payload={
                        "revision_text": command.revision_text or "",
                        "via": command.via,
                        "post_decision": post_decision,
                    },
                    now=now,
                    actor_type="user",
                    actor_ref=context.channel_binding_id or context.openclaw_account_id,
                )
            )
            await self._dispatch_post_decision(
                context,
                session,
                command=command,
                post_decision=post_decision,
                now=now,
            )
            deep_link = build_confirmation_deep_link(
                self._webapp_base_url,
                context.tenant_id,
                session_id,
                str(session["session_token"]),
                pending_action_id=pending_action_id,
                channel="wechat",
            )
            return DecisionResult(
                outcome="rebuild_required",
                pending_action_id=pending_action_id,
                confirmation_session_id=session_id,
                reply_text=_reply_with_no_fact_write(
                    "已记下你要修改。这条确认先取消，请重新发送修正后的内容。",
                    include_webapp_hint=True,
                ),
                status="revoked",
                deep_link=deep_link,
            )

        post_decision = "commit_or_recalculate"
        await self._repository.update_pending_action(
            pending_action_id,
            {
                "status": "confirmed",
                "confirmed_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )
        await self._repository.update_confirmation_session(
            session_id,
            {
                "session_status": "consumed",
                "consumed_at": now.isoformat(),
            },
        )
        await self._repository.append_event(
            _event_payload(
                tenant_id=context.tenant_id,
                pending_action_id=pending_action_id,
                confirmation_session_id=session_id,
                event_type="confirmed",
                payload={"via": command.via, "post_decision": post_decision},
                now=now,
                actor_type="user",
                actor_ref=context.channel_binding_id or context.openclaw_account_id,
            )
        )
        dispatch_status = await self._dispatch_post_decision(
            context,
            session,
            command=command,
            post_decision=post_decision,
            now=now,
        )
        if dispatch_status == "failed_retryable":
            reply_text = _reply_with_no_fact_write(
                "已收到确认，但后台暂时没接住这次处理。系统会保留这条确认并稍后重试。",
                include_webapp_hint=True,
            )
            result_status = "failed_retryable"
        else:
            reply_text = (
                "已收到确认。系统会按你确认的内容继续处理；如果涉及交易，"
                "只会记录或生成草稿，不会自动下单。"
            )
            result_status = dispatch_status or "confirmed"
        return DecisionResult(
            outcome="confirmed",
            pending_action_id=pending_action_id,
            confirmation_session_id=session_id,
            reply_text=reply_text,
            status=result_status,
        )

    async def _dispatch_post_decision(
        self,
        context: RoutingContext,
        session: dict[str, Any],
        *,
        command: ConfirmationCommand,
        post_decision: str,
        now: datetime,
    ) -> str | None:
        if self._post_decision_dispatcher is None:
            return None

        pending_action_id = str(session["pending_action_id"])
        session_id = str(session["id"])
        pending_action = await self._repository.get_pending_action(pending_action_id)
        if pending_action is None:
            logger.warning(
                "Pending action %s missing during post-decision dispatch",
                pending_action_id,
            )
            return None

        try:
            dispatch_result = await self._post_decision_dispatcher.dispatch(
                context=context,
                pending_action=pending_action,
                session=session,
                command=command,
                post_decision=post_decision,
            )
        except Exception as exc:
            logger.exception(
                "Failed to dispatch confirmation post-decision task "
                "(pending_action_id=%s, post_decision=%s)",
                pending_action_id,
                post_decision,
            )
            if post_decision == "commit_or_recalculate":
                await self._repository.update_pending_action(
                    pending_action_id,
                    {
                        "status": "failed_retryable",
                        "updated_at": now.isoformat(),
                    },
                )
            await self._repository.append_event(
                _event_payload(
                    tenant_id=context.tenant_id,
                    pending_action_id=pending_action_id,
                    confirmation_session_id=session_id,
                    event_type="commit_failed",
                    payload={
                        "post_decision": post_decision,
                        "error": str(exc),
                        "phase": "enqueue_post_confirmation_task",
                    },
                    now=now,
                    actor_type="runtime",
                    actor_ref="confirmation-dispatcher",
                )
            )
            return "failed_retryable"

        if dispatch_result is None:
            return None

        if post_decision == "commit_or_recalculate":
            await self._repository.update_pending_action(
                pending_action_id,
                {
                    "status": "committing",
                    "updated_at": now.isoformat(),
                },
            )
            return "committing"
        return "queued"

    async def _handled_session_result(
        self,
        context: RoutingContext,
        command: ConfirmationCommand,
        session: dict[str, Any],
    ) -> DecisionResult:
        now = self._now_provider()
        pending_action_id = str(session["pending_action_id"])
        session_id = str(session["id"])
        pending = await self._repository.get_pending_action(pending_action_id)
        action_status = str(pending.get("status") if pending else session.get("session_status") or "processed")

        await self._repository.append_event(
            _event_payload(
                tenant_id=context.tenant_id,
                pending_action_id=pending_action_id,
                confirmation_session_id=session_id,
                event_type="duplicate_ignored",
                payload={
                    "via": command.via,
                    "requested_action": command.action,
                    "current_status": action_status,
                    "session_status": session.get("session_status"),
                },
                now=now,
                actor_type="user",
                actor_ref=context.channel_binding_id or context.openclaw_account_id,
            )
        )

        if action_status in {"confirmed", "committing", "committed"}:
            reply = (
                "这条确认已经处理过或正在处理中，不会重复记录，也不会重复下单。"
                f"{WEBAPP_CONFIRMATION_CENTER_HINT}"
            )
            outcome = "already_confirmed"
        elif action_status == "rejected":
            reply = _reply_with_no_fact_write(
                "这条确认已经取消过。",
                include_webapp_hint=True,
            )
            outcome = "already_rejected"
        elif action_status == "revoked":
            reply = _reply_with_no_fact_write(
                "这条确认已经转去修改，请重新发送修正后的内容。",
                include_webapp_hint=True,
            )
            outcome = "already_revoked"
        elif action_status == "expired":
            reply = _reply_with_no_fact_write(
                "这条确认已经过期，需要重新发起。",
                include_webapp_hint=True,
            )
            outcome = "already_expired"
        else:
            reply = (
                "这条确认已经处理过。为避免重复处理，请查看确认页面里的最新状态。"
                f"{WEBAPP_CONFIRMATION_CENTER_HINT}"
            )
            outcome = "already_processed"

        return DecisionResult(
            outcome=outcome,
            pending_action_id=pending_action_id,
            confirmation_session_id=session_id,
            reply_text=reply,
            status=action_status,
        )


def _default_expiry(now: datetime, confirmation_strength: str) -> datetime:
    if confirmation_strength == "high_attention":
        return now + timedelta(minutes=HIGH_ATTENTION_TTL_MINUTES)
    return now + timedelta(hours=LOW_ATTENTION_TTL_HOURS)


def _reply_with_no_fact_write(prefix: str, *, include_webapp_hint: bool = False) -> str:
    reply = f"{prefix}{NO_FACT_WRITE_TEXT}"
    if include_webapp_hint:
        reply = f"{reply}{WEBAPP_CONFIRMATION_CENTER_HINT}"
    return reply


def _short_session_token(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest().upper()
    return f"CFM{digest[:6]}"


def _extract_session_hint(text: str) -> str | None:
    token_match = re.search(r"(CFM[A-Z0-9]{4,}|[A-Za-z0-9_-]{6,})", text, re.IGNORECASE)
    if token_match:
        return token_match.group(1)
    return None


def _extract_revision_text(text: str, session_hint: str | None) -> str | None:
    remainder = text
    if session_hint:
        remainder = remainder.replace(session_hint, "", 1).strip()
    return remainder or None


def _looks_like_trade_input(text: str) -> bool:
    patterns = (
        r"\b(buy|sell)\b",
        r"(买入|卖出|加仓|减仓|清仓|补仓)",
        r"(\d+\s*(股|手|shares))",
    )
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _looks_like_sell_put(text: str) -> bool:
    patterns = (
        r"sell put",
        r"\bput\b",
        r"(认沽|卖沽|期权草稿|现金担保)",
    )
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _looks_like_rule_change(text: str) -> bool:
    patterns = (
        r"(以后不要|别再提醒|规则|纪律|阈值|提醒我)",
        r"\b(rule|alert)\b",
    )
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _fingerprint(tenant_id: str, seed: str) -> str:
    return hashlib.sha256(f"{tenant_id}:{seed}".encode("utf-8")).hexdigest()


def _normalize_db_channel(channel: str | None) -> str:
    aliases = {
        "openclaw-weixin": "openclaw_wechat",
        "openclaw-wechat": "openclaw_wechat",
        "wechat": "openclaw_wechat",
        "weixin": "openclaw_wechat",
    }
    normalized = (channel or "openclaw_wechat").strip()
    return aliases.get(normalized, normalized)


def _event_payload(
    *,
    tenant_id: str,
    pending_action_id: str,
    confirmation_session_id: str,
    event_type: str,
    payload: dict[str, Any],
    now: datetime,
    actor_type: str = "system",
    actor_ref: str | None = "openclaw-gateway",
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "pending_action_id": pending_action_id,
        "confirmation_session_id": confirmation_session_id,
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_ref": actor_ref,
        "event_payload": payload,
        "created_at": now.isoformat(),
    }


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_uuid_like(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False
