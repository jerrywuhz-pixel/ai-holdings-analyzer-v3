#!/usr/bin/env python3
"""
Build a single-message Hermes WeChat trace bundle.

The trace is read-only. With a DATABASE_URL it queries the DB for binding,
receipt, persistence, delivery, and message-event evidence. Without DB access it
still writes a structured bundle showing the exact missing proof.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".omx" / "evidence"
DEFAULT_WINDOW_MINUTES = 60
MAX_ROWS = 20

SECRET_RE = re.compile(
    r"(?i)([\"']?\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|DATABASE_URL|DB_URL|DSN)[A-Z0-9_]*[\"']?)"
    r"(\s*[:=]\s*[\"']?)([^\"'\s,}]+)"
)
POSTGRES_PASSWORD_RE = re.compile(r"(postgres(?:ql)?://[^:\s]+:)([^@\s]+)(@)", re.IGNORECASE)

TRACE_STAGES = [
    "input",
    "binding",
    "bridge_receipt",
    "hermes_ingress",
    "stock_analysis_persistence",
    "delivery",
    "user_visible",
]


@dataclass
class TraceStage:
    name: str
    status: str
    detail: str
    rows: list[dict[str, Any]] | None = None


def redact_text(value: str) -> str:
    value = POSTGRES_PASSWORD_RE.sub(r"\1<redacted>\3", value)
    return SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", value)


def json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_rows(rows: list[dict[str, Any]], *, max_rows: int = MAX_ROWS) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows[:max_rows]:
        if "row" in row and isinstance(row["row"], dict):
            normalized.append(row["row"])
        else:
            normalized.append(row)
    return json.loads(redact_text(json.dumps(normalized, ensure_ascii=False, default=json_default)))


def text_filter(rows: list[dict[str, Any]], message_text: str) -> list[dict[str, Any]]:
    needle = message_text.strip()
    if not needle:
        return rows
    compact_needle = needle[:80].lower()
    matched = [
        row
        for row in rows
        if compact_needle in json.dumps(row, ensure_ascii=False, default=json_default).lower()
    ]
    return matched or rows


def db_url_from_env(explicit: str = "") -> str:
    if explicit:
        return explicit
    load_env_file(PROJECT_ROOT / ".env.server")
    load_env_file(PROJECT_ROOT / ".env")
    return os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or ""


def table_exists(conn: Any, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) AS table_name", (f"public.{table_name}",))
        row = cur.fetchone()
    return bool(row and row.get("table_name"))


def fetch_rows(conn: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def collect_db_trace(
    *,
    db_url: str,
    message_text: str,
    sent_at: datetime,
    window_minutes: int,
    tenant_id: str = "",
    channel_account_id: str = "",
    message_id: str = "",
) -> tuple[list[TraceStage], dict[str, Any]]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:  # noqa: BLE001 - missing DB driver is a trace gap, not a script crash
        return (
            [TraceStage("input", "unknown", f"psycopg unavailable: {exc}", [])],
            {"db_available": False, "reason": "psycopg_unavailable"},
        )

    start = sent_at - timedelta(minutes=window_minutes)
    end = sent_at + timedelta(minutes=window_minutes)
    stages: list[TraceStage] = []
    meta = {"db_available": True, "window_start": start.isoformat(), "window_end": end.isoformat()}

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        binding_rows = []
        if table_exists(conn, "channel_bindings"):
            where = ["channel IN ('hermes_wechat', 'openclaw_wechat')"]
            params: list[Any] = []
            if tenant_id:
                where.append("tenant_id::text = %s")
                params.append(tenant_id)
            if channel_account_id:
                where.append(
                    "(openclaw_account_id = %s OR channel_user_ref = %s "
                    "OR to_jsonb(channel_bindings)->>'channel_account_id' = %s "
                    "OR binding_metadata::text ILIKE %s)"
                )
                params.extend([channel_account_id, channel_account_id, channel_account_id, f"%{channel_account_id}%"])
            binding_rows = fetch_rows(
                conn,
                f"""
                SELECT to_jsonb(channel_bindings) AS row
                FROM public.channel_bindings
                WHERE {' AND '.join(where)}
                ORDER BY updated_at DESC
                LIMIT 10
                """,
                tuple(params),
            )
        binding_rows = normalize_rows(binding_rows)
        stages.append(
            TraceStage(
                "binding",
                "pass" if binding_rows else "gap",
                f"{len(binding_rows)} active/recent WeChat binding row(s) matched",
                binding_rows,
            )
        )

        receipt_rows: list[dict[str, Any]] = []
        if table_exists(conn, "wechat_clawbot_message_receipts"):
            receipt_rows = fetch_rows(
                conn,
                """
                SELECT to_jsonb(wechat_clawbot_message_receipts) AS row
                FROM public.wechat_clawbot_message_receipts
                WHERE created_at BETWEEN %s AND %s
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (start, end),
            )
        receipt_rows = text_filter(normalize_rows(receipt_rows), message_text)
        stages.append(
            TraceStage(
                "bridge_receipt",
                "pass" if receipt_rows else "unknown",
                f"{len(receipt_rows)} bridge receipt row(s) found in window",
                receipt_rows[:MAX_ROWS],
            )
        )

        agent_rows = []
        if table_exists(conn, "agent_runs"):
            where = ["entry_surface = 'wechat'", "created_at BETWEEN %s AND %s"]
            params = [start, end]
            if tenant_id:
                where.append("tenant_id::text = %s")
                params.append(tenant_id)
            if message_id:
                where.append("(input_refs::text ILIKE %s OR page_context::text ILIKE %s OR idempotency_key ILIKE %s)")
                params.extend([f"%{message_id}%", f"%{message_id}%", f"%{message_id}%"])
            elif message_text:
                snippet = f"%{message_text.strip()[:80]}%"
                where.append("(input_refs::text ILIKE %s OR page_context::text ILIKE %s OR output_refs::text ILIKE %s)")
                params.extend([snippet, snippet, snippet])
            agent_rows = fetch_rows(
                conn,
                f"""
                SELECT to_jsonb(agent_runs) AS row
                FROM public.agent_runs
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC
                LIMIT 20
                """,
                tuple(params),
            )
        agent_rows = normalize_rows(agent_rows)
        stages.append(
            TraceStage(
                "hermes_ingress",
                "pass" if agent_rows else "unknown",
                f"{len(agent_rows)} wechat agent_run row(s) found",
                agent_rows,
            )
        )

        run_ids = [row.get("id") for row in agent_rows if row.get("id")]
        persistence_rows = collect_persistence_rows(conn, start, end, tenant_id=tenant_id, run_ids=run_ids)
        stages.append(
            TraceStage(
                "stock_analysis_persistence",
                "pass" if persistence_rows else "unknown",
                f"{len(persistence_rows)} persistence row(s) found across artifacts/signals/discipline",
                persistence_rows,
            )
        )

        delivery_rows = []
        if table_exists(conn, "delivery_outbox"):
            where = ["created_at BETWEEN %s AND %s"]
            params = [start, end]
            if tenant_id:
                where.append("tenant_id::text = %s")
                params.append(tenant_id)
            delivery_rows = fetch_rows(
                conn,
                f"""
                SELECT to_jsonb(delivery_outbox) AS row
                FROM public.delivery_outbox
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC
                LIMIT 20
                """,
                tuple(params),
            )
        delivery_rows = normalize_rows(delivery_rows)
        stages.append(
            TraceStage(
                "delivery",
                "pass" if delivery_rows else "unknown",
                f"{len(delivery_rows)} delivery_outbox row(s) found in window",
                delivery_rows,
            )
        )

        event_rows = []
        if table_exists(conn, "message_events"):
            event_rows = fetch_rows(
                conn,
                """
                SELECT to_jsonb(message_events) AS row
                FROM public.message_events
                WHERE occurred_at BETWEEN %s AND %s
                ORDER BY occurred_at DESC
                LIMIT 20
                """,
                (start, end),
            )
        event_rows = normalize_rows(event_rows)
        stages.append(
            TraceStage(
                "user_visible",
                "pass" if any(str(row.get("event_type", "")).lower() == "delivered" for row in event_rows) else "unknown",
                f"{len(event_rows)} message_event row(s) found in window",
                event_rows,
            )
        )

    return stages, meta


