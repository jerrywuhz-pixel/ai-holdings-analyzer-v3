from datetime import datetime, timedelta, timezone

from services.freshness import FreshnessGate


def test_freshness_gate_marks_stale_l1_as_analysis_only():
    gate = FreshnessGate()
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    result = gate.evaluate(
        as_of=now - timedelta(seconds=120),
        max_age_seconds=60,
        source_tier="L1_trading",
        now=now,
    )

    assert result.is_fresh is False
    assert result.actionability == "analysis_only"
    assert any("stale" in reason for reason in result.reasons)


def test_sell_put_freshness_without_verified_broker_degrades_to_analysis_only():
    gate = FreshnessGate()
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    result = gate.evaluate_sell_put_inputs(
        quote_as_of=now - timedelta(seconds=15),
        option_chain_as_of=now - timedelta(seconds=20),
        broker_as_of=now - timedelta(seconds=30),
        quote_source_tier="L1_trading",
        option_source_tier="L1_trading",
        broker_source_tier="estimated",
        broker_verified=False,
        now=now,
    )

    assert result.overall_actionability == "analysis_only"
    assert result.broker.actionability == "analysis_only"
    assert "broker_cash_margin_not_verified" in result.reasons
