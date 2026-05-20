from __future__ import annotations

"""
System-level OpenAI Codex auth bridge.

This sidecar is intended for a trusted Mac mini / OpenClaw / Hermes node that
already owns an `openai-codex` auth profile. The cloud stack calls this bridge
through an OpenAI-compatible `/v1/chat/completions` contract, while user and
tenant isolation stays in the application run contract.
"""

import asyncio
import json
import os
from typing import Any, Literal, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


BridgeMode = Literal["stub", "command", "http"]


class BridgeSettings(BaseModel):
    mode: BridgeMode = "stub"
    auth_profile: str = "default"
    inbound_api_key: Optional[str] = None
    upstream_base_url: Optional[str] = None
    upstream_api_key: Optional[str] = None
    command: Optional[str] = None
    timeout_seconds: float = 60.0


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: Optional[float] = None
    stream: bool = False


def load_settings() -> BridgeSettings:
    return BridgeSettings(
        mode=_normalize_mode(os.getenv("CODEX_BRIDGE_MODE", "stub")),
        auth_profile=(
            os.getenv("CODEX_BRIDGE_AUTH_PROFILE")
            or os.getenv("OPENAI_CODEX_AUTH_PROFILE")
            or os.getenv("HERMES_AUTH_PROFILE_ID")
            or "default"
        ),
        inbound_api_key=os.getenv("CODEX_BRIDGE_API_KEY") or os.getenv("OPENAI_CODEX_BRIDGE_API_KEY") or None,
        upstream_base_url=_strip_trailing_slash(os.getenv("CODEX_BRIDGE_UPSTREAM_BASE_URL")),
        upstream_api_key=os.getenv("CODEX_BRIDGE_UPSTREAM_API_KEY") or None,
        command=os.getenv("CODEX_BRIDGE_COMMAND") or None,
        timeout_seconds=float(os.getenv("CODEX_BRIDGE_TIMEOUT_SECONDS", "60")),
    )


def _normalize_mode(value: str) -> BridgeMode:
    normalized = value.strip().lower()
    if normalized in {"stub", "command", "http"}:
        return normalized  # type: ignore[return-value]
    return "stub"


def _strip_trailing_slash(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.rstrip("/")


def _authorize(settings: BridgeSettings, authorization: Optional[str]) -> None:
    if not settings.inbound_api_key:
        return
    expected = f"Bearer {settings.inbound_api_key}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="invalid bridge authorization")


def _stub_response(request: ChatCompletionRequest, settings: BridgeSettings) -> dict[str, Any]:
    prompt = " ".join(message.content for message in request.messages if message.role == "user")[:220]
    text = "\n".join(
        [
            "provider=openai-codex",
            f"auth_profile={settings.auth_profile}",
            f"model={request.model}",
            "mode=stub",
            "response=Stubbed Codex bridge response. Configure CODEX_BRIDGE_MODE=command or http for live use.",
            f"prompt_preview={prompt}",
        ]
    )
    return {
        "id": "codex-bridge-stub",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": max(1, sum(len(message.content) for message in request.messages) // 4),
            "completion_tokens": max(1, len(text) // 4),
        },
    }


async def _command_response(request: ChatCompletionRequest, settings: BridgeSettings) -> dict[str, Any]:
    if not settings.command:
        raise HTTPException(status_code=503, detail="CODEX_BRIDGE_COMMAND is not configured")
    payload = {
        "auth_profile": settings.auth_profile,
        "model": request.model,
        "messages": [message.model_dump() for message in request.messages],
        "temperature": request.temperature,
    }
    process = await asyncio.create_subprocess_shell(
        settings.command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(payload).encode("utf-8")),
            timeout=settings.timeout_seconds,
        )
    except TimeoutError as exc:
        process.kill()
        raise HTTPException(status_code=504, detail="Codex bridge command timed out") from exc
    if process.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=f"Codex bridge command failed: {stderr.decode('utf-8', errors='replace')[:500]}",
        )
    try:
        return json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Codex bridge command returned invalid JSON") from exc


async def _http_response(request: ChatCompletionRequest, settings: BridgeSettings) -> dict[str, Any]:
    if not settings.upstream_base_url:
        raise HTTPException(status_code=503, detail="CODEX_BRIDGE_UPSTREAM_BASE_URL is not configured")
    headers = {
        "Content-Type": "application/json",
        "X-Hermes-Auth-Profile": settings.auth_profile,
    }
    if settings.upstream_api_key:
        headers["Authorization"] = f"Bearer {settings.upstream_api_key}"
    async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
        response = await client.post(
            f"{settings.upstream_base_url}/chat/completions",
            headers=headers,
            json=request.model_dump(exclude_none=True),
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text[:500])
    return response.json()


def create_app() -> FastAPI:
    app = FastAPI(title="OpenAI Codex Auth Bridge", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        settings = load_settings()
        return {
            "status": "ok",
            "mode": settings.mode,
            "auth_profile_configured": bool(settings.auth_profile),
            "inbound_auth_required": bool(settings.inbound_api_key),
            "command_configured": bool(settings.command),
            "upstream_base_url_configured": bool(settings.upstream_base_url),
        }

    @app.post("/v1/chat/completions")
    @app.post("/chat/completions")
    async def chat_completions(
        request: ChatCompletionRequest,
        authorization: Optional[str] = Header(default=None),
    ) -> dict[str, Any]:
        settings = load_settings()
        _authorize(settings, authorization)
        if request.stream:
            raise HTTPException(status_code=400, detail="streaming is not supported by this bridge contract yet")
        if settings.mode == "command":
            return await _command_response(request, settings)
        if settings.mode == "http":
            return await _http_response(request, settings)
        return _stub_response(request, settings)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("CODEX_BRIDGE_HOST", "127.0.0.1")
    port = int(os.getenv("CODEX_BRIDGE_PORT", "8091"))
    uvicorn.run("local_connectors.openai_codex_bridge.server:app", host=host, port=port, reload=False)
