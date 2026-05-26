from __future__ import annotations

from .sellput_models import ScoreResult


def format_open_report(score: ScoreResult, market_data: dict | None = None) -> str:
    return _format_single_score("Hermes Sell Put Open Score", score, market_data=market_data)


def format_hold_report(score: ScoreResult, market_data: dict | None = None) -> str:
    return _format_single_score("Hermes Sell Put Hold Score", score, market_data=market_data)


def format_scan_report(candidates: list[ScoreResult]) -> str:
    lines = ["## Hermes Sell Put Candidate Scan", ""]
    if not candidates:
        lines.append("No candidates passed the configured threshold.")
        return "\n".join(lines)

    lines.extend([
        "| Rank | Symbol | Score | Grade | Action |",
        "|------|--------|-------|-------|--------|",
    ])
    for idx, score in enumerate(candidates, start=1):
        lines.append(
            f"| {idx} | {score.symbol} | {score.total_score:.2f} | "
            f"{score.grade} | {score.action} |"
        )
    return "\n".join(lines)


def _format_single_score(
    title: str,
    score: ScoreResult,
    market_data: dict | None = None,
) -> str:
    lines = [
        f"## {title}",
        "",
        f"**Symbol:** {score.symbol}",
        f"**Score:** {score.total_score:.2f} / 100",
        f"**Grade:** {score.grade}",
        f"**Action:** {score.action}",
        f"**Recommendation:** {score.recommendation}",
        "",
        "### Dimensions",
    ]
    for name, value in score.dimension_scores.items():
        lines.append(f"- {name}: {value:.2f}")
    if score.warnings:
        lines.extend(["", "### Warnings"])
        lines.extend(f"- {warning}" for warning in score.warnings)
    if market_data:
        quote = market_data.get("underlying_quote", {})
        lines.extend(["", "### Market Data"])
        lines.append(f"- source: {market_data.get('source', 'unknown')}")
        if quote:
            lines.append(f"- underlying: {quote.get('symbol', score.symbol)} @ {quote.get('price')}")
    return "\n".join(lines)
