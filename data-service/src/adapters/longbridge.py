"""
Longbridge 数据源适配器（港股实时行情）

通过 Longbridge OpenAPI 获取港股实时行情，
并提供业务层 symbol 与 Longbridge 格式的自动映射。

注意：longbridge 不在 requirements.txt 中，使用前需单独安装：
    pip install longbridge
若未安装，所有方法将抛出 RuntimeError("longbridge SDK not installed")。
"""

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

from adapters.base import DataSourceAdapter

try:
    from longbridge.openapi import Config, QuoteContext
    _HAS_LONGBRIDGE = True
except ImportError:
    _HAS_LONGBRIDGE = False


def to_longbridge_symbol(symbol: str) -> str:
    """
    将业务层 symbol 转换为 Longbridge 格式。

    规则：
        - HK00700 -> 700.HK（去掉 HK 前缀，追加 .HK）
        - 其他市场保持原样（Longbridge 主要支持港股）
    """
    s = symbol.strip().upper()
    if s.startswith("HK"):
        return f"{s[2:]}.HK"
    return s


def to_business_symbol(lb_symbol: str) -> str:
    """
    将 Longbridge symbol 反向映射为业务层统一格式。

    规则：
        - 700.HK -> HK00700（补齐前导零至 5 位）
        - 其他保持原样
    """
    lb = lb_symbol.strip().upper()
    if lb.endswith(".HK"):
        code = lb[:-3]
        return f"HK{code.zfill(5)}"
    return lb


def _normalize_quote(lb_symbol: str, quote: Any) -> Dict[str, Any]:
    """
    将 Longbridge QuoteContext 返回的 Quote 对象转换为标准化行情字典。
    """
    # Longbridge SDK 返回的对象通常包含以下属性：
    # symbol, name, last_done, change, change_rate, timestamp 等
    # 由于 SDK 类型可能变化，使用 getattr 安全访问
    price = getattr(quote, "last_done", None)
    change = getattr(quote, "change", None)
    change_rate = getattr(quote, "change_rate", None)
    name = getattr(quote, "name", "") or ""
    timestamp = getattr(quote, "timestamp", None)

    # 处理时间戳
    ts = int(time.time())
    if isinstance(timestamp, (int, float)):
        ts = int(timestamp) if timestamp < 1e11 else int(timestamp / 1000)

    return {
        "symbol": to_business_symbol(lb_symbol),
        "name": name,
        "market": "HK",
        "exchange": "HKEX",
        "price": round(float(price), 4) if price is not None else None,
        "change": round(float(change), 4) if change is not None else None,
        "change_rate": round(float(change_rate), 2) if change_rate is not None else None,
        "currency": "HKD",
        "timestamp": ts,
    }


class LongbridgeAdapter(DataSourceAdapter):
    """Longbridge OpenAPI 数据源适配器实现（港股为主）。"""

    def __init__(self):
        self._available = _HAS_LONGBRIDGE
        if not self._available:
            return

        self._app_key = os.getenv("LONGBRIDGE_APP_KEY")
        self._app_secret = os.getenv("LONGBRIDGE_APP_SECRET")
        self._access_token = os.getenv("LONGBRIDGE_ACCESS_TOKEN")

        if not self._app_key or not self._app_secret or not self._access_token:
            self._available = False
            return

        self._config = Config(
            app_key=self._app_key,
            app_secret=self._app_secret,
            access_token=self._access_token,
        )
        self._ctx: Optional[Any] = None

    def _get_context(self) -> Any:
        """惰性初始化 QuoteContext。"""
        if self._ctx is None:
            self._ctx = QuoteContext(self._config)
        return self._ctx

    async def fetch_quote(self, symbol: str) -> Dict[str, Any]:
        """
        获取单只股票实时行情。

        Args:
            symbol: 业务层代码，如 "HK00700"

        Returns:
            标准化行情字典

        Raises:
            RuntimeError: SDK 未安装、未配置或请求失败
        """
        if not self._available:
            raise RuntimeError("longbridge SDK not installed")

        lb_sym = to_longbridge_symbol(symbol)

        # Longbridge SDK 是同步库，使用 asyncio.to_thread 包装
        ctx = self._get_context()
        quotes = await asyncio.to_thread(ctx.quote, lb_sym)

        if not quotes:
            raise RuntimeError(f"No quote returned for {lb_sym}")

        quote = quotes[0] if isinstance(quotes, list) else quotes
        return _normalize_quote(lb_sym, quote)

    async def fetch_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量获取行情。

        使用 asyncio.gather 并发获取，并对失败项进行优雅降级。

        Returns:
            {业务层 symbol: 标准化字典} 的映射，失败的 symbol 不包含在结果中。
        """
        if not self._available:
            raise RuntimeError("longbridge SDK not installed")

        results: Dict[str, Dict[str, Any]] = {}
        semaphore = asyncio.Semaphore(5)

        async def _fetch_one(sym: str):
            async with semaphore:
                try:
                    quote = await self.fetch_quote(sym)
                    return sym, quote
                except Exception:
                    return sym, None

        tasks = [_fetch_one(sym) for sym in symbols]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, Exception):
                continue
            sym, quote = item
            if quote is not None:
                results[sym] = quote

        return results

    async def search_symbols(self, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        根据关键词搜索股票代码。

        Longbridge OpenAPI 暂无标准搜索接口，暂返回空列表
        或根据 keyword 做简单的港股代码过滤。
        """
        return []
