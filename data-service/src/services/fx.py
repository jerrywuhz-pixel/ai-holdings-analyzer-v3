from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import httpx


FALLBACK_FX_SOURCE = "fallback_estimate"
FALLBACK_FX_TO_USD = {
    "USD": 1.0,
    "HKD": 0.128,
    "CNY": 0.138,
}


@dataclass(frozen=True)
class FxRateSnapshot:
    base_currency: str
    rates: dict[str, float]
    source: str
    as_of: datetime
    trusted: bool


class FxRateProvider(Protocol):
    async def get_rates(self, currencies: list[str], base_currency: str) -> FxRateSnapshot:
        ...


def normalize_currency(value: object, default: str = "USD") -> str:
    text = str(value or default).strip().upper()
    return text or default


class StaticFallbackFxRateProvider:
    async def get_rates(self, currencies: list[str], base_currency: str) -> FxRateSnapshot:
        base = normalize_currency(base_currency)
        rates = {normalize_currency(currency): _fallback_fx_rate(currency, base) for currency in currencies}
        rates[base] = 1.0
        return FxRateSnapshot(
            base_currency=base,
            rates=rates,
            source=FALLBACK_FX_SOURCE,
            as_of=datetime.now(timezone.utc),
            trusted=False,
        )


class EnvTrustedFxRateProvider:
    """
    Reads trusted pair rates from FX_RATES_JSON.

    Expected shape:
      {"HKD:USD": 0.1278, "CNY:USD": 0.1382}
    Values are direct conversion rates from source currency to base currency.
    """

    def __init__(self, raw_json: str, *, source: str = "trusted_env") -> None:
        self._source = source
        parsed = json.loads(raw_json)
        if not isinstance(parsed, dict):
            raise ValueError("FX_RATES_JSON must be a JSON object")
        self._rates = {str(key).upper(): float(value) for key, value in parsed.items()}

    async def get_rates(self, currencies: list[str], base_currency: str) -> FxRateSnapshot:
        base = normalize_currency(base_currency)
        rates: dict[str, float] = {base: 1.0}
        fallback = StaticFallbackFxRateProvider()
        fallback_snapshot = await fallback.get_rates(currencies, base)
        for currency in currencies:
            source = normalize_currency(currency)
            rates[source] = self._rates.get(f"{source}:{base}", fallback_snapshot.rates.get(source, 1.0))
        return FxRateSnapshot(
            base_currency=base,
            rates=rates,
            source=self._source,
            as_of=datetime.now(timezone.utc),
            trusted=True,
        )


class HttpFxRateProvider:
    """
    Generic production FX provider for APIs that return `rates` per base currency.

    Example response:
      {"base": "USD", "rates": {"HKD": 7.82, "CNY": 7.23}}

    The portfolio read model needs source -> base conversion, so for a USD base
    the HKD conversion rate is `1 / rates.HKD`.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        api_key: str | None = None,
        source: str = "trusted_http_fx",
        timeout_seconds: float = 5.0,
    ) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._source = source
        self._timeout_seconds = timeout_seconds

    async def get_rates(self, currencies: list[str], base_currency: str) -> FxRateSnapshot:
        base = normalize_currency(base_currency)
        symbols = sorted({normalize_currency(currency) for currency in currencies if normalize_currency(currency) != base})
        if not symbols:
            return FxRateSnapshot(
                base_currency=base,
                rates={base: 1.0},
                source=self._source,
                as_of=datetime.now(timezone.utc),
                trusted=True,
            )

        params = {"base": base, "symbols": ",".join(symbols)}
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(self._endpoint, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()

        provider_rates = payload.get("rates") if isinstance(payload, dict) else None
        if not isinstance(provider_rates, dict):
            raise ValueError("FX provider response must include a rates object")

        rates: dict[str, float] = {base: 1.0}
        fallback_snapshot = await StaticFallbackFxRateProvider().get_rates(currencies, base)
        for currency in currencies:
            source = normalize_currency(currency)
            if source == base:
                rates[source] = 1.0
                continue
            quoted = provider_rates.get(source)
            rates[source] = (1.0 / float(quoted)) if quoted else fallback_snapshot.rates.get(source, 1.0)

        return FxRateSnapshot(
            base_currency=base,
            rates=rates,
            source=self._source,
            as_of=datetime.now(timezone.utc),
            trusted=True,
        )


def create_fx_rate_provider_from_env() -> FxRateProvider:
    raw_rates = os.getenv("FX_RATES_JSON", "").strip()
    if raw_rates:
        return EnvTrustedFxRateProvider(raw_rates, source=os.getenv("FX_RATES_SOURCE", "trusted_env"))

    endpoint = os.getenv("FX_RATE_ENDPOINT", "").strip()
    if endpoint:
        return HttpFxRateProvider(
            endpoint,
            api_key=os.getenv("FX_RATE_API_KEY") or None,
            source=os.getenv("FX_RATES_SOURCE", "trusted_http_fx"),
            timeout_seconds=float(os.getenv("FX_RATE_TIMEOUT_SECONDS", "5")),
        )

    return StaticFallbackFxRateProvider()


def fallback_fx_rate(currency: object, base_currency: str) -> float:
    return _fallback_fx_rate(currency, base_currency)


def _fallback_fx_rate(currency: object, base_currency: str) -> float:
    source = normalize_currency(currency)
    target = normalize_currency(base_currency)
    if source == target:
        return 1.0

    source_to_usd = FALLBACK_FX_TO_USD.get(source)
    base_to_usd = FALLBACK_FX_TO_USD.get(target)
    if source_to_usd is None or base_to_usd is None or base_to_usd == 0:
        return 1.0
    return source_to_usd / base_to_usd
