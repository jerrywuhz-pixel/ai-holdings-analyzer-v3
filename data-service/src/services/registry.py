"""
数据源注册与健康检测服务

统一管理多个行情数据源（Yahoo Finance / Stooq / Tushare / FTShare / AkShare），
实现智能路由、Redis 缓存集成和健康检查。
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from adapters.ftshare import FtShareMarketDataAdapter
from adapters.futu_quote import FutuQuoteAdapter
from adapters.yahoo import YahooFinanceAdapter
from adapters.stooq import StooqAdapter
from adapters.tushare import TushareAdapter
from adapters.akshare import AkShareAdapter
from adapters.longbridge import LongbridgeAdapter
from services.cache import QuoteCache


class QuoteFreshnessError(RuntimeError):
    """Raised when a caller requires realtime data but only stale data is available."""


class DataSourceRegistry:
    """
    数据源注册表。

    维护多个适配器实例，根据股票代码自动推断市场并选择最优数据源，
    同时集成 QuoteCache 实现查询结果缓存。
    """

    # 各市场的默认数据源优先级（越靠前越优先）
    _CN_PRIORITY = ["tushare", "ftshare", "yahoo", "stooq", "akshare"]
    _HK_PRIORITY = ["longbridge", "yahoo", "tushare", "akshare"]
    _US_PRIORITY = ["yahoo", "stooq", "longbridge", "tushare", "akshare"]

    def __init__(self):
        self._adapters = {
            "yahoo": YahooFinanceAdapter(),
            "stooq": StooqAdapter(),
            "futu": FutuQuoteAdapter(),
            "tushare": TushareAdapter(),
            "ftshare": FtShareMarketDataAdapter(),
            "akshare": AkShareAdapter(),
            "longbridge": LongbridgeAdapter(),
        }
        self._cache = QuoteCache()

    @staticmethod
    def _infer_market(symbol: str) -> str:
        """根据业务层 symbol 前缀推断市场。"""
        s = symbol.strip().upper()
        if s.startswith(("SH", "SZ")):
            return "CN"
        if s.startswith("HK"):
            return "HK"
        return "US"

    def _get_priority(self, symbol: str, prefer: Optional[str] = None) -> List[str]:
        """确定数据源尝试优先级。"""
        if prefer:
            if prefer not in self._adapters:
                raise ValueError(f"Unknown data source: {prefer}")
            return [prefer]

        market = self._infer_market(symbol)
        if market == "CN":
            return self._CN_PRIORITY
        if market == "HK":
            return self._with_optional_futu_default(self._HK_PRIORITY)
        return self._with_optional_futu_default(self._US_PRIORITY)

    @staticmethod
    def _with_optional_futu_default(priority: List[str]) -> List[str]:
        if os.getenv("FUTU_QUOTE_DEFAULT_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return priority
        return ["futu", *[source for source in priority if source != "futu"]]

    async def get_quote(
        self,
        symbol: str,
        prefer: Optional[str] = None,
        *,
        require_fresh: bool = False,
        max_age_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        获取单只股票实时行情，优先读缓存，未命中按优先级请求数据源。

        新增字段说明：
            - source_fallback: bool  是否使用了非首选数据源
            - cached: bool            是否来自缓存（含 stale）
            - stale: bool             是否来自 stale 缓存兜底

        Args:
            symbol: 业务层股票代码，如 "SH600519"、"AAPL"
            prefer: 强制指定数据源（"futu" / "yahoo" / "stooq" / "tushare" / "ftshare" / "akshare" / "longbridge"），可选
            require_fresh: 是否要求返回可用于交易草稿的实时行情
            max_age_seconds: 调用方指定的最大行情年龄，默认读取环境变量 / 内置策略

        Returns:
            标准化行情字典（可能携带 source_fallback / cached / stale 字段）

        Raises:
            RuntimeError: 所有数据源及 stale 缓存均失败
        """
        # 1. 读缓存
        cache_key = QuoteCache.build_key(symbol, source=f"quote:{prefer}") if prefer else QuoteCache.build_key(symbol)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            cached = self._enrich_quote_freshness(
                dict(cached),
                cached=True,
                stale_cache=False,
                max_age_seconds=max_age_seconds,
            )
            if not require_fresh or cached.get("quote_actionability") == "trade_draft":
                return cached

        # 2. 按优先级尝试各数据源
        priority = self._get_priority(symbol, prefer)
        last_error = ""
        realtime_error: QuoteFreshnessError | None = None
        first_source = priority[0] if priority else None

        for source in priority:
            adapter = self._adapters.get(source)
            if adapter is None:
                continue
            try:
                quote = await adapter.fetch_quote(symbol)
                # 复制后再添加元数据，避免副作用
                quote = dict(quote)
                quote["source_fallback"] = source != first_source
                quote = self._enrich_quote_freshness(
                    quote,
                    cached=False,
                    stale_cache=False,
                    max_age_seconds=max_age_seconds,
                )
                self._raise_if_realtime_required(symbol, quote, require_fresh=require_fresh)
                # 写入缓存后返回
                await self._cache.set(cache_key, quote, ttl=60)
                await self.record_source_health(source, success=True)
                return quote
            except Exception as exc:
                if isinstance(exc, QuoteFreshnessError):
                    realtime_error = exc
                last_error = f"{source}: {exc}"
                await self.record_source_health(source, success=False, error=str(exc))
                continue

        # 3. 所有数据源失败，尝试 stale 缓存兜底
        stale_data, is_stale = await self._cache.get_with_stale(cache_key)
        if stale_data is not None:
            stale_data = dict(stale_data)
            stale_data = self._enrich_quote_freshness(
                stale_data,
                cached=True,
                stale_cache=True,
                max_age_seconds=max_age_seconds,
            )
            stale_data["source"] = stale_data.get("source", "unknown") + "_stale"
            self._raise_if_realtime_required(symbol, stale_data, require_fresh=require_fresh)
            return stale_data

        if require_fresh and realtime_error is not None:
            raise realtime_error
        raise RuntimeError(f"All data sources failed for {symbol}. Last error: {last_error}")

    async def fetch_batch_quotes(
        self,
        symbols: List[str],
        prefer: Optional[str] = None,
        *,
        require_fresh: bool = False,
        max_age_seconds: Optional[int] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        批量获取行情。

        先批量读缓存，未命中的 symbol 再并发请求数据源。

        Args:
            symbols: 业务层股票代码列表
            prefer:  强制指定数据源，可选
            require_fresh: 是否要求每条结果都满足实时行情策略
            max_age_seconds: 调用方指定的最大行情年龄

        Returns:
            {业务层 symbol: 标准化行情字典} 的映射，失败的 symbol 不包含在内
        """
        results: Dict[str, Dict[str, Any]] = {}
        uncached: List[str] = []

        # 批量读缓存
        for sym in symbols:
            cache_key = QuoteCache.build_key(sym, source=f"quote:{prefer}") if prefer else QuoteCache.build_key(sym)
            cached = await self._cache.get(cache_key)
            if cached is not None:
                enriched = self._enrich_quote_freshness(
                    dict(cached),
                    cached=True,
                    stale_cache=False,
                    max_age_seconds=max_age_seconds,
                )
                if require_fresh and enriched.get("quote_actionability") != "trade_draft":
                    uncached.append(sym)
                else:
                    results[sym] = enriched
            else:
                uncached.append(sym)

        # 并发请求未命中缓存的 symbol
        async def _fetch_one(sym: str):
            try:
                quote = await self.get_quote(
                    sym,
                    prefer=prefer,
                    require_fresh=require_fresh,
                    max_age_seconds=max_age_seconds,
                )
                return sym, quote
            except Exception:
                return sym, None

        if uncached:
            tasks = [_fetch_one(sym) for sym in uncached]
            completed = await asyncio.gather(*tasks, return_exceptions=True)
            for item in completed:
                if isinstance(item, Exception):
                    continue
                sym, quote = item
                if quote is not None:
                    results[sym] = quote

        return results

    def _enrich_quote_freshness(
        self,
        quote: Dict[str, Any],
        *,
        cached: bool,
        stale_cache: bool,
        max_age_seconds: Optional[int],
    ) -> Dict[str, Any]:
        resolved_max_age = max_age_seconds or self._default_realtime_quote_max_age_seconds()
        analysis_max_age = self._default_analysis_quote_max_age_seconds(resolved_max_age)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        quote_ts = self._quote_timestamp(quote)
        reasons: list[str] = []

        quote["cached"] = cached
        quote["stale"] = stale_cache
        quote["max_age_seconds"] = resolved_max_age
        quote["analysis_max_age_seconds"] = analysis_max_age

        if quote_ts is None:
            quote["freshness_seconds"] = None
            quote["freshness_status"] = "missing_timestamp"
            quote["quote_actionability"] = "analysis_only"
            quote["freshness_reasons"] = ["missing_timestamp"]
            return quote

        age_seconds = max(0, now_ts - quote_ts)
        quote["timestamp"] = quote_ts
        quote["freshness_seconds"] = age_seconds

        source_tier = str(quote.get("source_tier") or "unknown")
        if source_tier != "L1_trading":
            reasons.append(f"source_tier:{source_tier}")

        if stale_cache:
            reasons.append("stale_cache_fallback")

        if age_seconds <= resolved_max_age and not stale_cache:
            status = "fresh"
            actionability = "trade_draft" if source_tier == "L1_trading" else "analysis_only"
        elif age_seconds <= analysis_max_age:
            status = "stale"
            actionability = "analysis_only"
            reasons.append(f"stale:{age_seconds}s>{resolved_max_age}s")
        else:
            status = "expired"
            actionability = "blocked"
            reasons.append(f"expired:{age_seconds}s>{analysis_max_age}s")

        quote["freshness_status"] = status
        quote["quote_actionability"] = actionability
        quote["freshness_reasons"] = sorted(set(reasons))
        return quote

    @staticmethod
    def _raise_if_realtime_required(
        symbol: str,
        quote: Dict[str, Any],
        *,
        require_fresh: bool,
    ) -> None:
        if not require_fresh:
            return
        if quote.get("quote_actionability") == "trade_draft":
            return
        raise QuoteFreshnessError(
            f"Realtime quote required for {symbol}, got "
            f"{quote.get('freshness_status')} age={quote.get('freshness_seconds')}s "
            f"max={quote.get('max_age_seconds')}s reasons={quote.get('freshness_reasons')}"
        )

    @staticmethod
    def _quote_timestamp(quote: Dict[str, Any]) -> Optional[int]:
        value = quote.get("timestamp") or quote.get("updated_at") or quote.get("as_of")
        if isinstance(value, (int, float)):
            return int(value if value < 1e11 else value / 1000)
        if isinstance(value, str):
            try:
                return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
            except ValueError:
                return None
        if isinstance(value, datetime):
            return int(value.timestamp())
        return None

    @staticmethod
    def _default_realtime_quote_max_age_seconds() -> int:
        return _positive_int_env("REALTIME_QUOTE_MAX_AGE_SECONDS", 60)

    @staticmethod
    def _default_analysis_quote_max_age_seconds(realtime_max_age_seconds: int) -> int:
        return max(
            realtime_max_age_seconds,
            _positive_int_env("ANALYSIS_QUOTE_MAX_AGE_SECONDS", 15 * 60),
        )

    async def search_symbols(self, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        搜索股票代码。

        优先使用 Yahoo Finance 搜索，失败返回空列表。
        """
        try:
            return await self._adapters["yahoo"].search_symbols(keyword, market=market)
        except Exception:
            return []

    async def record_source_health(self, source: str, success: bool, error: str = "") -> None:
        """
        记录数据源健康状态。

        当前仅打印日志，后续可扩展为写入数据库或时序存储。

        Args:
            source:  数据源标识（如 "yahoo" / "stooq" / "longbridge"）
            success: 本次请求是否成功
            error:   失败时的错误信息
        """
        status_str = "OK" if success else "FAIL"
        print(f"[DataSourceHealth] source={source} status={status_str} error={error}")

    async def health_check(self) -> Dict[str, bool]:
        """
        检测各数据源可用性。

        对每个数据源并行尝试一次真实请求，返回布尔状态映射。
        """
        async def _check_one(name: str, sym: str) -> tuple[str, bool]:
            try:
                await self._adapters[name].fetch_quote(sym)
                return name, True
            except Exception:
                return name, False

        checks = [
            _check_one("yahoo", "AAPL"),
            _check_one("stooq", "AAPL"),
            _check_one("futu", "AAPL"),
            _check_one("tushare", "SH600519"),
            _check_one("ftshare", "SH600519"),
            _check_one("akshare", "SH600519"),
            _check_one("longbridge", "HK00700"),
        ]
        results = await asyncio.gather(*checks)
        return {name: ok for name, ok in results}


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default
