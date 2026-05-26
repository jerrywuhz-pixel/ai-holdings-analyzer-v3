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
POSITION_SCREENSHOT_KEYWORDS = (
    "持仓",
    "持有",
    "仓位",
    "可用",
    "数量",
    "成本",
    "成本价",
    "市值",
    "盈亏",
    "证券名称",
    "股票名称",
    "资产",
    "position",
    "qty",
    "quantity",
    "shares",
)

_ACTION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("confirm", ("确认", "同意", "yes", "ok", "approve")),
    ("reject", ("拒绝", "取消", "不同意", "reject", "cancel", "no")),
    ("revise", ("修改", "修正", "更正", "改成", "revise", "edit")),
    ("status", ("状态", "进度", "查询确认", "status", "check")),
    ("help", ("帮助", "help", "怎么确认", "确认说明")),
)

BROKER_TRADE_KEYWORDS = (
    "成交",
    "成交通知",
    "成交提醒",
    "成交回报",
    "委托已成交",
    "委托成交",
    "买入成交",
    "卖出成交",
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

    broker_trade = parse_broker_trade_message(text)
    if broker_trade is not None:
        side_label = "买入" if broker_trade["side"] == "BUY" else "卖出"
        body = (
            f"{side_label} {broker_trade.get('stock_name') or broker_trade['symbol']}"
            f"({broker_trade['symbol']}) {broker_trade['quantity']:g}股"
            f" @{broker_trade['price']:g}"
        )
        summary = {
            "title": f"待确认{broker_trade['broker_label']}成交提醒",
            "body": body,
            "source_type": "broker_wechat",
            "risk_note": "这是券商成交提醒解析结果；确认后才会记录到持仓系统，不会自动下单。",
        }
        return PendingActionInput(
            object_type="trade_event_input",
            action_type="trade_input",
            action_scope="fact_record",
            source_type="broker_wechat",
            source_surface=source_surface,
            risk_level="high",
            confirmation_strength="high_attention",
            action_payload={
                "raw_text": text,
                "normalized_text": normalized,
                "confidence": confidence,
                "structured_trade": broker_trade,
                "source_broker": broker_trade["broker"],
                "broker_message_fingerprint": broker_trade["fingerprint"],
                "broker_order_no": broker_trade.get("order_no"),
            },
            normalized_summary=summary,
            fingerprint_seed=f"broker:{broker_trade['fingerprint']}",
        )

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


def parse_broker_trade_message(text: str) -> dict[str, Any] | None:
    raw_text = text.strip()
    normalized = normalize_user_text(raw_text)
    if not normalized:
        return None
    if not any(keyword in raw_text for keyword in BROKER_TRADE_KEYWORDS):
        return None

    broker, broker_label = _detect_broker(raw_text)
    if not broker:
        return None

    parsed: dict[str, Any] | None = None
    if broker == "huatai":
        parsed = _parse_huatai_trade(raw_text)
    elif broker == "zhongxin":
        parsed = _parse_zhongxin_trade(raw_text)
    elif broker == "zhaoshang":
        parsed = _parse_zhaoshang_trade(raw_text)
    elif broker == "futu":
        parsed = _parse_futu_trade(raw_text)

    if parsed is None:
        return None

    try:
        side = _normalize_trade_side(str(parsed["side"]))
        symbol = _normalize_broker_symbol(str(parsed["symbol"]))
        quantity = _as_float(parsed["quantity"])
        price = _as_float(parsed["price"])
    except (KeyError, ValueError):
        return None
    if quantity is None or quantity <= 0 or price is None or price <= 0:
        return None

    market, exchange = _infer_position_market_exchange(symbol)
    fingerprint = hashlib.md5(raw_text.encode("utf-8")).hexdigest()
    return {
        "broker": broker,
        "broker_label": broker_label,
        "side": side,
        "symbol": symbol,
        "provider_symbol": symbol,
        "market": market,
        "exchange": exchange,
        "stock_name": _clean_stock_name(parsed.get("stock_name")),
        "quantity": quantity,
        "price": price,
        "trade_amount": round(quantity * price, 2),
        "trade_time": parsed.get("trade_time"),
        "order_no": parsed.get("order_no"),
        "fingerprint": fingerprint,
    }


def _detect_broker(text: str) -> tuple[str | None, str | None]:
    checks = (
        ("huatai", "华泰证券", ("华泰证券", "华泰")),
        ("zhongxin", "中信证券", ("中信证券", "中信")),
        ("zhaoshang", "招商证券", ("招商证券", "招商")),
        ("futu", "富途牛牛", ("富途牛牛", "富途")),
    )
    for broker, label, keywords in checks:
        if any(keyword in text for keyword in keywords):
            return broker, label
    return None, None


def _field(text: str, pattern: str, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags | re.MULTILINE)
    if not match:
        return None
    return next((group.strip() for group in match.groups() if group is not None), None)


def _parse_huatai_trade(text: str) -> dict[str, Any] | None:
    return _require_trade_fields(
        {
            "stock_name": _field(text, r"证券名称[：:]\s*([^\n\r]+)"),
            "symbol": _field(text, r"证券代码[：:]\s*(\d{6})"),
            "side": _field(text, r"委托方向[：:]\s*(买入|卖出)"),
            "quantity": _field(text, r"成交数量[：:]\s*([\d,]+(?:\.\d+)?)\s*股?"),
            "price": _field(text, r"成交价格[：:]\s*([\d,]+(?:\.\d+)?)"),
            "trade_time": _field(text, r"成交时间[：:]\s*([^\n\r]+)"),
            "order_no": _field(text, r"委托编号[：:]\s*([A-Za-z0-9_-]+)"),
        }
    )


def _parse_zhongxin_trade(text: str) -> dict[str, Any] | None:
    line_match = re.search(r"(买入|卖出)\s+(\d{6})\s+([^\n\r]+)", text)
    return _require_trade_fields(
        {
            "side": line_match.group(1) if line_match else None,
            "symbol": line_match.group(2) if line_match else None,
            "stock_name": line_match.group(3).strip() if line_match else None,
            "quantity": _field(text, r"成交量[：:]\s*([\d,]+(?:\.\d+)?)\s*股?"),
            "price": _field(text, r"成交价[：:]\s*([\d,]+(?:\.\d+)?)"),
            "trade_time": _field(text, r"成交时间[：:]\s*([^\n\r]+)"),
        }
    )


def _parse_zhaoshang_trade(text: str) -> dict[str, Any] | None:
    name_symbol = re.search(r"股票名称[：:]\s*(.+?)\((\d{6})\)", text)
    return _require_trade_fields(
        {
            "side": _field(text, r"成交方向[：:]\s*(买入|卖出)"),
            "stock_name": name_symbol.group(1).strip() if name_symbol else None,
            "symbol": name_symbol.group(2) if name_symbol else None,
            "quantity": _field(text, r"成交数量[：:]\s*([\d,]+(?:\.\d+)?)\s*股?"),
            "price": _field(text, r"成交均价[：:]\s*([\d,]+(?:\.\d+)?)"),
            "trade_time": _field(text, r"成交时间[：:]\s*([^\n\r]+)"),
            "order_no": _field(text, r"(?:合同编号|委托编号)[：:]\s*([A-Za-z0-9_-]+)"),
        }
    )


def _parse_futu_trade(text: str) -> dict[str, Any] | None:
    return _require_trade_fields(
        {
            "side": _field(text, r"方向[：:]\s*(BUY|SELL|买入|卖出)", re.IGNORECASE),
            "symbol": _field(text, r"代码[：:]\s*([A-Za-z0-9.]+)"),
            "stock_name": _field(text, r"名称[：:]\s*([^\n\r]+)"),
            "quantity": _field(text, r"数量[：:]\s*([\d,]+(?:\.\d+)?)\s*股?"),
            "price": _field(text, r"价格[：:]\s*\$?\s*([\d,]+(?:\.\d+)?)"),
            "trade_time": _field(text, r"时间[：:]\s*([^\n\r]+)"),
        }
    )


def _require_trade_fields(values: dict[str, Any]) -> dict[str, Any] | None:
    required = ("side", "symbol", "quantity", "price")
    if any(not values.get(key) for key in required):
        return None
    return values


def _normalize_trade_side(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"buy", "买入", "买"}:
        return "BUY"
    if lowered in {"sell", "卖出", "卖"}:
        return "SELL"
    raise ValueError("unknown broker trade side")


def _normalize_broker_symbol(value: str) -> str:
    token = value.strip().upper()
    if not token:
        raise ValueError("broker symbol is empty")
    if re.fullmatch(r"\d{6}", token):
        if token.startswith(("60", "68")):
            return f"{token}.SH"
        if token.startswith(("00", "30")):
            return f"{token}.SZ"
        return token
    if re.fullmatch(r"\d{5}", token):
        return f"{token}.HK"
    return token


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
        source_type="ocr",
        source_surface=source_surface,
        risk_level="high",
        confirmation_strength="high_attention",
        action_payload=payload,
        normalized_summary={
            "title": "待确认图片识别内容",
            "body": normalized_text,
            "source_type": "ocr",
            "risk_note": risk_note,
        },
        fingerprint_seed=f"ocr:{media_id or ''}:{normalized_text}",
    )


