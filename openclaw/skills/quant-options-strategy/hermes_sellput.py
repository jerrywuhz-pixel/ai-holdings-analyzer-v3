from __future__ import annotations

from dataclasses import asdict
import os
from typing import Any

import httpx

from .sellput_formatter import format_hold_report, format_open_report, format_scan_report
from .sellput_models import HoldScoreInput, OpenScoreInput, ScoreResult
from .sellput_scorecard import ScoreEngine


class FutuSellPutDataSource:
    """Fetch Sell Put market data through data-service with Futu preference."""

    def __init__(
        self,
        data_service_url: str | None = None,
        http_client_factory: Any | None = None,
    ) -> None:
        self.data_service_url = (data_service_url or os.getenv(
            "DATA_SERVICE_URL", "http://localhost:8000"
        )).rstrip("/")
        self.http_client_factory = http_client_factory or httpx.AsyncClient

    async def fetch_underlying_quote(self, symbol: str) -> dict[str, Any]:
        url = f"{self.data_service_url}/api/quote/{symbol}"
        max_age_seconds = _positive_int_env("SELLPUT_REALTIME_QUOTE_MAX_AGE_SECONDS", 60)
        async with self.http_client_factory() as client:
            response = await client.get(
                url,
                params={
                    "source": "futu",
                    "require_fresh": "true",
                    "max_age_seconds": max_age_seconds,
                },
            )
            response.raise_for_status()
            payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Futu quote fetch failed for {symbol}: {payload}")
        data = payload.get("data") or {}
        if data.get("price") is None:
            raise RuntimeError(f"Futu quote missing price for {symbol}")
        if data.get("quote_actionability") not in {None, "trade_draft"}:
            raise RuntimeError(
                f"Futu quote is not realtime-actionable for {symbol}: "
                f"{data.get('freshness_status')} {data.get('freshness_reasons')}"
            )
        return data


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class HermesSellPutService:
    """Hermes-facing Sell Put strategy service."""

    def __init__(
        self,
        score_engine: ScoreEngine | None = None,
        futu_data_source: FutuSellPutDataSource | None = None,
    ) -> None:
        self.score_engine = score_engine or ScoreEngine()
        self.futu_data_source = futu_data_source or FutuSellPutDataSource()

    def evaluate_open(
        self,
        payload: dict[str, Any] | OpenScoreInput,
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        score_input = self._coerce_open_input(payload)
        score = self.score_engine.score_open(score_input)
        return {
            "ok": True,
            "strategy": "sell_put_open",
            "score": self._score_to_dict(score),
            "market_data": market_data or {},
            "formatted_report": format_open_report(score, market_data=market_data),
        }

    async def evaluate_open_with_futu(
        self,
        payload: dict[str, Any] | OpenScoreInput,
    ) -> dict[str, Any]:
        if isinstance(payload, OpenScoreInput):
            payload_dict = asdict(payload)
        else:
            payload_dict = dict(payload)

        quote = await self.futu_data_source.fetch_underlying_quote(payload_dict["symbol"])
        if payload_dict.get("underlying_price") is None:
            payload_dict["underlying_price"] = quote["price"]

        market_data = {
            "source": "futu",
            "underlying_quote": quote,
        }
        return self.evaluate_open(payload_dict, market_data=market_data)

    def evaluate_hold(self, payload: dict[str, Any] | HoldScoreInput) -> dict[str, Any]:
        score_input = self._coerce_hold_input(payload)
        score = self.score_engine.score_hold(score_input)
        return {
            "ok": True,
            "strategy": "sell_put_hold",
            "score": self._score_to_dict(score),
            "formatted_report": format_hold_report(score),
        }

    def scan_candidates(
        self,
        contracts: list[dict[str, Any] | OpenScoreInput],
        min_score: int = 70,
    ) -> dict[str, Any]:
        score_inputs = [self._coerce_open_input(contract) for contract in contracts]
        candidates = self.score_engine.scan_chain(score_inputs, min_score=min_score)
        return {
            "ok": True,
            "strategy": "sell_put_scan",
            "min_score": min_score,
            "candidates": [self._score_to_dict(score) for score in candidates],
            "formatted_report": format_scan_report(candidates),
        }

    @staticmethod
    def _coerce_open_input(payload: dict[str, Any] | OpenScoreInput) -> OpenScoreInput:
        if isinstance(payload, OpenScoreInput):
            return payload
        return OpenScoreInput(**payload)

    @staticmethod
    def _coerce_hold_input(payload: dict[str, Any] | HoldScoreInput) -> HoldScoreInput:
        if isinstance(payload, HoldScoreInput):
            return payload
        return HoldScoreInput(**payload)

    @staticmethod
    def _score_to_dict(score: ScoreResult) -> dict[str, Any]:
        return asdict(score)
