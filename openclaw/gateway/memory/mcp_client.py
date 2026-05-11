"""
MCP Client — 管理 gbrain MCP 子进程的 Python 客户端

通过 stdin/stdout JSON-RPC 2.0 与 gbrain MCP Server 通信。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class MCPClientError(RuntimeError):
    """MCP 通信错误"""


class MCPClient:
    """
    管理 gbrain MCP 子进程，提供异步 call_tool 接口。

    兼容两种初始化方式：
    - 当前接口：`MCPClient(command="bun", args=[...])`
    - 旧接口：`MCPClient(adapter_path="...", runtime="bun")`
    """

    supports_tenant_scoped_tools = True

    def __init__(
        self,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        *,
        adapter_path: str | None = None,
        runtime: str | None = None,
        request_timeout: float = 30.0,
    ):
        self._command = command or runtime or "bun"
        self._args = list(args) if args is not None else self._default_args(adapter_path)
        self._env = env or {}
        self._request_timeout = request_timeout

        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._buffered_responses: dict[int, dict[str, Any]] = {}
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._started = False
        self._initialized = False

    @staticmethod
    def _default_args(adapter_path: str | None) -> list[str]:
        return ["run", adapter_path or "./gbrain/src/mcp-adapter.ts"]

    async def start(self) -> None:
        """启动 MCP 子进程并进行 initialize 握手"""
        if self._started:
            return

        env = {**os.environ, **self._env}
        env.pop("PYTHONPATH", None)

        self._process = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_reader())

        try:
            await self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "openclaw-gateway", "version": "0.1.0"},
                },
            )
        except Exception as exc:
            logger.error("[mcp_client] Initialize handshake failed: %s", exc)
            await self.stop()
            raise MCPClientError(f"Initialize failed: {exc}") from exc

        self._started = True
        self._initialized = True
        logger.info("[mcp_client] MCP subprocess started and initialized")

    async def stop(self) -> None:
        """优雅关闭子进程"""
        self._started = False
        self._initialized = False

        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._process and self._process_is_running():
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

        for future in self._pending.values():
            if not future.done():
                future.set_exception(MCPClientError("Client shutting down"))
        self._pending.clear()
        self._buffered_responses.clear()

        self._reader_task = None
        self._stderr_task = None
        self._process = None
        logger.info("[mcp_client] MCP subprocess stopped")

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用 MCP tool，返回解析后的结果"""
        if not self._started:
            raise MCPClientError("Client not started")

        result = await self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments or {},
            },
        )

        content = result.get("content", [])
        if not content:
            return result

        for item in content:
            if item.get("type") != "text":
                continue
            text = item.get("text", "")
            if not text:
                return {}
            try:
                parsed = json.loads(text)
            except (TypeError, json.JSONDecodeError):
                return {"raw": text}
            return parsed if isinstance(parsed, dict) else {"results": parsed}

        return result

    async def health_check(self) -> dict[str, Any]:
        """检查 MCP Server 是否可用"""
        try:
            return await asyncio.wait_for(self.call_tool("health", {}), timeout=5.0)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        buffered = self._buffered_responses.pop(request_id, None)
        if buffered is not None:
            self._fulfill_request(request_id, buffered)

        payload = json.dumps(message) + "\n"
        if not self._process or not self._process.stdin:
            self._pending.pop(request_id, None)
            raise MCPClientError("MCP process stdin unavailable")

        self._process.stdin.write(payload.encode("utf-8"))
        await self._maybe_await(getattr(self._process.stdin, "drain", None))

        try:
            result = await asyncio.wait_for(future, timeout=self._request_timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise MCPClientError(f"Request {method} timed out") from exc

        return result

    async def _read_loop(self) -> None:
        if not self._process or not self._process.stdout:
            return

        try:
            while True:
                raw_line = await self._maybe_await(self._process.stdout.readline)
                if not raw_line:
                    break
                if not isinstance(raw_line, (bytes, str)):
                    break

                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", errors="replace").strip()
                else:
                    line = str(raw_line).strip()
                if not line:
                    continue

                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("[mcp_client] Non-JSON on stdout: %s", line[:100])
                    continue

                request_id = message.get("id")
                if request_id is None:
                    logger.debug("[mcp_client] Notification: %s", message.get("method"))
                    continue

                future = self._pending.get(request_id)
                if not future or future.done():
                    self._buffered_responses[request_id] = message
                    continue
                self._fulfill_request(request_id, message)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("[mcp_client] Read loop error: %s", exc)
        finally:
            if self._pending:
                error = MCPClientError("MCP transport closed")
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(error)
                self._pending.clear()

    async def _stderr_reader(self) -> None:
        if not self._process or not self._process.stderr:
            return

        try:
            while True:
                raw_line = await self._maybe_await(self._process.stderr.readline)
                if not raw_line:
                    break
                if not isinstance(raw_line, (bytes, str)):
                    break

                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", errors="replace").strip()
                else:
                    line = str(raw_line).strip()
                if line:
                    logger.debug("[gbrain-stderr] %s", line)
        except asyncio.CancelledError:
            pass

    async def _maybe_await(self, value: Any) -> Any:
        if callable(value):
            value = value()
        if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
            return await value
        return value

    def _fulfill_request(self, request_id: int, message: dict[str, Any]) -> None:
        future = self._pending.pop(request_id, None)
        if not future or future.done():
            return
        if "error" in message:
            error = message["error"]
            future.set_exception(
                MCPClientError(
                    f"MCP tool error: {error.get('message', 'unknown error')}"
                )
            )
            return
        future.set_result(message.get("result", {}))

    def _process_is_running(self) -> bool:
        if not self._process:
            return False
        returncode = getattr(self._process, "returncode", None)
        if isinstance(returncode, int):
            return False
        poll = getattr(self._process, "poll", None)
        if callable(poll):
            return poll() is None
        return True