def parse_position_snapshot_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()
    for raw_line in re.split(r"[\n\r;；]+", text):
        line = normalize_user_text(raw_line)
        if not line:
            continue
        name_only = _parse_name_only_position_line(line, raw_line)
        if name_only is not None and name_only["symbol"] not in seen_symbols:
            rows.append(name_only)
            seen_symbols.add(name_only["symbol"])
            continue
        symbol_match = _position_symbol_match(line)
        if not symbol_match:
            continue
        symbol = symbol_match.group(1).upper()
        if symbol in seen_symbols:
            continue
        tail = f"{line[:symbol_match.start()]} {line[symbol_match.end():]}"
        quantity = _position_quantity(tail)
        if quantity is None or quantity <= 0:
            continue
        average_cost = _position_average_cost(tail, quantity)
        market, exchange = _infer_position_market_exchange(symbol)
        rows.append(
            {
                "symbol": symbol,
                "provider_symbol": symbol,
                "market": market,
                "exchange": exchange,
                "stock_name": _position_stock_name(line, symbol_match) or None,
                "quantity": quantity,
                "average_cost": average_cost,
                "raw_line": raw_line.strip(),
            }
        )
        seen_symbols.add(symbol)
    return rows


def normalize_position_snapshot_rows(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()
    for raw_position in positions:
        stock_name = _clean_stock_name(raw_position.get("stock_name") or raw_position.get("name"))
        symbol = str(raw_position.get("symbol") or "").upper().strip()
        if not symbol and stock_name:
            symbol = _name_only_symbol(stock_name)
        if not symbol or symbol in seen_symbols:
            continue

        quantity = _as_float(raw_position.get("quantity") or raw_position.get("total_quantity"))
        if quantity is None or quantity <= 0:
            continue

        average_cost = _as_float(raw_position.get("average_cost") or raw_position.get("cost_price"))
        provider_symbol = str(raw_position.get("provider_symbol") or symbol).strip() or symbol
        market = str(raw_position.get("market") or "").upper().strip()
        exchange = str(raw_position.get("exchange") or "").upper().strip()
        if not market or not exchange:
            inferred_market, inferred_exchange = _infer_position_market_exchange(symbol)
            market = market or inferred_market
            exchange = exchange or inferred_exchange

        position = dict(raw_position)
        position.update(
            {
                "symbol": symbol,
                "provider_symbol": provider_symbol,
                "market": market,
                "exchange": exchange,
                "stock_name": stock_name,
                "quantity": quantity,
                "average_cost": average_cost,
            }
        )
        available_quantity = _as_float(raw_position.get("available_quantity"))
        if available_quantity is not None:
            position["available_quantity"] = available_quantity
        for key in ("current_price", "market_value", "unrealized_pnl", "pnl_ratio"):
            value = _as_float(raw_position.get(key))
            if value is not None:
                position[key] = value
        normalized.append(position)
        seen_symbols.add(symbol)
    return normalized


def _position_symbol_match(line: str) -> re.Match[str] | None:
    upper_match = re.search(r"\b([A-Z]{1,6}(?:\.[A-Z]{1,4})?)\b", line)
    if upper_match and upper_match.group(1).upper() not in {"USD", "HKD", "CNY", "RMB", "ETF"}:
        return upper_match
    return re.search(r"(?<![\d.])(\d{5,6}(?:\.(?:SH|SZ|HK))?)(?![\d.])", line, re.IGNORECASE)


def _numeric_values(text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r"[-+]?\d[\d,]*(?:\.\d+)?", text):
        token = match.group(0).replace(",", "")
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip().replace(",", "")
        if not normalized or normalized == "--":
            return None
        try:
            return float(normalized.rstrip("%")) / 100 if normalized.endswith("%") else float(normalized)
        except ValueError:
            return None
    return None


def _clean_stock_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9·.\- ]+", "", value).strip()
    if not cleaned or any(keyword.lower() == cleaned.lower() for keyword in POSITION_SCREENSHOT_KEYWORDS):
        return None
    return cleaned[:40]


