"""
MCPClient 单元测试
"""
from __future__ import annotations

import asyncio
import json
import sys
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.gateway.memory.mcp_client import MCPClient


class TestMCPClient:
    """测试 MCPClient 的核心功能"""

    @pytest.fixture
    def client(self):
        return MCPClient(
            adapter_path="./gbrain/src/mcp-adapter.ts",
            runtime="bun",
        )

    @pytest.mark.asyncio
    async def test_start_initializes_subprocess(self, client):
        """测试 start() 正确启动子进程并发送 initialize 请求"""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.poll = MagicMock(return_value=None)

        # 模拟 stdout 返回 initialize 响应
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}}
        }
        mock_proc.stdout.readline = MagicMock(side_effect=[
            json.dumps(init_response) + "\n",
        ])

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await client.start()

        assert client._process is mock_proc
        assert client._initialized is True

    @pytest.mark.asyncio
    async def test_call_tool_sends_request(self, client):
        """测试 call_tool 发送正确格式的 JSON-RPC 请求"""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.poll = MagicMock(return_value=None)

        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}}
        }
        tool_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": "{\"ok\": true}"}]
            }
        }
        mock_proc.stdout.readline = MagicMock(side_effect=[
            json.dumps(init_response) + "\n",
            json.dumps(tool_response) + "\n",
        ])

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await client.start()
            result = await client.call_tool("health", {})

        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_call_tool_handles_error(self, client):
        """测试 call_tool 正确处理错误响应"""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.poll = MagicMock(return_value=None)

        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}}
        }
        error_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32602, "message": "Invalid params"}
        }
        mock_proc.stdout.readline = MagicMock(side_effect=[
            json.dumps(init_response) + "\n",
            json.dumps(error_response) + "\n",
        ])

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await client.start()
            with pytest.raises(RuntimeError, match="MCP tool error"):
                await client.call_tool("upsert_page", {"invalid": "data"})

    @pytest.mark.asyncio
    async def test_stop_terminates_gracefully(self, client):
        """测试 stop() 优雅终止子进程"""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.poll = MagicMock(return_value=None)
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}}
        }
        mock_proc.stdout.readline = MagicMock(side_effect=[
            json.dumps(init_response) + "\n",
        ])

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await client.start()
            await client.stop()

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """测试 health_check 返回正确状态"""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.poll = MagicMock(return_value=None)

        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}}
        }
        health_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": "{\"status\":\"ok\"}"}]
            }
        }
        mock_proc.stdout.readline = MagicMock(side_effect=[
            json.dumps(init_response) + "\n",
            json.dumps(health_response) + "\n",
        ])

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await client.start()
            health = await client.health_check()

        assert health == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_call_tool_timeout(self, client):
        """测试 call_tool 超时处理"""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.poll = MagicMock(return_value=None)

        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}}
        }
        # 只返回 init，不返回 tool 响应 → 超时
        mock_proc.stdout.readline = MagicMock(side_effect=[
            json.dumps(init_response) + "\n",
            asyncio.TimeoutError,
        ])

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await client.start()
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    client.call_tool("search", {"q": "test"}),
                    timeout=0.1,
                )
