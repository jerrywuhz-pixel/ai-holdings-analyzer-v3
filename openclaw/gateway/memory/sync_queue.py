"""
SyncQueue — 异步批量写入队列

Fire-and-forget 写入模式：Skill 执行不阻塞等待 brain 写入。
信号入队后由后台消费者批量处理。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from openclaw.gateway.memory.brain_ops import BrainOps, BrainOpsError

logger = logging.getLogger(__name__)
_STOP_MARKER = object()


@dataclass
class WriteSignal:
    """待写入 brain 的信号"""

    tenant_id: str
    operation: str
    path: str = ""
    title: str = ""
    content: str = ""
    page_type: str = "compiled_truth"
    metadata: dict[str, Any] = field(default_factory=dict)
    event_date: str = ""
    event_type: str = "MANUAL"
    timeline_title: str = ""
    timeline_content: str = ""
    importance: int = 5
    source_path: str = ""
    target_path: str = ""
    link_type: str = "MENTIONS"
    confidence: float = 0.7
    retry_count: int = 0


class SyncQueue:
    """异步批量写入队列。"""

    def __init__(
        self,
        brain_ops: BrainOps,
        batch_size: int = 10,
        flush_interval: float = 15.0,
        max_retries: int = 3,
    ):
        self._brain_ops = brain_ops
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries

        self._queue: asyncio.Queue[WriteSignal] | None = None
        self._consumer_task: asyncio.Task | None = None
        self._running = False
        self._closed = False
        self._stopping = False

    def _ensure_queue(self) -> asyncio.Queue[WriteSignal]:
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    async def enqueue(self, signal: WriteSignal) -> bool:
        if self._closed or self._stopping:
            logger.warning(
                "[sync_queue] Ignoring %s for %s because queue is shutting down",
                signal.operation,
                signal.tenant_id[:8],
            )
            return False

        if not self._running:
            self.start_consumer()
        queue = self._ensure_queue()
        await queue.put(signal)
        logger.debug(
            "[sync_queue] Enqueued %s for %s (queue depth: %d)",
            signal.operation,
            signal.tenant_id[:8],
            queue.qsize(),
        )
        return True

    def start_consumer(self) -> None:
        """启动后台消费者协程。"""
        if self._closed or self._stopping:
            logger.warning("[sync_queue] Consumer start ignored during shutdown")
            return
        if self._running and self._consumer_task and not self._consumer_task.done():
            return
        self._ensure_queue()
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_loop())
        logger.info(
            "[sync_queue] Consumer started (batch=%d, interval=%.1fs)",
            self._batch_size,
            self._flush_interval,
        )

    async def flush(self, timeout: float | None = None) -> bool:
        """等待已入队任务处理完成。"""
        if self._consumer_task is None and self.depth == 0:
            return True

        wait_coro = self._ensure_queue().join()
        try:
            if timeout is None:
                await wait_coro
            else:
                await asyncio.wait_for(wait_coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "[sync_queue] Flush timed out with %d pending items",
                self._queue.qsize(),
            )
            return False
        return True

    async def stop_consumer(self, timeout: float = 10.0, drain: bool = True) -> None:
        """优雅停止消费者并尽量清空队列。"""
        self._stopping = True
        self._running = False

        try:
            if drain:
                await self.flush(timeout=timeout)

            if self._consumer_task:
                await self._ensure_queue().put(_STOP_MARKER)
                try:
                    await asyncio.wait_for(self._consumer_task, timeout=timeout)
                except asyncio.TimeoutError:
                    self._consumer_task.cancel()
                    try:
                        await self._consumer_task
                    except asyncio.CancelledError:
                        pass
                    logger.warning("[sync_queue] Consumer cancelled during shutdown")
        finally:
            self._consumer_task = None
            self._closed = True
            self._stopping = False
            logger.info("[sync_queue] Consumer stopped")

    async def aclose(self, timeout: float = 10.0, drain: bool = True) -> None:
        """兼容 async closing 协议。"""
        await self.stop_consumer(timeout=timeout, drain=drain)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def accepting(self) -> bool:
        return not (self._closed or self._stopping)

    @property
    def depth(self) -> int:
        if self._queue is None:
            return 0
        return self._queue.qsize()

    async def _consume_loop(self) -> None:
        queue = self._ensure_queue()
        while True:
            try:
                signal = await queue.get()
            except asyncio.CancelledError:
                break

            if signal is _STOP_MARKER:
                queue.task_done()
                if not self._running:
                    break
                continue

            try:
                batch = [signal]
                while len(batch) < self._batch_size:
                    try:
                        next_signal = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    if next_signal is _STOP_MARKER:
                        queue.task_done()
                        if not self._running:
                            break
                        continue

                    batch.append(next_signal)

                await self._process_batch(batch)
            except Exception as exc:
                logger.error("[sync_queue] Consume loop error: %s", exc)
                await asyncio.sleep(0.1)

    async def _consume_batch(self) -> None:
        batch: list[WriteSignal] = []
        if self._queue is None:
            return
        while len(batch) < self._batch_size:
            try:
                signal = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if signal is _STOP_MARKER:
                self._queue.task_done()
                continue

            batch.append(signal)

        if not batch:
            return

        await self._process_batch(batch)

    async def _process_batch(self, batch: list[WriteSignal]) -> None:
        queue = self._ensure_queue()
        for signal in batch:
            try:
                await self._execute_signal(signal)
            except (BrainOpsError, Exception) as exc:
                signal.retry_count += 1
                if signal.retry_count < self._max_retries:
                    logger.warning(
                        "[sync_queue] Signal %s failed (retry %d/%d): %s",
                        signal.operation,
                        signal.retry_count,
                        self._max_retries,
                        exc,
                    )
                    await self._queue.put(signal)
                else:
                    logger.error(
                        "[sync_queue] Signal %s exceeded max retries, dropping: %s",
                        signal.operation,
                        exc,
                    )
            finally:
                queue.task_done()

    async def _execute_signal(self, signal: WriteSignal) -> None:
        if signal.operation == "upsert_page":
            await self._brain_ops.upsert_page(
                tenant_id=signal.tenant_id,
                path=signal.path,
                title=signal.title,
                content=signal.content,
                page_type=signal.page_type,
                metadata=signal.metadata,
            )
            return

        if signal.operation == "add_timeline":
            await self._brain_ops.add_timeline_entry(
                tenant_id=signal.tenant_id,
                path=signal.path,
                event_date=signal.event_date,
                event_type=signal.event_type,
                title=signal.timeline_title,
                content=signal.timeline_content,
                importance=signal.importance,
                metadata=signal.metadata,
            )
            return

        if signal.operation == "create_link":
            await self._brain_ops.create_link(
                tenant_id=signal.tenant_id,
                source_path=signal.source_path,
                target_path=signal.target_path,
                link_type=signal.link_type,
                confidence=signal.confidence,
            )
            return

        logger.warning("[sync_queue] Unknown operation: %s", signal.operation)
