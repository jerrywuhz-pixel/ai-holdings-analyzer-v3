from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.hermes.alerts import evaluate_rule_hit


def test_evaluate_rule_hit_triggers_on_price_move_from_reference():
    now = datetime.now(timezone.utc)
    result = evaluate_rule_hit(
        {
            "alert_type": "decision_watch_condition",
            "parameters": {
                "reference_price": 100,
                "move_threshold_pct": 5,
                "review_due_at": (now + timedelta(days=1)).isoformat(),
            },
        },
        {"price": 106},
        now,
    )

    assert result["triggered"] is True
    assert result["reason"] == "price_move_from_analysis_reference"
    assert result["move_pct"] == 6.0


def test_evaluate_rule_hit_triggers_on_review_due_without_price_move():
    now = datetime.now(timezone.utc)
    result = evaluate_rule_hit(
        {
            "alert_type": "decision_watch_condition",
            "parameters": {
                "reference_price": 100,
                "move_threshold_pct": 5,
                "review_due_at": (now - timedelta(minutes=1)).isoformat(),
            },
        },
        {"price": 101},
        now,
    )

    assert result["triggered"] is True
    assert result["reason"] == "review_due"


def test_evaluate_rule_hit_skips_when_thresholds_are_not_met():
    now = datetime.now(timezone.utc)
    result = evaluate_rule_hit(
        {
            "alert_type": "decision_watch_condition",
            "parameters": {
                "reference_price": 100,
                "move_threshold_pct": 5,
                "review_due_at": (now + timedelta(days=1)).isoformat(),
            },
        },
        {"price": 102},
        now,
    )

    assert result["triggered"] is False
    assert result["reason"] == "condition_not_met"


def test_evaluate_rule_hit_supports_price_cross_below():
    result = evaluate_rule_hit(
        {
            "alert_type": "price_cross",
            "parameters": {"direction": "below", "threshold": 90},
        },
        {"price": 88},
        datetime.now(timezone.utc),
    )

    assert result["triggered"] is True
    assert result["reason"] == "price_cross_below"


def test_evaluate_rule_hit_supports_price_change_pct():
    result = evaluate_rule_hit(
        {"alert_type": "price_change_pct", "parameters": {"threshold_pct": 3}},
        {"price": 42, "change_rate": -4.2},
        datetime.now(timezone.utc),
    )

    assert result["triggered"] is True
    assert result["reason"] == "price_change_pct"
    assert result["change_pct"] == -4.2


def test_evaluate_rule_hit_supports_earnings_window():
    now = datetime.now(timezone.utc)
    result = evaluate_rule_hit(
        {"alert_type": "earnings_window", "parameters": {"event_at": (now + timedelta(days=2)).isoformat(), "window_days": 3}},
        {},
        now,
    )

    assert result["triggered"] is True
    assert result["reason"] == "earnings_window"


def test_evaluate_rule_hit_supports_discipline_blocking():
    result = evaluate_rule_hit(
        {
            "alert_type": "discipline_violation",
            "parameters": {
                "violations": [
                    {"rule": "cash_buffer", "severity": "critical", "message": "cash buffer below floor"},
                ]
            },
        },
        {},
        datetime.now(timezone.utc),
    )

    assert result["triggered"] is True
    assert result["reason"] == "discipline_violation"
    assert result["actionability_cap"] == "blocked"
