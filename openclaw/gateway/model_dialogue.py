"""Model-backed dialogue routing for OpenClaw WeChat ingress."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

import httpx

from openclaw.gateway.confirmation_center import RoutingContext

ModelRoute = Literal["light", "deep"]
Provider = Literal["minimax", "openai", "openai-codex"]


DEEP_RESEARCH_KEYWORDS = (
    "深度研究",
    "深研",
    "研究报告",
    "完整报告",
    "深度分析",
    "deep research",
    "openapt",
    "hermes",
)


@dataclass(frozen=True)
class ModelDialogueResult:
    route: ModelRoute
    provider: Provider
    model: str
    reply_text: str
    response_id: str | None = None
    stub: bool = False
    error: str | None = None


def is_deep_research_request(text: str) -> bool:
    normalized = text.strip().lower()
    return any(keyword in normalized for keyword in DEEP_RESEARCH_KEYWORDS)


async def generate_openclaw_reply(
    text: str,
    *,
    context: RoutingContext,
    route: ModelRoute | None = None,
) -> ModelDialogueResult:
    resolved_route: ModelRoute = route or ("deep" if is_deep_research_request(text) else "light")
    provider = _resolve_provider(resolved_route)
    model = _resolve_model(resolved_route, provider)

    if not _live_models_enabled():
        return _route_unavailable(
            resolved_route,
            provider,
            model,
            "live_models_disabled",
        )

    if not _provider_ready(provider):
        return _route_unavailable(
            resolved_route,
            provider,
            model,
            f"missing_{provider}_auth",
        )

    invocation = _build_invocation(text, context=context, route=resolved_route)
    timeout_seconds = _resolve_timeout_seconds(resolved_route)

    try:
        if provider == "minimax":
            return await _call_minimax(invocation, model=model, route=resolved_route, timeout_seconds=timeout_seconds)
        if provider == "openai-codex":
            return await _call_openai_like(
                invocation,
                provider=provider,
                model=_prefix_openai_codex_model(model),
                route=resolved_route,
                base_url=_openai_codex_bridge_base_url(),
                api_key=_openai_codex_bridge_api_key(),
                auth_profile=_openai_codex_auth_profile(),
                timeout_seconds=timeout_seconds,
            )
        return await _call_openai_like(
            invocation,
            provider=provider,
            model=model,
            route=resolved_route,
            base_url=_openai_base_url(),
            api_key=_openai_api_key(),
            auth_profile="",
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - exact transport errors vary by provider
        return _route_unavailable(
            resolved_route,
            provider,
            model,
            f"provider_error:{type(exc).__name__}",
        )


def _live_models_enabled() -> bool:
    return _env_bool("GBRAIN_LIVE_MODELS_ENABLED", False)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_provider(route: ModelRoute) -> Provider:
    if route == "light":
        return "minimax"
    configured = os.getenv("HERMES_DEEP_PROVIDER") or os.getenv("MODEL_ADAPTER_FALLBACK_PROVIDER")
    if configured in {"openai", "openai-codex", "minimax"}:
        return configured  # type: ignore[return-value]
    if os.getenv("MODEL_AUTH_MODE") in {"openai_codex", "hermes_auth_profile"}:
        return "openai-codex"
    return "openai"


def _resolve_model(route: ModelRoute, provider: Provider) -> str:
    if route == "light":
        return os.getenv("ANTHROPIC_MODEL") or os.getenv("MINIMAX_MODEL") or os.getenv("HERMES_LIGHT_MODEL") or "MiniMax-M2.7"
    if os.getenv("HERMES_DEEP_MODEL"):
        return os.environ["HERMES_DEEP_MODEL"]
    return "gpt-5.4" if provider == "openai-codex" else "gpt-5.5"


def _resolve_timeout_seconds(route: ModelRoute) -> float:
    if route == "deep":
        return float(os.getenv("HERMES_DEEP_TASK_TIMEOUT_SECONDS", "1800"))
    return float(os.getenv("OPENCLAW_MODEL_TIMEOUT_SECONDS") or os.getenv("HERMES_LIGHT_TASK_TIMEOUT_SECONDS", "300"))


def _provider_ready(provider: Provider) -> bool:
    if provider == "minimax":
        return bool(_minimax_api_key())
    if provider == "openai-codex":
        return bool(_openai_codex_auth_profile() and _openai_codex_bridge_base_url())
    return bool(_openai_api_key())


def _minimax_api_key() -> str:
    return os.getenv("MINIMAX_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY") or ""


def _minimax_base_url() -> str:
    return (
        os.getenv("MINIMAX_OPENAI_BASE_URL")
        or os.getenv("MINIMAX_BASE_URL")
        or os.getenv("ANTHROPIC_BASE_URL")
        or "https://api.minimaxi.com/anthropic"
    ).rstrip("/")


def _minimax_api_format() -> Literal["anthropic", "openai"]:
    configured = (os.getenv("MINIMAX_API_FORMAT") or "").strip().lower()
    if configured in {"anthropic", "openai"}:
        return configured  # type: ignore[return-value]
    if os.getenv("ANTHROPIC_BASE_URL") or os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "anthropic" if "/anthropic" in _minimax_base_url() else "openai"


def _openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY") or os.getenv("GBRAIN_OPENAI_API_KEY") or ""


def _openai_base_url() -> str:
    return (os.getenv("OPENAI_BASE_URL") or os.getenv("GBRAIN_OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")


def _openai_codex_auth_profile() -> str:
    return os.getenv("OPENAI_CODEX_AUTH_PROFILE") or os.getenv("HERMES_AUTH_PROFILE_ID") or os.getenv("OPENCLAW_AUTH_PROFILE") or ""


def _openai_codex_bridge_base_url() -> str:
    return (
        os.getenv("OPENAI_CODEX_BRIDGE_BASE_URL")
        or os.getenv("HERMES_CODEX_GATEWAY_BASE_URL")
        or os.getenv("OPENCLAW_CODEX_GATEWAY_BASE_URL")
        or ""
    ).rstrip("/")


def _openai_codex_bridge_api_key() -> str:
    return (
        os.getenv("OPENAI_CODEX_BRIDGE_API_KEY")
        or os.getenv("HERMES_CODEX_GATEWAY_API_KEY")
        or os.getenv("OPENCLAW_CODEX_GATEWAY_API_KEY")
        or ""
    )


def _prefix_openai_codex_model(model: str) -> str:
    return model if "/" in model else f"openai-codex/{model}"


def _build_invocation(text: str, *, context: RoutingContext, route: ModelRoute) -> dict[str, Any]:
    system_prompt = (
        "你是 AI Holdings 的 OpenClaw 轻量分析助手，正在微信里直接回复用户。"
        "回复要像产品内的分析同伴，不要像客服模板；不要用“您好”“感谢咨询”“抱歉我无法提供”开头。"
        "任何改动持仓、下单、同步账户、删除数据、改变通知策略的请求，都必须提醒用户走确认中心，不能声称已经执行。"
        "如果问题需要实时行情而上下文没有提供实时数据，只用一句短句说明限制，然后继续给出有用的分析框架、关键变量和下一步观察点。"
        "不要把回复主体写成“请提供数据/请去某 APP 查看”的模板；除非用户问数据来源，否则不要推荐外部行情软件清单。"
        "使用中文，结论先行，尽量给 3-5 条具体判断或检查项，不编造实时价格、涨跌幅或未给出的持仓事实。"
    )
    if route == "deep":
        system_prompt += (
            " 当前消息被识别为深度研究请求，应按 Hermes 深研口径组织：先给研究框架、关键假设、需要的数据，"
            "再给可后续展开的结论，不要伪造完整外部数据；避免泛泛免责声明。"
        )

    now = datetime.now().isoformat(timespec="seconds")
    prompt = "\n".join(
        [
            f"用户消息：{text.strip()}",
            f"当前时间：{now}",
            f"tenant_id={context.tenant_id}",
            f"channel={context.channel}",
            f"timezone={context.timezone_name}",
            "请生成要直接回给微信用户的内容。不要输出系统状态、路由信息或模型说明。",
        ]
    )
    return {
        "system": system_prompt,
        "prompt": prompt,
        "temperature": 0.2 if route == "deep" else 0.3,
    }


async def _call_minimax(
    invocation: dict[str, Any],
    *,
    model: str,
    route: ModelRoute,
    timeout_seconds: float,
) -> ModelDialogueResult:
    if _minimax_api_format() == "anthropic":
        return await _call_minimax_anthropic(invocation, model=model, route=route, timeout_seconds=timeout_seconds)
    return await _call_openai_like(
        invocation,
        provider="minimax",
        model=model,
        route=route,
        base_url=_minimax_base_url(),
        api_key=_minimax_api_key(),
        auth_profile="",
        timeout_seconds=timeout_seconds,
    )


async def _call_minimax_anthropic(
    invocation: dict[str, Any],
    *,
    model: str,
    route: ModelRoute,
    timeout_seconds: float,
) -> ModelDialogueResult:
    base_url = _minimax_base_url()
    endpoint = "/messages" if base_url.endswith("/v1") else "/v1/messages"
    body = {
        "model": model,
        "max_tokens": int(os.getenv("MINIMAX_MAX_TOKENS", "2048")),
        "system": invocation["system"],
        "messages": [{"role": "user", "content": invocation["prompt"]}],
        "temperature": invocation["temperature"],
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{base_url}{endpoint}",
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": _minimax_api_key(),
                "anthropic-version": "2023-06-01",
            },
            json=body,
        )
        response.raise_for_status()
        payload = response.json()

    content = payload.get("content") or []
    text = "\n".join(
        part.get("text", "")
        for part in content
        if isinstance(part, dict) and (part.get("type") in {None, "text"})
    ).strip()
    if not text:
        raise ValueError("minimax provider returned an empty response")
    return ModelDialogueResult(
        route=route,
        provider="minimax",
        model=model,
        reply_text=text,
        response_id=payload.get("id"),
        stub=False,
    )


async def _call_openai_like(
    invocation: dict[str, Any],
    *,
    provider: Provider,
    model: str,
    route: ModelRoute,
    base_url: str,
    api_key: str,
    auth_profile: str,
    timeout_seconds: float,
) -> ModelDialogueResult:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if auth_profile:
        headers["X-Hermes-Auth-Profile"] = auth_profile

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": invocation["system"]},
                    {"role": "user", "content": invocation["prompt"]},
                ],
                "temperature": invocation["temperature"],
            },
        )
        response.raise_for_status()
        payload = response.json()

    choices = payload.get("choices") or []
    first = choices[0] if choices else {}
    message = first.get("message") if isinstance(first, dict) else {}
    text = (message or {}).get("content") or first.get("text") or ""
    if not str(text).strip():
        raise ValueError(f"{provider} provider returned an empty response")
    return ModelDialogueResult(
        route=route,
        provider=provider,
        model=model,
        reply_text=str(text).strip(),
        response_id=payload.get("id") or str(uuid4()),
        stub=False,
    )


def _route_unavailable(
    route: ModelRoute,
    provider: Provider,
    model: str,
    reason: str,
) -> ModelDialogueResult:
    label = "日常对话" if route == "light" else "深度研究"
    return ModelDialogueResult(
        route=route,
        provider=provider,
        model=model,
        stub=True,
        error=reason,
        reply_text=(
            f"{label}模型路由暂时未就绪（{provider}/{model}: {reason}）。"
            "消息已进入 OpenClaw 网关，但不会伪装成模型回复；当前没有改动持仓，也没有下单。"
        ),
    )
