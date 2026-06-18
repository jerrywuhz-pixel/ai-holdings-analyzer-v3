from scripts.hermes_explain_routing import explain_routing, quote_priority


def test_financial_query_prefers_gpt_before_minimax(monkeypatch):
    monkeypatch.setenv("HERMES_DEEP_PROVIDER", "openai-codex")
    monkeypatch.setenv("HERMES_DEEP_MODEL", "gpt-5.5")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M3")
    monkeypatch.delenv("GBRAIN_LIVE_MODELS_ENABLED", raising=False)

    summary = explain_routing(query="分析一下 NVDA", symbol="NVDA", complexity="standard")

    routes = summary["model_routing"]["routes"]
    assert routes[0]["provider"] == "openai-codex"
    assert routes[0]["model"] == "gpt-5.5"
    assert routes[1]["provider"] == "minimax"
    assert "finance" in summary["model_routing"]["decision"] or "金融" in summary["model_routing"]["decision"] or "investment" in summary["model_routing"]["decision"]


def test_light_non_financial_query_uses_minimax_primary(monkeypatch):
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M3")

    summary = explain_routing(query="你好，今天怎么安排？", complexity="standard")

    assert summary["model_routing"]["routes"][0]["provider"] == "minimax"


def test_investment_job_type_overrides_standard_complexity(monkeypatch):
    monkeypatch.setenv("HERMES_DEEP_PROVIDER", "openai-codex")

    summary = explain_routing(query="run job", job_type="equity_analysis", complexity="standard")

    assert summary["model_routing"]["routes"][0]["provider"] == "openai-codex"
    assert "equity_analysis" in summary["model_routing"]["decision"]


def test_quote_priority_respects_longbridge_and_akshare(monkeypatch):
    monkeypatch.setenv("LONGBRIDGE_MCP_ACCESS_TOKEN", "token")
    monkeypatch.setenv("AKSHARE_ENABLED", "true")

    market, priority, reasons = quote_priority("NVDA")

    assert market == "US"
    assert priority[:2] == ["longbridge", "yahoo"]
    assert priority[-1] == "akshare"
    assert any("Longbridge" in reason for reason in reasons)


def test_quote_priority_excludes_akshare_by_default(monkeypatch):
    monkeypatch.delenv("AKSHARE_ENABLED", raising=False)

    _market, priority, _reasons = quote_priority("SH600519")

    assert priority == ["tushare", "ftshare", "yahoo"]


def test_explicit_source_override():
    _market, priority, reasons = quote_priority("AAPL", prefer="futu")

    assert priority == ["futu"]
    assert "explicit source=futu" in reasons[0]
