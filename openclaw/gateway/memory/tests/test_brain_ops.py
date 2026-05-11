"""
BrainOps 单元测试
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from openclaw.gateway.memory.brain_ops import BrainOps, BrainOpsError


class TestBrainOps:
    """测试 BrainOps 的域名 API 包装"""

    @pytest.fixture
    def mock_mcp(self):
        mcp = MagicMock()
        mcp.call_tool = AsyncMock()
        mcp.start = AsyncMock()
        return mcp

    @pytest.fixture
    def brain_ops(self, mock_mcp):
        return BrainOps(mcp_client=mock_mcp)

    @pytest.mark.asyncio
    async def test_ensure_source_creates_new(self, mock_mcp, brain_ops):
        """测试 ensure_source 在 source 不存在时创建"""
        mock_mcp.call_tool.side_effect = [
            # search 返回空
            {"results": []},
            # ensure_source 返回新 source
            {"id": "src-123", "name": "tenant-abc"},
        ]

        source_id = await brain_ops.ensure_source("tenant-abc")

        assert source_id == "src-123"
        assert "tenant-abc" in brain_ops._source_cache

    @pytest.mark.asyncio
    async def test_ensure_source_uses_cache(self, mock_mcp, brain_ops):
        """测试 ensure_source 使用缓存避免重复查询"""
        brain_ops._source_cache["tenant-abc"] = "cached-src-id"

        source_id = await brain_ops.ensure_source("tenant-abc")

        assert source_id == "cached-src-id"
        mock_mcp.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_page(self, mock_mcp, brain_ops):
        """测试 upsert_page 正确包装 MCP 调用"""
        brain_ops._source_cache["tenant-abc"] = "src-123"
        mock_mcp.call_tool.return_value = {"id": "page-456", "path": "stocks/600519"}

        result = await brain_ops.upsert_page(
            tenant_id="tenant-abc",
            path="stocks/600519",
            title="贵州茅台",
            content="测试内容",
            page_type="stock",
        )

        mock_mcp.call_tool.assert_called_once()
        call_args = mock_mcp.call_tool.call_args
        assert call_args[0][0] == "upsert_page"
        assert call_args[0][1]["path"] == "stocks/600519"
        assert call_args[0][1]["source_id"] == "src-123"

    @pytest.mark.asyncio
    async def test_get_page(self, mock_mcp, brain_ops):
        """测试 get_page 读取页面"""
        brain_ops._source_cache["tenant-abc"] = "src-123"
        mock_mcp.call_tool.return_value = {
            "id": "page-456",
            "path": "stocks/600519",
            "title": "贵州茅台",
            "content": "compiled truth",
        }

        page = await brain_ops.get_page("tenant-abc", "stocks/600519")

        assert page["title"] == "贵州茅台"
        mock_mcp.call_tool.assert_called_once_with(
            "get_page",
            {"source_id": "src-123", "path": "stocks/600519"},
        )

    @pytest.mark.asyncio
    async def test_search(self, mock_mcp, brain_ops):
        """测试 search 执行混合搜索"""
        brain_ops._source_cache["tenant-abc"] = "src-123"
        mock_mcp.call_tool.return_value = {
            "results": [
                {"path": "stocks/600519", "title": "贵州茅台", "score": 0.95},
                {"path": "stocks/300750", "title": "宁德时代", "score": 0.82},
            ]
        }

        results = await brain_ops.search(
            tenant_id="tenant-abc",
            query="白酒龙头",
            limit=5,
            search_type="hybrid",
        )

        assert len(results) == 2
        assert results[0]["score"] == 0.95
        mock_mcp.call_tool.assert_called_once_with(
            "search",
            {
                "source_id": "src-123",
                "query": "白酒龙头",
                "limit": 5,
                "search_type": "hybrid",
            },
        )

    @pytest.mark.asyncio
    async def test_add_timeline_entry(self, mock_mcp, brain_ops):
        """测试 add_timeline_entry"""
        brain_ops._source_cache["tenant-abc"] = "src-123"
        mock_mcp.call_tool.return_value = {"id": "tl-789"}

        result = await brain_ops.add_timeline_entry(
            tenant_id="tenant-abc",
            path="stocks/600519",
            event_date="2024-01-15",
            event_type="BUY",
            title="买入贵州茅台",
            content="100股 @¥1680",
            importance=7,
        )

        assert result["id"] == "tl-789"
        call_args = mock_mcp.call_tool.call_args
        assert call_args[0][0] == "add_timeline_entry"
        assert call_args[0][1]["event_type"] == "BUY"

    @pytest.mark.asyncio
    async def test_create_link(self, mock_mcp, brain_ops):
        """测试 create_link"""
        brain_ops._source_cache["tenant-abc"] = "src-123"
        mock_mcp.call_tool.return_value = {"id": "link-999"}

        result = await brain_ops.create_link(
            tenant_id="tenant-abc",
            source_path="portfolios/abc",
            target_path="stocks/600519",
            link_type="HOLDS",
            confidence=0.9,
        )

        assert result["id"] == "link-999"
        call_args = mock_mcp.call_tool.call_args
        assert call_args[0][0] == "create_link"
        assert call_args[0][1]["link_type"] == "HOLDS"

    @pytest.mark.asyncio
    async def test_get_page_context(self, mock_mcp, brain_ops):
        """测试 get_page_context 获取完整上下文"""
        brain_ops._source_cache["tenant-abc"] = "src-123"
        mock_mcp.call_tool.return_value = {
            "page": {"id": "page-456", "title": "贵州茅台"},
            "timeline": [{"id": "tl-1", "event_type": "BUY"}],
            "links_outgoing": [{"target_path": "sectors/白酒"}],
            "links_incoming": [],
        }

        ctx = await brain_ops.get_page_context(
            "tenant-abc", "stocks/600519",
            include_timeline=True, include_links=True,
        )

        assert ctx["page"]["title"] == "贵州茅台"
        assert len(ctx["timeline"]) == 1

    @pytest.mark.asyncio
    async def test_brain_ops_error(self, mock_mcp, brain_ops):
        """测试 MCP 错误转换为 BrainOpsError"""
        brain_ops._source_cache["tenant-abc"] = "src-123"
        mock_mcp.call_tool.side_effect = RuntimeError("MCP connection lost")

        with pytest.raises(BrainOpsError):
            await brain_ops.get_page("tenant-abc", "stocks/600519")