def _name_only_symbol(stock_name: str) -> str:
    digest = hashlib.sha1(stock_name.encode("utf-8")).hexdigest()[:10].upper()
    return f"CNNAME_{digest}"


def _parse_name_only_position_line(line: str, raw_line: str) -> dict[str, Any] | None:
    if not re.search(r"[\u4e00-\u9fff]", line):
        return None
    if any(keyword in line for keyword in ("证券名称", "证券市值", "浮动盈亏", "成本价", "实际数量")):
        return None

    name_match = re.match(r"\s*([\u4e00-\u9fffA-Za-z·]{2,16})", line)
    stock_name = _clean_stock_name(name_match.group(1) if name_match else "")
    if not stock_name:
        return None

    values = _numeric_values(line)
    if len(values) < 5:
        return None

    quantity = values[-2]
    if quantity <= 0:
        return None
    available_quantity = values[-1]
    average_cost = values[-4]
    current_price = values[-3]
    market_value = values[0] if values else None
    unrealized_pnl = values[1] if len(values) >= 2 else None
    percent_match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%", line)
    pnl_ratio = float(percent_match.group(1)) / 100 if percent_match else None

    symbol = _name_only_symbol(stock_name)
    return {
        "symbol": symbol,
        "provider_symbol": symbol,
        "market": "CN",
        "exchange": "UNKNOWN",
        "stock_name": stock_name,
        "quantity": quantity,
        "available_quantity": available_quantity,
        "average_cost": average_cost,
        "current_price": current_price,
        "market_value": market_value,
        "unrealized_pnl": unrealized_pnl,
        "pnl_ratio": pnl_ratio,
        "symbol_confidence": "name_only",
        "requires_symbol_review": True,
        "raw_line": raw_line.strip(),
    }



