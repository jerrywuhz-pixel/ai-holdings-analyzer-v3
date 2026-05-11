from __future__ import annotations

"""
Built-in margin estimator.

P0 仅作为无券商确认口径时的参考估算，不能伪装为 broker-confirmed。
"""

from typing import Literal, Optional

from pydantic import BaseModel


class SellPutMarginEstimateRequest(BaseModel):
    underlying_symbol: str
    underlying_price: float
    strike: float
    contracts: int = 1
    premium_per_share: float = 0.0
    available_cash: Optional[float] = None


class SellPutMarginEstimate(BaseModel):
    underlying_symbol: str
    estimate_mode: Literal["builtin_reference"] = "builtin_reference"
    disclaimer: str
    contracts: int
    multiplier: int = 100
    strike: float
    premium_per_share: float
    cash_secured_requirement: float
    estimated_margin_requirement: float
    premium_credit: float
    net_collateral_after_premium: float
    sufficient_available_cash: Optional[bool] = None


class MarginEstimator:
    """
    保守的单腿 Sell Put 估算器。

    cash secured requirement 使用最直接的 strike * 100 * contracts，
    同时给出一个常见规则下的 indicative margin。
    """

    DISCLAIMER = "仅供参考：这是系统内置保证金估算，不能替代券商确认口径。"

    def estimate_sell_put(self, request: SellPutMarginEstimateRequest) -> SellPutMarginEstimate:
        multiplier = 100
        premium_credit = round(request.premium_per_share * multiplier * request.contracts, 2)
        cash_secured_requirement = round(request.strike * multiplier * request.contracts, 2)

        otm_amount = max(request.underlying_price - request.strike, 0.0) * multiplier * request.contracts
        reg_t_estimate = max(
            0.2 * request.underlying_price * multiplier * request.contracts - otm_amount + premium_credit,
            0.1 * request.strike * multiplier * request.contracts + premium_credit,
        )
        estimated_margin_requirement = round(max(reg_t_estimate, 0.0), 2)
        net_collateral = round(max(cash_secured_requirement - premium_credit, 0.0), 2)

        sufficient_cash = None
        if request.available_cash is not None:
            sufficient_cash = request.available_cash >= cash_secured_requirement

        return SellPutMarginEstimate(
            underlying_symbol=request.underlying_symbol,
            disclaimer=self.DISCLAIMER,
            contracts=request.contracts,
            strike=request.strike,
            premium_per_share=request.premium_per_share,
            cash_secured_requirement=cash_secured_requirement,
            estimated_margin_requirement=estimated_margin_requirement,
            premium_credit=premium_credit,
            net_collateral_after_premium=net_collateral,
            sufficient_available_cash=sufficient_cash,
        )
