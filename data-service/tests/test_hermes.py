"""
Tests for openclaw.skills.opportunity-hunter.hermes (HermesOrchestrator)

Covers:
- generate_daily_report: unknown market, CN success, scanner failure
- generate_all_reports: 3 markets
- _determine_action: HOLD / REDUCE / WATCH / None thresholds
- _generate_reason: HOLD / REDUCE reason text
- _save_report: Supabase not configured → skips save
"""
import importlib
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so we can import openclaw.*
# ---------------------------------------------------------------------------
_PROJECT_ROOT = "/Users/jerry.wu/Documents/vibecodingapp/ai-holdings-analyzer-v2"
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Import the hermes module using importlib (directory name contains hyphens)
hermes_mod = importlib.import_module("openclaw.skills.opportunity-hunter.hermes")
HermesOrchestrator = hermes_mod.HermesOrchestrator


# ====================================================================== #
# Fixtures
# ====================================================================== #


@pytest.fixture
def orchestrator():
    """HermesOrchestrator with no Supabase config (skips save)."""
    return HermesOrchestrator(
        data_service_url="http://localhost:8000",
        supabase_url="",
        supabase_key="",
    )


# ====================================================================== #
# generate_daily_report
# ====================================================================== #


@pytest.mark.asyncio
async def test_generate_daily_report_unknown_market(orchestrator):
    """未知市场标识 → 返回 ok=False。"""
    result = await orchestrator.generate_daily_report(market="XX")

    assert result["ok"] is False
    assert "Unknown market: XX" in result["message"]
    assert result["market"] == "XX"


@pytest.mark.asyncio
async def test_generate_daily_report_cn_success(orchestrator):
    """CN 市场正常生成日报 → 报告结构完整。"""
    mock_market_overview = {
        "advance_count": 2500,
        "decline_count": 1800,
        "flat_count": 200,
        "total_volume": 8500000000,
        "index_quotes": [
            {"symbol": "SH000001", "name": "上证指数", "price": 3200.5, "change_rate": 0.85}
        ],
    }
    mock_top_sectors = [
        {"name": "券商", "symbol": "SH512880", "change_rate": 3.5, "volume": 120000000},
        {"name": "白酒", "symbol": "SH512690", "change_rate": 1.2, "volume": 98000000},
    ]
    mock_formatted_report = "## 市场日报 - A股 - 2026-04-23\n..."

    with patch.object(hermes_mod, "scan_market", new_callable=AsyncMock) as mock_scan, \
         patch.object(hermes_mod, "hunt_sectors", new_callable=AsyncMock) as mock_hunt, \
         patch.object(hermes_mod, "select_leaders", new_callable=AsyncMock) as mock_leaders, \
         patch.object(hermes_mod, "format_daily_report", return_value=mock_formatted_report) as mock_format:

        mock_scan.return_value = mock_market_overview
        mock_hunt.return_value = mock_top_sectors
        mock_leaders.return_value = [
            {"symbol": "SH601688", "name": "华泰证券", "change_rate": 5.2}
        ]

        # Patch _generate_strategy_suggestions to avoid position fetch
        with patch.object(
            orchestrator, "_generate_strategy_suggestions",
            new_callable=AsyncMock, return_value=[]
        ):
            result = await orchestrator.generate_daily_report(
                market="CN", report_date="2026-04-23"
            )

    assert result["ok"] is True
    assert result["market"] == "CN"
    assert result["date"] == "2026-04-23"
    assert result["market_overview"] == mock_market_overview
    assert result["top_sectors"] == mock_top_sectors
    assert result["formatted_report"] == mock_formatted_report
    assert result["strategy_suggestions"] == []

    # Verify scan_market was called with correct args
    mock_scan.assert_awaited_once_with("CN", "http://localhost:8000")
    mock_hunt.assert_awaited_once_with("CN", "http://localhost:8000")
    # select_leaders should be called for top 2 sectors ([:5])
    assert mock_leaders.await_count == 2
    mock_format.assert_called_once()


