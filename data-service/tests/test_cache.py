import json
import pytest
from unittest.mock import patch, AsyncMock

from services.cache import QuoteCache


@pytest.fixture
def cache():
    return QuoteCache(redis_url="redis://localhost:6379/0")


@pytest.mark.asyncio
async def test_get_hit_returns_dict(cache):
    """缓存命中时返回反序列化后的 dict。"""
    mock_quote = {"symbol": "AAPL", "price": 191.24}

    with patch("redis.asyncio.from_url") as mock_from_url:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=json.dumps(mock_quote))
        mock_from_url.return_value = mock_instance

        result = await cache.get("quote:AAPL")

        assert result == mock_quote
        mock_instance.get.assert_awaited_once_with("quote:AAPL")


@pytest.mark.asyncio
async def test_get_miss_returns_none(cache):
    """缓存未命中时返回 None。"""
    with patch("redis.asyncio.from_url") as mock_from_url:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=None)
        mock_from_url.return_value = mock_instance

        result = await cache.get("quote:AAPL")

        assert result is None
        mock_instance.get.assert_awaited_once_with("quote:AAPL")


@pytest.mark.asyncio
async def test_set_calls_setex_with_ttl(cache):
    """set 正确调用 Redis.setex 并传入 key、ttl、json 字符串，同时写入 stale 副本。"""
    mock_quote = {"symbol": "AAPL", "price": 191.24}

    with patch("redis.asyncio.from_url") as mock_from_url:
        mock_instance = AsyncMock()
        mock_instance.setex = AsyncMock(return_value=True)
        mock_from_url.return_value = mock_instance

        await cache.set("quote:AAPL", mock_quote, ttl=60)

        # setex 被调用两次：正常 key + stale key
        assert mock_instance.setex.await_count == 2
        calls = mock_instance.setex.await_args_list
        # 第一次：正常 key
        assert calls[0][0][0] == "quote:AAPL"
        assert calls[0][0][1] == 60
        assert json.loads(calls[0][0][2]) == mock_quote
        # 第二次：stale key
        assert calls[1][0][0] == "quote:AAPL:stale"
        assert json.loads(calls[1][0][2]) == mock_quote


@pytest.mark.asyncio
async def test_get_with_stale_fresh_hit(cache):
    """get_with_stale 在缓存新鲜命中时返回数据且 is_stale=False。"""
    mock_quote = {"symbol": "AAPL", "price": 191.24}

    with patch("redis.asyncio.from_url") as mock_from_url:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=json.dumps(mock_quote))
        mock_from_url.return_value = mock_instance

        data, is_stale = await cache.get_with_stale("quote:AAPL")

        assert data == mock_quote
        assert is_stale is False


@pytest.mark.asyncio
async def test_get_with_stale_miss_but_stale_exists(cache):
    """get_with_stale 在正常 key miss 但 stale key 存在时返回 stale 数据。"""
    mock_quote = {"symbol": "AAPL", "price": 191.24}

    with patch("redis.asyncio.from_url") as mock_from_url:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(side_effect=[None, json.dumps(mock_quote)])
        mock_from_url.return_value = mock_instance

        data, is_stale = await cache.get_with_stale("quote:AAPL")

        assert data == mock_quote
        assert is_stale is True
        assert mock_instance.get.await_count == 2


@pytest.mark.asyncio
async def test_get_connection_failure_returns_none_silently(cache):
    """Redis 连接失败时静默返回 None，不抛异常。"""
    with patch("redis.asyncio.from_url") as mock_from_url:
        mock_from_url.side_effect = ConnectionError("Connection refused")

        result = await cache.get("quote:AAPL")

        assert result is None
