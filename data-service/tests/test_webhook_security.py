"""
Tests for openclaw.gateway.webhook_security

Covers:
- HMAC-SHA256 webhook signature verification (valid, invalid, expired, edge cases)
- Skill API Key whitelist validation
- IP rate limiting (Redis path, in-memory fallback, cleanup)
"""
import hashlib
import hmac
import sys
import time

import pytest
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so we can import openclaw.*
# ---------------------------------------------------------------------------
_PROJECT_ROOT = "/Users/jerry.wu/Documents/vibecodingapp/ai-holdings-analyzer-v2"
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from openclaw.gateway.webhook_security import (
    verify_webhook_signature,
    verify_skill_key,
    check_rate_limit,
    _InMemoryRateLimiter,
    _rate_limiters,
)


# ====================================================================== #
# verify_webhook_signature
# ====================================================================== #


def test_verify_signature_valid():
    """正确计算 HMAC-SHA256 签名 → 返回 True。"""
    timestamp = str(int(time.time()))
    payload = b'{"event": "test"}'
    secret = "test_secret_key"

    signed_payload = f"{timestamp}.".encode() + payload
    expected_sig = hmac.new(
        secret.encode(), signed_payload, hashlib.sha256
    ).hexdigest()

    assert verify_webhook_signature(payload, expected_sig, timestamp, secret) is True


def test_verify_signature_invalid():
    """错误的签名 → 返回 False。"""
    timestamp = str(int(time.time()))
    payload = b'{"event": "test"}'
    secret = "test_secret_key"

    wrong_sig = "0" * 64  # 明显错误的签名

    assert verify_webhook_signature(payload, wrong_sig, timestamp, secret) is False


def test_verify_signature_expired_timestamp():
    """时间戳超出 max_skew_seconds → 返回 False。"""
    # 构造一个 600 秒前的时间戳，默认 max_skew_seconds=300
    expired_timestamp = str(int(time.time()) - 600)
    payload = b'{"event": "test"}'
    secret = "test_secret_key"

    # 即使签名正确，过期时间戳也应被拒绝
    signed_payload = f"{expired_timestamp}.".encode() + payload
    expected_sig = hmac.new(
        secret.encode(), signed_payload, hashlib.sha256
    ).hexdigest()

    assert (
        verify_webhook_signature(payload, expected_sig, expired_timestamp, secret)
        is False
    )


def test_verify_signature_invalid_timestamp():
    """非数字时间戳 → 返回 False。"""
    payload = b'{"event": "test"}'
    secret = "test_secret_key"

    assert (
        verify_webhook_signature(payload, "somesig", "not-a-number", secret)
        is False
    )


def test_verify_signature_empty_payload():
    """空 bytes payload → 仍正确计算签名并验证。"""
    timestamp = str(int(time.time()))
    payload = b""
    secret = "test_secret_key"

    signed_payload = f"{timestamp}.".encode() + payload
    expected_sig = hmac.new(
        secret.encode(), signed_payload, hashlib.sha256
    ).hexdigest()

    assert verify_webhook_signature(payload, expected_sig, timestamp, secret) is True


# ====================================================================== #
# verify_skill_key
# ====================================================================== #


def test_verify_skill_key_valid():
    """Key 在白名单中 → True。"""
    allowed = ["key_alpha_001", "key_beta_002", "key_gamma_003"]
    assert verify_skill_key("key_beta_002", allowed) is True


def test_verify_skill_key_invalid():
    """Key 不在白名单中 → False。"""
    allowed = ["key_alpha_001", "key_beta_002"]
    assert verify_skill_key("key_unknown", allowed) is False


def test_verify_skill_key_empty():
    """空 key 或空白名单 → False。"""
    assert verify_skill_key("", ["key_alpha_001"]) is False
    assert verify_skill_key("key_alpha_001", []) is False
    assert verify_skill_key("", []) is False


# ====================================================================== #
# check_rate_limit — in-memory path (redis_client=None)
# ====================================================================== #

@pytest.fixture(autouse=True)
def _clear_global_rate_limiters():
    """每个测试前清空全局 _rate_limiters 缓存，避免测试间污染。"""
    _rate_limiters.clear()
    yield
    _rate_limiters.clear()


def test_check_rate_limit_allows_under_limit():
    """请求次数在限制内 → True。"""
    ip = "192.168.1.1"
    for _ in range(5):
        assert check_rate_limit(ip, redis_client=None, max_requests=10, window_seconds=60) is True


def test_check_rate_limit_blocks_over_limit():
    """请求次数超出限制 → False。"""
    ip = "10.0.0.1"
    max_req = 3
    for i in range(max_req):
        assert check_rate_limit(ip, redis_client=None, max_requests=max_req, window_seconds=60) is True
    # 第 max_req + 1 次应被拒绝
    assert check_rate_limit(ip, redis_client=None, max_requests=max_req, window_seconds=60) is False


def test_check_rate_limit_empty_ip():
    """空 IP → False。"""
    assert check_rate_limit("", redis_client=None, max_requests=100, window_seconds=60) is False


# ====================================================================== #
# check_rate_limit — Redis path
# ====================================================================== #


def test_check_rate_limit_redis_success():
    """Redis INCR 返回 1 → 在限制内 → True。"""
    mock_redis = MagicMock()
    mock_redis.incr.return_value = 1
    mock_redis.expire = MagicMock()

    result = check_rate_limit("1.2.3.4", redis_client=mock_redis, max_requests=100, window_seconds=60)

    assert result is True
    mock_redis.incr.assert_called_once_with("rate_limit:1.2.3.4")
    # 首次请求（current==1）应设置过期时间
    mock_redis.expire.assert_called_once_with("rate_limit:1.2.3.4", 60)


def test_check_rate_limit_redis_over():
    """Redis INCR 返回超出 max_requests → False。"""
    mock_redis = MagicMock()
    mock_redis.incr.return_value = 101  # 超出 max_requests=100
    mock_redis.expire = MagicMock()

    result = check_rate_limit("5.6.7.8", redis_client=mock_redis, max_requests=100, window_seconds=60)

    assert result is False
    mock_redis.incr.assert_called_once_with("rate_limit:5.6.7.8")
    # current != 1，不应调用 expire
    mock_redis.expire.assert_not_called()


# ====================================================================== #
# _InMemoryRateLimiter — cleanup
# ====================================================================== #


def test_in_memory_limiter_cleanup():
    """_InMemoryRateLimiter 在 cleanup 后移除过期条目。"""
    limiter = _InMemoryRateLimiter(max_requests=10, window_seconds=10)
    ip = "172.16.0.1"

    # 手动注入一个过期的时间戳（模拟旧请求）
    with limiter._lock:
        limiter._counts[ip] = [time.time() - 100]  # 100 秒前，已超出 window_seconds=10
        limiter._last_cleanup = time.time() - 120  # 确保触发 cleanup

    # is_allowed 应先执行 cleanup，清除过期记录后再检查
    result = limiter.is_allowed(ip)

    assert result is True  # 过期记录被清除后，新请求应被允许
    # 验证过期时间戳已被清除
    with limiter._lock:
        # 只应保留新添加的时间戳
        assert len(limiter._counts[ip]) == 1
        assert limiter._counts[ip][0] > time.time() - 1
