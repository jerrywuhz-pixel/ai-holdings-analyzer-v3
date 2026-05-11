from services.margin import MarginEstimator, SellPutMarginEstimateRequest


def test_margin_estimator_returns_reference_disclaimer():
    estimator = MarginEstimator()

    result = estimator.estimate_sell_put(
        SellPutMarginEstimateRequest(
            underlying_symbol="AAPL",
            underlying_price=190.0,
            strike=175.0,
            contracts=2,
            premium_per_share=2.5,
            available_cash=40000.0,
        )
    )

    assert result.estimate_mode == "builtin_reference"
    assert "仅供参考" in result.disclaimer
    assert "券商确认口径" in result.disclaimer
    assert result.cash_secured_requirement == 35000.0
    assert result.sufficient_available_cash is True
