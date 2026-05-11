"""
MemoryMiddleware — OpenClaw 记忆中间件主编排器

提供 on_skill_complete / on_skill_invoke 钩子，
将 Skill 的输入输出与 gbrain 记忆层连接。
"""
from __future__ import annotations

import logging
from typing import Any

from openclaw.gateway.memory.brain_ops import BrainOps, BrainOpsError
from openclaw.gateway.memory.signal_detector import (
    SignalDetector, TradeSignal, AnalysisSignal,
)
from openclaw.gateway.memory.sync_queue import SyncQueue, WriteSignal

logger = logging.getLogger(__name__)


class MemoryMiddleware:
    """
    OpenClaw 记忆中间件。

    用法：
    - on_skill_complete(): Skill 执行完毕后调用，检测信号并写入 brain
    - on_skill_invoke(): Skill 执行前调用，注入记忆上下文
    """

    def __init__(
        self,
        brain_ops: BrainOps,
        signal_detector: SignalDetector,
        sync_queue: SyncQueue,
    ):
        self._brain_ops = brain_ops
        self._signal_detector = signal_detector
        self._sync_queue = sync_queue

    # ------------------------------------------------------------------ #
    # Skill 完成后 — 记忆写入
    # ------------------------------------------------------------------ #

    async def on_skill_complete(
        self,
        skill_name: str,
        tenant_id: str,
        skill_output: dict[str, Any],
    ) -> None:
        """
        Skill 执行完毕后的记忆写入钩子。

        根据技能类型检测信号并入队写入，不阻塞调用方。
        """
        try:
            if skill_name in ("trade-input", "broker-parse"):
                await self._handle_trade_complete(tenant_id, skill_output)
            elif skill_name in ("daily-analysis", "daily-analysis"):
                await self._handle_analysis_complete(tenant_id, skill_output)
            elif skill_name == "position-aggregate":
                await self._handle_position_complete(tenant_id, skill_output)
            # 其他 skill 暂不处理（Phase 2+）
        except Exception as e:
            logger.error("[memory] on_skill_complete error for %s: %s", skill_name, e)

    # ------------------------------------------------------------------ #
    # Skill 调用前 — 记忆检索
    # ------------------------------------------------------------------ #

    async def on_skill_invoke(
        self,
        skill_name: str,
        tenant_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Skill 执行前的记忆检索钩子。

        返回记忆上下文供 Skill 使用，或 None。
        """
        try:
            if skill_name == "daily-analysis":
                return await self._get_analysis_context(tenant_id)
            # 其他 skill 暂不注入记忆（Phase 2+）
            return None
        except Exception as e:
            logger.error("[memory] on_skill_invoke error for %s: %s", skill_name, e)
            return None

    async def flush(self, timeout: float | None = None) -> bool:
        """等待队列中的记忆写入完成。"""
        return await self._sync_queue.flush(timeout=timeout)

    async def shutdown(self, timeout: float = 10.0, drain: bool = True) -> None:
        """停止后台记忆同步队列。"""
        await self._sync_queue.stop_consumer(timeout=timeout, drain=drain)

    # ------------------------------------------------------------------ #
    # Trade Input → 记忆写入
    # ------------------------------------------------------------------ #

    async def _handle_trade_complete(
        self,
        tenant_id: str,
        skill_output: dict,
    ) -> None:
        """处理交易完成后的记忆写入"""
        signal = self._signal_detector.detect_trade_signal(skill_output)
        if not signal:
            return

        portfolio_path = f"portfolios/{tenant_id[:8]}"

        # 1. Upsert stock page (compiled truth)
        compiled_truth = self._build_stock_compiled_truth(signal)
        await self._sync_queue.enqueue(WriteSignal(
            tenant_id=tenant_id,
            operation="upsert_page",
            path=signal.page_path,
            title=signal.stock_name or signal.symbol,
            content=compiled_truth,
            page_type="stock",
            metadata={
                "symbol": signal.symbol,
                "market": signal.market,
                "stock_name": signal.stock_name,
            },
        ))

        # 2. Add timeline entry
        await self._sync_queue.enqueue(WriteSignal(
            tenant_id=tenant_id,
            operation="add_timeline",
            path=signal.page_path,
            event_date=signal.trade_date,
            event_type=signal.event_type,
            timeline_title=self._format_trade_title(signal),
            timeline_content=self._format_trade_detail(signal),
            importance=7,
            metadata={
                "trade_event_id": signal.trade_event_id,
                "source": "skill",
            },
        ))

        # 3. Create link: portfolio → stock
        await self._sync_queue.enqueue(WriteSignal(
            tenant_id=tenant_id,
            operation="create_link",
            source_path=portfolio_path,
            target_path=signal.page_path,
            link_type="HOLDS",
            confidence=0.9,
        ))

        logger.info(
            "[memory] Trade signal queued: %s %s %s@%s → %s",
            signal.event_type, signal.stock_name, signal.quantity, signal.price, signal.page_path,
        )

    # ------------------------------------------------------------------ #
    # Daily Analysis → 记忆读取 + 写入
    # ------------------------------------------------------------------ #

    async def _get_analysis_context(self, tenant_id: str) -> dict[str, Any]:
        """获取 daily-analysis 所需的记忆上下文"""
        portfolio_path = f"portfolios/{tenant_id[:8]}"
        brain_context: dict[str, Any] = {
            "recent_trades": [],
            "position_summary": [],
            "past_insights": [],
        }

        # 1. 获取 portfolio 页面及其关联
        portfolio_ctx = await self._brain_ops.get_page_context(
            tenant_id, portfolio_path,
            include_timeline=True, include_links=True,
        )
        if portfolio_ctx:
            # 从关联链接中获取持仓股票
            for link in portfolio_ctx.get("links_outgoing", []):
                if link.get("link_type") == "HOLDS":
                    stock_path = link.get("target_path", "")
                    # 2. 获取每只股票的 compiled truth
                    stock_page = await self._brain_ops.get_page(tenant_id, stock_path)
                    if stock_page:
                        brain_context["position_summary"].append({
                            "path": stock_path,
                            "title": stock_page.get("title", ""),
                            "content": stock_page.get("content", "")[:500],
                        })

            # 从 portfolio timeline 获取近期交易
            for entry in portfolio_ctx.get("timeline", [])[:5]:
                brain_context["recent_trades"].append({
                    "date": entry.get("event_date", ""),
                    "type": entry.get("event_type", ""),
                    "title": entry.get("title", ""),
                })

        # 3. 搜索相关历史洞察
        insights = await self._brain_ops.search(
            tenant_id, "日终分析 持仓分析", limit=3, search_type="hybrid"
        )
        for insight in insights:
            brain_context["past_insights"].append({
                "path": insight.get("path", ""),
                "title": insight.get("title", ""),
                "content": str(insight.get("content", ""))[:300],
            })

        return brain_context

    async def _handle_analysis_complete(
        self,
        tenant_id: str,
        skill_output: dict,
    ) -> None:
        """处理分析完成后的记忆写入"""
        signal = self._signal_detector.detect_analysis_signal(skill_output)
        if not signal:
            return

        # 1. Upsert insight page
        analysis_content = self._build_insight_content(signal, skill_output)
        await self._sync_queue.enqueue(WriteSignal(
            tenant_id=tenant_id,
            operation="upsert_page",
            path=signal.insight_path,
            title=f"日终分析 {signal.analysis_date}",
            content=analysis_content,
            page_type="insight",
            metadata={
                "date": signal.analysis_date,
                "analysis_type": "daily",
                "symbols": signal.symbols,
                "sentiment": signal.sentiment,
            },
        ))

        # 2. 为每只提及的股票添加 timeline entry
        for symbol in signal.symbols:
            stock_path = f"stocks/{symbol}"
            # 找到对应的洞察摘要
            insight_summary = ""
            for ins in signal.insights:
                if symbol in ins:
                    insight_summary = ins
                    break
            if not insight_summary and signal.insights:
                insight_summary = signal.insights[0]

            await self._sync_queue.enqueue(WriteSignal(
                tenant_id=tenant_id,
                operation="add_timeline",
                path=stock_path,
                event_date=signal.analysis_date,
                event_type="ANALYSIS",
                timeline_title=f"AI分析：{insight_summary[:50]}",
                timeline_content=insight_summary,
                importance=5,
                metadata={"report_id": signal.report_id},
            ))

            # 3. Create link: insight → stock
            await self._sync_queue.enqueue(WriteSignal(
                tenant_id=tenant_id,
                operation="create_link",
                source_path=signal.insight_path,
                target_path=stock_path,
                link_type="ANALYZES",
                confidence=0.9,
            ))

        logger.info(
            "[memory] Analysis signal queued: %s (%d symbols) → %s",
            signal.analysis_date, len(signal.symbols), signal.insight_path,
        )

    # ------------------------------------------------------------------ #
    # Position Aggregate → 记忆写入
    # ------------------------------------------------------------------ #

    async def _handle_position_complete(
        self,
        tenant_id: str,
        skill_output: dict,
    ) -> None:
        """处理持仓更新后的记忆写入"""
        signal = self._signal_detector.detect_position_signal(skill_output)
        if not signal:
            return

        portfolio_path = f"portfolios/{tenant_id[:8]}"

        # Upsert portfolio page
        await self._sync_queue.enqueue(WriteSignal(
            tenant_id=tenant_id,
            operation="upsert_page",
            path=portfolio_path,
            title="当前持仓全景",
            content=f"持仓股票: {', '.join(signal.symbols)}",
            page_type="portfolio",
            metadata={
                "symbols": signal.symbols,
                "total_value": signal.total_value,
            },
        ))

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_stock_compiled_truth(signal: TradeSignal) -> str:
        """构建股票页面的 compiled truth 内容"""
        lines = [
            f"## {signal.stock_name or signal.symbol}",
            f"代码: {signal.symbol} | 市场: {signal.market}",
            "",
        ]
        if signal.side:
            direction = "买入" if signal.side == "BUY" else "卖出"
            lines.append(f"**最新操作**: {direction} {signal.quantity}股 @¥{signal.price:.2f}")
        if signal.tags:
            lines.append(f"**标签**: {', '.join(signal.tags)}")
        if signal.strategy_tag:
            lines.append(f"**策略**: {signal.strategy_tag}")
        return "\n".join(lines)

    @staticmethod
    def _format_trade_title(signal: TradeSignal) -> str:
        """格式化交易时间线标题"""
        direction = "买入" if signal.side == "BUY" else "卖出"
        return f"{direction} {signal.stock_name or signal.symbol} {signal.quantity}股@¥{signal.price:.2f}"

    @staticmethod
    def _format_trade_detail(signal: TradeSignal) -> str:
        """格式化交易时间线详情"""
        lines = [
            f"方向: {signal.side}",
            f"数量: {signal.quantity}",
            f"价格: ¥{signal.price:.2f}",
            f"金额: ¥{signal.quantity * signal.price:.2f}",
        ]
        if signal.strategy_tag:
            lines.append(f"策略: {signal.strategy_tag}")
        return " | ".join(lines)

    @staticmethod
    def _build_insight_content(signal: AnalysisSignal, skill_output: dict) -> str:
        """构建洞察页面内容"""
        lines = [
            f"## 日终分析 {signal.analysis_date}",
            f"**情绪**: {signal.sentiment}",
            f"**涉及股票**: {', '.join(signal.symbols)}",
            "",
        ]
        if signal.insights:
            lines.append("### 关键洞察")
            for i, insight in enumerate(signal.insights, 1):
                lines.append(f"{i}. {insight}")

        # 如果有原始分析内容，附加
        data = skill_output.get("data", {})
        markdown = data.get("formatted_markdown", "")
        if markdown:
            lines.append("")
            lines.append("---")
            lines.append(markdown[:2000])

        return "\n".join(lines)
