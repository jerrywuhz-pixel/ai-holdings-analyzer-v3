from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from adapters.futu import FutuAccountSnapshot
from services.sell_put import (
    SellPutAnalysisRequest,
    SellPutAnalysisService,
    SellPutOptionCandidateInput,
    SellPutQuoteInput,
)


def _account_snapshot(
    *,
    available_cash: float = 25000.0,
    buying_power: float = 50000.0,
    positions: list[dict] | None = None,
    missing_fields: list[str] | None = None,
) -> FutuAccountSnapshot:
    now = datetime.now(timezone.utc)
    return FutuAccountSnapshot.model_validate(
        {
            "tenant_id": "tenant-1",
            "broker_connection_id": "bc-1",
            "as_of": now.isoformat(),
            "received_at": now.isoformat(),
            "positions": positions or [],
            "cash_balances": [
                {
                    "currency": "USD",
                    "available_cash": available_cash,
                    "buying_power": buying_power,
                    "cash_secured_reserve": 0.0,
                }
            ],
            "missing_fields": missing_fields or [],
            "status": "partial" if missing_fields else "complete",
            "lineage": {"read_only": True},
        }
    )


def _quote(now: datetime) -> SellPutQuoteInput:
    return SellPutQuoteInput(
        symbol="AAPL",
        as_of=now - timedelta(seconds=10),
        price=190.0,
        currency="USD",
        cross_check_status="matched",
    )


def _candidate(
    now: datetime,
    *,
    contract_symbol: str,
    strike: float,
    contracts: int = 1,
    days_to_expiry: int = 40,
    bid: float = 2.4,
    ask: float = 2.7,
    delta: float = 0.21,
    implied_volatility: float = 0.34,
    open_interest: int | None = 1200,
    volume: int | None = 180,
) -> SellPutOptionCandidateInput:
    return SellPutOptionCandidateInput(
        contract_symbol=contract_symbol,
        strike=strike,
        contracts=contracts,
        expiry="2026-06-19",
        days_to_expiry=days_to_expiry,
        bid=bid,
        ask=ask,
        delta=delta,
        implied_volatility=implied_volatility,
        open_interest=open_interest,
        volume=volume,
        as_of=now - timedelta(seconds=10),
    )


@pytest.mark.asyncio
async def test_sell_put_ranks_best_candidate_and_returns_structured_outputs():
    service = SellPutAnalysisService()
    now = datetime.now(timezone.utc)

    payload = SellPutAnalysisRequest(
        tenant_id="tenant-1",
        underlying_symbol="AAPL",
        quote=_quote(now),
        account_snapshot=_account_snapshot(),
        option_candidates=[
            _candidate(now, contract_symbol="AAPL260619P165", strike=165.0, bid=1.2, ask=1.35, delta=0.12, volume=95),
            _candidate(now, contract_symbol="AAPL260619P175", strike=175.0),
            _candidate(now, contract_symbol="AAPL260619P170", strike=170.0, bid=1.8, ask=2.0, delta=0.17, open_interest=850, volume=120),
        ],
    )

    result = await service.analyze(payload)

    assert result.overall_actionability == "trade_draft"
    assert result.underlying_gate.gate_status == "passed"
    assert result.candidate_ranking[0].contract_symbol == "AAPL260619P175"
    assert result.candidate_ranking[0].rank == 1
    assert result.candidates[0].contract_symbol == "AAPL260619P175"
    assert result.candidates[0].actionability == "trade_draft"
    assert result.candidates[0].playbook.mode == "draft_only"
    assert result.candidates[0].playbook.actions


@pytest.mark.asyncio
async def test_sell_put_missing_option_fields_blocks_candidate():
    service = SellPutAnalysisService()
    now = datetime.now(timezone.utc)

    payload = SellPutAnalysisRequest(
        tenant_id="tenant-1",
        underlying_symbol="AAPL",
        quote=_quote(now),
        account_snapshot=_account_snapshot(),
        option_candidates=[
            _candidate(now, contract_symbol="AAPL260619P175", strike=175.0, open_interest=None)
        ],
    )

    result = await service.analyze(payload)

    assert result.candidates[0].actionability == "blocked"
    assert "open_interest" in result.candidates[0].missing_fields
    assert any("missing_fields" in reason for reason in result.candidates[0].reasons)


