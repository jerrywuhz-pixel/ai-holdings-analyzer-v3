"""MiniMax vision extraction helpers for image-only OpenClaw ingress."""
from __future__ import annotations

import json
import os
import re
import base64
import asyncio
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from openclaw.gateway.model_dialogue import (
    _env_bool,
    _minimax_api_format,
    _minimax_api_key,
    _minimax_base_url,
    _resolve_timeout_seconds,
)


@dataclass(frozen=True)
class ImageTextExtraction:
    ocr_text: str
    positions: list[dict[str, Any]]
    confidence: float | None
    provider: str
    model: str
    response_id: str | None = None
    error: str | None = None


async def extract_image_text_from_metadata(metadata: dict[str, Any]) -> ImageTextExtraction | None:
    image_url = _image_reference(metadata)
    if not image_url:
        return None

    provider, base_url, api_key, model = _vision_provider_config()
    if not _env_bool("OPENCLAW_IMAGE_VISION_ENABLED", True):
        return ImageTextExtraction("", [], None, provider, model, error="image_vision_disabled")
    if not base_url or not api_key:
        return ImageTextExtraction("", [], None, provider, model, error=f"missing_{provider}_auth")

    try:
        image_url = await _prepare_image_reference_for_provider(image_url)
        payload: dict[str, Any] | None = None
        try:
            payload = await _call_minimax_vision(
                image_url,
                base_url=base_url,
                api_key=api_key,
                model=model,
            )
            content = _message_content(payload)
        except Exception as api_exc:
            try:
                content = await _call_mmx_cli_vision(image_url)
            except Exception:
                content = ""
            if not content:
                raise api_exc
            payload = {"id": f"mmx-cli-{uuid4()}", "content": [{"type": "text", "text": content}]}
        parsed = _parse_json_object(content)
        positions = parsed.get("positions") if isinstance(parsed.get("positions"), list) else []
        return ImageTextExtraction(
            ocr_text=str(parsed.get("ocr_text") or content or "").strip(),
            positions=[item for item in positions if isinstance(item, dict)],
            confidence=_numeric_or_none(parsed.get("confidence")),
            provider=provider,
            model=model,
            response_id=str(payload.get("id") or uuid4()),
            error=None,
        )
    except Exception as exc:  # pragma: no cover - provider and transport failures vary
        return ImageTextExtraction("", [], None, provider, model, error=f"{type(exc).__name__}:{exc}")


def _image_reference(metadata: dict[str, Any]) -> str | None:
    for key in ("image_data_url", "image_url", "media_url"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            url = value.strip()
            if url.startswith("data:image/") or url.startswith("http://") or url.startswith("https://"):
                return url
    return None


async def _prepare_image_reference_for_provider(image_url: str) -> str:
    if _minimax_api_format() != "anthropic" or image_url.startswith("data:image/"):
        return image_url
    return await _download_image_as_data_url(image_url)


async def _download_image_as_data_url(image_url: str) -> str:
    max_bytes = int(os.getenv("OPENCLAW_IMAGE_VISION_MAX_IMAGE_BYTES", str(5 * 1024 * 1024)))
    timeout_seconds = float(
        os.getenv("OPENCLAW_IMAGE_VISION_DOWNLOAD_TIMEOUT_SECONDS")
        or _resolve_timeout_seconds("light")
    )
    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
        response = await client.get(image_url)
        response.raise_for_status()
        content_length = int(response.headers.get("content-length") or "0")
        if content_length > max_bytes:
            raise ValueError(f"image_too_large:{content_length}>{max_bytes}")
        content = response.content
    if len(content) > max_bytes:
        raise ValueError(f"image_too_large:{len(content)}>{max_bytes}")
    content_type = response.headers.get("content-type") or "image/jpeg"
    media_type = content_type.split(";", 1)[0].strip().lower()
    if not media_type.startswith("image/"):
        raise ValueError(f"unsupported_image_content_type:{media_type}")
    data = base64.b64encode(content).decode("ascii")
    return f"data:{media_type};base64,{data}"


def _vision_provider_config() -> tuple[str, str, str, str]:
    model = (
        os.getenv("OPENCLAW_IMAGE_VISION_MODEL")
        or os.getenv("ANTHROPIC_MODEL")
        or os.getenv("MINIMAX_MODEL")
        or os.getenv("HERMES_LIGHT_MODEL")
        or "MiniMax-M2.7"
    )
    return ("minimax", _minimax_base_url(), _minimax_api_key(), model)


async def _call_minimax_vision(
    image_url: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    timeout_seconds = float(
        os.getenv("OPENCLAW_IMAGE_VISION_TIMEOUT_SECONDS")
        or _resolve_timeout_seconds("light")
    )
    max_tokens = int(os.getenv("OPENCLAW_IMAGE_VISION_MAX_TOKENS", "1800"))
    last_error: Exception | None = None
    attempts = int(os.getenv("OPENCLAW_IMAGE_VISION_API_ATTEMPTS", "3"))
    for attempt in range(max(1, attempts)):
        try:
            if _minimax_api_format() == "anthropic":
                return await _call_minimax_anthropic_vision(
                    image_url,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                )
            return await _call_minimax_openai_vision(
                image_url,
                base_url=base_url,
                api_key=api_key,
                model=model,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code < 500 or attempt >= attempts - 1:
                raise _annotated_http_status_error(exc) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if attempt >= attempts - 1:
                raise
        await asyncio.sleep(0.3 * (attempt + 1))
    if last_error:
        raise last_error
    raise RuntimeError("image_vision_api_failed")


async def _call_minimax_anthropic_vision(
    image_url: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    image_source = _anthropic_image_source(image_url)
    endpoint = "/messages" if base_url.endswith("/v1") else "/v1/messages"
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": _vision_system_prompt(),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _vision_user_prompt()},
                    {"type": "image", "source": image_source},
                ],
            }
        ],
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{base_url}{endpoint}",
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json=body,
        )
        response.raise_for_status()
        return response.json()