def _position_quantity(text: str) -> float | None:
    explicit = re.search(
        r"(?:持仓|持有|数量|可用|qty|quantity|shares?)\s*[:：]?\s*([-+]?\d[\d,]*(?:\.\d+)?)|([-+]?\d[\d,]*(?:\.\d+)?)\s*(?:股|shares?)",
        text,
        re.IGNORECASE,
    )
    if explicit:
        token = explicit.group(1) or explicit.group(2)
        return float(token.replace(",", ""))
    values = _numeric_values(text)
    return values[0] if values else None


def _position_average_cost(text: str, quantity: float) -> float | None:
    explicit = re.search(
        r"(?:成本价|成本|均价|平均成本|average cost|avg cost)\s*[:：]?\s*([-+]?\d[\d,]*(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if explicit:
        return float(explicit.group(1).replace(",", ""))
    values = _numeric_values(text)
    if len(values) < 2:
        return None
    for value in values[1:]:
        if value != quantity:
            return value
    return None


def _position_stock_name(line: str, symbol_match: re.Match[str]) -> str | None:
    before = line[: symbol_match.start()].strip()
    after = line[symbol_match.end() :].strip()
    candidates = [before, after]
    for candidate in candidates:
        words = re.findall(r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z·.\- ]{0,30}", candidate)
        if words:
            value = words[0].strip()
            if value and not any(keyword in value.lower() for keyword in POSITION_SCREENSHOT_KEYWORDS):
                return value[:40]
    return None


def _infer_position_market_exchange(symbol: str) -> tuple[str, str]:
    upper = symbol.upper()
    if upper.endswith(".HK") or (upper.isdigit() and len(upper) == 5):
        return "HK", "HKEX"
    if upper.endswith(".SH") or (upper.isdigit() and upper.startswith(("60", "68"))):
        return "CN", "SSE"
    if upper.endswith(".SZ") or (upper.isdigit() and upper.startswith(("00", "30"))):
        return "CN", "SZSE"
    return "US", "NASDAQ"


def _looks_like_position_snapshot(text: str, rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    lowered = text.lower()
    has_keyword = any(keyword.lower() in lowered for keyword in POSITION_SCREENSHOT_KEYWORDS)
    return has_keyword or len(rows) >= 2


def build_position_snapshot_candidate(
    normalized_text: str,
    positions: list[dict[str, Any]],
    *,
    ocr_confidence: float | None,
    media_id: str | None,
    metadata: dict[str, Any] | None,
    source_field: str,
    raw_text: str,
    source_surface: str,
) -> PendingActionInput:
    positions = normalize_position_snapshot_rows(positions)
    symbols = [str(position["symbol"]) for position in positions]
    source_policy = _position_snapshot_source_policy(
        source_type="ocr",
        source_surface=source_surface,
        ocr_confidence=ocr_confidence,
        metadata=metadata,
    )
    summary_lines = [
        f"{position.get('stock_name') or position['symbol']} {position['quantity']:g}股"
        + (f" 成本 {position['average_cost']:g}" if position.get("average_cost") is not None else "")
        for position in positions[:6]
    ]
    if len(positions) > 6:
        summary_lines.append(f"... 另有 {len(positions) - 6} 个标的")
    return PendingActionInput(
        object_type="position_snapshot_input",
        action_type="position_snapshot_input",
        action_scope="fact_record",
        source_type="ocr",
        source_surface=source_surface,
        risk_level="high",
        confirmation_strength="high_attention",
        actionability_level="fact_record",
        action_payload={
            source_field: raw_text,
            "normalized_text": normalized_text,
            "ocr_confidence": ocr_confidence,
            "media_id": media_id,
            "metadata": metadata or {},
            "positions": positions,
            "source_policy": source_policy,
        },
        normalized_summary={
            "title": "待确认持仓截图导入",
            "body": "\n".join(summary_lines),
            "source_type": "ocr",
            "source_tier": source_policy["source_tier"],
            "actionability": source_policy["actionability"],
            "risk_note": "图片识别出的持仓会先进入确认；确认后只写入持仓系统，不会自动下单。",
        },
        fingerprint_seed=f"position-ocr:{media_id or ''}:{','.join(symbols)}:{normalized_text}",
    )


def _position_snapshot_source_policy(
    *,
    source_type: str,
    source_surface: str,
    ocr_confidence: float | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    raw_as_of = None
    if isinstance(metadata, dict):
        raw_as_of = (
            metadata.get("captured_at")
            or metadata.get("created_at")
            or metadata.get("as_of")
            or metadata.get("message_time")
        )
    return {
        "source_type": source_type,
        "source_surface": source_surface,
        "source_tier": "user_confirmed",
        "actionability": "analysis_only",
        "fact_write_allowed": True,
        "trade_action_allowed": False,
        "requires_human_confirmation": True,
        "as_of": raw_as_of,
        "confidence": ocr_confidence,
        "quality_reasons": ["ocr_requires_human_confirmation"],
    }


def classify_image_text_candidate(
    text: str,
    *,
    ocr_confidence: float | None = None,
    media_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    positions: list[dict[str, Any]] | None = None,
    source_field: str = "ocr_text",
    source_surface: str = "wechat",
) -> PendingActionInput | None:
    normalized = normalize_user_text(text)
    supplied_positions = normalize_position_snapshot_rows(positions or [])
    if not normalized and supplied_positions:
        normalized = "\n".join(
            f"{position.get('stock_name') or position['symbol']} {position['quantity']:g}股"
            for position in supplied_positions
        )
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
    position_rows = supplied_positions or normalize_position_snapshot_rows(parse_position_snapshot_rows(text))
    if _looks_like_position_snapshot(normalized, position_rows):
        return build_position_snapshot_candidate(
            normalized,
            position_rows,
            ocr_confidence=ocr_confidence,
            media_id=media_id,
            metadata=metadata,
            source_field=source_field,
            raw_text=text,
            source_surface=source_surface,
        )

    candidate = classify_high_attention_text(
        normalized,
        source_type="ocr",
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


class PostgresConfirmationRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @staticmethod
    def _adapt(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            from psycopg.types.json import Jsonb

            return Jsonb(value)
        return value

    async def create_pending_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._insert("pending_actions", payload)

    async def create_confirmation_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._insert("confirmation_sessions", payload)

    async def append_event(self, payload: dict[str, Any]) -> None:
        await self._insert("confirmation_events", payload)

    async def get_active_session(
        self,
        tenant_id: str,
        *,
        session_hint: str | None = None,
        channel_binding_id: str | None = None,
    ) -> dict[str, Any] | None:
        return await self._get_session(
            tenant_id,
            session_hint=session_hint,
            channel_binding_id=channel_binding_id,
            active_only=True,
        )

    async def get_session_by_hint(
        self,
        tenant_id: str,
        *,
        session_hint: str,
        channel_binding_id: str | None = None,
    ) -> dict[str, Any] | None:
        return await self._get_session(
            tenant_id,
            session_hint=session_hint,
            channel_binding_id=channel_binding_id,
            active_only=False,
        )

    async def get_pending_action(self, pending_action_id: str) -> dict[str, Any] | None:
        from psycopg import connect
        from psycopg.rows import dict_row

        def _query() -> dict[str, Any] | None:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM public.pending_actions WHERE id = %s LIMIT 1", [pending_action_id])
                    row = cur.fetchone()
                    return dict(row) if row else None

        return await asyncio.to_thread(_query)

    async def update_pending_action(self, pending_action_id: str, updates: dict[str, Any]) -> None:
        await self._update("pending_actions", pending_action_id, updates)

    async def update_confirmation_session(
        self,
        confirmation_session_id: str,
        updates: dict[str, Any],
    ) -> None:
        await self._update("confirmation_sessions", confirmation_session_id, updates)

    async def _insert(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        from psycopg import connect, sql
        from psycopg.rows import dict_row

        def _insert() -> dict[str, Any]:
            columns = list(payload.keys())
            query = sql.SQL("INSERT INTO public.{table} ({columns}) VALUES ({values}) RETURNING *").format(
                table=sql.Identifier(table),
                columns=sql.SQL(", ").join(sql.Identifier(column) for column in columns),
                values=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            )
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, [self._adapt(payload[column]) for column in columns])
                    row = cur.fetchone()
                    return dict(row) if row else dict(payload)

        return await asyncio.to_thread(_insert)

    async def _update(self, table: str, record_id: str, updates: dict[str, Any]) -> None:
        from psycopg import connect, sql

        def _update() -> None:
            query = sql.SQL("UPDATE public.{table} SET {updates} WHERE id = %s").format(
                table=sql.Identifier(table),
                updates=sql.SQL(", ").join(
                    sql.SQL("{} = {}").format(sql.Identifier(column), sql.Placeholder())
                    for column in updates
                ),
            )
            with connect(self._database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, [*[self._adapt(value) for value in updates.values()], record_id])

        await asyncio.to_thread(_update)

    async def _get_session(
        self,
        tenant_id: str,
        *,
        session_hint: str | None,
        channel_binding_id: str | None,
        active_only: bool,
    ) -> dict[str, Any] | None:
        from psycopg import connect, sql
        from psycopg.rows import dict_row

        fields = ["session_token"]
        if session_hint and _is_uuid_like(session_hint):
            fields.extend(["id", "pending_action_id"])
        if not session_hint:
            fields = [""]

        def _query() -> dict[str, Any] | None:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    for field in fields:
                        clauses = [sql.SQL("tenant_id = {}").format(sql.Placeholder())]
                        params: list[Any] = [tenant_id]
                        if active_only:
                            clauses.append(sql.SQL("session_status = 'active'"))
                        if channel_binding_id:
                            clauses.append(sql.SQL("channel_binding_id = {}").format(sql.Placeholder()))
                            params.append(channel_binding_id)
                        if field:
                            clauses.append(sql.SQL("{} = {}").format(sql.Identifier(field), sql.Placeholder()))
                            params.append(session_hint)
                        query = sql.SQL(
                            "SELECT * FROM public.confirmation_sessions WHERE {where} ORDER BY created_at DESC LIMIT 1"
                        ).format(where=sql.SQL(" AND ").join(clauses))
                        cur.execute(query, params)
                        row = cur.fetchone()
                        if row:
                            return dict(row)
            return None

        return await asyncio.to_thread(_query)


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