@pytest.mark.asyncio
async def test_sell_put_wide_spread_blocks_candidate():
    service = SellPutAnalysisService()
    now = datetime.now(timezone.utc)

    payload = SellPutAnalysisRequest(
        tenant_id="tenant-1",
        underlying_symbol="AAPL",
        quote=_quote(now),
        account_snapshot=_account_snapshot(),
        option_candidates=[
            _candidate(now, contract_symbol="AAPL260619P175", strike=175.0, bid=1.8, ask=2.6)
        ],
    )

    result = await service.analyze(payload)

    assert result.overall_actionability == "blocked"
    assert result.candidates[0].actionability == "blocked"
    assert "spread_too_wide" in result.candidates[0].reasons
    assert result.underlying_gate.gate_status == "blocked"


@pytest.mark.asyncio
async def test_sell_put_stressed_market_degrades_actionability():
    service = SellPutAnalysisService()
    now = datetime.now(timezone.utc)

    payload = SellPutAnalysisRequest(
        tenant_id="tenant-1",
        underlying_symbol="AAPL",
        quote=_quote(now),
        account_snapshot=_account_snapshot(),
        market_state="stressed",
        option_candidates=[
            _candidate(
                now,
                contract_symbol="AAPL260619P175",
                strike=175.0,
                days_to_expiry=21,
                bid=2.4,
                ask=2.5,
                delta=0.15,
                implied_volatility=0.30,
            )
        ],
    )

    result = await service.analyze(payload)

    assert result.overall_actionability == "analysis_only"
    assert result.underlying_gate.gate_status == "degraded"
    assert "market_state_stressed" in result.blocked_reasons
    assert all(item.actionability != "trade_draft" for item in result.candidates)


@pytest.mark.asyncio
async def test_sell_put_assignment_risk_warns_in_playbook():
    service = SellPutAnalysisService()
    now = datetime.now(timezone.utc)

    payload = SellPutAnalysisRequest(
        tenant_id="tenant-1",
        underlying_symbol="AAPL",
        quote=_quote(now),
        account_snapshot=_account_snapshot(),
        option_candidates=[
            _candidate(now, contract_symbol="AAPL260619P187", strike=187.0, delta=0.26, bid=4.3, ask=4.7, implied_volatility=0.31)
        ],
    )

    result = await service.analyze(payload)

    assert result.underlying_gate.gate_status == "degraded"
    assert result.candidates[0].playbook.assignment_risk == "high"
    assert any("被指派" in note for note in result.candidates[0].user_reasons)
    assert any(step.phase == "assignment" for step in result.candidates[0].playbook.actions)
    assert "不会自动下单" in result.candidates[0].playbook.summary


@pytest.mark.asyncio
async def test_sell_put_insufficient_cash_blocks_candidate():
    service = SellPutAnalysisService()
    now = datetime.now(timezone.utc)

    payload = SellPutAnalysisRequest(
        tenant_id="tenant-1",
        underlying_symbol="AAPL",
        quote=_quote(now),
        account_snapshot=_account_snapshot(available_cash=8000.0),
        option_candidates=[
            _candidate(now, contract_symbol="AAPL260619P175", strike=175.0)
        ],
    )

    result = await service.analyze(payload)

    assert result.overall_actionability == "blocked"
    assert result.candidates[0].actionability == "blocked"
    assert "insufficient_available_cash" in result.candidates[0].reasons
    assert result.underlying_gate.gate_status == "blocked"


@pytest.mark.asyncio
async def test_sell_put_multiple_contracts_use_cash_secured_requirement_for_block():
    service = SellPutAnalysisService()
    now = datetime.now(timezone.utc)

    payload = SellPutAnalysisRequest(
        tenant_id="tenant-1",
        underlying_symbol="AAPL",
        quote=_quote(now),
        account_snapshot=_account_snapshot(available_cash=30000.0),
        option_candidates=[
            _candidate(now, contract_symbol="AAPL260619P175X2", strike=175.0, contracts=2)
        ],
    )

    result = await service.analyze(payload)

    assert result.overall_actionability == "blocked"
    assert result.candidates[0].actionability == "blocked"
    assert result.candidates[0].margin_estimate.cash_secured_requirement == 35000.0
    assert "insufficient_available_cash" in result.candidates[0].reasons


