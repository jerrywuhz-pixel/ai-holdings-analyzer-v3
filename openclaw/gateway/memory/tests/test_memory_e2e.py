"""
MemoryMiddleware 端到端测试

验证 Skill 完成后的完整记忆写入流程：
trade-input → SignalDetector → SyncQueue → BrainOps → MCPClient
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.gateway.memory.brain_ops import BrainOps
from openclaw.gateway.memory.memory_middleware import MemoryMiddleware
from openclaw.gateway.memory.signal_detector import SignalDetector
from openclaw.gateway.memory.sync_queue import SyncQueue


class TestMemoryMiddlewareE2E:
    """测试 MemoryMiddleware 的完整集成流程"""

    @pytest.fixture
    def mock_brain_ops(self):
        """创建模拟的 BrainOps"""
        ops = MagicMock(spec=BrainOps)
        ops.ensure_source = AsyncMock(return_value="src-test")
        ops.upsert_page = AsyncMock(return_value={"id": "page-1"})
        ops.add_timeline_entry = AsyncMock(return_value={"id": "tl-1"})
        ops.create_link = AsyncMock(return_value={"id": "link-1"})
        ops.get_page = AsyncMock(return_value={
            "id": "page-2",
            "title": "贵州茅台",
            "content": "compiled",
        })
        ops.get_page_context = AsyncMock(return_value={
            "page": {"title": "portfolio"},
            "timeline": [],
            "links_outgoing": [
                {"target_path": "stocks/600519.SH", "link_type": "HOLDS"}
            ],
        })
        ops.search = AsyncMock(return_value=[
            {"path": "insights/daily-2024-01-15", "title": "日终分析"}
        ])
        return ops

    @pytest.fixture
    def middleware(self, mock_brain_ops):
        """创建 MemoryMiddleware 实例"""
        detector = SignalDetector()
        queue = SyncQueue(brain_ops=mock_brain_ops)
        return MemoryMiddleware(
            brain_ops=mock_brain_ops,
            signal_detector=detector,
            sync_queue=queue,
        )

    @pytest.mark.asyncio
    async def test_trade_input_to_brain(self, middleware, mock_brain_ops):
        """测试 trade-input Skill 完成后写入 brain"""
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
                    }
                ]
            }
        }

        await middleware.on_skill_complete(
            skill_name="trade-input",
            tenant_id="tenant-abc",
            skill_output=skill_output,
        )

        # 等待队列消费
        await middleware._sync_queue.stop_consumer()

        # 验证 BrainOps 被调用
        mock_brain_ops.upsert_page.assert_called()
        mock_brain_ops.add_timeline_entry.assert_called()
        mock_brain_ops.create_link.assert_called()

    @pytest.mark.asyncio
    async def test_analysis_complete_to_brain(self, middleware, mock_brain_ops):
        """测试 daily-analysis Skill 完成后写入 brain"""
        skill_output = {
            "data": {
                "analysis_id": "da-1",
                "analysis_date": "2024-01-15",
                "sentiment": "积极",
                "symbols": ["600519.SH"],
                "insights": ["茅台业绩超预期"],
                "formatted_markdown": "## 分析\n...",
            }
        }

        await middleware.on_skill_complete(
            skill_name="daily-analysis",
            tenant_id="tenant-abc",
            skill_output=skill_output,
        )

        await middleware._sync_queue.stop_consumer()

        mock_brain_ops.upsert_page.assert_called()
        mock_brain_ops.add_timeline_entry.assert_called()
        mock_brain_ops.create_link.assert_called()

    @pytest.mark.asyncio
    async def test_analysis_context_retrieval(self, middleware, mock_brain_ops):
        """测试 daily-analysis 调用前获取记忆上下文"""
        context = await middleware.on_skill_invoke(
            skill_name="daily-analysis",
            tenant_id="tenant-abc",
        )

        assert context is not None
        assert "recent_trades" in context
        assert "position_summary" in context
        assert "past_insights" in context

        # 验证 BrainOps 被调用来获取上下文
        mock_brain_ops.get_page_context.assert_called()
        mock_brain_ops.search.assert_called()

    @pytest.mark.asyncio
    async def test_position_complete_to_brain(self, middleware, mock_brain_ops):
        """测试 position-aggregate Skill 完成后更新 portfolio"""
        skill_output = {
            "data": {
                "positions": [
                    {"symbol": "600519.SH", "quantity": 200, "market_value": 336000},
                ],
                "total_value": 336000,
            }
        }

        await middleware.on_skill_complete(
            skill_name="position-aggregate",
            tenant_id="tenant-abc",
            skill_output=skill_output,
        )

        await middleware._sync_queue.stop_consumer()

        mock_brain_ops.upsert_page.assert_called()
        call_args = mock_brain_ops.upsert_page.call_args
        assert call_args[1]["path"] == "portfolios/tenant-a"
        assert call_args[1]["page_type"] == "portfolio"

    @pytest.mark.asyncio
    async def test_unknown_skill_ignored(self, middleware, mock_brain_ops):
        """测试未知 Skill 不触发记忆操作"""
        await middleware.on_skill_complete(
            skill_name="unknown-skill",
            tenant_id="tenant-abc",
            skill_output={"data": {}},
        )

        await middleware._sync_queue.stop_consumer()

        mock_brain_ops.upsert_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_handling_does_not_propagate(self, middleware, mock_brain_ops):
        """测试记忆操作失败不抛出到上层"""
        mock_brain_ops.upsert_page.side_effect = RuntimeError("DB down")

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
                    }
                ]
            }
        }

        # 不应该抛出异常
        await middleware.on_skill_complete(
            skill_name="trade-input",
            tenant_id="tenant-abc",
            skill_output=skill_output,
        )

        await middleware._sync_queue.stop_consumer()
