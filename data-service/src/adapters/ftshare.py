"""
FTShare Market Data adapter.

Wraps the ClawHub/OpenClaw `ftshare-market-data` skill and normalizes its
JSON output into the data-service quote contract.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from adapters.base import DataSourceAdapter


def to_ftshare_symbol(symbol: str) -> str:
    """
    Convert business symbols into ftshare-market-data symbols.

    Rules:
        - SH600519 -> 600519.SH
        - SZ000001 -> 000001.SZ
        - 600519.SH -> 600519.SH
    """
    s = symbol.strip().upper()
    if s.startswith("SH"):
        return f"{s[2:]}.SH"
    if s.startswith("SZ"):
        return f"{s[2:]}.SZ"
    return s


def _to_business_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if s.endswith(".SH"):
        return f"SH{s[:-3]}"
    if s.endswith(".SZ"):
        return f"SZ{s[:-3]}"
    return s


def _infer_exchange(symbol: str) -> str:
    s = symbol.strip().upper()
    if s.startswith("SH") or s.endswith(".SH"):
        return "SSE"
    if s.startswith("SZ") or s.endswith(".SZ"):
        return "SZSE"
    return ""


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_change_rate(value: Any) -> Optional[float]:
    rate = _to_float(value)
    if rate is None:
        return None
    if abs(rate) <= 1:
        rate *= 100
    return round(rate, 2)


def _timestamp_from_payload(payload: Dict[str, Any]) -> int:
    ts_nanos = payload.get("ts_nanos")
    if ts_nanos:
        try:
            return int(int(ts_nanos) / 1_000_000_000)
        except (TypeError, ValueError):
            pass
    return int(time.time())


def _default_skill_dir() -> Path:
    env_dir = os.getenv("FTSHARE_MARKET_DATA_SKILL_DIR")
    if env_dir:
        return Path(env_dir).expanduser()

    current = Path(__file__).resolve()
    candidates = [
        current.parents[2] / "skills" / "ftshare-market-data",
        Path("/app/skills/ftshare-market-data"),
    ]
    for candidate in candidates:
        if (candidate / "run.py").exists():
            return candidate
    return candidates[0]


class FtShareMarketDataAdapter(DataSourceAdapter):
    """Adapter for the Hermes `ftshare-market-data` skill asset."""

    def __init__(
        self,
        skill_dir: Optional[str] = None,
        python_bin: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.skill_dir = Path(skill_dir).expanduser() if skill_dir else _default_skill_dir()
        self.python_bin = python_bin or os.getenv("FTSHARE_MARKET_DATA_PYTHON") or sys.executable
        self.timeout = timeout or float(os.getenv("FTSHARE_MARKET_DATA_TIMEOUT_SECONDS", "10"))

    @property
    def run_py(self) -> Path:
        return self.skill_dir / "run.py"

    async def _run_skill(self, subskill: str, args: List[str]) -> Any:
        if not self.run_py.exists():
            raise RuntimeError(f"ftshare-market-data skill is not installed at {self.skill_dir}")

        process = await asyncio.create_subprocess_exec(
            self.python_bin,
            str(self.run_py),
            subskill,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise RuntimeError(f"ftshare-market-data timed out after {self.timeout:g}s")

        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip() or stdout.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ftshare-market-data {subskill} failed: {detail[:240]}")

        text = stdout.decode("utf-8", errors="replace").strip()
        if not text:
            raise RuntimeError(f"ftshare-market-data {subskill} returned empty output")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"ftshare-market-data {subskill} returned non-JSON output: {text[:240]}") from exc

    async def fetch_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch A-share quote and valuation data via stock-security-info.

        ftshare-market-data exposes HK and macro endpoints too, but the quote
        contract currently uses the stable A-share stock-security-info payload.
        """
        business_symbol = symbol.strip().upper()
        if not business_symbol.startswith(("SH", "SZ")):
            raise RuntimeError("ftshare-market-data quote adapter only supports CN symbols")

        ft_symbol = to_ftshare_symbol(business_symbol)
        payload = await self._run_skill("stock-security-info", ["--symbol", ft_symbol])
        if not isinstance(payload, dict):
            raise RuntimeError("ftshare-market-data stock-security-info returned non-object JSON")

        raw_symbol = str(payload.get("symbol") or ft_symbol)
        normalized_symbol = _to_business_symbol(raw_symbol)
        price = _to_float(payload.get("close") or payload.get("price"))
        change = _to_float(payload.get("change"))
        change_rate = _normalize_change_rate(payload.get("change_rate"))

        return {
            "symbol": normalized_symbol,
            "name": str(payload.get("symbol_name") or ""),
            "market": "CN",
            "exchange": _infer_exchange(normalized_symbol),
            "price": round(price, 4) if price is not None else None,
            "change": round(change, 4) if change is not None else None,
            "change_rate": change_rate,
            "currency": "CNY",
            "timestamp": _timestamp_from_payload(payload),
            "source": "ftshare",
            "open": _to_float(payload.get("open")),
            "high": _to_float(payload.get("high")),
            "low": _to_float(payload.get("low")),
            "prev_close": _to_float(payload.get("prev_close")),
            "volume": _to_float(payload.get("volume")),
            "turnover": _to_float(payload.get("turnover")),
            "fundamentals": {
                "pe_ttm": _to_float(payload.get("pe_ttm")),
                "pb": _to_float(payload.get("pb")),
                "ps_ttm": _to_float(payload.get("ps_ttm")),
                "roe_ttm": _to_float(payload.get("roe_ttm")),
                "market_cap": _to_float(payload.get("market_cap")),
                "float_a_market_cap": _to_float(payload.get("float_a_market_cap")),
                "eps_ttm": _to_float(payload.get("eps_ttm")),
                "bvps": _to_float(payload.get("bvps")),
            },
        }

    async def fetch_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        results: Dict[str, Dict[str, Any]] = {}
        for symbol in symbols:
            try:
                results[symbol] = await self.fetch_quote(symbol)
            except Exception:
                continue
        return results

    async def search_symbols(self, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        return []