@pytest.mark.asyncio
async def test_sell_put_stale_option_chain_candidate_is_never_trade_draft():
    service = SellPutAnalysisService()
    now = datetime.now(timezone.utc)

    payload = SellPutAnalysisRequest(
        tenant_id="tenant-1",
        underlying_symbol="AAPL",
        quote=_quote(now),
        account_snapshot=_account_snapshot(),
        option_candidates=[
            _candidate(
                now - timedelta(minutes=3),
                contract_symbol="AAPL260619P175",
                strike=175.0,
            )
        ],
    )

    result = await service.analyze(payload)

    assert result.overall_actionability == "analysis_only"
    assert result.candidates[0].actionability == "analysis_only"
    assert result.candidates[0].actionability != "trade_draft"
    assert any(reason.startswith("stale:") for reason in result.candidates[0].reasons)


@pytest.mark.asyncio
async def test_sell_put_existing_short_put_exposure_degrades_candidate_and_returns_constraint_summary():
    service = SellPutAnalysisService()
    now = datetime.now(timezone.utc)

    payload = SellPutAnalysisRequest(
        tenant_id="tenant-1",
        underlying_symbol="AAPL",
        quote=_quote(now),
        account_snapshot=_account_snapshot(
            positions=[
                {
                    "symbol": "AAPL",
                    "market": "US",
                    "instrument_type": "stock",
                    "quantity": 100,
                    "average_cost": 182.5,
                    "market_price": 191.2,
                    "currency": "USD",
                },
                {
                    "symbol": "AAPL260619P170",
                    "market": "US",
                    "instrument_type": "option_contract",
                    "quantity": -1,
                    "average_cost": 4.8,
                    "market_price": 3.9,
                    "currency": "USD",
                    "option_type": "put",
                    "strike": 170.0,
                    "expiry": "2026-06-19",
                },
            ]
        ),
        option_candidates=[
            _candidate(now, contract_symbol="AAPL260619P175", strike=175.0)
        ],
    )

    result = await service.analyze(payload)

    assert result.overall_actionability == "analysis_only"
    assert result.underlying_gate.gate_status == "degraded"
    assert result.candidates[0].actionability == "analysis_only"
    assert "existing_short_put_exposure_present" in result.candidates[0].reasons
    assert "same_underlying_concentration_high" in result.candidates[0].reasons
    assert result.candidates[0].account_constraint_summary.has_existing_short_put is True
    assert result.candidates[0].account_constraint_summary.existing_short_put_contracts == 1
    assert result.candidates[0].account_constraint_summary.projected_cash_secured_requirement == 17500.0
    assert result.candidates[0].account_constraint_summary.concentration_is_high is True
    assert "已有同标的短 Put" in result.candidates[0].account_constraint_summary.constraint_note


@pytest.mark.asyncio
async def test_sell_put_without_broker_snapshot_is_reference_only_and_never_trade_draft():
    service = SellPutAnalysisService()
    now = datetime.now(timezone.utc)

    payload = SellPutAnalysisRequest(
        tenant_id="tenant-1",
        underlying_symbol="AAPL",
        quote=_quote(now),
        option_candidates=[
            _candidate(now, contract_symbol="AAPL260619P175", strike=175.0)
        ],
    )

    result = await service.analyze(payload)

    assert result.overall_actionability == "analysis_only"
    assert result.broker_snapshot_mode == "estimated_only"
    assert result.underlying_gate.actionability == "analysis_only"
    assert result.candidates[0].actionability != "trade_draft"
    assert result.candidate_ranking[0].actionability != "trade_draft"
    assert result.candidates[0].margin_estimate.disclaimer.startswith("仅供参考")
    assert "broker_cash_margin_not_verified" in result.blocked_reasons
