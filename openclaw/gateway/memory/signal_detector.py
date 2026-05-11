"""
SignalDetector — 从 Skill 输出中提取结构化实体信号

检测 trade-input 和 daily-analysis 的输出，提取需要写入 brain 的实体信息。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """交易事件信号"""

    symbol: str
    stock_name: str
    side: str
    quantity: int
    price: float
    trade_date: str
    tags: list[str] = field(default_factory=list)
    strategy_tag: str = ""
    trade_event_id: str = ""
    market: str = "CN"

    @property
    def page_path(self) -> str:
        return f"stocks/{self.symbol}"

    @property
    def event_type(self) -> str:
        return "TRADE_BUY" if self.side == "BUY" else "TRADE_SELL"


@dataclass
class AnalysisSignal:
    """AI 分析信号"""

    symbols: list[str] = field(default_factory=list)
    stock_names: list[str] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    sentiment: str = "neutral"
    report_id: str = ""
    analysis_date: str = ""

    @property
    def insight_path(self) -> str:
        return f"insights/daily-{self.analysis_date}"


@dataclass
class PositionSignal:
    """持仓更新信号"""

    symbols: list[str] = field(default_factory=list)
    quantities: dict[str, int] = field(default_factory=dict)
    total_value: float = 0.0


@dataclass
class ReportSignal:
    """Hermes 机会猎手信号"""

    market: str = "CN"
    sectors: list[str] = field(default_factory=list)
    leaders: list[str] = field(default_factory=list)
    strategy_suggestions: list[dict] = field(default_factory=list)
    report_id: str = ""


class SignalDetector:
    """
    从 Skill 输出中提取结构化实体信号。

    同时兼容当前直接业务输出与早期 table/data 写入回调格式。
    """

    def detect_trade_signal(self, skill_output: dict[str, Any]) -> TradeSignal | None:
        try:
            data = skill_output.get("data", {})
            event = self._extract_trade_event(skill_output, data)
            if not isinstance(event, dict):
                return None

            raw_symbol = str(event.get("symbol", "")).strip()
            if not raw_symbol:
                return None

            market = str(event.get("market", "")).strip().upper() or self._infer_market(raw_symbol)
            symbol = self._normalize_symbol(raw_symbol, market_hint=market)

            return TradeSignal(
                symbol=symbol,
                stock_name=str(event.get("stock_name", "")),
                side=str(event.get("side", "")),
                quantity=int(event.get("quantity", 0) or 0),
                price=float(event.get("price", 0) or 0),
                trade_date=str(event.get("trade_date", "")),
                tags=list(event.get("tags", []) or []),
                strategy_tag=str(event.get("strategy_tag", "")),
                trade_event_id=str(event.get("id", "")),
                market=market or self._infer_market(symbol),
            )
        except (TypeError, ValueError) as exc:
            logger.warning("[signal_detector] Failed to detect trade signal: %s", exc)
            return None

    def detect_analysis_signal(self, skill_output: dict[str, Any]) -> AnalysisSignal | None:
        try:
            data = skill_output.get("data", {})
            if not data:
                return None

            content = data.get("content", {})
            if not isinstance(content, dict):
                content = {}

            symbols = data.get("symbols") or content.get("symbols") or []
            if not symbols and isinstance(data.get("formatted_markdown"), str):
                symbols = self._extract_symbols_from_text(data["formatted_markdown"])

            normalized_symbols: list[str] = []
            for symbol in symbols:
                normalized = self._normalize_symbol(str(symbol))
                if normalized and normalized not in normalized_symbols:
                    normalized_symbols.append(normalized)

            insights = data.get("insights") or content.get("insights") or []
            if not insights and isinstance(data.get("formatted_markdown"), str):
                insights = self._extract_key_points(data["formatted_markdown"])

            analysis_date = str(data.get("analysis_date") or data.get("report_date") or "")
            sentiment = str(data.get("sentiment") or content.get("sentiment") or "neutral")
            report_id = str(data.get("analysis_id") or data.get("id") or "")

            if not normalized_symbols and not insights:
                return None

            return AnalysisSignal(
                symbols=normalized_symbols,
                stock_names=list(data.get("stock_names") or content.get("stock_names") or []),
                insights=[str(item) for item in insights][:5],
                sentiment=sentiment,
                report_id=report_id,
                analysis_date=analysis_date,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("[signal_detector] Failed to detect analysis signal: %s", exc)
            return None

    def detect_position_signal(self, skill_output: dict[str, Any]) -> PositionSignal | None:
        try:
            data = skill_output.get("data", {})
            positions = data.get("positions", [])
            if not isinstance(positions, list) or not positions:
                return None

            symbols: list[str] = []
            quantities: dict[str, int] = {}
            for position in positions:
                if not isinstance(position, dict):
                    continue
                symbol = self._normalize_symbol(str(position.get("symbol", "")))
                if not symbol:
                    continue
                symbols.append(symbol)
                quantities[symbol] = int(position.get("quantity", 0) or 0)

            if not symbols:
                return None

            return PositionSignal(
                symbols=symbols,
                quantities=quantities,
                total_value=float(data.get("total_value", 0) or 0),
            )
        except (TypeError, ValueError) as exc:
            logger.warning("[signal_detector] Failed to detect position signal: %s", exc)
            return None

    @staticmethod
    def _normalize_symbol(symbol: str, market_hint: str = "") -> str:
        symbol = symbol.strip().upper()
        if not symbol:
            return ""
        if re.fullmatch(r"(SH|SZ)\d{6}", symbol):
            return f"{symbol[2:]}.{symbol[:2]}"
        if re.fullmatch(r"\d{6}\.(SH|SZ)", symbol):
            return symbol
        if re.fullmatch(r"\d{6}", symbol):
            if market_hint in {"SH", "SZ"}:
                return f"{symbol}.{market_hint}"
            if symbol.startswith(("5", "6", "688")):
                return f"{symbol}.SH"
            if symbol.startswith(("0", "3")):
                return f"{symbol}.SZ"
        return symbol

    @classmethod
    def _extract_symbols_from_text(cls, text: str) -> list[str]:
        patterns = [
            r"\b(?:SH|SZ)\d{6}\b",
            r"\b\d{6}\.(?:SH|SZ)\b",
            r"[（(]((?:SH|SZ)\d{6}|\d{6}\.(?:SH|SZ))[）)]",
        ]
        symbols: list[str] = []
        for pattern in patterns:
            for match in re.findall(pattern, text, flags=re.IGNORECASE):
                candidate = match if isinstance(match, str) else match[0]
                normalized = cls._normalize_symbol(candidate)
                if normalized and normalized not in symbols:
                    symbols.append(normalized)
        return symbols

    @staticmethod
    def _extract_key_points(text: str, max_points: int = 5) -> list[str]:
        points: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if re.match(r"^[-*•]\s+", line):
                point = re.sub(r"^[-*•]\s+", "", line).strip()
            elif re.match(r"^\d+[.)]\s+", line):
                point = re.sub(r"^\d+[.)]\s+", "", line).strip()
            else:
                continue
            if point:
                points.append(point)
            if len(points) >= max_points:
                break
        return points

    @staticmethod
    def _extract_trade_event(skill_output: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        if skill_output.get("table") == "trade_events" and isinstance(data, dict):
            return data
        trade_events = data.get("trade_events")
        if isinstance(trade_events, list) and trade_events:
            first = trade_events[0]
            return first if isinstance(first, dict) else None
        return None

    @staticmethod
    def _infer_market(symbol: str) -> str:
        symbol = symbol.strip().upper()
        if symbol.endswith(".SH") or symbol.startswith("SH"):
            return "SH"
        if symbol.endswith(".SZ") or symbol.startswith("SZ"):
            return "SZ"
        return "CN"
