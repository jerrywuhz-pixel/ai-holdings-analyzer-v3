import os

from scripts.e2e_smoke import load_env_file, run_live_flow, run_mock_flow, summarize


def test_run_mock_flow_returns_all_p0_steps():
    results = run_mock_flow()

    assert [result.step for result in results] == [
        "tenant",
        "broker_snapshot",
        "portfolio",
        "sell_put",
        "confirmation",
        "delivery",
    ]


def test_summarize_marks_mock_flow_as_pass():
    summary = summarize(run_mock_flow(), "mock")

    assert summary["status"] == "pass"


def test_run_live_flow_skips_missing_hooks():
    results = run_live_flow({}, allow_builtin_probes=False)

    assert all(result.status == "skipped" for result in results)


def test_summarize_strict_live_marks_skips_as_fail():
    results = run_live_flow({}, allow_builtin_probes=False)

    summary = summarize(results, "live", strict_skips=True)

    assert summary["status"] == "fail"
    assert summary["counts"]["skipped"] == 6


def test_run_live_flow_uses_builtin_data_service_probes(monkeypatch):
    def fake_post_json(url, payload):
        if url.endswith("/api/v3/broker/futu/sync"):
            return 200, {
                "ok": True,
                "data": {
                    "broker_sync_snapshot_id": "sync-1",
                    "snapshot_summary": {"positions_count": 2},
                    "source_quality": "estimated",
                },
            }, "{}"
        if url.endswith("/api/v3/options/sell-put/analyze"):
            return 200, {
                "ok": True,
                "data": {
                    "overall_actionability": "analysis_only",
                    "candidate_ranking": [{"rank": 1, "contract_symbol": "AAPL260619P175"}],
                    "candidates": [{"contract_symbol": "AAPL260619P175", "actionability": "analysis_only"}],
                },
            }, "{}"
        return 500, None, "unexpected"

    def fake_get_json(url):
        if "/api/v3/portfolio/overview" in url:
            return 200, {
                "ok": True,
                "data": {
                    "positions_count": 2,
                    "freshness": {"snapshot_id": "sync-1"},
                    "source_quality": "broker_verified",
                },
            }, "{}"
        return 500, None, "unexpected"

    monkeypatch.setattr("scripts.e2e_smoke._post_json", fake_post_json)
    monkeypatch.setattr("scripts.e2e_smoke._get_json", fake_get_json)

    results = run_live_flow({}, tenant_id="tenant-live-1")

    assert [result.status for result in results] == [
        "passed",
        "passed",
        "passed",
        "passed",
        "skipped",
        "skipped",
    ]
    assert results[0].payload["tenant_id"] == "tenant-live-1"


def test_load_env_file_keeps_existing_environment_priority(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SMOKE_TENANT_ENDPOINT=http://from-env-file\nSMOKE_PORTFOLIO_ENDPOINT=http://portfolio\n")

    monkeypatch.setenv("SMOKE_TENANT_ENDPOINT", "http://from-real-env")
    monkeypatch.delenv("SMOKE_PORTFOLIO_ENDPOINT", raising=False)

    load_env_file(env_file)

    assert os.environ["SMOKE_TENANT_ENDPOINT"] == "http://from-real-env"
    assert os.environ["SMOKE_PORTFOLIO_ENDPOINT"] == "http://portfolio"
