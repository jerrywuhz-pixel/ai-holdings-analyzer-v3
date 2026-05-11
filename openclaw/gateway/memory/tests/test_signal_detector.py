"""
SignalDetector 单元测试
"""
from __future__ import annotations

import pytest

from openclaw.gateway.memory.signal_detector import (
    SignalDetector,
    TradeSignal,
    AnalysisSignal,
    PositionSignal,
)


class TestSignalDetector:
    """测试信号检测器的各种场景"""

    @pytest.fixture
    def detector(self):
        return SignalDetector()

    def test_detect_trade_signal_buy(self, detector):
        """测试检测买入交易信号"""
        skill_output = {
            "data": {
                "trade_events": [
                    {
                        "id": "te-1",
                        "symbol": "600519",
                        "stock_name": "贵州茅台",
                        "market": "SH",
                        "side": "BUY",
                        "quantity": 100,
                        "price": 1680.0,
                        "trade_date": "2024-01-15",
                        "tags": ["业绩驱动"],
                        "strategy_tag": "价值投资",
                    }
                ]
            }
        }

        signal = detector.detect_trade_signal(skill_output)

        assert isinstance(signal, TradeSignal)
        assert signal.symbol == "600519.SH"
        assert signal.stock_name == "贵州茅台"
        assert signal.side == "BUY"
        assert signal.quantity == 100
        assert signal.price == 1680.0
        assert signal.page_path == "stocks/600519.SH"

    def test_detect_trade_signal_sell(self, detector):
        """测试检测卖出交易信号"""
        skill_output = {
            "data": {
                "trade_events": [
                    {
                        "id": "te-2",
                        "symbol": "300750",
                        "stock_name": "宁德时代",
                        "market": "SZ",
                        "side": "SELL",
                        "quantity": 50,
                        "price": 210.0,
                        "trade_date": "2024-01-15",
                        "tags": ["趋势跟随"],
                    }
                ]
            }
        }

        signal = detector.detect_trade_signal(skill_output)

        assert signal.symbol == "300750.SZ"
        assert signal.side == "SELL"
        assert signal.page_path == "stocks/300750.SZ"

    def test_detect_trade_signal_no_events(self, detector):
        """测试无交易事件时返回 None"""
        skill_output = {"data": {"trade_events": []}}
        assert detector.detect_trade_signal(skill_output) is None

    def test_detect_trade_signal_missing_data(self, detector):
        """测试缺少 data 字段时返回 None"""
        assert detector.detect_trade_signal({}) is None
        assert detector.detect_trade_signal({"data": {}}) is None

    def test_detect_analysis_signal(self, detector):
        """测试检测分析信号"""
        skill_output = {
            "data": {
                "analysis_id": "da-1",
                "analysis_date": "2024-01-15",
                "sentiment": "中性偏多",
                "symbols": ["600519.SH", "300750.SZ"],
                "insights": [
                    "茅台业绩预告超预期，可考虑持仓",
                    "宁德触及压力位，建议减仓",
                ],
                "formatted_markdown": "## 日终分析\n...",
            }
        }

        signal = detector.detect_analysis_signal(skill_output)

        assert isinstance(signal, AnalysisSignal)
        assert signal.analysis_date == "2024-01-15"
        assert signal.sentiment == "中性偏多"
        assert signal.symbols == ["600519.SH", "300750.SZ"]
        assert len(signal.insights) == 2
        assert signal.insight_path == "insights/daily-2024-01-15"

    def test_detect_analysis_signal_with_unnormalized_symbols(self, detector):
        """测试分析信号中的股票代码规范化"""
        skill_output = {
            "data": {
                "analysis_id": "da-2",
                "analysis_date": "2024-01-15",
                "sentiment": "积极",
                "symbols": ["600519", "300750.SZ", "AAPL"],
                "insights": ["看好白酒板块"],
            }
        }

        signal = detector.detect_analysis_signal(skill_output)

        assert "600519.SH" in signal.symbols
        assert "300750.SZ" in signal.symbols
        assert "AAPL" in signal.symbols  # 美股代码保持原样

    def test_detect_position_signal(self, detector):
        """测试检测持仓信号"""
        skill_output = {
            "data": {
                "positions": [
                    {"symbol": "600519.SH", "quantity": 200, "market_value": 336000},
                    {"symbol": "300750.SZ", "quantity": 100, "market_value": 21000},
                ],
                "total_value": 357000,
            }
        }

        signal = detector.detect_position_signal(skill_output)

        assert isinstance(signal, PositionSignal)
        assert signal.symbols == ["600519.SH", "300750.SZ"]
        assert signal.total_value == 357000

    def test_detect_position_signal_empty(self, detector):
        """测试空仓时返回 None"""
        skill_output = {"data": {"positions": [], "total_value": 0}}
        assert detector.detect_position_signal(skill_output) is None

    def test_normalize_symbol(self, detector):
        """测试股票代码规范化"""
        assert detector._normalize_symbol("600519") == "600519.SH"
        assert detector._normalize_symbol("300750") == "300750.SZ"
        assert detector._normalize_symbol("688001") == "688001.SH"
        assert detector._normalize_symbol("600519.SH") == "600519.SH"
        assert detector._normalize_symbol("AAPL") == "AAPL"
        assert detector._normalize_symbol("TSLA") == "TSLA"

    def test_extract_symbols_from_text(self, detector):
        """测试从文本中提取股票代码"""
        text = "分析了贵州茅台(SH600519)和宁德时代(300750.SZ)"
        symbols = detector._extract_symbols_from_text(text)
        assert "600519.SH" in symbols
        assert "300750.SZ" in symbols

    def test_extract_key_points(self, detector):
        """测试从 markdown 中提取要点"""
        markdown = """
1. 茅台业绩超预期
2. 宁德面临压力
3. 建议分散持仓
"""
        points = detector._extract_key_points(markdown)
        assert len(points) == 3
        assert "茅台业绩超预期" in points[0]