async def _call_minimax_openai_vision(
    image_url: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _vision_system_prompt()},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _vision_user_prompt()},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=body,
        )
        response.raise_for_status()
        return response.json()


async def _call_mmx_cli_vision(image_url: str) -> str:
    cli = os.getenv("MMX_CLI_PATH") or shutil.which("mmx")
    if not cli:
        return ""
    timeout_seconds = float(
        os.getenv("OPENCLAW_IMAGE_VISION_CLI_TIMEOUT_SECONDS")
        or os.getenv("OPENCLAW_IMAGE_VISION_TIMEOUT_SECONDS")
        or _resolve_timeout_seconds("light")
    )
    prompt = f"{_vision_system_prompt()}\n\n{_vision_user_prompt()}"

    with _image_cli_arg(image_url) as image_arg:
        args = [
            cli,
            "vision",
            "describe",
            "--image",
            image_arg,
            "--prompt",
            prompt,
            "--output",
            "json",
            "--quiet",
        ]
        completed = await asyncio.to_thread(
            subprocess.run,
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise RuntimeError(f"mmx_cli_vision_failed:{stderr[:500] or completed.returncode}")
    return (completed.stdout or "").strip()


class _image_cli_arg:
    def __init__(self, image_url: str) -> None:
        self.image_url = image_url
        self.path: Path | None = None

    def __enter__(self) -> str:
        if not self.image_url.startswith("data:image/"):
            return self.image_url
        match = re.match(r"^data:(image/[-+.A-Za-z0-9]+);base64,(.+)$", self.image_url, flags=re.DOTALL)
        if not match:
            raise ValueError("invalid_data_image_url")
        suffix = _image_suffix(match.group(1))
        handle = tempfile.NamedTemporaryFile(prefix="openclaw-vision-", suffix=suffix, delete=False)
        try:
            handle.write(base64.b64decode(match.group(2), validate=False))
            self.path = Path(handle.name)
            return handle.name
        finally:
            handle.close()

    def __exit__(self, *_: object) -> None:
        if self.path:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


def _image_suffix(media_type: str) -> str:
    if media_type == "image/png":
        return ".png"
    if media_type in {"image/webp", "image/x-webp"}:
        return ".webp"
    return ".jpg"


def _annotated_http_status_error(exc: httpx.HTTPStatusError) -> RuntimeError:
    body = (exc.response.text or "").strip().replace("\n", " ")
    return RuntimeError(f"http_{exc.response.status_code}:{body[:500] or exc.response.reason_phrase}")


def _vision_system_prompt() -> str:
    return (
        "你是券商持仓截图识别器。只抽取图片里明确可见的信息，不猜股票代码。"
        "如果截图没有显示代码，symbol 置空，但保留 stock_name。"
        "输出严格 JSON，不要 Markdown。"
    )


def _vision_user_prompt() -> str:
    return (
        "从这张持仓截图中识别 OCR 文本和持仓行。返回 JSON："
        "{\"ocr_text\": string, \"confidence\": number, \"positions\": ["
        "{\"symbol\": string|null, \"provider_symbol\": string|null, "
        "\"stock_name\": string|null, \"market\": \"CN\"|\"HK\"|\"US\"|null, "
        "\"exchange\": string|null, \"quantity\": number|null, "
        "\"available_quantity\": number|null, \"average_cost\": number|null, "
        "\"current_price\": number|null, \"market_value\": number|null, "
        "\"unrealized_pnl\": number|null, \"pnl_ratio\": number|null}"
        "]}。"
        "中文券商列常见顺序是：证券名称/证券市值、浮动盈亏/盈亏比例、"
        "成本价/现价、实际数量/可用数量。数量为 0 的行也可以返回。"
    )


def _anthropic_image_source(image_url: str) -> dict[str, str]:
    match = re.match(r"^data:(image/[-+.A-Za-z0-9]+);base64,(.+)$", image_url, flags=re.DOTALL)
    if not match:
        raise ValueError("minimax_anthropic_vision_requires_image_data_url")
    return {
        "type": "base64",
        "media_type": match.group(1),
        "data": match.group(2),
    }


def _message_content(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") in {None, "text"}
        ).strip()

    choices = payload.get("choices") or []
    first = choices[0] if choices else {}
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "\n".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict)
            ).strip()
    return str(first.get("text") or "").strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return {}
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}


def _numeric_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
