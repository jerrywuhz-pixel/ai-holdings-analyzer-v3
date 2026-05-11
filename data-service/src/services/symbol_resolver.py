"""
Symbol 解析服务

提供用户输入到标准化股票信息的解析与搜索能力：
- resolve_symbol: 精确匹配 / 别名匹配 / 规则推断
- search_symbols: 关键词模糊搜索

所有 Supabase 操作均优雅降级：无客户端或查询失败时返回空结果或基于规则的推断值。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 可选依赖
# ---------------------------------------------------------------------------
try:
    from supabase import create_client

    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass
class SymbolInfo:
    """标准化股票信息。"""

    symbol: str
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    market: str = ""
    exchange: str = ""
    provider_symbols: Dict[str, str] = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------
def _get_supabase_client() -> Optional[Any]:
    """尝试从环境变量创建 Supabase 客户端，失败时返回 None。"""
    if not SUPABASE_AVAILABLE:
        return None

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None

    try:
        return create_client(url, key)
    except Exception:
        return None


def _execute_sync(builder: Any) -> Any:
    """在后台线程中执行同步 Supabase 查询，避免阻塞事件循环。"""
    return builder.execute()


def _row_to_symbol_info(row: Dict[str, Any]) -> SymbolInfo:
    """将 symbol_registry 行数据转换为 SymbolInfo。"""
    return SymbolInfo(
        symbol=row["symbol"],
        name_zh=row.get("name_zh"),
        name_en=row.get("name_en"),
        market=row.get("market", ""),
        exchange=row.get("exchange", ""),
        provider_symbols=row.get("provider_symbols") or {},
        aliases=row.get("aliases") or [],
    )


def _infer_symbol_info(query: str) -> Optional[SymbolInfo]:
    """
    基于规则推断股票信息（无需数据库）。

    规则：
        - 6 位数字且以 0/3/6 开头 -> A 股
        - 5 位数字                  -> 港股
        - 纯字母                    -> 美股
    """
    if query.isdigit():
        # A 股：6 位数字
        if len(query) == 6:
            if query.startswith(("0", "3")):
                symbol = f"SZ{query}"
                exchange = "SZ"
                yahoo_suffix = ".SZ"
            elif query.startswith("6"):
                symbol = f"SH{query}"
                exchange = "SH"
                yahoo_suffix = ".SS"
            else:
                return None

            return SymbolInfo(
                symbol=symbol,
                market="CN",
                exchange=exchange,
                provider_symbols={
                    "tushare": f"{query}.{exchange}",
                    "yahoo": f"{query}{yahoo_suffix}",
                    "akshare": query,
                },
                aliases=[],
            )

        # 港股：5 位数字
        if len(query) == 5:
            symbol = f"HK{query}"
            yahoo_code = str(int(query)).zfill(4)
            return SymbolInfo(
                symbol=symbol,
                market="HK",
                exchange="HKEX",
                provider_symbols={
                    "yahoo": f"{yahoo_code}.HK",
                    "longbridge": f"{int(query)}.HK",
                },
                aliases=[],
            )

    # 美股：纯字母
    if query.isalpha():
        return SymbolInfo(
            symbol=query,
            market="US",
            exchange="NASDAQ",
            provider_symbols={"yahoo": query},
            aliases=[query],
        )

    return None


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------
async def resolve_symbol(
    user_input: str, supabase_client: Optional[Any] = None
) -> Optional[SymbolInfo]:
    """
    将用户输入解析为标准化 SymbolInfo。

    解析优先级：
        1. 精确匹配 symbol_registry.symbol
        2. 别名匹配 symbol_registry.aliases
        3. 基于输入格式的规则推断

    Args:
        user_input:     用户输入，如 "600519"、"贵州茅台"、"AAPL"
        supabase_client: 外部传入的 Supabase 客户端（可选）

    Returns:
        SymbolInfo 或 None（无法解析）
    """
    query = user_input.strip().upper()
    if not query:
        return None

    client = supabase_client or _get_supabase_client()

    # 1) 精确匹配 symbol
    if client is not None:
        try:
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("symbol_registry").select("*").eq("symbol", query),
            )
            if resp.data:
                return _row_to_symbol_info(resp.data[0])
        except Exception:
            pass

    # 2) 别名匹配（数组 contains）
    if client is not None:
        try:
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("symbol_registry").select("*").contains("aliases", [query]),
            )
            if resp.data:
                return _row_to_symbol_info(resp.data[0])
        except Exception:
            pass

    # 3) 规则推断（无数据库也可使用）
    return _infer_symbol_info(query)


async def search_symbols(
    keyword: str,
    supabase_client: Optional[Any] = None,
    limit: int = 20,
) -> List[SymbolInfo]:
    """
    在 symbol_registry 中执行关键词模糊搜索。

    Args:
        keyword: 搜索关键词
        supabase_client: 外部传入的 Supabase 客户端（可选）
        limit:   最大返回条数

    Returns:
        SymbolInfo 列表（无结果时返回空列表）
    """
    client = supabase_client or _get_supabase_client()
    if client is None:
        return []

    kw = keyword.strip()
    if not kw:
        return []

    results: List[SymbolInfo] = []
    seen: set[str] = set()

    try:
        # --- 查询 1：对 symbol / name_zh / name_en 做 ILIKE ---
        or_filter = (
            f'"symbol.ilike.%{kw}%",'
            f'"name_zh.ilike.%{kw}%",'
            f'"name_en.ilike.%{kw}%"'
        )
        resp_text = await asyncio.to_thread(
            _execute_sync,
            client.table("symbol_registry").select("*").or_(or_filter).limit(limit),
        )

        for row in resp_text.data:
            sym = row["symbol"]
            if sym not in seen:
                seen.add(sym)
                results.append(_row_to_symbol_info(row))
    except Exception:
        pass

    # --- 查询 2：对 aliases 数组做 ILIKE（转为 text）---
    remaining = limit - len(results)
    if remaining > 0:
        try:
            resp_alias = await asyncio.to_thread(
                _execute_sync,
                client.table("symbol_registry").select("*").ilike("aliases::text", f"%{kw}%").limit(remaining),
            )
            for row in resp_alias.data:
                sym = row["symbol"]
                if sym not in seen:
                    seen.add(sym)
                    results.append(_row_to_symbol_info(row))
        except Exception:
            pass

    return results
