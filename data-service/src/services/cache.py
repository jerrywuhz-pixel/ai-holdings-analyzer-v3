"""
Redis 缓存服务

为行情数据提供基于 Redis 的读写缓存，支持 TTL 过期。
连接失败时静默降级，不阻塞业务主流程。
"""

import json
import os
from typing import Any, Dict, Optional

import redis.asyncio as redis


class QuoteCache:
    """
    行情数据 Redis 缓存封装。

    使用 redis.asyncio 实现非阻塞读写，所有异常均被捕获并降级为
    None（读）或静默跳过（写），确保数据源直连可用。
    """

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._client: Optional[redis.Redis] = None

    async def _get_client(self) -> Optional[redis.Redis]:
        """惰性初始化 Redis 连接，失败时返回 None。"""
        if self._client is None:
            try:
                self._client = redis.from_url(self._redis_url, decode_responses=True)
                await self._client.ping()
            except Exception:
                self._client = None
        return self._client

    async def get(self, key: str) -> Optional[dict]:
        """
        从 Redis 读取 JSON 数据。

        Args:
            key: 缓存键

        Returns:
            反序列化后的字典，或 None（键不存在 / 连接失败）
        """
        client = await self._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            return None

    async def set(self, key: str, value: dict, ttl: int = 60) -> None:
        """
        向 Redis 写入 JSON 数据并设置 TTL。

        同时写入一份 stale 副本，TTL 为 7 天，用于所有数据源失败时的兜底返回。

        Args:
            key:   缓存键
            value: 要缓存的字典
            ttl:   过期时间（秒），默认 60 秒
        """
        client = await self._get_client()
        if client is None:
            return
        try:
            await client.setex(key, ttl, json.dumps(value))
        except Exception:
            pass
        # 写入 stale 副本（静默失败不影响主流程）
        await self._write_stale(key, value)

    async def _write_stale(self, key: str, value: dict) -> None:
        """
        写入 stale 缓存副本，TTL 7 天。
        """
        client = await self._get_client()
        if client is None:
            return
        try:
            stale_key = f"{key}:stale"
            await client.setex(stale_key, 7 * 24 * 60 * 60, json.dumps(value))
        except Exception:
            pass

    async def get_with_stale(self, key: str, ttl: int = 60) -> tuple[Optional[dict], bool]:
        """
        读取缓存，优先返回新鲜数据；若缺失则尝试返回 stale 数据。

        Args:
            key: 缓存键
            ttl: 新鲜数据 TTL（仅用于 get 语义，实际过期由 Redis 维护）

        Returns:
            (data, is_stale) 元组。data 为 None 表示新鲜和 stale 均缺失。
        """
        # 1. 尝试新鲜数据
        fresh = await self.get(key)
        if fresh is not None:
            return fresh, False

        # 2. 尝试 stale 数据
        client = await self._get_client()
        if client is None:
            return None, False
        try:
            stale_key = f"{key}:stale"
            raw = await client.get(stale_key)
            if raw is not None:
                return json.loads(raw), True
        except Exception:
            pass

        return None, False

    async def delete(self, key: str) -> None:
        """删除指定缓存键。"""
        client = await self._get_client()
        if client is None:
            return
        try:
            await client.delete(key)
        except Exception:
            pass

    @staticmethod
    def build_key(symbol: str, source: str = "quote") -> str:
        """
        生成标准化缓存键。

        Args:
            symbol: 业务层股票代码，如 "SH600519"
            source: 数据类别标识，默认 "quote"

        Returns:
            格式如 "quote:SH600519"
        """
        return f"{source}:{symbol.upper()}"
