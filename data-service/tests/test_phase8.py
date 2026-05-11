"""
Tests for Phase 8: Health Cache, Heartbeat Reporter, Sentry Service
"""
import json
import sys
import os
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# Add project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Mock supabase before importing
if "supabase" not in sys.modules:
    _mock_supabase = MagicMock()
    _mock_supabase.Client = MagicMock
    _mock_supabase.create_client = MagicMock()
    sys.modules["supabase"] = _mock_supabase


# ====================================================================== #
# HealthCache Tests
# ====================================================================== #

from services.health_cache import HealthCache, _InMemoryCache


class TestInMemoryCache:
    def test_set_and_get(self):
        cache = _InMemoryCache()
        # Run async methods via asyncio
        import asyncio
        asyncio.get_event_loop().run_until_complete(cache.set("k1", "v1", 60))
        result = asyncio.get_event_loop().run_until_complete(cache.get("k1"))
        assert result == "v1"

    def test_get_expired(self):
        import asyncio
        cache = _InMemoryCache()
        asyncio.get_event_loop().run_until_complete(cache.set("k1", "v1", 0))
        # Manually expire
        cache._store["k1"] = (0, "v1")
        result = asyncio.get_event_loop().run_until_complete(cache.get("k1"))
        assert result is None

    def test_get_missing(self):
        import asyncio
        cache = _InMemoryCache()
        result = asyncio.get_event_loop().run_until_complete(cache.get("nonexistent"))
        assert result is None

    def test_delete(self):
        import asyncio
        cache = _InMemoryCache()
        asyncio.get_event_loop().run_until_complete(cache.set("k1", "v1", 60))
        asyncio.get_event_loop().run_until_complete(cache.delete("k1"))
        result = asyncio.get_event_loop().run_until_complete(cache.get("k1"))
        assert result is None


@pytest.mark.asyncio
async def test_health_cache_data_sources_from_cache():
    """数据源健康从缓存返回。"""
    hc = HealthCache(redis_url="redis://localhost:6379/0")
    mock_data = [{"source_name": "yahoo", "status": "healthy"}]

    with patch.object(hc, "_cache_get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = json.dumps(mock_data)
        result = await hc.get_data_source_health()

    assert result == mock_data


@pytest.mark.asyncio
async def test_health_cache_gateway_status():
    """网关综合状态正确聚合。"""
    hc = HealthCache(redis_url="redis://localhost:6379/0")

    mock_heartbeat = {
        "gateway_status": "healthy",
        "reported_at": "2099-01-01T00:00:00+00:00",
        "deployment_mode": "local",
        "active_skills": ["daily-analysis"],
    }
    mock_sources = [{"source_name": "yahoo", "status": "healthy"}]

    with patch.object(hc, "get_heartbeat", new_callable=AsyncMock) as mock_hb, \
         patch.object(hc, "get_data_source_health", new_callable=AsyncMock) as mock_ds:
        mock_hb.return_value = mock_heartbeat
        mock_ds.return_value = mock_sources

        result = await hc.get_gateway_status()

    assert result["gateway"]["status"] == "healthy"
    assert result["data_sources"] == mock_sources


# ====================================================================== #
# HeartbeatReporter Tests
# ====================================================================== #

from openclaw.gateway.heartbeat_reporter import HeartbeatReporter


@pytest.mark.asyncio
async def test_heartbeat_report_no_supabase():
    """无 Supabase 配置时上报跳过。"""
    reporter = HeartbeatReporter(supabase_url="", supabase_key="")
    result = await reporter.report()
    assert result is False


def test_heartbeat_register_skill():
    """Skill 注册和注销正常工作。"""
    reporter = HeartbeatReporter(supabase_url="", supabase_key="")
    reporter.register_skill("daily-analysis")
    reporter.register_skill("heartbeat")
    assert "daily-analysis" in reporter._active_skills
    assert "heartbeat" in reporter._active_skills

    reporter.unregister_skill("heartbeat")
    assert "heartbeat" not in reporter._active_skills
    assert "daily-analysis" in reporter._active_skills


def test_heartbeat_set_claw_status():
    """Claw 插件状态可设置。"""
    reporter = HeartbeatReporter(supabase_url="", supabase_key="")
    reporter.set_claw_plugin_status("connected")
    assert reporter._claw_plugin_status == "connected"


@pytest.mark.asyncio
async def test_heartbeat_report_with_mock_client():
    """有 Supabase 客户端时上报成功。"""
    reporter = HeartbeatReporter(
        supabase_url="https://test.supabase.co",
        supabase_key="test-key",
    )

    mock_client = MagicMock()
    mock_client.table.return_value.upsert.return_value.execute = MagicMock()
    reporter._client = mock_client

    result = await reporter.report(gateway_status="healthy")
    assert result is True
    mock_client.table.assert_called_with("openclaw_heartbeat")


# ====================================================================== #
# Sentry Service Tests
# ====================================================================== #

from services.sentry_service import init_sentry, capture_exception, capture_message


def test_sentry_init_no_sdk():
    """无 sentry-sdk 时初始化返回 False。"""
    with patch("services.sentry_service._HAS_SENTRY", False):
        result = init_sentry()
        assert result is False


def test_sentry_init_no_dsn():
    """无 SENTRY_DSN 时初始化返回 False。"""
    with patch("services.sentry_service._HAS_SENTRY", True):
        with patch.dict(os.environ, {}, clear=True):
            result = init_sentry()
            assert result is False


def test_sentry_capture_no_sdk():
    """无 sentry-sdk 时 capture_exception 不报错。"""
    with patch("services.sentry_service._HAS_SENTRY", False):
        capture_exception(Exception("test"))  # 不应抛异常


def test_sentry_capture_message_no_sdk():
    """无 sentry-sdk 时 capture_message 不报错。"""
    with patch("services.sentry_service._HAS_SENTRY", False):
        capture_message("test message")  # 不应抛异常
