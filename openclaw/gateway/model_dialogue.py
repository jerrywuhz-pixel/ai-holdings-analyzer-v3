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
    "详细分析",
    "系统分析",
    "完整分析",
    "deep research",
    "openapt",
    "hermes",
)

SELL_PUT_KEYWORDS = ("sell put", "sellput", "卖 put", "卖put", "现金担保", "期权", "put")
POSITION_KEYWORDS = ("持仓", "仓位", "盈亏", "止盈", "止损", "补仓", "清仓", "复盘")
MARKET_KEYWORDS = ("行情", "走势", "趋势", "大盘", "指数", "板块", "异动", "涨跌")
CONFIRMATION_SAFE_TEXT = "当前不会改动持仓，也不会下单。"


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
    conversation_context: str | None = None,
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
            text=text,
        )

    if not _provider_ready(provider):
        return _route_unavailable(
            resolved_route,
            provider,
            model,
            f"missing_{provider}_auth",
            text=text,
        )

    invocation = _build_invocation(
        text,
        context=context,
        route=resolved_route,
        conversation_context=conversation_context,
    )
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
            text=text,
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


def _build_invocation(
    text: str,
    *,
    context: RoutingContext,
    route: ModelRoute,
    conversation_context: str | None = None,
) -> dict[str, Any]:
    system_prompt = (
        "你是 AI Holdings 的 OpenClaw 轻量分析助手，正在微信里直接回复用户。"
        "回复要像产品内的分析同伴，不要像客服模板；不要用“您好”“感谢咨询”“抱歉我无法提供”开头。"
        "任何改动持仓、下单、同步账户、删除数据、改变通知策略的请求，都必须提醒用户走确认中心，不能声称已经执行。"
        "如果问题需要实时行情而上下文没有提供实时数据，只用一句短句说明限制，然后继续给出有用的分析框架、关键变量和下一步观察点。"
        "不要把回复主体写成“请提供数据/请去某 APP 查看”的模板；除非用户问数据来源，否则不要推荐外部行情软件清单。"
        "使用中文，结论先行，适合微信阅读，尽量控制在 800 字以内。"
        "如果用户只是发一句短句、感叹或情绪化市场观察，先像真人一样接住情绪，再给 2-3 个自然短段落，"
        "不要写成报告，不要使用 Markdown 大标题、加粗小标题、表格、编号清单或项目符号。"
        "这类短句的语气示例：'是有点难受，今天这种跌法先别急着把所有问题归因到个股。"
        "我会先看三件事：是不是放量杀跌、有没有主线一起崩、以及你的仓位是不是已经超过舒服区。'"
        "只有用户明确要求分析报告、候选排序或深度研究时，才使用更结构化的 3-5 条检查项。"
        "不编造实时价格、涨跌幅或未给出的持仓事实。"
    )
    if route == "deep":
        system_prompt += (
            " 当前消息被识别为深度研究请求，应按 Hermes 深研口径组织：先给研究框架、关键假设、需要的数据，"
            "再给可后续展开的结论，不要伪造完整外部数据；避免泛泛免责声明。"
        )

    now = datetime.now().isoformat(timespec="seconds")
    prompt_parts = [
        f"用户消息：{text.strip()}",
        f"当前时间：{now}",
        f"tenant_id={context.tenant_id}",
        f"channel={context.channel}",
        f"timezone={context.timezone_name}",
    ]
    if conversation_context:
        prompt_parts.extend(
            [
                "同一微信会话的共享上下文如下。它同时包含 OpenClaw 日常沟通和 Hermes 深研后的对话记忆；",
                "回答时要延续这些上下文，但不要把它当成已经确认写入持仓的业务事实。",
                conversation_context,
            ]
        )
    prompt_parts.append("请生成要直接回给微信用户的内容。不要输出系统状态、路由信息或模型说明。")
    prompt = "\n".join(prompt_parts)
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
    *,
    text: str = "",
) -> ModelDialogueResult:
    return ModelDialogueResult(
        route=route,
        provider=provider,
        model=model,
        stub=True,
        error=reason,
        reply_text=_friendly_fallback_reply(text, route=route),
    )


def _friendly_fallback_reply(text: str, *, route: ModelRoute) -> str:
    normalized = text.strip().lower()
    if route == "deep":
        return (
            "收到，这个问题适合做深度研究。我先给你一版研究框架：\n"
            "1. 先确认标的、市场、时间窗口和你当前是否已有持仓。\n"
            "2. 再拆基本面、行情趋势、估值位置、事件催化和风险约束。\n"
            "3. 如果涉及期权，会单独看波动率、流动性、Delta、到期日和资金占用。\n"
            "4. 最后给出可执行动作：观察、分批买入、止盈止损、Sell Put 或暂不交易。\n"
            f"{CONFIRMATION_SAFE_TEXT} 你可以继续补充标的代码、持仓截图或成交消息，我会按这个框架展开。"
        )

    if any(keyword in normalized for keyword in SELL_PUT_KEYWORDS):
        return (
            "收到，我先按 Sell Put 机会来拆。核心分两层看：\n"
            "1. 标的层：这只股票本身是否适合接货，重点看趋势、估值、事件风险、财报窗口和你愿意持有的价格。\n"
            "2. 期权链层：再按到期日、Delta、年化收益、保证金占用、bid/ask、成交量、OI 和 IV 分位做排序。\n"
            "默认会避开流动性差、财报前风险过高、接货价不舒服的合约。"
            f"{CONFIRMATION_SAFE_TEXT}"
        )

    if any(keyword in normalized for keyword in POSITION_KEYWORDS):
        return (
            "收到，我先按持仓分析来处理。建议先看三件事：\n"
            "1. 仓位结构：单一标的、行业和市场是否过度集中。\n"
            "2. 风险位置：当前价格离成本、止损线、止盈区间还有多远。\n"
            "3. 下一步动作：继续持有、减仓、移动止损、补仓，还是清仓后复盘。\n"
            "如果你发持仓截图或成交消息，我可以把它整理成确认项再写入系统。"
            f"{CONFIRMATION_SAFE_TEXT}"
        )

    if any(keyword in normalized for keyword in MARKET_KEYWORDS):
        return (
            "收到，我先按行情分析来处理。没有实时行情上下文时，我不会编价格；可以先从这几项判断：\n"
            "1. 指数方向和成交量是否配合。\n"
            "2. 行业强弱是否延续，还是只有短线脉冲。\n"
            "3. 个股是否站上关键均线、前高或放量区。\n"
            "4. 是否临近财报、议息、CPI 等事件窗口。\n"
            f"{CONFIRMATION_SAFE_TEXT}"
        )

    return (
        "收到，我会按普通投资问题继续处理。你可以直接发标的代码、持仓截图、成交消息、语音口令，"
        "或者回复确认/取消口令处理待确认事项。"
        f"{CONFIRMATION_SAFE_TEXT}"
    )
