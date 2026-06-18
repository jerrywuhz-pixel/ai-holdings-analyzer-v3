from scripts.stock_analysis_smoke import (
    StepResult,
    run_domain_tool_probe,
    run_wechat_probe,
    summarize,
)


def _analysis_result(persistence_status="skipped"):
    return {
        "tool": "stock.analysis",
        "ok": True,
        "status": "ok",
        "data": {
            "schema_version": "stock_analysis_p1",
            "symbol": "NVDA",
            "action": "watch",
            "action_label": "观察",
            "actionability_cap": "analysis_only",
            "score": 55,
            "data_quality": {"quote_source": "longbridge"},
            "persistence": {"status": persistence_status},
            "report": {
                "conclusion": "NVDA 当前结论：观察。",
                "position": "未匹配到持仓。",
                "market": "最新价 100 USD。",
                "risk": "暂无硬性阻断。",
                "discipline": "只读分析，不下单。",
                "next_steps": "加入关注清单。",
            },
            "report_constraints": {"conclusion_first": True, "module_max_chars": 200},
        },
        "source_refs": [],
    }


def test_domain_tool_probe_validates_stock_analysis_shape(monkeypatch):
    def fake_post_json(url, payload, *, internal_key=""):
        assert url.endswith("/api/hermes/domain-tools/invoke")
        assert payload["tool"] == "stock.analysis"
        assert payload["arguments"]["persist"] is False
        return 200, {"ok": True, "runtime": "hermes", "result": _analysis_result()}, "{}"

    monkeypatch.setattr("scripts.stock_analysis_smoke._post_json", fake_post_json)

    result = run_domain_tool_probe(
        base_url="http://service",
        tenant_id="tenant-1",
        symbol="NVDA",
        prompt="NVDA 怎么看",
        persist=False,
    )

    assert result.status == "passed"
    assert result.payload["data"]["report"]["conclusion"].startswith("NVDA")


def test_domain_tool_probe_fails_on_oversized_report_module(monkeypatch):
    oversized = _analysis_result()
    oversized["data"]["report"]["risk"] = "长" * 201

    def fake_post_json(url, payload, *, internal_key=""):
        return 200, {"ok": True, "runtime": "hermes", "result": oversized}, "{}"

    monkeypatch.setattr("scripts.stock_analysis_smoke._post_json", fake_post_json)

    result = run_domain_tool_probe(
        base_url="http://service",
        tenant_id="tenant-1",
        symbol="NVDA",
        prompt="NVDA 怎么看",
        persist=False,
    )

    assert result.status == "failed"
    assert "exceed 200" in result.detail


def test_wechat_probe_validates_stock_analysis_route_and_safety(monkeypatch):
    def fake_post_json(url, payload, *, internal_key=""):
        assert url.endswith("/api/hermes/wechat/messages")
        assert payload["message"]["text"] == "NVDA 怎么看"
        return 200, {
            "ok": True,
            "runtime": "hermes",
            "result_type": "stock_analysis",
            "reply_text": "NVDA 当前结论：观察。",
            "intent": {"name": "stock_analysis", "symbol": "NVDA"},
            "analysis": {
                "symbol": "NVDA",
                "actionability_cap": "analysis_only",
                "persistence": {"status": "skipped"},
                "report": _analysis_result()["data"]["report"],
            },
            "safety": {"mode": "read_only_analysis_artifact", "places_orders": False},
        }, "{}"

    monkeypatch.setattr("scripts.stock_analysis_smoke._post_json", fake_post_json)

    result = run_wechat_probe(
        base_url="http://service",
        tenant_id="tenant-1",
        symbol="NVDA",
        prompt="NVDA 怎么看",
    )

    assert result.status == "passed"
    assert result.payload["result_type"] == "stock_analysis"
    assert result.payload["safety"]["places_orders"] is False


def test_summarize_can_gate_on_persistence():
    saved = StepResult(
        "domain_tool",
        "passed",
        "ok",
        {"data": {"persistence": {"status": "saved"}}},
    )
    skipped = StepResult(
        "wechat_message",
        "passed",
        "ok",
        {"analysis": {"persistence": {"status": "skipped"}}},
    )

    assert summarize([saved], strict_persistence=True)["status"] == "pass"
    summary = summarize([saved, skipped], strict_persistence=True)
    assert summary["status"] == "fail"
    assert summary["persistence_failures"] == ["wechat_message: persistence=skipped"]
