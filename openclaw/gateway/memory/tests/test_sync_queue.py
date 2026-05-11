"""
SyncQueue 单元测试
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from openclaw.gateway.memory.sync_queue import SyncQueue, WriteSignal


class TestSyncQueue:
    """测试同步队列的批量消费逻辑"""

    @pytest.fixture
    def mock_brain_ops(self):
        return MagicMock()

    @pytest.fixture
    def queue(self, mock_brain_ops):
        return SyncQueue(brain_ops=mock_brain_ops)

    @pytest.mark.asyncio
    async def test_enqueue_starts_consumer(self, queue, mock_brain_ops):
        """测试 enqueue 会接受信号并启动消费者"""
        mock_brain_ops.upsert_page = AsyncMock(return_value={"id": "page-1"})
        signal = WriteSignal(
            tenant_id="tenant-abc",
            operation="upsert_page",
            path="stocks/600519",
            title="贵州茅台",
        )

        accepted = await queue.enqueue(signal)

        assert accepted is True
        assert queue._consumer_task is not None
        await queue.stop_consumer()

    @pytest.mark.asyncio
    async def test_batch_consumer_processes_signals(self, queue, mock_brain_ops):
        """测试批量消费者正确处理信号"""
        mock_brain_ops.upsert_page = AsyncMock(return_value={"id": "page-1"})
        mock_brain_ops.add_timeline_entry = AsyncMock(return_value={"id": "tl-1"})

        # 添加两个信号
        queue._ensure_queue().put_nowait(WriteSignal(
            tenant_id="tenant-abc",
            operation="upsert_page",
            path="stocks/600519",
            title="贵州茅台",
        ))
        queue._ensure_queue().put_nowait(WriteSignal(
            tenant_id="tenant-abc",
            operation="add_timeline",
            path="stocks/600519",
            event_date="2024-01-15",
            event_type="BUY",
        ))

        # 手动触发一次消费
        queue._batch_size = 2  # 减小批次以便测试
        await queue._consume_batch()

        mock_brain_ops.upsert_page.assert_called_once()
        mock_brain_ops.add_timeline_entry.assert_called_once()
        assert queue._queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_consumer_handles_errors(self, queue, mock_brain_ops):
        """测试消费者处理失败信号并记录重试"""
        mock_brain_ops.upsert_page = AsyncMock(side_effect=RuntimeError("DB error"))

        signal = WriteSignal(
            tenant_id="tenant-abc",
            operation="upsert_page",
            path="stocks/600519",
            title="贵州茅台",
        )

        queue._ensure_queue().put_nowait(signal)
        queue._batch_size = 1
        await queue._consume_batch()

        # 失败信号应该留在队列中等待重试
        mock_brain_ops.upsert_page.assert_called()

    @pytest.mark.asyncio
    async def test_start_stop_consumer(self, queue):
        """测试启动和停止消费者"""
        queue.start_consumer()
        assert queue._consumer_task is not None
        assert not queue._consumer_task.done()

        await queue.stop_consumer()
        assert queue._consumer_task is None

    @pytest.mark.asyncio
    async def test_flush_interval_processing(self, queue, mock_brain_ops):
        """测试刷新间隔触发消费"""
        mock_brain_ops.upsert_page = AsyncMock(return_value={"id": "page-1"})

        queue._flush_interval = 0.1  # 100ms 便于测试
        queue.start_consumer()

        await queue.enqueue(WriteSignal(
            tenant_id="tenant-abc",
            operation="upsert_page",
            path="stocks/600519",
            title="贵州茅台",
        ))

        # 等待刷新间隔
        await asyncio.sleep(0.2)

        mock_brain_ops.upsert_page.assert_called_once()

        await queue.stop_consumer()

    @pytest.mark.asyncio
    async def test_flush_processes_enqueued_signal(self, queue, mock_brain_ops):
        """测试 flush 会等待入队信号处理完成"""
        mock_brain_ops.upsert_page = AsyncMock(return_value={"id": "page-1"})

        accepted = await queue.enqueue(WriteSignal(
            tenant_id="tenant-abc",
            operation="upsert_page",
            path="stocks/600519",
            title="贵州茅台",
        ))

        flushed = await queue.flush(timeout=1.0)

        assert accepted is True
        assert flushed is True
        assert queue.depth == 0
        mock_brain_ops.upsert_page.assert_called_once()

        await queue.stop_consumer()

    @pytest.mark.asyncio
    async def test_enqueue_after_stop_is_ignored(self, queue, mock_brain_ops):
        """测试关闭后新任务会被安全忽略"""
        await queue.stop_consumer()

        accepted = await queue.enqueue(WriteSignal(
            tenant_id="tenant-abc",
            operation="upsert_page",
            path="stocks/600519",
            title="贵州茅台",
        ))

        assert accepted is False
        assert queue.closed is True
        assert queue.depth == 0
        mock_brain_ops.upsert_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_shutdown_logs_failures_without_blocking(self, queue, mock_brain_ops, caplog):
        """测试异常任务不会阻塞关闭"""
        mock_brain_ops.upsert_page = AsyncMock(side_effect=RuntimeError("DB error"))

        await queue.enqueue(WriteSignal(
            tenant_id="tenant-abc",
            operation="upsert_page",
            path="stocks/600519",
            title="贵州茅台",
        ))

        await queue.stop_consumer(timeout=1.0)

        assert queue.closed is True
        assert queue.depth == 0
        assert mock_brain_ops.upsert_page.await_count == queue._max_retries
        assert "exceeded max retries" in caplog.text

    def test_write_signal_creation(self):
        """测试 WriteSignal 数据类创建"""
        signal = WriteSignal(
            tenant_id="t-1",
            operation="upsert_page",
            path="stocks/600519",
            title="贵州茅台",
            content="测试",
            page_type="stock",
            metadata={"symbol": "600519"},
        )

        assert signal.tenant_id == "t-1"
        assert signal.operation == "upsert_page"
        assert signal.metadata["symbol"] == "600519"
