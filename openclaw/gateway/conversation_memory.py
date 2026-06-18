"""Shared conversation memory for OpenClaw channel ingress.

The WeChat surface is one continuous conversation even when individual turns
route to different model providers. This module keeps that product-level
thread separate from provider-specific chat state.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from openclaw.gateway.confirmation_center import RoutingContext
from openclaw.gateway.model_dialogue import ModelDialogueResult

logger = logging.getLogger(__name__)

RECENT_TURN_LIMIT = 10
SUMMARY_SOURCE_TURN_LIMIT = 24
SUMMARY_MAX_CHARS = 1800


@dataclass(frozen=True)
class ConversationTurnInput:
    role: str
    content: str
    content_type: str = "text"
    message_id: str | None = None
    route: str | None = None
    provider: str | None = None
    model: str | None = None
    response_id: str | None = None
    raw_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConversationContext:
    thread_id: str | None
    thread_key: str
    summary: str
    recent_turns: list[dict[str, Any]]

    def render_for_prompt(self) -> str:
        lines: list[str] = []
        if self.summary:
            lines.append(f"会话摘要：{self.summary}")
        if self.recent_turns:
            lines.append("最近对话：")
            for turn in self.recent_turns:
                role = "用户" if turn.get("role") == "user" else "助手"
                route = turn.get("route")
                route_label = f"/{route}" if route else ""
                content = str(turn.get("content") or "").strip()
                if content:
                    lines.append(f"- {role}{route_label}: {content}")
        return "\n".join(lines).strip()


class ConversationMemoryRepository(Protocol):
    async def get_or_create_thread(self, context: RoutingContext) -> dict[str, Any]:
        ...

    async def append_turn(self, thread: dict[str, Any], turn: ConversationTurnInput) -> dict[str, Any]:
        ...

    async def list_recent_turns(self, thread_id: str, *, limit: int = RECENT_TURN_LIMIT) -> list[dict[str, Any]]:
        ...

    async def update_thread_summary(self, thread_id: str, *, summary: str, turn_count: int) -> None:
        ...

    async def append_summary_snapshot(
        self,
        thread: dict[str, Any],
        *,
        summary: str,
        turn_count: int,
        source_turn_id: str | None,
    ) -> None:
        ...


class InMemoryConversationMemoryRepository:
    def __init__(self) -> None:
        self.threads_by_key: dict[str, dict[str, Any]] = {}
        self.turns_by_thread: dict[str, list[dict[str, Any]]] = {}
        self.summary_snapshots: list[dict[str, Any]] = []

    async def get_or_create_thread(self, context: RoutingContext) -> dict[str, Any]:
        thread_key = conversation_thread_key(context)
        existing = self.threads_by_key.get(thread_key)
        now = _utc_now_iso()
        if existing:
            existing["updated_at"] = now
            return dict(existing)

        thread = {
            "id": str(uuid.uuid4()),
            "tenant_id": context.tenant_id,
            "channel_binding_id": context.channel_binding_id,
            "openclaw_account_id": context.openclaw_account_id,
            "channel": context.channel,
            "target_conversation": context.target_conversation,
            "context_token": context.context_token,
            "session_space": context.session_space,
            "thread_key": thread_key,
            "summary": "",
            "summary_turn_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        self.threads_by_key[thread_key] = thread
        self.turns_by_thread[thread["id"]] = []
        return dict(thread)

    async def append_turn(self, thread: dict[str, Any], turn: ConversationTurnInput) -> dict[str, Any]:
        thread_id = str(thread["id"])
        record = _turn_payload(thread, turn)
        self.turns_by_thread.setdefault(thread_id, []).append(record)
        current = self.threads_by_key[str(thread["thread_key"])]
        current["last_turn_at"] = record["created_at"]
        current["updated_at"] = record["created_at"]
        return dict(record)

    async def list_recent_turns(self, thread_id: str, *, limit: int = RECENT_TURN_LIMIT) -> list[dict[str, Any]]:
        turns = self.turns_by_thread.get(thread_id, [])
        return [dict(item) for item in turns[-limit:]]

    async def update_thread_summary(self, thread_id: str, *, summary: str, turn_count: int) -> None:
        for thread in self.threads_by_key.values():
            if thread["id"] == thread_id:
                thread["summary"] = summary
                thread["summary_turn_count"] = turn_count
                thread["updated_at"] = _utc_now_iso()
                return

    async def append_summary_snapshot(
        self,
        thread: dict[str, Any],
        *,
        summary: str,
        turn_count: int,
        source_turn_id: str | None,
    ) -> None:
        self.summary_snapshots.append(
            {
                "id": str(uuid.uuid4()),
                "thread_id": thread["id"],
                "tenant_id": thread["tenant_id"],
                "summary_text": summary,
                "turn_count": turn_count,
                "source_turn_id": source_turn_id,
                "created_at": _utc_now_iso(),
            }
        )


class SupabaseConversationMemoryRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def get_or_create_thread(self, context: RoutingContext) -> dict[str, Any]:
        thread_key = conversation_thread_key(context)

        def _lookup_or_create() -> dict[str, Any]:
            response = (
                self._client.table("conversation_threads")
                .select("*")
                .eq("tenant_id", context.tenant_id)
                .eq("thread_key", thread_key)
                .limit(1)
                .execute()
            )
            if response.data:
                return response.data[0]

            payload = {
                "tenant_id": context.tenant_id,
                "channel_binding_id": context.channel_binding_id,
                "openclaw_account_id": context.openclaw_account_id,
                "channel": context.channel,
                "target_conversation": context.target_conversation,
                "context_token": context.context_token,
                "session_space": context.session_space,
                "thread_key": thread_key,
                "summary": "",
                "summary_turn_count": 0,
            }
            try:
                created = self._client.table("conversation_threads").insert(payload).execute()
                if created.data:
                    return created.data[0]
            except Exception as exc:
                message = str(exc).lower()
                if "duplicate" not in message and "unique" not in message and "23505" not in message:
                    raise
            retry = (
                self._client.table("conversation_threads")
                .select("*")
                .eq("tenant_id", context.tenant_id)
                .eq("thread_key", thread_key)
                .limit(1)
                .execute()
            )
            if retry.data:
                return retry.data[0]
            raise RuntimeError("conversation thread was not created")

        return await asyncio.to_thread(_lookup_or_create)

    async def append_turn(self, thread: dict[str, Any], turn: ConversationTurnInput) -> dict[str, Any]:
        payload = _turn_payload(thread, turn)

        def _insert() -> dict[str, Any]:
            try:
                response = self._client.table("conversation_turns").insert(payload).execute()
                row = response.data[0] if response.data else payload
            except Exception as exc:
                message = str(exc).lower()
                if "duplicate" not in message and "unique" not in message and "23505" not in message:
                    raise
                lookup = (
                    self._client.table("conversation_turns")
                    .select("*")
                    .eq("thread_id", thread["id"])
                    .eq("role", turn.role)
                    .eq("message_id", turn.message_id)
                    .limit(1)
                    .execute()
                )
                row = lookup.data[0] if lookup.data else payload
            self._client.table("conversation_threads").update(
                {
                    "last_turn_at": row.get("created_at"),
                    "updated_at": row.get("created_at"),
                }
            ).eq("id", thread["id"]).execute()
            return row

        return await asyncio.to_thread(_insert)

    async def list_recent_turns(self, thread_id: str, *, limit: int = RECENT_TURN_LIMIT) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            response = (
                self._client.table("conversation_turns")
                .select("*")
                .eq("thread_id", thread_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return list(reversed(response.data or []))

        return await asyncio.to_thread(_query)

    async def update_thread_summary(self, thread_id: str, *, summary: str, turn_count: int) -> None:
        def _update() -> None:
            self._client.table("conversation_threads").update(
                {
                    "summary": summary,
                    "summary_turn_count": turn_count,
                    "updated_at": _utc_now_iso(),
                }
            ).eq("id", thread_id).execute()

        await asyncio.to_thread(_update)

    async def append_summary_snapshot(
        self,
        thread: dict[str, Any],
        *,
        summary: str,
        turn_count: int,
        source_turn_id: str | None,
    ) -> None:
        payload = {
            "thread_id": thread["id"],
            "tenant_id": thread["tenant_id"],
            "summary_text": summary,
            "turn_count": turn_count,
            "source_turn_id": source_turn_id,
            "summary_metadata": {"strategy": "deterministic_recent_turn_digest"},
        }

        def _insert() -> None:
            self._client.table("conversation_summaries").insert(payload).execute()

        await asyncio.to_thread(_insert)


class PostgresConversationMemoryRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        self._database_url = database_url

    async def get_or_create_thread(self, context: RoutingContext) -> dict[str, Any]:
        thread_key = conversation_thread_key(context)

        def _lookup_or_create() -> dict[str, Any]:
            import psycopg
            from psycopg.rows import dict_row

            with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
                row = conn.execute(
                    """
                    SELECT *
                    FROM public.conversation_threads
                    WHERE tenant_id = %s AND thread_key = %s
                    LIMIT 1
                    """,
                    (context.tenant_id, thread_key),
                ).fetchone()
                if row:
                    return dict(row)

                row = conn.execute(
                    """
                    INSERT INTO public.conversation_threads (
                      tenant_id,
                      channel_binding_id,
                      openclaw_account_id,
                      channel,
                      target_conversation,
                      context_token,
                      session_space,
                      thread_key,
                      summary,
                      summary_turn_count
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '', 0)
                    ON CONFLICT (tenant_id, thread_key) DO UPDATE
                    SET updated_at = now()
                    RETURNING *
                    """,
                    (
                        context.tenant_id,
                        context.channel_binding_id,
                        context.openclaw_account_id,
                        context.channel,
                        context.target_conversation,
                        context.context_token,
                        context.session_space,
                        thread_key,
                    ),
                ).fetchone()
                conn.commit()
                return dict(row)

        return await asyncio.to_thread(_lookup_or_create)

    async def append_turn(self, thread: dict[str, Any], turn: ConversationTurnInput) -> dict[str, Any]:
        payload = _turn_payload(thread, turn)

        def _insert() -> dict[str, Any]:
            import psycopg
            from psycopg.rows import dict_row

            with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
                if turn.message_id:
                    row = conn.execute(
                        """
                        INSERT INTO public.conversation_turns (
                          id,
                          thread_id,
                          tenant_id,
                          channel_binding_id,
                          message_id,
                          role,
                          content_type,
                          content,
                          route,
                          provider,
                          model,
                          response_id,
                          raw_payload,
                          created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        ON CONFLICT (thread_id, role, message_id) WHERE message_id IS NOT NULL
                        DO UPDATE SET raw_payload = EXCLUDED.raw_payload
                        RETURNING *
                        """,
                        _turn_insert_params(payload),
                    ).fetchone()
                else:
                    row = conn.execute(
                        """
                        INSERT INTO public.conversation_turns (
                          id,
                          thread_id,
                          tenant_id,
                          channel_binding_id,
                          message_id,
                          role,
                          content_type,
                          content,
                          route,
                          provider,
                          model,
                          response_id,
                          raw_payload,
                          created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        RETURNING *
                        """,
                        _turn_insert_params(payload),
                    ).fetchone()
                conn.execute(
                    """
                    UPDATE public.conversation_threads
                    SET last_turn_at = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (row["created_at"], thread["id"]),
                )
                conn.commit()
                return dict(row)

        return await asyncio.to_thread(_insert)

    async def list_recent_turns(self, thread_id: str, *, limit: int = RECENT_TURN_LIMIT) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            import psycopg
            from psycopg.rows import dict_row

            with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM public.conversation_turns
                    WHERE thread_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (thread_id, limit),
                ).fetchall()
            return [dict(row) for row in reversed(rows)]

        return await asyncio.to_thread(_query)

    async def update_thread_summary(self, thread_id: str, *, summary: str, turn_count: int) -> None:
        def _update() -> None:
            import psycopg

            with psycopg.connect(self._database_url) as conn:
                conn.execute(
                    """
                    UPDATE public.conversation_threads
                    SET summary = %s, summary_turn_count = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (summary, turn_count, thread_id),
                )
                conn.commit()

        await asyncio.to_thread(_update)

    async def append_summary_snapshot(
        self,
        thread: dict[str, Any],
        *,
        summary: str,
        turn_count: int,
        source_turn_id: str | None,
    ) -> None:
        def _insert() -> None:
            import psycopg

            with psycopg.connect(self._database_url) as conn:
                conn.execute(
                    """
                    INSERT INTO public.conversation_summaries (
                      thread_id,
                      tenant_id,
                      summary_text,
                      turn_count,
                      source_turn_id,
                      summary_metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        thread["id"],
                        thread["tenant_id"],
                        summary,
                        turn_count,
                        source_turn_id,
                        json.dumps({"strategy": "deterministic_recent_turn_digest"}, ensure_ascii=False),
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_insert)


class ConversationMemoryService:
    def __init__(self, repository: ConversationMemoryRepository) -> None:
        self._repository = repository

    async def context_for_model(self, context: RoutingContext) -> ConversationContext:
        thread = await self._repository.get_or_create_thread(context)
        recent_turns = await self._repository.list_recent_turns(str(thread["id"]), limit=RECENT_TURN_LIMIT)
        return ConversationContext(
            thread_id=str(thread["id"]),
            thread_key=str(thread["thread_key"]),
            summary=str(thread.get("summary") or ""),
            recent_turns=recent_turns,
        )

    async def append_user_message(
        self,
        context: RoutingContext,
        *,
        content: str,
        content_type: str = "text",
        message_id: str | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._append_turn(
            context,
            ConversationTurnInput(
                role="user",
                content=content,
                content_type=content_type,
                message_id=message_id,
                raw_payload=raw_payload,
            ),
        )

    async def append_assistant_reply(
        self,
        context: RoutingContext,
        *,
        content: str,
        result: ModelDialogueResult | None = None,
        message_id: str | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._append_turn(
            context,
            ConversationTurnInput(
                role="assistant",
                content=content,
                content_type="text",
                message_id=message_id,
                route=result.route if result else None,
                provider=result.provider if result else None,
                model=result.model if result else None,
                response_id=result.response_id if result else None,
                raw_payload=raw_payload,
            ),
        )

    async def _append_turn(self, context: RoutingContext, turn: ConversationTurnInput) -> dict[str, Any]:
        thread = await self._repository.get_or_create_thread(context)
        record = await self._repository.append_turn(thread, turn)
        await self._refresh_summary(thread)
        return record

    async def _refresh_summary(self, thread: dict[str, Any]) -> None:
        thread_id = str(thread["id"])
        turns = await self._repository.list_recent_turns(thread_id, limit=SUMMARY_SOURCE_TURN_LIMIT)
        if not turns:
            return
        summary = _build_deterministic_summary(turns)
        await self._repository.update_thread_summary(thread_id, summary=summary, turn_count=len(turns))
        await self._repository.append_summary_snapshot(
            thread,
            summary=summary,
            turn_count=len(turns),
            source_turn_id=str(turns[-1].get("id")) if turns[-1].get("id") else None,
        )


def conversation_thread_key(context: RoutingContext) -> str:
    stable_parts = [
        context.channel or "openclaw_wechat",
        context.channel_binding_id or "",
        context.openclaw_account_id or "",
        context.target_conversation or "",
        context.context_token or "",
        context.session_space or "",
    ]
    seed = "|".join(stable_parts)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def safe_content_from_message(
    *,
    text: str | None = None,
    transcript: str | None = None,
    image_text: str | None = None,
    media_id: str | None = None,
) -> str:
    content = (text or transcript or image_text or "").strip()
    if content:
        return content
    if media_id:
        return f"[图片消息 media_id={media_id}]"
    return "[空消息]"


def _turn_payload(thread: dict[str, Any], turn: ConversationTurnInput) -> dict[str, Any]:
    now = _utc_now_iso()
    return {
        "id": str(uuid.uuid4()),
        "thread_id": thread["id"],
        "tenant_id": thread["tenant_id"],
        "channel_binding_id": thread.get("channel_binding_id"),
        "message_id": turn.message_id,
        "role": turn.role,
        "content_type": turn.content_type,
        "content": turn.content,
        "route": turn.route,
        "provider": turn.provider,
        "model": turn.model,
        "response_id": turn.response_id,
        "raw_payload": turn.raw_payload or {},
        "created_at": now,
    }


def _turn_insert_params(payload: dict[str, Any]) -> tuple[Any, ...]:
    return (
        payload["id"],
        payload["thread_id"],
        payload["tenant_id"],
        payload["channel_binding_id"],
        payload["message_id"],
        payload["role"],
        payload["content_type"],
        payload["content"],
        payload["route"],
        payload["provider"],
        payload["model"],
        payload["response_id"],
        json.dumps(payload["raw_payload"], ensure_ascii=False),
        payload["created_at"],
    )


def _build_deterministic_summary(turns: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for turn in turns[-SUMMARY_SOURCE_TURN_LIMIT:]:
        role = "用户" if turn.get("role") == "user" else "助手"
        route = turn.get("route")
        route_label = f"/{route}" if route else ""
        content = " ".join(str(turn.get("content") or "").split())
        if len(content) > 220:
            content = content[:217] + "..."
        if content:
            lines.append(f"{role}{route_label}: {content}")
    summary = " | ".join(lines)
    if len(summary) > SUMMARY_MAX_CHARS:
        return summary[-SUMMARY_MAX_CHARS:]
    return summary


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
