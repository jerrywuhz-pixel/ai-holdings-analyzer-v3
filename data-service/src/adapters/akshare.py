"""
AkShare 数据源适配器

通过 AkShare 获取 A 股 / 美股实时全市场行情，在异步方法中使用
asyncio.to_thread() 包装同步调用，避免阻塞事件循环。

注意：akshare 不在 requirements.txt 中，使用前需单独安装：
    pip install akshare
若未安装，所有方法将抛出 RuntimeError("akshare not installed")。
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

from adapters.base import DataSourceAdapter

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False


def _to_ak_symbol(symbol: str) -> str:
    """
    将业务层 symbol 转换为 AkShare 纯代码格式。

    规则：
        - SH600519 -> 600519
        - SZ000001 -> 000001
        - AAPL     -> AAPL
    """
    s = symbol.strip().upper()
    if s.startswith(("SH", "SZ", "HK")):
        return s[2:]
    return s


def _to_business_symbol(code: str, market: str) -> str:
    """
    将 AkShare 纯代码转换为业务层统一格式（仅对 A 股补充前缀）。

    规则：
        - 600519 + CN -> SH600519
        - 000001 + CN -> SZ000001
        - AAPL   + US -> AAPL
    """
    code = str(code).strip()
    if market == "CN" and len(code) == 6 and code.isdigit():
        if code.startswith(("0", "3")):
            return f"SZ{code}"
        return f"SH{code}"
    return code


def _infer_market(symbol: str) -> str:
    """根据业务层 symbol 前缀推断市场。"""
    s = symbol.strip().upper()
    if s.startswith(("SH", "SZ")):
        return "CN"
    if s.startswith("HK"):
        return "HK"
    return "US"


def _normalize_zh_a_row(row: Any) -> Dict[str, Any]:
    """将 AkShare A 股 spot DataFrame 单行转换为标准化行情字典。"""
    code = str(row["代码"])
    biz_sym = _to_business_symbol(code, "CN")

    price = row.get("最新价")
    change = row.get("涨跌额")
    change_rate = row.get("涨跌幅")
    name = row.get("名称", "")

    return {
        "symbol": biz_sym,
        "name": name,
        "market": "CN",
        "exchange": "SSE" if biz_sym.startswith("SH") else "SZSE",
        "price": float(price) if price is not None else None,
        "change": float(change) if change is not None else None,
        "change_rate": float(change_rate) if change_rate is not None else None,
        "currency": "CNY",
        "timestamp": int(time.time()),
    }


def _normalize_us_row(row: Any) -> Dict[str, Any]:
    """将 AkShare 美股 spot DataFrame 单行转换为标准化行情字典。"""
    code = str(row["代码"])

    price = row.get("最新价")
    change = row.get("涨跌额")
    change_rate = row.get("涨跌幅")
    name = row.get("名称", "")

    return {
        "symbol": code,
        "name": name,
        "market": "US",
        "exchange": "",
        "price": float(price) if price is not None else None,
        "change": float(change) if change is not None else None,
        "change_rate": float(change_rate) if change_rate is not None else None,
        "currency": "USD",
        "timestamp": int(time.time()),
    }


class AkShareAdapter(DataSourceAdapter):
    """AkShare 数据源适配器实现（同步库异步包装）。"""

    def __init__(self):
        pass

    async def fetch_quote(self, symbol: str) -> Dict[str, Any]:
        """
        获取单只股票实时行情。

        通过调用 AkShare 全市场 spot 接口后过滤目标代码。
        A 股使用 stock_zh_a_spot_em()，美股使用 stock_us_spot_em()。

        Args:
            symbol: 业务层代码，如 "SH600519"、"AAPL"

        Returns:
            标准化行情字典

        Raises:
            RuntimeError: akshare 未安装或目标代码未找到
        """
        if not AKSHARE_AVAILABLE:
            raise RuntimeError("akshare not installed")

        market = _infer_market(symbol)
        code = _to_ak_symbol(symbol)

        if market == "CN":
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
            mask = df["代码"].astype(str) == code
            if not mask.any():
                raise RuntimeError(f"Symbol {symbol} not found in AkShare A-share spot data")
            return _normalize_zh_a_row(df[mask].iloc[0])

        if market == "US":
            df = await asyncio.to_thread(ak.stock_us_spot_em)
            mask = df["代码"].astype(str) == code
            if not mask.any():
                raise RuntimeError(f"Symbol {symbol} not found in AkShare US spot data")
            return _normalize_us_row(df[mask].iloc[0])

        raise RuntimeError(f"AkShare spot adapter does not support market {market}")

    async def fetch_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量获取行情。

        按市场分组，每个市场仅调用一次全市场 spot 接口，再批量过滤，
        避免每个 symbol 都重复请求全量数据。
        """
        if not AKSHARE_AVAILABLE:
            raise RuntimeError("akshare not installed")

        # 按市场分组
        cn_codes: List[str] = []
        us_codes: List[str] = []
        for sym in symbols:
            market = _infer_market(sym)
            code = _to_ak_symbol(sym)
            if market == "CN":
                cn_codes.append((sym, code))
            elif market == "US":
                us_codes.append((sym, code))

        results: Dict[str, Dict[str, Any]] = {}

        # A 股批量查询
        if cn_codes:
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
            df["代码"] = df["代码"].astype(str)
            target_codes = {c for _, c in cn_codes}
            matched = df[df["代码"].isin(target_codes)]
            for _, row in matched.iterrows():
                quote = _normalize_zh_a_row(row)
                results[quote["symbol"]] = quote
            # 补回原始传入的 symbol（防止前缀映射后 key 不一致）
            for orig_sym, code in cn_codes:
                biz = _to_business_symbol(code, "CN")
                if biz in results and biz != orig_sym:
                    results[orig_sym] = results.pop(biz)

        # 美股批量查询
        if us_codes:
            df = await asyncio.to_thread(ak.stock_us_spot_em)
            df["代码"] = df["代码"].astype(str)
            target_codes = {c for _, c in us_codes}
            matched = df[df["代码"].isin(target_codes)]
            for _, row in matched.iterrows():
                quote = _normalize_us_row(row)
                results[quote["symbol"]] = quote

        return results

    async def search_symbols(self, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        AkShare 搜索需额外接口调用，暂返回空列表。
        """
        return []
