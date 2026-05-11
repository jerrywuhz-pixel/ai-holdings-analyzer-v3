"""
Webhook Security — Webhook 请求安全验证

提供三层安全防护：
1. HMAC-SHA256 签名验证 + 时间戳防重放
2. Skill API Key 白名单校验
3. IP 速率限制（Redis INCR 或内存 fallback）
"""
from __future__ import annotations

import hashlib
import hmac
import time
import threading
from collections import defaultdict
from typing import Optional


# ====================================================================== #
# 1. Webhook 签名验证
# ====================================================================== #

def verify_webhook_signature(
    payload: bytes,
    signature: str,
    timestamp: str,
    secret: str,
    max_skew_seconds: int = 300,
) -> bool:
    """
    验证 Webhook 请求的 HMAC-SHA256 签名与时间戳。

    防护能力：
    - **签名验证**：确保请求来源持有 secret，防止伪造
    - **时间戳验证**：防止重放攻击（超过 max_skew_seconds 的请求被拒绝）
    - **恒定时间比较**：使用 hmac.compare_digest 防止时序攻击

    签名计算方式::

        signed_payload = f"{timestamp}.{payload.decode()}"
        expected_sig  = hmac_sha256(signed_payload, secret)

    Args:
        payload: 请求体原始字节。
        signature: 请求头中携带的签名（十六进制）。
        timestamp: 请求头中携带的时间戳（Unix 秒级）。
        secret: Webhook 签名密钥。
        max_skew_seconds: 允许的最大时间偏移（秒），默认 300（5 分钟）。

    Returns:
        True 验证通过，False 验证失败。
    """
    # 1. 时间戳校验：防止重放攻击
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False

    now = int(time.time())
    if abs(now - ts) > max_skew_seconds:
        return False

    # 2. 计算期望签名
    #    签名输入格式: "timestamp.payload"
    signed_payload = f"{timestamp}.".encode() + payload
    expected_sig = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    # 3. 恒定时间比较（防时序攻击）
    return hmac.compare_digest(expected_sig, signature)


# ====================================================================== #
# 2. Skill API Key 白名单
# ====================================================================== #

def verify_skill_key(skill_key: str, allowed_keys: list[str]) -> bool:
    """
    验证 Skill API Key 是否在白名单中。

    使用恒定时间比较防止时序攻击。

    Args:
        skill_key: 请求中携带的 Skill API Key。
        allowed_keys: 允许的 API Key 列表。

    Returns:
        True key 在白名单中，False 不在。
    """
    if not skill_key or not allowed_keys:
        return False

    for allowed in allowed_keys:
        if hmac.compare_digest(skill_key, allowed):
            return True

    return False


# ====================================================================== #
# 3. 速率限制
# ====================================================================== #

class _InMemoryRateLimiter:
    """
    基于内存的速率限制器（无 Redis 时的 fallback）。

    使用滑动窗口：每 (ip, window) 维护一个计数器。
    定期清理过期窗口以防内存泄漏。

    注意：此实现为单进程适用，多进程部署需使用 Redis 方案。
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._counts: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def is_allowed(self, ip: str) -> bool:
        """
        检查 IP 是否在速率限制内。

        Args:
            ip: 客户端 IP 地址。

        Returns:
            True 允许请求，False 超出限制。
        """
        now = time.time()

        with self._lock:
            # 定期清理过期记录（每 60 秒）
            if now - self._last_cleanup > 60:
                self._cleanup(now)
                self._last_cleanup = now

            # 清除过期时间戳
            window_start = now - self._window_seconds
            self._counts[ip] = [
                ts for ts in self._counts[ip] if ts > window_start
            ]

            # 检查是否超限
            if len(self._counts[ip]) >= self._max_requests:
                return False

            # 记录当前请求
            self._counts[ip].append(now)
            return True

    def _cleanup(self, now: float) -> None:
        """清理所有 IP 的过期时间戳。"""
        window_start = now - self._window_seconds
        expired_ips = []
        for ip, timestamps in self._counts.items():
            self._counts[ip] = [ts for ts in timestamps if ts > window_start]
            if not self._counts[ip]:
                expired_ips.append(ip)
        for ip in expired_ips:
            del self._counts[ip]


# 全局内存速率限制器实例（按 (max_requests, window_seconds) 参数缓存）
_rate_limiters: dict[tuple[int, int], _InMemoryRateLimiter] = {}


def check_rate_limit(
    ip: str,
    redis_client=None,
    max_requests: int = 100,
    window_seconds: int = 60,
) -> bool:
    """
    检查 IP 速率限制。

    优先使用 Redis（INCR + EXPIRE），无 Redis 时降级到内存实现。

    Redis 方案（推荐生产使用）::

        key = f"rate_limit:{ip}"
        current = redis.incr(key)
        if current == 1:
            redis.expire(key, window_seconds)
        return current <= max_requests

    内存方案（开发/单进程 fallback）::

        滑动窗口：维护每个 IP 的请求时间戳列表，
        清除 window_seconds 之外的记录，检查剩余数量。

    Args:
        ip: 客户端 IP 地址。
        redis_client: 可选的 Redis 客户端实例。需支持 ``incr`` / ``expire`` 方法。
        max_requests: 窗口内最大请求数，默认 100。
        window_seconds: 窗口时间（秒），默认 60。

    Returns:
        True 允许请求，False 超出速率限制。
    """
    if not ip:
        return False

    # Redis 方案
    if redis_client is not None:
        try:
            key = f"rate_limit:{ip}"
            current = redis_client.incr(key)
            if current == 1:
                redis_client.expire(key, window_seconds)
            return current <= max_requests
        except Exception:
            # Redis 异常时降级到内存方案
            pass

    # 内存 fallback 方案
    limiter_key = (max_requests, window_seconds)
    if limiter_key not in _rate_limiters:
        _rate_limiters[limiter_key] = _InMemoryRateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )

    return _rate_limiters[limiter_key].is_allowed(ip)
