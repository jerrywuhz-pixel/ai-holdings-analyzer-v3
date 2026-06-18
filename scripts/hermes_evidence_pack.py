#!/usr/bin/env python3
"""
Build a replayable Hermes evidence pack.

The pack is intentionally read-only by default. It collects local OMX/session
state, recent logs, existing Hermes workflow surfaces, and optional command
outputs into paired JSON/Markdown artifacts under `.omx/evidence/`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".omx" / "evidence"
DEFAULT_LOG_LINES = 80
COMMAND_TIMEOUT_SECONDS = 90
MAX_TEXT_CHARS = 20000

EVIDENCE_SECTIONS = [
    "service_health",
    "route_truth",
    "persistence_truth",
    "delivery_truth",
    "user_surface_truth",
    "remaining_risks",
]

HERMES_SKILL_PATHS = [
    Path("/Users/jerry.wu/.codex/skills/hermes-cloud-truth-check/SKILL.md"),
    Path("/Users/jerry.wu/.codex/skills/hermes-deploy-smoke/SKILL.md"),
    Path("/Users/jerry.wu/.codex/skills/hermes-wechat-path-triage/SKILL.md"),
    Path("/Users/jerry.wu/.codex/agents/hermes-runtime-verifier.toml"),
]

SECRET_RE = re.compile(
    r"(?i)([\"']?\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|DATABASE_URL|DB_URL|DSN)[A-Z0-9_]*[\"']?)"
    r"(\s*[:=]\s*[\"']?)([^\"'\s,}]+)"
)
POSTGRES_PASSWORD_RE = re.compile(r"(postgres(?:ql)?://[^:\s]+:)([^@\s]+)(@)", re.IGNORECASE)


@dataclass
class EvidenceItem:
    label: str
    status: str
    detail: str
    payload: Any | None = None


@dataclass
class CommandResult:
    command: list[str]
    status: str
    returncode: int | None
    stdout: str
    stderr: str


def redact_text(value: str) -> str:
    value = POSTGRES_PASSWORD_RE.sub(r"\1<redacted>\3", value)
    return SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", value)


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_text_tail(path: Path, *, lines: int = DEFAULT_LOG_LINES) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return redact_text("\n".join(content[-lines:]))


def safe_json_load(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(redact_text(path.read_text(encoding="utf-8", errors="replace")))
    except Exception as exc:  # noqa: BLE001 - evidence collection should not crash on malformed state
        return {"error": str(exc), "path": str(path)}


def compact_payload(value: Any, *, max_chars: int = MAX_TEXT_CHARS) -> Any:
    raw = json.dumps(value, ensure_ascii=False, default=json_default)
    if len(raw) <= max_chars:
        return value
    return {"truncated": True, "chars": len(raw), "preview": raw[:max_chars]}


def run_command(command: list[str], *, cwd: Path = PROJECT_ROOT, timeout: int = COMMAND_TIMEOUT_SECONDS) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            command=command,
            status="passed" if completed.returncode == 0 else "failed",
            returncode=completed.returncode,
            stdout=redact_text(completed.stdout[-MAX_TEXT_CHARS:]),
            stderr=redact_text(completed.stderr[-MAX_TEXT_CHARS:]),
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command,
            status="failed",
            returncode=None,
            stdout=redact_text((exc.stdout or "")[-MAX_TEXT_CHARS:] if isinstance(exc.stdout, str) else ""),
            stderr=f"timed out after {timeout}s",
        )
    except FileNotFoundError as exc:
        return CommandResult(command=command, status="skipped", returncode=None, stdout="", stderr=str(exc))


def latest_files(directory: Path, pattern: str, *, limit: int = 2) -> list[Path]:
    if not directory.exists():
        return []
    files = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return files[:limit]


def build_evidence_pack(
    *,
    project_root: Path = PROJECT_ROOT,
    claim: str = "",
    log_lines: int = DEFAULT_LOG_LINES,
    run_foundation: bool = False,
    run_git_status: bool = True,
    include_trace_json: Path | None = None,
) -> dict[str, Any]:
    omx_dir = project_root / ".omx"
    state_dir = omx_dir / "state"
    log_dir = omx_dir / "logs"
    generated_at = datetime.now(timezone.utc)

    sections: dict[str, list[EvidenceItem]] = {section: [] for section in EVIDENCE_SECTIONS}
    commands: list[CommandResult] = []

    state_files = sorted(state_dir.glob("*.json")) if state_dir.exists() else []
    state_payload = {path.name: safe_json_load(path) for path in state_files}
    sections["service_health"].append(
        EvidenceItem(
            "local_omx_state",
            "collected" if state_payload else "unknown",
            f"{len(state_payload)} state file(s) collected from {state_dir}",
            compact_payload(state_payload, max_chars=12000),
        )
    )

    log_payload = []
    for pattern in ("turns-*.jsonl", "omx-*.jsonl", "tmux-hook-*.jsonl"):
        for path in latest_files(log_dir, pattern, limit=2):
            log_payload.append({"file": str(path.relative_to(project_root)), "tail": read_text_tail(path, lines=log_lines)})
    sections["remaining_risks"].append(
        EvidenceItem(
            "recent_omx_logs",
            "collected" if log_payload else "unknown",
            f"{len(log_payload)} recent log tail(s) collected",
            compact_payload(log_payload, max_chars=16000),
        )
    )

    skill_payload = [{"path": str(path), "exists": path.exists()} for path in HERMES_SKILL_PATHS]
    sections["route_truth"].append(
        EvidenceItem(
            "hermes_workflow_surfaces",
            "collected",
            "Existing Hermes skills/subagent that this pack can hand off to",
            skill_payload,
        )
    )

    if include_trace_json:
        trace_payload = safe_json_load(include_trace_json)
        sections["user_surface_truth"].append(
            EvidenceItem(
                "wechat_trace_bundle",
                "collected" if trace_payload else "unknown",
                f"Included trace bundle {include_trace_json}",
                compact_payload(trace_payload, max_chars=16000),
            )
        )

    if run_git_status:
        commands.append(run_command(["git", "status", "--short"], cwd=project_root, timeout=30))

    if run_foundation:
        verifier = project_root / "scripts" / "verify-foundation-runtime.sh"
        if verifier.exists():
            commands.append(run_command(["bash", str(verifier)], cwd=project_root, timeout=180))
        else:
            commands.append(CommandResult(["bash", "scripts/verify-foundation-runtime.sh"], "skipped", None, "", "script missing"))

    command_items = [asdict(result) for result in commands]
    if command_items:
        failed = [result for result in commands if result.status == "failed"]
        sections["service_health"].append(
            EvidenceItem(
                "local_commands",
                "failed" if failed else "passed",
                f"{len(commands)} command(s) executed; {len(failed)} failed",
                compact_payload(command_items, max_chars=16000),
            )
        )

    sections["persistence_truth"].append(
        EvidenceItem(
            "persistence_truth_placeholder",
            "unknown",
            "Use scripts/hermes_wechat_trace_bundle.py or a DB-backed smoke to prove agent_runs/artifact_registry/decision_signals/discipline_checks.",
        )
    )
    sections["delivery_truth"].append(
        EvidenceItem(
            "delivery_truth_placeholder",
            "unknown",
            "Check delivery_outbox/message_events or include a WeChat trace bundle for user-visible delivery proof.",
        )
    )
    sections["user_surface_truth"].append(
        EvidenceItem(
            "user_surface_truth_placeholder",
            "unknown",
            "Screenshots, browser checks, or WeChat delivery evidence are required for user-visible PASS.",
        )
    )

    verdict = classify_pack(sections, commands)
    return {
        "schema_version": "hermes_evidence_pack_v1",
        "generated_at": generated_at.isoformat(),
        "project_root": str(project_root),
        "claim": claim,
        "verdict": verdict,
        "sections": {section: [asdict(item) for item in items] for section, items in sections.items()},
        "commands": command_items,
    }


def classify_pack(sections: dict[str, list[EvidenceItem]], commands: list[CommandResult]) -> str:
    if any(command.status == "failed" for command in commands):
        return "FAIL"
    statuses = [item.status for items in sections.values() for item in items]
    if "failed" in statuses:
        return "FAIL"
    if any(status in {"unknown", "skipped"} for status in statuses):
        return "PARTIAL"
    return "PASS"


def write_pack(pack: dict[str, Any], *, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    json_path = output_dir / f"hermes-evidence-pack-{stamp}.json"
    md_path = output_dir / f"hermes-evidence-pack-{stamp}.md"
    json_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(pack), encoding="utf-8")
    return json_path, md_path


def render_markdown(pack: dict[str, Any]) -> str:
    lines = [
        "# Hermes Evidence Pack",
        "",
        f"- Generated: `{pack['generated_at']}`",
        f"- Verdict: **{pack['verdict']}**",
        f"- Claim: {pack.get('claim') or '(not specified)'}",
        f"- Project: `{pack['project_root']}`",
        "",
    ]
    for section in EVIDENCE_SECTIONS:
        lines.extend([f"## {section.replace('_', ' ').title()}", ""])
        for item in pack["sections"].get(section, []):
            lines.append(f"- **{item['label']}** `{item['status']}`: {item['detail']}")
            if item.get("payload") is not None:
                preview = json.dumps(item["payload"], ensure_ascii=False, indent=2, default=json_default)
                if len(preview) > 3000:
                    preview = preview[:3000] + "\n... <truncated>"
                lines.extend(["", "```json", preview, "```", ""])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a replayable Hermes evidence pack.")
    parser.add_argument("--claim", default="", help="Claim or release being verified.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--log-lines", type=int, default=DEFAULT_LOG_LINES)
    parser.add_argument("--include-wechat-trace-json", type=Path, default=None)
    parser.add_argument("--run-foundation", action="store_true", help="Run scripts/verify-foundation-runtime.sh.")
    parser.add_argument("--skip-git-status", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    pack = build_evidence_pack(
        claim=args.claim,
        log_lines=args.log_lines,
        run_foundation=args.run_foundation,
        run_git_status=not args.skip_git_status,
        include_trace_json=args.include_wechat_trace_json,
    )
    json_path, md_path = write_pack(pack, output_dir=args.output_dir)
    print(json.dumps({"ok": True, "verdict": pack["verdict"], "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False))
    return 0 if pack["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
