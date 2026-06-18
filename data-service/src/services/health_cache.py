"""
Health Cache — 数据源健康与 Hermes 心跳缓存

缓存 data_source_health 和 hermes_heartbeat 查询结果，
减少 Supabase 读取次数，提升缓存命中率至 80%+。

缓存策略：
- data_source_health: TTL 60s (源状态变更不频繁)
- hermes_heartbeat: TTL 30s (需要较新的心跳状态)
- 内存 fallback: 无 Redis 时使用进程内缓存
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False

try:
    from supabase import create_client
    _HAS_SUPABASE = True
except ImportError:
    _HAS_SUPABASE = False


class _InMemoryCache:
    """Simple TTL cache for when Redis is unavailable."""

    def __init__(self):
        self._store: dict[str, tuple[float, str]] = {}  # key -> (expires_at, value)

    async def get(self, key: str) -> Optional[str]:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: str, ttl: int) -> None:
        self._store[key] = (time.time() + ttl, value)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


def _execute_sync(builder: Any) -> Any:
    return builder.execute()


class HealthCache:
    """
    健康状态缓存服务。

    缓存 data_source_health 和 hermes_heartbeat 查询结果。
    优先使用 Redis，无 Redis 时降级到进程内缓存。
    """

    DATA_SOURCE_TTL = 60      # seconds
    HEARTBEAT_TTL = 30        # seconds

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis: Optional[Any] = None
        self._memory = _InMemoryCache()
        self._supabase: Optional[Any] = None

    def _get_supabase(self) -> Optional[Any]:
        if self._supabase is None and _HAS_SUPABASE:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            if url and key:
                try:
                    self._supabase = create_client(url, key)
                except Exception:
                    pass
        return self._supabase

    async def _get_redis(self) -> Optional[Any]:
        if self._redis is None and _HAS_REDIS:
            try:
                self._redis = aioredis.from_url(self._redis_url)
            except Exception:
                pass
        return self._redis

    async def get_data_source_health(self) -> list[dict[str, Any]]:
        """获取数据源健康状态（优先缓存）。"""
        cache_key = "health:data_sources"

        # Try cache first
        cached = await self._cache_get(cache_key)
        if cached is not None:
            return json.loads(cached)

        # Fetch from Supabase
        client = self._get_supabase()
        if client is None:
            return []

        try:
            resp = await asyncio.to_thread(
                _execute_sync,
                client.table("data_source_health")
                .select("source_name, status, priority_cn, priority_hk, priority_us")
            )
            data = resp.data or []
            # Cache the result
            await self._cache_set(cache_key, json.dumps(data), self.DATA_SOURCE_TTL)
            return data
        except Exception as exc:
            logger.error("Failed to fetch data source health: %s", exc)
            return []

    async def get_heartbeat(self) -> Optional[dict[str, Any]]:
        """获取最新 Hermes 心跳记录（优先缓存，兼容旧表）。"""
        cache_key = "health:heartbeat"

        cached = await self._cache_get(cache_key)
        if cached is not None:
            data = json.loads(cached)
            return data if data else None

        client = self._get_supabase()
        if client is None:
            return None

        try:
            try:
                resp = await asyncio.to_thread(
                    _execute_sync,
                    client.table("hermes_heartbeat")
                    .select("*")
                    .order("reported_at", desc=True)
                    .limit(1)
                )
            except Exception:
                resp = await asyncio.to_thread(
                    _execute_sync,
                    client.table("openclaw_heartbeat")
                    .select("*")
                    .order("reported_at", desc=True)
                    .limit(1)
                )
            data = resp.data[0] if resp.data else None
            await self._cache_set(cache_key, json.dumps(data or []), self.HEARTBEAT_TTL)
            return data
        except Exception as exc:
            logger.error("Failed to fetch heartbeat: %s", exc)
            return None

    async def get_gateway_status(self) -> dict[str, Any]:
        """
        获取 Hermes runtime 综合状态（用于 /health 端点和前端面板）。

        Returns:
            {
                "gateway": {"status": "healthy"/"down", "last_reported_at": "..."},
                "data_sources": [...],
                "stale_minutes": 15
            }
        """
        heartbeat = await self.get_heartbeat()
        data_sources = await self.get_data_source_health()

        gateway_status = "unknown"
        last_reported = None
        stale_minutes = None

        if heartbeat:
            last_reported = heartbeat.get("reported_at")
            gateway_status = heartbeat.get("hermes_status") or heartbeat.get("gateway_status", "unknown")

            # Check if heartbeat is stale (> 15 minutes)
            if last_reported:
                try:
                    from datetime import datetime, timezone
                    reported = datetime.fromisoformat(
                        str(last_reported).replace("Z", "+00:00")
                    )
                    stale_minutes = (datetime.now(timezone.utc) - reported).total_seconds() / 60

                    if stale_minutes > 15:
                        gateway_status = "down"
                except (ValueError, TypeError):
                    pass

        return {
            "gateway": {
                "status": gateway_status,
                "runtime": "hermes",
                "last_reported_at": last_reported,
                "deployment_mode": heartbeat.get("deployment_mode") if heartbeat else None,
                "active_skills": heartbeat.get("active_skills") if heartbeat else [],
            },
            "data_sources": data_sources,
            "stale_minutes": round(stale_minutes, 1) if stale_minutes is not None else None,
        }

    async def invalidate(self) -> None:
        """手动清除所有健康缓存（数据源状态变更后调用）。"""
        for key in ["health:data_sources", "health:heartbeat"]:
            await self._cache_delete(key)

    # -- Cache helpers --

    async def _cache_get(self, key: str) -> Optional[str]:
        redis = await self._get_redis()
        if redis:
            try:
                return await redis.get(key)
            except Exception:
                pass
        return await self._memory.get(key)

    async def _cache_set(self, key: str, value: str, ttl: int) -> None:
        redis = await self._get_redis()
        if redis:
            try:
                await redis.setex(key, ttl, value)
                return
            except Exception:
                pass
        await self._memory.set(key, value, ttl)

    async def _cache_delete(self, key: str) -> None:
        redis = await self._get_redis()
        if redis:
            try:
                await redis.delete(key)
            except Exception:
                pass
        await self._memory.delete(key)
