"""
Hermes Orchestrator — 机会猎手调度器

协调 Market Scanner、Sector Hunter、Leader Selector、Report Formatter
生成市场日报，写入 Supabase daily_reports 表。

支持按市场（CN/US/HK）单独生成，或并发生成所有市场日报。
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
from datetime import date
from typing import Any

# 同目录模块导入（目录名含连字符，需使用 importlib）
_market_scanner = importlib.import_module(
    "openclaw.skills.opportunity-hunter.market_scanner"
)
_sector_hunter = importlib.import_module(
    "openclaw.skills.opportunity-hunter.sector_hunter"
)
_leader_selector = importlib.import_module(
    "openclaw.skills.opportunity-hunter.leader_selector"
)
_report_formatter = importlib.import_module(
    "openclaw.skills.opportunity-hunter.report_formatter"
)

scan_market = _market_scanner.scan_market
hunt_sectors = _sector_hunter.hunt_sectors
select_leaders = _leader_selector.select_leaders
format_daily_report = _report_formatter.format_daily_report

logger = logging.getLogger(__name__)

# 市场报告类型映射
REPORT_TYPE_MAP: dict[str, str] = {
    "CN": "opportunity_cn",
    "US": "opportunity_us",
    "HK": "opportunity_hk",
}


class HermesOrchestrator:
    """
    Hermes 机会猎手调度器。

    协调各子模块生成市场日报，写入 Supabase。

    Usage::

        hermes = HermesOrchestrator()
        report = await hermes.generate_daily_report("CN")
        all_reports = await hermes.generate_all_reports()
    """

    def __init__(
        self,
        data_service_url: str | None = None,
        supabase_url: str | None = None,
        supabase_key: str | None = None,
    ) -> None:
        """
        Args:
            data_service_url: data-service 基础 URL，
                默认从环境变量 DATA_SERVICE_URL 读取。
            supabase_url: Supabase Project URL，
                默认从环境变量 SUPABASE_URL 读取。
            supabase_key: Supabase API Key（service_role），
                默认从环境变量 SUPABASE_SERVICE_ROLE_KEY 读取。
        """
        self.data_service_url = data_service_url or os.getenv(
            "DATA_SERVICE_URL", "http://localhost:8000"
        )
        self.supabase_url = supabase_url or os.getenv("SUPABASE_URL", "")
        self.supabase_key = supabase_key or os.getenv(
            "SUPABASE_SERVICE_ROLE_KEY", ""
        )

    async def generate_daily_report(
        self,
        market: str,
        tenant_id: str | None = None,
        report_date: str | None = None,
    ) -> dict[str, Any]:
        """
        生成指定市场的日报。

        执行流程：
        1. scan_market — 市场扫描
        2. hunt_sectors — 板块分析
        3. select_leaders — 逐板块龙头识别
        4. generate_strategy_suggestions — 策略建议
        5. format_daily_report — 格式化报告
        6. save_report — 写入 Supabase

        Args:
            market: 市场标识，"CN" / "US" / "HK"。
            tenant_id: 用户租户 ID，为 None 时生成系统级公共报告。
            report_date: 报告日期，格式 "YYYY-MM-DD"，默认当天。

        Returns:
            完整报告字典，包含 market, date, market_overview,
            top_sectors, strategy_suggestions, formatted_report。
        """
        if report_date is None:
            report_date = date.today().isoformat()

        if market not in REPORT_TYPE_MAP:
            logger.error("Unknown market: %s", market)
            return {
                "ok": False,
                "message": f"Unknown market: {market}",
                "market": market,
            }

        logger.info(
            "Generating daily report for market=%s, date=%s, tenant=%s",
            market,
            report_date,
            tenant_id or "system",
        )

        # 1. Market Scanner
        market_overview: dict[str, Any] = {}
        try:
            market_overview = await scan_market(market, self.data_service_url)
        except Exception as exc:
            logger.error("Market scanner failed for %s: %s", market, exc)
            market_overview = {
                "advance_count": 0,
                "decline_count": 0,
                "flat_count": 0,
                "total_volume": 0,
                "index_quotes": [],
            }

        # 2. Sector Hunter
        top_sectors: list[dict[str, Any]] = []
        try:
            top_sectors = await hunt_sectors(market, self.data_service_url)
        except Exception as exc:
            logger.error("Sector hunter failed for %s: %s", market, exc)
            top_sectors = []

        # 3. Leader Selector — 对 Top 5 板块识别龙头
        for sector in top_sectors[:5]:
            sector_symbol = sector.get("symbol", "")
            if not sector_symbol:
                continue
            try:
                leaders = await select_leaders(
                    sector_symbol, market, self.data_service_url
                )
                sector["leaders"] = leaders
            except Exception as exc:
                logger.error(
                    "Leader selector failed for sector %s: %s",
                    sector_symbol,
                    exc,
                )
                sector["leaders"] = []

        # 4. Strategy Suggestions
        strategy_suggestions: list[dict[str, Any]] = []
        try:
            strategy_suggestions = await self._generate_strategy_suggestions(
                market, tenant_id, top_sectors
            )
        except Exception as exc:
            logger.error("Strategy suggestions failed for %s: %s", market, exc)
            strategy_suggestions = []

        # 5. Format Report
        formatted_report = format_daily_report(
            market_overview=market_overview,
            top_sectors=top_sectors,
            strategy_suggestions=strategy_suggestions,
            market=market,
            report_date=report_date,
        )

        # 构建完整报告
        report = {
            "ok": True,
            "market": market,
            "date": report_date,
            "market_overview": market_overview,
            "top_sectors": top_sectors,
            "strategy_suggestions": strategy_suggestions,
            "formatted_report": formatted_report,
        }

        # 6. Save to Supabase
        try:
            await self._save_report(
                tenant_id=tenant_id,
                market=market,
                report_date=report_date,
                report=report,
            )
        except Exception as exc:
            logger.error("Failed to save report to Supabase: %s", exc)
            # 不阻断返回，报告仍然返回给调用方

        return report

    async def generate_all_reports(
        self,
        tenant_id: str | None = None,
        report_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        生成所有市场日报（CN, US, HK），并发执行。

        Args:
            tenant_id: 用户租户 ID，为 None 时生成系统级公共报告。
            report_date: 报告日期，默认当天。

        Returns:
            三个市场日报的列表。
        """
        markets = ["CN", "US", "HK"]

        tasks = [
            self.generate_daily_report(
                market=m,
                tenant_id=tenant_id,
                report_date=report_date,
            )
            for m in markets
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        reports: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Report generation failed for %s: %s",
                    markets[i],
                    result,
                )
                reports.append({
                    "ok": False,
                    "market": markets[i],
                    "message": f"Report generation failed: {result}",
                })
            else:
                reports.append(result)

        return reports

    async def _generate_strategy_suggestions(
        self,
        market: str,
        tenant_id: str | None,
        top_sectors: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        基于持仓和板块表现生成策略建议。

        Args:
            market: 市场标识。
            tenant_id: 用户租户 ID。
            top_sectors: 板块排名列表。

        Returns:
            策略建议列表。
        """
        suggestions: list[dict[str, Any]] = []

        # 获取用户持仓
        positions = await self._fetch_positions(tenant_id, market)

        if not positions:
            return suggestions

        # 构建板块涨跌幅查找表
        sector_change_map: dict[str, float | None] = {}
        for sector in top_sectors:
            sector_name = sector.get("name", "").lower()
            cr = sector.get("change_rate")
            sector_change_map[sector_name] = cr

        # 持仓匹配板块并生成建议
        for pos in positions:
            symbol = pos.get("symbol", "")
            pos_market = pos.get("market", "")
            if pos_market != market:
                continue

            # 尝试匹配板块
            pos_sector = pos.get("sector", "").lower()
            sector_cr = sector_change_map.get(pos_sector)

            action = self._determine_action(sector_cr, pos)
            reason = self._generate_reason(
                symbol, pos.get("stock_name", pos.get("name", "")),
                pos_sector, sector_cr, action
            )

            suggestions.append({
                "symbol": symbol,
                "action": action,
                "reason": reason,
            })

        return suggestions

    def _determine_action(
        self,
        sector_change_rate: float | None,
        position: dict[str, Any],
    ) -> str:
        """
        根据板块表现和持仓状态确定策略动作。

        Args:
            sector_change_rate: 板块涨跌幅。
            position: 持仓信息。

        Returns:
            策略动作，"HOLD" / "ADD" / "REDUCE" / "WATCH"。
        """
        if sector_change_rate is None:
            return "HOLD"

        if sector_change_rate > 3:
            # 板块强势上涨
            return "REDUCE"  # 可考虑减仓锁定利润
        if sector_change_rate > 1:
            # 板块温和上涨
            return "HOLD"
        if sector_change_rate > -1:
            # 板块横盘
            return "HOLD"
        if sector_change_rate > -3:
            # 板块回调
            return "WATCH"  # 关注低吸机会
        # 板块大幅下跌
        return "WATCH"

    def _generate_reason(
        self,
        symbol: str,
        name: str,
        sector: str,
        sector_cr: float | None,
        action: str,
    ) -> str:
        """
        生成策略建议理由。

        Args:
            symbol: 股票代码。
            name: 股票名称。
            sector: 所属板块。
            sector_cr: 板块涨跌幅。
            action: 策略动作。

        Returns:
            策略建议理由文本。
        """
        display = f"{name}({symbol})" if name else symbol
        sector_display = f"{sector}板块" if sector else "所属板块"

        if sector_cr is None:
            return f"{display}：{sector_display}数据暂不可用，建议持有观望"

        cr_str = f"+{sector_cr:.2f}%" if sector_cr > 0 else f"{sector_cr:.2f}%"

        reason_templates = {
            "HOLD": f"{display}：{sector_display}今日{cr_str}，建议持有观望",
            "ADD": f"{display}：{sector_display}今日{cr_str}，趋势向好可考虑加仓",
            "REDUCE": f"{display}：{sector_display}今日{cr_str}，涨幅较大可考虑减仓锁定利润",
            "WATCH": f"{display}：{sector_display}今日{cr_str}，回调中可关注低吸机会",
        }

        return reason_templates.get(action, f"{display}：建议持有观望")

    async def _fetch_positions(
        self,
        tenant_id: str | None,
        market: str,
    ) -> list[dict[str, Any]]:
        """
        从 Supabase 获取用户持仓。

        Args:
            tenant_id: 用户租户 ID。
            market: 市场标识。

        Returns:
            持仓列表。
        """
        if not tenant_id or not self.supabase_url or not self.supabase_key:
            logger.debug(
                "Skipping position fetch: tenant_id=%s, supabase configured=%s",
                tenant_id,
                bool(self.supabase_url and self.supabase_key),
            )
            return []

        try:
            from openclaw.gateway.supabase_client import create_skill_client

            client = create_skill_client(
                "opportunity-hunter",
                self.supabase_key,
                self.supabase_url,
            )

            resp = (
                await client.table("position_snapshots")
                .select("symbol, market, stock_name, total_quantity, average_cost")
                .eq("tenant_id", tenant_id)
                .eq("market", market)
                .gt("total_quantity", 0)
                .execute()
            )

            return resp.data or []
        except ImportError:
            logger.warning("supabase package not available, skipping position fetch")
            return []
        except Exception as exc:
            logger.error("Failed to fetch positions: %s", exc)
            return []

    async def _save_report(
        self,
        tenant_id: str | None,
        market: str,
        report_date: str,
        report: dict[str, Any],
    ) -> None:
        """
        将报告写入 Supabase daily_reports 表。

        使用 UPSERT（ON CONFLICT UPDATE）保证幂等性。

        Args:
            tenant_id: 用户租户 ID。
            market: 市场标识。
            report_date: 报告日期。
            report: 完整报告字典。
        """
        if not self.supabase_url or not self.supabase_key:
            logger.warning("Supabase not configured, skipping report save")
            return

        try:
            from openclaw.gateway.supabase_client import create_skill_client

            client = create_skill_client(
                "opportunity-hunter",
                self.supabase_key,
                self.supabase_url,
            )

            report_type = REPORT_TYPE_MAP.get(market, f"opportunity_{market.lower()}")

            payload = {
                "tenant_id": tenant_id,
                "report_type": report_type,
                "report_date": report_date,
                "market": market,
                "content": {
                    "market_overview": report.get("market_overview", {}),
                    "top_sectors": report.get("top_sectors", []),
                    "strategy_suggestions": report.get("strategy_suggestions", []),
                },
                "formatted_markdown": report.get("formatted_report", ""),
            }

            # 尝试 UPSERT：先尝试插入，冲突则更新
            try:
                resp = (
                    await client.table("daily_reports")
                    .insert(payload)
                    .execute()
                )
                logger.info(
                    "Report saved: market=%s, date=%s, id=%s",
                    market,
                    report_date,
                    resp.data[0].get("id") if resp.data else "unknown",
                )
            except Exception as insert_exc:
                # 如果是唯一约束冲突，尝试更新
                error_msg = str(insert_exc).lower()
                if "duplicate" in error_msg or "unique" in error_msg or "23505" in error_msg:
                    logger.info(
                        "Report already exists, updating: market=%s, date=%s",
                        market,
                        report_date,
                    )
                    update_data = {
                        "content": payload["content"],
                        "formatted_markdown": payload["formatted_markdown"],
                    }
                    await (
                        client.table("daily_reports")
                        .update(update_data)
                        .eq("tenant_id", tenant_id or "")
                        .eq("report_type", report_type)
                        .eq("report_date", report_date)
                        .execute()
                    )
                    logger.info(
                        "Report updated: market=%s, date=%s",
                        market,
                        report_date,
                    )
                else:
                    raise

        except ImportError:
            logger.warning("supabase package not available, skipping report save")
        except Exception as exc:
            logger.error("Failed to save report to Supabase: %s", exc)
            raise