def collect_persistence_rows(
    conn: Any,
    start: datetime,
    end: datetime,
    *,
    tenant_id: str,
    run_ids: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    run_filter = tuple(run_ids) if run_ids else tuple()

    if table_exists(conn, "artifact_registry"):
        where = ["created_at BETWEEN %s AND %s"]
        params: list[Any] = [start, end]
        if tenant_id:
            where.append("tenant_id::text = %s")
            params.append(tenant_id)
        if run_filter:
            where.append("source_run_id::text = ANY(%s)")
            params.append(list(run_filter))
        artifact_rows = fetch_rows(
            conn,
            f"SELECT 'artifact_registry' AS source, to_jsonb(artifact_registry) AS row FROM public.artifact_registry WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT 10",
            tuple(params),
        )
        rows.extend(normalize_rows(artifact_rows))

    if table_exists(conn, "decision_signals"):
        where = ["created_at BETWEEN %s AND %s"]
        params = [start, end]
        if tenant_id:
            where.append("tenant_id::text = %s")
            params.append(tenant_id)
        if run_filter:
            where.append("source_run_id::text = ANY(%s)")
            params.append(list(run_filter))
        signal_rows = fetch_rows(
            conn,
            f"SELECT 'decision_signals' AS source, to_jsonb(decision_signals) AS row FROM public.decision_signals WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT 10",
            tuple(params),
        )
        rows.extend(normalize_rows(signal_rows))

    if table_exists(conn, "discipline_checks"):
        where = ["created_at BETWEEN %s AND %s"]
        params = [start, end]
        if tenant_id:
            where.append("tenant_id::text = %s")
            params.append(tenant_id)
        if run_filter:
            where.append("agent_run_id::text = ANY(%s)")
            params.append(list(run_filter))
        discipline_rows = fetch_rows(
            conn,
            f"SELECT 'discipline_checks' AS source, to_jsonb(discipline_checks) AS row FROM public.discipline_checks WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT 10",
            tuple(params),
        )
        rows.extend(normalize_rows(discipline_rows))

    return rows


def classify_trace(stages: list[TraceStage], *, db_available: bool, screenshot: str = "") -> str:
    if not db_available:
        return "UNKNOWN"
    by_name = {stage.name: stage for stage in stages}
    binding = by_name.get("binding")
    receipt = by_name.get("bridge_receipt")
    ingress = by_name.get("hermes_ingress")
    persistence = by_name.get("stock_analysis_persistence")
    delivery = by_name.get("delivery")

    if binding and binding.status == "gap":
        return "NO_ACTIVE_BINDING_EVIDENCE"
    if ingress and ingress.status == "pass" and persistence and persistence.status == "pass":
        if screenshot or (delivery and delivery.status == "pass"):
            return "ARRIVED_PERSISTED_USER_VISIBLE"
        return "ARRIVED_AND_PERSISTED"
    if ingress and ingress.status == "pass":
        return "ARRIVED_BUT_PERSISTENCE_NOT_PROVEN"
    if receipt and receipt.status == "pass":
        return "RECEIVED_BY_BRIDGE_BUT_INGRESS_NOT_PROVEN"
    return "NOT_RECEIVED_OR_NOT_PROVEN"


def build_trace_bundle(
    *,
    message_text: str,
    sent_at: datetime,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    tenant_id: str = "",
    channel_account_id: str = "",
    message_id: str = "",
    db_url: str = "",
    screenshot: str = "",
) -> dict[str, Any]:
    input_stage = TraceStage(
        "input",
        "collected",
        "Trace input captured",
        [
            {
                "message_text": message_text,
                "sent_at": sent_at.isoformat(),
                "window_minutes": window_minutes,
                "tenant_id": tenant_id,
                "channel_account_id": channel_account_id,
                "message_id": message_id,
                "screenshot": screenshot,
            }
        ],
    )

    resolved_db_url = db_url_from_env(db_url)
    if not resolved_db_url:
        stages = [
            input_stage,
            TraceStage("binding", "unknown", "DATABASE_URL/SUPABASE_DB_URL not configured; DB trace skipped", []),
            TraceStage("bridge_receipt", "unknown", "DB trace skipped", []),
            TraceStage("hermes_ingress", "unknown", "DB trace skipped", []),
            TraceStage("stock_analysis_persistence", "unknown", "DB trace skipped", []),
            TraceStage("delivery", "unknown", "DB trace skipped", []),
            TraceStage("user_visible", "pass" if screenshot else "unknown", "Screenshot supplied" if screenshot else "No screenshot or delivery event supplied", []),
        ]
        meta = {"db_available": False, "reason": "missing_database_url"}
    else:
        db_stages, meta = collect_db_trace(
            db_url=resolved_db_url,
            message_text=message_text,
            sent_at=sent_at,
            window_minutes=window_minutes,
            tenant_id=tenant_id,
            channel_account_id=channel_account_id,
            message_id=message_id,
        )
        stages = [input_stage, *db_stages]
        if screenshot:
            stages.append(TraceStage("screenshot", "pass", "User supplied screenshot evidence", [{"path": screenshot}]))

    verdict = classify_trace(stages, db_available=bool(meta.get("db_available")), screenshot=screenshot)
    return {
        "schema_version": "hermes_wechat_trace_bundle_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "meta": meta,
        "stages": [asdict(stage) for stage in stages],
    }


def write_bundle(bundle: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    json_path = output_dir / f"hermes-wechat-trace-{stamp}.json"
    md_path = output_dir / f"hermes-wechat-trace-{stamp}.md"
    json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(bundle), encoding="utf-8")
    return json_path, md_path


def render_markdown(bundle: dict[str, Any]) -> str:
    lines = [
        "# Hermes WeChat Trace Bundle",
        "",
        f"- Generated: `{bundle['generated_at']}`",
        f"- Verdict: **{bundle['verdict']}**",
        "",
    ]
    for stage in bundle["stages"]:
        lines.extend([f"## {stage['name']}", "", f"- Status: `{stage['status']}`", f"- Detail: {stage['detail']}"])
        rows = stage.get("rows") or []
        if rows:
            preview = json.dumps(rows, ensure_ascii=False, indent=2, default=json_default)
            if len(preview) > 3000:
                preview = preview[:3000] + "\n... <truncated>"
            lines.extend(["", "```json", preview, "```"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a single-message Hermes WeChat trace bundle.")
    parser.add_argument("--message-text", required=True)
    parser.add_argument("--sent-at", default="", help="ISO timestamp. Defaults to now UTC.")
    parser.add_argument("--window-minutes", type=int, default=DEFAULT_WINDOW_MINUTES)
    parser.add_argument("--tenant-id", default="")
    parser.add_argument("--channel-account-id", default="")
    parser.add_argument("--message-id", default="")
    parser.add_argument("--db-url", default="")
    parser.add_argument("--screenshot", default="")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    bundle = build_trace_bundle(
        message_text=args.message_text,
        sent_at=parse_timestamp(args.sent_at),
        window_minutes=args.window_minutes,
        tenant_id=args.tenant_id,
        channel_account_id=args.channel_account_id,
        message_id=args.message_id,
        db_url=args.db_url,
        screenshot=args.screenshot,
    )
    json_path, md_path = write_bundle(bundle, output_dir=args.output_dir)
    print(json.dumps({"ok": True, "verdict": bundle["verdict"], "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
