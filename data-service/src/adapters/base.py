"""
数据源适配器抽象基类
定义统一的股票行情数据接口，所有具体适配器必须实现以下方法。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class DataSourceAdapter(ABC):
    """
    股票数据源适配器抽象基类。

    所有子类必须实现 fetch_quote、fetch_batch_quotes 和 search_symbols 方法，
    并返回标准化的字典/列表结构，便于上层业务统一处理。
    """

    @abstractmethod
    async def fetch_quote(self, symbol: str) -> Dict[str, Any]:
        """
        获取单只股票的实时行情。

        Args:
            symbol: 股票代码，格式由业务层统一（如 "SH600519"、"AAPL"）

        Returns:
            标准化字典，包含字段：
                - symbol: str       业务层代码
                - name: str         股票名称（如有）
                - market: str       市场标识（如 "CN"、"US"、"HK"）
                - exchange: str     交易所代码（如 "SSE"、"NASDAQ"）
                - price: float      最新价格
                - change: float     涨跌额
                - change_rate: float 涨跌幅（百分比，如 1.25 表示 +1.25%）
                - currency: str     计价货币（如 "CNY"、"USD"）
                - timestamp: int    数据时间戳（Unix epoch，秒级）
        """
        ...

    @abstractmethod
    async def fetch_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量获取多只股票实时行情。

        Args:
            symbols: 股票代码列表

        Returns:
            以 symbol 为键、标准化行情字典为值的映射字典。
            若某只股票获取失败，该键应不存在或包含错误信息。
        """
        ...

    @abstractmethod
    async def search_symbols(self, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        根据关键词搜索股票代码。

        Args:
            keyword: 搜索关键词（股票名称或代码片段）
            market:  可选的市场过滤（如 "CN"、"US"、"HK"）

        Returns:
            匹配结果列表，每个元素为标准化字典，包含字段：
                - symbol: str       业务层代码
                - name: str         股票名称
                - market: str       市场标识
                - exchange: str     交易所
                - type: str         品种类型（如 "EQUITY"、"INDEX"、"ETF"）
        """
        ...
