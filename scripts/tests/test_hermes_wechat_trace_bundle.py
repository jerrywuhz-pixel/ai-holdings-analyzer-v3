from datetime import datetime, timezone

from scripts.hermes_wechat_trace_bundle import (
    TraceStage,
    build_trace_bundle,
    classify_trace,
    parse_timestamp,
    text_filter,
    write_bundle,
)


def test_classify_trace_arrived_and_persisted_user_visible():
    stages = [
        TraceStage("binding", "pass", "ok", [{}]),
        TraceStage("bridge_receipt", "pass", "ok", [{}]),
        TraceStage("hermes_ingress", "pass", "ok", [{"id": "run-1"}]),
        TraceStage("stock_analysis_persistence", "pass", "ok", [{"id": "signal-1"}]),
        TraceStage("delivery", "pass", "ok", [{"status": "delivered"}]),
    ]

    assert classify_trace(stages, db_available=True) == "ARRIVED_PERSISTED_USER_VISIBLE"


def test_classify_trace_not_proven_without_db():
    assert classify_trace([], db_available=False) == "UNKNOWN"


def test_text_filter_prefers_rows_containing_message_text():
    rows = [{"text": "分析一下 INTC"}, {"text": "other"}]

    assert text_filter(rows, "分析一下 INTC") == [{"text": "分析一下 INTC"}]


def test_build_trace_bundle_without_db_writes_structured_gap(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setattr("scripts.hermes_wechat_trace_bundle.load_env_file", lambda path: None)

    bundle = build_trace_bundle(
        message_text="分析一下 CRCL",
        sent_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        db_url="",
    )
    json_path, md_path = write_bundle(bundle, output_dir=tmp_path)

    assert bundle["verdict"] == "UNKNOWN"
    assert bundle["meta"]["reason"] == "missing_database_url"
    assert json_path.exists()
    assert "DATABASE_URL" in md_path.read_text(encoding="utf-8")


def test_parse_timestamp_accepts_z_suffix():
    parsed = parse_timestamp("2026-06-17T01:02:03Z")

    assert parsed.tzinfo is not None
    assert parsed.isoformat().startswith("2026-06-17T01:02:03")
