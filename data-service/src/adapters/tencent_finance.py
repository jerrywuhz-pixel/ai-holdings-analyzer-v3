from __future__ import annotations

"""
Tencent Finance L3 placeholder adapter.

P0 只提供 contract / capability 占位，不调用真实公共接口。
"""

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class TencentFinanceQuoteRequest(BaseModel):
    symbol: str
    market: Optional[str] = None


class TencentFinanceQuoteSnapshot(BaseModel):
    symbol: str
    market: str
    source_key: Literal["tencent_finance"] = "tencent_finance"
    source_tier: Literal["L3_public_stable"] = "L3_public_stable"
    as_of: datetime
    price: Optional[float] = None
    currency: Optional[str] = None
    can_drive_trade_strategy: bool = False
    status: Literal["placeholder"] = "placeholder"
    notes: list[str] = Field(default_factory=list)


class TencentFinanceAdapter:
    def capabilities(self) -> dict[str, Any]:
        return {
            "source_key": "tencent_finance",
            "source_tier": "L3_public_stable",
            "supports": {
                "display_quotes": True,
                "cross_check": True,
                "fallback": True,
                "trade_strategy_primary": False,
            },
            "notes": [
                "P0 keeps Tencent Finance as an L3 placeholder / fallback contract only.",
                "It must not drive trade-level strategy output on its own.",
            ],
        }

    async def fetch_placeholder_quote(
        self,
        request: TencentFinanceQuoteRequest,
    ) -> TencentFinanceQuoteSnapshot:
        market = (request.market or "").upper()
        if not market:
            market = "HK" if request.symbol.upper().startswith("HK") else "US"

        return TencentFinanceQuoteSnapshot(
            symbol=request.symbol.upper(),
            market=market,
            as_of=datetime.now(timezone.utc),
            notes=[
                "placeholder_only",
                "use_for_cross_check_or_fallback_display",
                "not_trade_actionable",
            ],
        )
