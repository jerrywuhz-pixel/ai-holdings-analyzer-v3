import importlib.util
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "scripts" / "p0_cron_dispatcher.py"


def load_dispatcher(monkeypatch, task, db_path):
    monkeypatch.setenv("P0_TASK", task)
    monkeypatch.setenv("P0_LOCAL_HOLDINGS_DB", str(db_path))
    module_name = "p0_cron_dispatcher_%s_%s" % (task.replace("-", "_"), id(db_path))
    spec = importlib.util.spec_from_file_location(module_name, DISPATCHER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def create_holdings_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE positions (
          owner_id TEXT,
          symbol TEXT,
          market TEXT,
          quantity REAL,
          avg_cost REAL,
          currency TEXT,
          updated_at TEXT
        );
        CREATE TABLE option_positions (
          owner_id TEXT,
          underlying TEXT,
          option_type TEXT,
          position_side TEXT,
          strike REAL,
          expiry TEXT,
          contracts REAL,
          avg_premium REAL,
          currency TEXT,
          market TEXT,
          updated_at TEXT
        );
        CREATE TABLE trades (
          id TEXT,
          owner_id TEXT,
          symbol TEXT,
          market TEXT,
          side TEXT,
          quantity REAL,
          price REAL,
          currency TEXT,
          trade_time TEXT,
          raw_input TEXT,
          draft_id TEXT,
          created_at TEXT
        );
        CREATE TABLE option_trades (
          id TEXT,
          owner_id TEXT,
          underlying TEXT,
          market TEXT,
          option_type TEXT,
          position_side TEXT,
          action TEXT,
          contracts REAL,
          strike REAL,
          expiry TEXT,
          premium REAL,
          multiplier REAL,
          currency TEXT,
          trade_time TEXT,
          raw_input TEXT,
          draft_id TEXT,
          created_at TEXT
        );
        """
    )
    con.execute(
        "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
        ("wechat-user-1", "NVDA", "US", 3, 120.5, "USD", "2026-06-18T12:00:00+08:00"),
    )
    con.execute(
        "INSERT INTO option_positions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("wechat-user-1", "NVDA", "CALL", "short", 150, "2026-07-17", 1, 2.1, "USD", "US", "2026-06-18T12:00:00+08:00"),
    )
    con.commit()
    con.close()


def test_daily_summary_upgrades_to_action_brief(monkeypatch, tmp_path):
    db_path = tmp_path / "holdings.db"
    create_holdings_db(db_path)
    module = load_dispatcher(monkeypatch, "p0-us-close-summary", db_path)
    today = datetime.now().date().isoformat()

    def fake_psql_json(_sql, timeout=15):
        return True, "", [
            {"market": "US", "sector": "半导体", "snapshot_date": today, "change_pct": 2.4, "relative_strength": 1.2},
            {"market": "US", "sector": "软件", "snapshot_date": today, "change_pct": 0.7, "relative_strength": 0.5},
            {"market": "US", "sector": "公用事业", "snapshot_date": today, "change_pct": -1.1, "relative_strength": -0.4},
        ]

    monkeypatch.setattr(module, "psql_json", fake_psql_json)
    monkeypatch.setattr(module, "refresh_market_snapshots_for_summary", lambda markets: {"status": "ok", "rows": 3})
    monkeypatch.setattr(
        module,
        "fetch_quotes_for_symbols",
        lambda symbols: (
            {
                "NVDA": {
                    "symbol": "NVDA",
                    "price": 150.0,
                    "change_rate": 3.2,
                    "timestamp": 1781712000,
                    "source": "longbridge_mcp",
                    "freshness_status": "fresh",
                    "quote_actionability": "analysis_only",
                }
            },
            {"attempts": [{"source": "longbridge", "returned": 1, "failed": []}], "failed": []},
        ),
    )
    message = module.summary_direct_message({"wechat_user_id": "wechat-user-1"}, "ok", {"data_service": "ok"})

    assert "美股日终持仓行动简报" in message
    assert "1. 组合变化" in message
    assert "2. 最大风险" in message
    assert "3. 市场走向与强势板块" in message
    assert "今日无操作" in message
    assert "NVDA：市值USD450" in message
    assert "持仓强势：NVDA 当日+3.20%" in message
    assert "持仓内强势标的可以继续跟踪" in message
    assert "4. 数据异常提醒" not in message
    assert "5. 规则命中" in message
    assert "6. 明天观察项" in message
    assert "强势：半导体 +2.40%" in message


def test_daily_summary_exposes_no_holding_context(monkeypatch, tmp_path):
    db_path = tmp_path / "holdings.db"
    create_holdings_db(db_path)
    module = load_dispatcher(monkeypatch, "p0-cn-close-summary", db_path)

    def fake_psql_json(_sql, timeout=15):
        return True, "", []

    monkeypatch.setattr(module, "psql_json", fake_psql_json)
    monkeypatch.setattr(module, "refresh_market_snapshots_for_summary", lambda markets: {"status": "degraded", "rows": 0})
    monkeypatch.setattr(module, "fetch_quotes_for_symbols", lambda symbols: ({}, {"attempts": [], "failed": []}))
    message = module.summary_direct_message({"wechat_user_id": "wechat-user-1"}, "ok", {})

    assert "A股/港股日终持仓行动简报" in message
    assert "组合可行动性：无持仓上下文（no_holding_context）" in message
    assert "整体市场/板块数据暂不可用" in message


def test_alert_task_templates_are_specific(monkeypatch, tmp_path):
    db_path = tmp_path / "holdings.db"
    db_path.touch()

    module = load_dispatcher(monkeypatch, "p0-broker-sync-staleness", db_path)
    assert "数据质量提醒｜持仓同步" in module.task_message({"reason": "stale"})
    assert "degrade_reason：holding_freshness_degraded" in module.task_message({"reason": "stale"})

    module = load_dispatcher(monkeypatch, "p0-price-alert-evaluator", db_path)
    assert "价格/纪律提醒｜待复核" in module.task_message({"reason": "rule_hit"})

    module = load_dispatcher(monkeypatch, "p0-backup-verify", db_path)
    message = module.task_message({"postgres_ready": False})
    assert "数据可恢复性告警" in message
    assert "actionability：数据过期" in message


def test_market_refresh_builds_and_persists_sector_snapshots(monkeypatch, tmp_path):
    db_path = tmp_path / "holdings.db"
    db_path.touch()
    module = load_dispatcher(monkeypatch, "p0-us-close-summary", db_path)

    def fake_quote_batch(symbols, source=None, max_age_seconds=None):
        if source is None:
            return {}, list(symbols)
        assert source == "longbridge"
        return {
            "SPY": {"symbol": "SPY", "price": 500, "change_rate": 1.0, "timestamp": 1781712000, "source": "longbridge_mcp", "freshness_status": "fresh", "quote_actionability": "analysis_only"},
            "QQQ": {"symbol": "QQQ", "price": 450, "change_rate": 2.5, "timestamp": 1781712000, "source": "longbridge_mcp", "freshness_status": "fresh", "quote_actionability": "analysis_only"},
            "SMH": {"symbol": "SMH", "price": 300, "change_rate": 3.1, "timestamp": 1781712000, "source": "longbridge_mcp", "freshness_status": "fresh", "quote_actionability": "analysis_only"},
        }, []

    calls = []

    def fake_psql_json(sql, timeout=25):
        calls.append(sql)
        return True, "", {"upserted": 3}

    monkeypatch.setattr(module, "_quote_batch", fake_quote_batch)
    monkeypatch.setattr(module, "psql_json", fake_psql_json)

    result = module.refresh_market_snapshots_for_summary(["US"])

    assert result["status"] == "ok"
    assert result["rows"] >= 3
    assert result["persist"]["upserted"] == 3
    assert "sector_daily_snapshots" in calls[0]
    assert "半导体" in calls[0]
