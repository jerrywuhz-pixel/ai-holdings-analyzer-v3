"""
Report Formatter — 日报格式化模块

将市场概览、板块排名、龙头股和策略建议格式化为 Markdown 日报。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

# 市场名称映射
MARKET_NAMES: dict[str, str] = {
    "CN": "A股",
    "US": "美股",
    "HK": "港股",
}

# 货币符号映射
CURRENCY_SYMBOLS: dict[str, str] = {
    "CN": "¥",
    "US": "$",
    "HK": "HK$",
}

# 策略建议动作映射
ACTION_LABELS: dict[str, str] = {
    "HOLD": "继续观察持有",
    "ADD": "回调后再评估加仓",
    "REDUCE": "考虑分批降低仓位",
    "WATCH": "加入关注清单观察",
}


def format_daily_report(
    market_overview: dict[str, Any],
    top_sectors: list[dict[str, Any]],
    strategy_suggestions: list[dict[str, Any]],
    market: str,
    report_date: str | None = None,
) -> str:
    """
    格式化市场日报为 Markdown 格式。

    Args:
        market_overview: 市场概览数据，包含 advance_count, decline_count,
            flat_count, total_volume, index_quotes。
        top_sectors: 板块排名列表，每个元素包含 name, symbol, change_rate,
            volume, leaders。
        strategy_suggestions: 策略建议列表，每个元素包含 symbol, action, reason。
        market: 市场标识，"CN" / "US" / "HK"。
        report_date: 报告日期，格式 "YYYY-MM-DD"，默认当天。

    Returns:
        格式化后的 Markdown 字符串。
    """
    if report_date is None:
        report_date = date.today().isoformat()

    market_name = MARKET_NAMES.get(market, market)
    currency = CURRENCY_SYMBOLS.get(market, "")

    lines: list[str] = []

    # ---------- 标题 ----------
    lines.append(f"## 市场机会观察 - {market_name} - {report_date}")
    lines.append("")

    # ---------- 市场概览 ----------
    lines.append("### 市场概览")
    lines.append("")

    advance = market_overview.get("advance_count", 0)
    decline = market_overview.get("decline_count", 0)
    flat = market_overview.get("flat_count", 0)
    total_volume = market_overview.get("total_volume", 0)

    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 上涨 | {advance} |")
    lines.append(f"| 下跌 | {decline} |")
    lines.append(f"| 平盘 | {flat} |")
    lines.append(f"| 总成交额 | {_format_volume(total_volume, market)} |")
    lines.append("")

    # 指数行情
    index_quotes = market_overview.get("index_quotes", [])
    if index_quotes:
        lines.append("**主要指数：**")
        lines.append("")
        for idx in index_quotes:
            idx_name = idx.get("name", idx.get("symbol", ""))
            idx_price = idx.get("price")
            idx_cr = idx.get("change_rate")

            price_str = _format_number(idx_price) if idx_price is not None else "-"
            change_str = _format_change_rate(idx_cr)

            lines.append(f"- {idx_name} {price_str} {change_str}")
        lines.append("")

    # ---------- 板块涨跌 Top 10 ----------
    if top_sectors:
        lines.append("### 板块表现前 10")
        lines.append("")
        lines.append("| 排名 | 板块 | 涨跌幅 | 成交额 |")
        lines.append("|------|------|--------|--------|")

        for rank, sector in enumerate(top_sectors, 1):
            s_name = sector.get("name", sector.get("symbol", ""))
            s_cr = sector.get("change_rate")
            s_vol = sector.get("volume", 0) or 0

            cr_str = _format_change_rate(s_cr)
            vol_str = _format_volume(s_vol, market)

            lines.append(f"| {rank} | {s_name} | {cr_str} | {vol_str} |")

        lines.append("")

        # ---------- 龙头股速览 ----------
        sectors_with_leaders = [
            s for s in top_sectors if s.get("leaders")
        ]
        if sectors_with_leaders:
            lines.append("### 代表性个股速览")
            lines.append("")

            for sector in sectors_with_leaders:
                s_name = sector.get("name", sector.get("symbol", ""))
                leaders = sector.get("leaders", [])

                lines.append(f"**{s_name}板块代表性个股：**")
                for leader in leaders:
                    l_name = leader.get("name", leader.get("symbol", ""))
                    l_cr = leader.get("change_rate")
                    change_str = _format_change_rate(l_cr)
                    lines.append(f"- {l_name}({leader.get('symbol', '')}) {change_str}")
                lines.append("")

    # ---------- 持仓策略建议 ----------
    if strategy_suggestions:
        lines.append("### 持仓观察与操作纪律")
        lines.append("")

        for suggestion in strategy_suggestions:
            sym = suggestion.get("symbol", "")
            action = suggestion.get("action", "HOLD")
            reason = suggestion.get("reason", "")

            action_label = ACTION_LABELS.get(action, action)
            lines.append(
                f"- **{sym}**：{action_label}。依据：{reason}"
            )

        lines.append("")
    else:
        lines.append("### 持仓观察与操作纪律")
        lines.append("")
        lines.append("暂无持仓。以上板块和个股仅作为观察线索，不构成买入建议。")
        lines.append("")

    # ---------- 页脚 ----------
    lines.append("---")
    lines.append(f"*报告生成时间：{report_date} | 数据来自系统已接入行情源；交易前请以实时行情和账户可用资金为准。*")

    return "\n".join(lines)


def _format_volume(volume: float | int | None, market: str) -> str:
    """
    格式化成交额为可读字符串。

    Args:
        volume: 成交额原始值。
        market: 市场标识。

    Returns:
        格式化后的字符串，如 "¥8567亿"、"$1234亿"。
    """
    if volume is None:
        return "-"

    currency = CURRENCY_SYMBOLS.get(market, "")

    try:
        v = float(volume)
    except (TypeError, ValueError):
        return "-"

    if abs(v) >= 1e12:
        return f"{currency}{v / 1e12:.1f}万亿"
    if abs(v) >= 1e8:
        return f"{currency}{v / 1e8:.1f}亿"
    if abs(v) >= 1e4:
        return f"{currency}{v / 1e4:.1f}万"
    return f"{currency}{v:.0f}"


def _format_change_rate(change_rate: float | None) -> str:
    """
    格式化涨跌幅为带方向标记的字符串。

    Args:
        change_rate: 涨跌幅百分比值。

    Returns:
        格式化后的字符串，如 "▲+2.35%"、"▼-1.20%"、"0.00%"。
    """
    if change_rate is None:
        return "-"

    try:
        cr = float(change_rate)
    except (TypeError, ValueError):
        return "-"

    if cr > 0:
        return f"▲+{cr:.2f}%"
    if cr < 0:
        return f"▼{cr:.2f}%"
    return "0.00%"


def _format_number(value: float | int | None) -> str:
    """
    格式化数字为可读字符串。

    Args:
        value: 数值。

    Returns:
        格式化后的字符串，如 "3,089.34"。
    """
    if value is None:
        return "-"

    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"

    if abs(v) >= 1000:
        return f"{v:,.2f}"
    return f"{v:.2f}"
