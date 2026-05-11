from __future__ import annotations

"""
Freshness and actionability gate for broker / market data.
"""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FreshnessAssessment(BaseModel):
    is_fresh: bool
    actionability: Literal["trade_draft", "analysis_only", "blocked"]
    age_seconds: int
    max_age_seconds: int
    source_tier: str
    reasons: list[str] = Field(default_factory=list)


class CombinedFreshnessResult(BaseModel):
    overall_actionability: Literal["trade_draft", "analysis_only", "blocked"]
    quote: FreshnessAssessment
    option_chain: FreshnessAssessment
    broker: FreshnessAssessment
    reasons: list[str] = Field(default_factory=list)


class FreshnessGate:
    def evaluate(
        self,
        *,
        as_of: datetime,
        max_age_seconds: int,
        source_tier: str,
        now: Optional[datetime] = None,
        allow_trade_action: bool = True,
        missing_fields: Optional[list[str]] = None,
    ) -> FreshnessAssessment:
        current = now or _utc_now()
        age_seconds = max(0, int((current - as_of).total_seconds()))
        missing_fields = missing_fields or []
        reasons: list[str] = []
        is_fresh = age_seconds <= max_age_seconds

        actionability: Literal["trade_draft", "analysis_only", "blocked"] = "trade_draft"
        if missing_fields:
            reasons.append(f"missing_fields:{','.join(sorted(set(missing_fields)))}")
            actionability = "blocked"

        if source_tier != "L1_trading" and actionability != "blocked":
            reasons.append(f"source_tier:{source_tier}")
            actionability = "analysis_only"

        if not allow_trade_action and actionability == "trade_draft":
            reasons.append("trade_action_not_allowed")
            actionability = "analysis_only"

        if not is_fresh:
            reasons.append(f"stale:{age_seconds}s>{max_age_seconds}s")
            if actionability == "trade_draft":
                actionability = "analysis_only"

        return FreshnessAssessment(
            is_fresh=is_fresh,
            actionability=actionability,
            age_seconds=age_seconds,
            max_age_seconds=max_age_seconds,
            source_tier=source_tier,
            reasons=reasons,
        )

    def evaluate_sell_put_inputs(
        self,
        *,
        quote_as_of: datetime,
        option_chain_as_of: datetime,
        broker_as_of: datetime,
        quote_source_tier: str,
        option_source_tier: str,
        broker_source_tier: str,
        max_market_age_seconds: int = 60,
        max_broker_age_seconds: int = 300,
        broker_verified: bool = True,
        option_missing_fields: Optional[list[str]] = None,
        broker_missing_fields: Optional[list[str]] = None,
        now: Optional[datetime] = None,
    ) -> CombinedFreshnessResult:
        current = now or _utc_now()
        quote = self.evaluate(
            as_of=quote_as_of,
            max_age_seconds=max_market_age_seconds,
            source_tier=quote_source_tier,
            now=current,
        )
        option_chain = self.evaluate(
            as_of=option_chain_as_of,
            max_age_seconds=max_market_age_seconds,
            source_tier=option_source_tier,
            now=current,
            missing_fields=option_missing_fields,
        )
        broker = self.evaluate(
            as_of=broker_as_of,
            max_age_seconds=max_broker_age_seconds,
            source_tier=broker_source_tier,
            now=current,
            allow_trade_action=broker_verified,
            missing_fields=broker_missing_fields,
        )

        reasons = quote.reasons + option_chain.reasons + broker.reasons
        if not broker_verified:
            reasons.append("broker_cash_margin_not_verified")

        actions = [quote.actionability, option_chain.actionability, broker.actionability]
        if "blocked" in actions:
            overall = "blocked"
        elif "analysis_only" in actions:
            overall = "analysis_only"
        else:
            overall = "trade_draft"

        return CombinedFreshnessResult(
            overall_actionability=overall,
            quote=quote,
            option_chain=option_chain,
            broker=broker,
            reasons=reasons,
        )