@pytest.mark.asyncio
async def test_generate_daily_report_scanner_failure(orchestrator):
    """scan_market 抛异常 → market_overview 使用默认空值。"""
    with patch.object(hermes_mod, "scan_market", new_callable=AsyncMock) as mock_scan, \
         patch.object(hermes_mod, "hunt_sectors", new_callable=AsyncMock, return_value=[]) as mock_hunt, \
         patch.object(hermes_mod, "select_leaders", new_callable=AsyncMock) as mock_leaders, \
         patch.object(hermes_mod, "format_daily_report", return_value="fallback report") as mock_format:

        mock_scan.side_effect = RuntimeError("data-service unreachable")

        with patch.object(
            orchestrator, "_generate_strategy_suggestions",
            new_callable=AsyncMock, return_value=[]
        ):
            result = await orchestrator.generate_daily_report(
                market="CN", report_date="2026-04-23"
            )

    assert result["ok"] is True
    # 验证 market_overview 使用了默认值
    assert result["market_overview"]["advance_count"] == 0
    assert result["market_overview"]["decline_count"] == 0
    assert result["market_overview"]["flat_count"] == 0
    assert result["market_overview"]["total_volume"] == 0
    assert result["market_overview"]["index_quotes"] == []


# ====================================================================== #
# generate_all_reports
# ====================================================================== #


@pytest.mark.asyncio
async def test_generate_all_reports(orchestrator):
    """generate_all_reports 返回 3 个市场报告（CN/US/HK）。"""
    cn_report = {"ok": True, "market": "CN", "date": "2026-04-23"}
    us_report = {"ok": True, "market": "US", "date": "2026-04-23"}
    hk_report = {"ok": True, "market": "HK", "date": "2026-04-23"}

    with patch.object(
        orchestrator, "generate_daily_report",
        new_callable=AsyncMock,
        side_effect=[cn_report, us_report, hk_report],
    ) as mock_gen:
        results = await orchestrator.generate_all_reports(report_date="2026-04-23")

    assert len(results) == 3
    assert results[0]["market"] == "CN"
    assert results[1]["market"] == "US"
    assert results[2]["market"] == "HK"
    assert mock_gen.await_count == 3


# ====================================================================== #
# _determine_action
# ====================================================================== #


def test_determine_action_hold(orchestrator):
    """板块涨跌幅在 -1 ~ 3 之间 → HOLD。"""
    # sector_change_rate = 0.5 → 在 (-1, 3) 区间
    assert orchestrator._determine_action(0.5, {}) == "HOLD"


def test_determine_action_reduce(orchestrator):
    """板块涨跌幅 > 3 → REDUCE（减仓锁定利润）。"""
    assert orchestrator._determine_action(4.0, {}) == "REDUCE"


def test_determine_action_watch(orchestrator):
    """板块涨跌幅 < -1 → WATCH（关注低吸机会）。"""
    assert orchestrator._determine_action(-2.5, {}) == "WATCH"


def test_determine_action_none(orchestrator):
    """板块涨跌幅为 None → HOLD（数据不可用，默认持有观望）。"""
    assert orchestrator._determine_action(None, {}) == "HOLD"


# ====================================================================== #
# _generate_reason
# ====================================================================== #


def test_generate_reason_hold(orchestrator):
    """HOLD 动作的理由文本包含关键信息。"""
    reason = orchestrator._generate_reason(
        symbol="SH600519",
        name="贵州茅台",
        sector="白酒",
        sector_cr=0.5,
        action="HOLD",
    )

    assert "贵州茅台(SH600519)" in reason
    assert "白酒板块" in reason
    assert "+0.50%" in reason
    assert "持有观望" in reason


def test_generate_reason_reduce(orchestrator):
    """REDUCE 动作的理由文本包含减仓锁定利润关键词。"""
    reason = orchestrator._generate_reason(
        symbol="SH512880",
        name="券商ETF",
        sector="券商",
        sector_cr=4.0,
        action="REDUCE",
    )

    assert "券商ETF(SH512880)" in reason
    assert "券商板块" in reason
    assert "+4.00%" in reason
    assert "减仓锁定利润" in reason


# ====================================================================== #
# _save_report — Supabase not configured
# ====================================================================== #


@pytest.mark.asyncio
async def test_save_report_supabase_not_configured(orchestrator):
    """Supabase 未配置 → _save_report 静默跳过，不抛异常。"""
    # orchestrator fixture 已设置 supabase_url="" 和 supabase_key=""
    # 调用 _save_report 应不报错
    await orchestrator._save_report(
        tenant_id=None,
        market="CN",
        report_date="2026-04-23",
        report={"market_overview": {}, "top_sectors": [], "strategy_suggestions": [], "formatted_report": ""},
    )
    # 无异常即通过
