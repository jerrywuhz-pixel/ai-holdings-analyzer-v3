"""
gbrain Memory Middleware for OpenClaw
======================================

为 OpenClaw Skills 提供持久化知识记忆能力的中间件层。

核心组件：
- MCPClient: 管理 gbrain MCP 子进程的底层通信
- BrainOps: 高级脑操作封装（upsert_page, search, add_timeline 等）
- SignalDetector: 从 Skill 输出中提取结构化实体信号
- SyncQueue: 异步批量写入队列（fire-and-forget）
- MemoryMiddleware: 主编排器，提供 on_skill_complete / on_skill_invoke 钩子
"""

from openclaw.gateway.memory.mcp_client import MCPClient
from openclaw.gateway.memory.brain_ops import BrainOps
from openclaw.gateway.memory.signal_detector import SignalDetector
from openclaw.gateway.memory.sync_queue import SyncQueue
from openclaw.gateway.memory.memory_middleware import MemoryMiddleware

__all__ = [
    "MCPClient",
    "BrainOps",
    "SignalDetector",
    "SyncQueue",
    "MemoryMiddleware",
]
