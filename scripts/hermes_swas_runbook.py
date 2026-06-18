#!/usr/bin/env python3
"""
Standard read-only Aliyun SWAS runbook for the Hermes holdings runtime.

This script is deliberately scoped to the lightweight-server path that has
recurred in Hermes operations: locate the instance, use Cloud Assistant instead
of fragile SSH, then verify services, routes, cron, WeChat, and DB persistence
as separate truth layers.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGION = "ap-southeast-5"
DEFAULT_PROJECT_DIR = "/opt/ai-holdings-analyzer-v3"
DEFAULT_ENV_FILE = ".env.server"
DEFAULT_COMPOSE_FILE = "docker-compose.server.yml"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".omx" / "evidence"
MAX_TEXT_CHARS = 24000
DEFAULT_TIMEOUT_SECONDS = 300

SECRET_RE = re.compile(
    r"(?i)([\"']?\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|DATABASE_URL|DB_URL|DSN)[A-Z0-9_]*[\"']?)"
    r"(\s*[:=]\s*[\"']?)([^\"'\s,}]+)"
)
POSTGRES_PASSWORD_RE = re.compile(r"(postgres(?:ql)?://[^:\s]+:)([^@\s]+)(@)", re.IGNORECASE)


@dataclass
class RunbookStep:
    stage: str
    status: str
    detail: str
    command: str | None = None
    output: str | None = None


@dataclass
class CommandResult:
    status: str
    returncode: int | None
    stdout: str
    stderr: str


def redact_text(value: str) -> str:
    value = POSTGRES_PASSWORD_RE.sub(r"\1<redacted>\3", value)
    return SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", value)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_local(command: list[str], *, timeout: int = 60) -> CommandResult:
    try:
        completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=timeout)
        return CommandResult(
            status="passed" if completed.returncode == 0 else "failed",
            returncode=completed.returncode,
            stdout=redact_text((completed.stdout or "")[-MAX_TEXT_CHARS:]),
            stderr=redact_text((completed.stderr or "")[-MAX_TEXT_CHARS:]),
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            status="failed",
            returncode=None,
            stdout=redact_text(exc.stdout or "" if isinstance(exc.stdout, str) else ""),
            stderr=f"timed out after {timeout}s",
        )
    except FileNotFoundError as exc:
        return CommandResult("failed", None, "", str(exc))


def bash_literal(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def read_remote_script(*, project_dir: str, env_file: str, compose_file: str, public_url: str) -> str:
    public_url_line = f"PUBLIC_WEBAPP_URL={bash_literal(public_url)}" if public_url else "PUBLIC_WEBAPP_URL=''"
    return f"""#!/usr/bin/env bash
set -u
PROJECT_DIR={bash_literal(project_dir)}
ENV_FILE={bash_literal(env_file)}
COMPOSE_FILE={bash_literal(compose_file)}
{public_url_line}

section() {{
  printf '\\n=== %s ===\\n' "$1"
}}

run() {{
  local label="$1"
  shift
  printf '\\n--- %s ---\\n' "$label"
  "$@" 2>&1 || printf '[WARN] %s failed with rc=%s\\n' "$label" "$?"
}}

section 'instance'
run whoami whoami
run hostname hostname
run uptime uptime
run date date -Is

section 'project'
if [ -d "$PROJECT_DIR" ]; then
  cd "$PROJECT_DIR" || exit 0
  run pwd pwd
  run files sh -lc 'ls -la | sed -n "1,80p"'
  run git-status sh -lc 'git rev-parse --short HEAD 2>/dev/null; git status --short 2>/dev/null | sed -n "1,80p"'
else
  echo "[ERROR] project dir missing: $PROJECT_DIR"
  exit 0
fi

section 'env presence'
if [ -f "$ENV_FILE" ]; then
  awk -F= '
    $1 ~ /(HERMES_DOMAIN_TOOLS_KEY|HERMES_INTERNAL_TOKEN|DATABASE_URL|WEBAPP_HTTP_PORT|DATA_SERVICE_PORT|INTERNAL_HOST_BIND|WECHAT_CLAWBOT_BRIDGE_SECRET|OPENAI_CODEX_BRIDGE_BASE_URL|MINIMAX_MODEL|HERMES_DEEP_MODEL)/ {{
      key=$1
      value=$0
      sub("^[^=]*=", "", value)
      if (value == "") print key "=empty"; else print key "=set"
    }}
  ' "$ENV_FILE"
else
  echo "[WARN] env file missing: $ENV_FILE"
fi

section 'docker compose'
run compose-services docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps --services
run compose-ps docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps --services 2>/dev/null | grep -qx openclaw; then
  echo '[FAIL] openclaw service present in Hermes-only lightweight runtime'
else
  echo '[PASS] openclaw service absent'
fi

section 'systemd hermes'
run hermes-services sh -lc 'systemctl list-units --type=service --no-pager | grep -E "hermes|wechat|claw|codex" || true'

section 'routes'
KEY=''
if [ -f "$ENV_FILE" ]; then
  KEY="$(awk -F= '$1=="HERMES_DOMAIN_TOOLS_KEY" || $1=="HERMES_INTERNAL_TOKEN" {{value=$0; sub("^[^=]*=", "", value); print value}}' "$ENV_FILE" | tail -1)"
fi
run webapp-head sh -lc 'curl -fsSI http://127.0.0.1:${{WEBAPP_HTTP_PORT:-3000}} | sed -n "1,8p"'
run data-health sh -lc 'curl -fsS http://127.0.0.1:${{DATA_SERVICE_PORT:-8000}}/health'
run domain-tools sh -lc 'curl -fsS -H "X-Hermes-Domain-Tools-Key: '"$KEY"'" http://127.0.0.1:${{DATA_SERVICE_PORT:-8000}}/api/hermes/domain-tools | head -c 4000'
if [ -n "$PUBLIC_WEBAPP_URL" ]; then
  run public-intro sh -lc 'curl -fsSI "$PUBLIC_WEBAPP_URL/intro" | sed -n "1,8p"'
  run public-domain-tools sh -lc 'curl -fsSI "$PUBLIC_WEBAPP_URL/api/hermes/domain-tools" | sed -n "1,8p"'
fi

section 'cron'
run crontab sh -lc 'crontab -l 2>/dev/null || true'
run cron-files sh -lc 'find /etc/cron.d /root/.hermes/cron -maxdepth 2 -type f 2>/dev/null | sort | xargs -r -I{{}} sh -c "echo --- {{}}; sed -n 1,80p {{}}"'
run hermes-cron sh -lc 'command -v hermes >/dev/null && hermes cron list 2>&1 || true'

section 'wechat bridge'
run wechat-containers sh -lc 'docker ps --format "{{{{.Names}}}} {{{{.Status}}}}" | grep -Ei "wechat|claw|bridge" || true'
run wechat-logs sh -lc 'docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=120 wechat-clawbot-bridge 2>&1 || true'

section 'db evidence'
PG_CONTAINER="$(docker ps --format '{{{{.Names}}}}' | grep -E 'postgres' | head -1)"
if [ -n "$PG_CONTAINER" ]; then
  run db-counts docker exec "$PG_CONTAINER" psql -U postgres -d ai_holdings -Atc "select 'agent_runs', count(*) from public.agent_runs union all select 'artifact_registry', count(*) from public.artifact_registry union all select 'decision_signals', count(*) from public.decision_signals union all select 'delivery_outbox', count(*) from public.delivery_outbox union all select 'channel_bindings', count(*) from public.channel_bindings;"
  run recent-agent-runs docker exec "$PG_CONTAINER" psql -U postgres -d ai_holdings -Atc "select created_at, entry_surface, intent, status from public.agent_runs order by created_at desc limit 8;"
  run recent-delivery docker exec "$PG_CONTAINER" psql -U postgres -d ai_holdings -Atc "select created_at, status, content_type, left(coalesce(last_error,''),120) from public.delivery_outbox order by created_at desc limit 8;"
else
  echo '[WARN] no postgres container found'
fi

section 'foundation verifier'
if [ -x scripts/verify-foundation-runtime.sh ]; then
  run foundation ./scripts/verify-foundation-runtime.sh
else
  echo '[WARN] scripts/verify-foundation-runtime.sh missing or not executable'
fi
"""


def build_runbook_script(*, project_dir: str, env_file: str, compose_file: str, public_url: str) -> str:
    return read_remote_script(
        project_dir=project_dir,
        env_file=env_file,
        compose_file=compose_file,
        public_url=public_url,
    )


def aliyun_command(region: str, args: list[str]) -> list[str]:
    return ["aliyun", "swas-open", *args, "--region", region]


def describe_instance(*, instance_id: str, region: str) -> RunbookStep:
    result = run_local(
        aliyun_command(
            region,
            ["DescribeInstances", "--InstanceIds", json.dumps([instance_id]), "--output", "json"],
        ),
        timeout=60,
    )
    status = "pass" if result.status == "passed" else "fail"
    detail = "instance describe succeeded" if status == "pass" else result.stderr or result.stdout
    return RunbookStep("instance", status, detail, command="DescribeInstances", output=result.stdout or result.stderr)


def invoke_cloud_assistant(
    *,
    instance_id: str,
    region: str,
    script: str,
    timeout_seconds: int,
    poll_interval: float = 3.0,
) -> RunbookStep:
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    command_content = f"base64 -d <<'EOF' | bash\n{encoded}\nEOF"
    run_payload = {
        "InstanceIds": [instance_id],
        "CommandType": "RunShellScript",
        "CommandContent": command_content,
        "Timeout": timeout_seconds,
    }
    run_result = run_local(
        aliyun_command(
            region,
            ["RunCommand", "--body", json.dumps(run_payload, ensure_ascii=False), "--output", "json"],
        ),
        timeout=60,
    )
    if run_result.status != "passed":
        return RunbookStep("cloud_assistant", "fail", run_result.stderr or run_result.stdout, command="RunCommand")

    invocation_id = extract_invocation_id(run_result.stdout)
    if not invocation_id:
        return RunbookStep("cloud_assistant", "fail", "RunCommand did not return InvocationId", command="RunCommand", output=run_result.stdout)

    deadline = time.time() + timeout_seconds
    last_output = ""
    while time.time() < deadline:
        describe_payload = {"InvocationId": invocation_id}
        describe_result = run_local(
            aliyun_command(
                region,
                ["DescribeInvocationResult", "--body", json.dumps(describe_payload), "--output", "json"],
            ),
            timeout=60,
        )
        last_output = describe_result.stdout or describe_result.stderr
        if describe_result.status != "passed":
            return RunbookStep("cloud_assistant", "fail", last_output, command=f"DescribeInvocationResult {invocation_id}")
        parsed = parse_invocation_result(last_output)
        if parsed.get("finished"):
            output = redact_text(parsed.get("output") or last_output)
            status = "pass" if parsed.get("exit_code") in {0, "0", None} else "warn"
            return RunbookStep("cloud_assistant", status, f"InvocationId={invocation_id}; exit_code={parsed.get('exit_code')}", command="Cloud Assistant runbook", output=output[-MAX_TEXT_CHARS:])
        time.sleep(poll_interval)

    return RunbookStep("cloud_assistant", "fail", f"timed out waiting for InvocationId={invocation_id}", command="DescribeInvocationResult", output=last_output)


def extract_invocation_id(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    for key in ("InvocationId", "invocationId"):
        if payload.get(key):
            return str(payload[key])
    data = payload.get("Data")
    if isinstance(data, dict):
        for key in ("InvocationId", "invocationId"):
            if data.get(key):
                return str(data[key])
    return ""


def parse_invocation_result(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"finished": True, "output": raw, "exit_code": None}

    candidates: list[Any] = [payload]
    for key in ("Data", "InvocationResult", "InvocationResults"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, list):
            candidates.extend(value)
        elif value is not None:
            candidates.append(value)

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        output = candidate.get("Output") or candidate.get("output") or candidate.get("CommandOutput")
        exit_code = candidate.get("ExitCode") if "ExitCode" in candidate else candidate.get("exitCode")
        status = str(candidate.get("Status") or candidate.get("status") or "").lower()
        finished = bool(output) or status in {"finished", "success", "succeeded", "failed"}
        if output:
            decoded = decode_output(str(output))
            return {"finished": finished, "output": decoded, "exit_code": exit_code, "status": status}
    return {"finished": False, "output": raw, "exit_code": None}


def decode_output(output: str) -> str:
    stripped = output.strip()
    try:
        decoded = base64.b64decode(stripped, validate=True)
        text = decoded.decode("utf-8", errors="replace")
        if text:
            return text
    except Exception:
        pass
    return output


def summarize_steps(steps: list[RunbookStep]) -> dict[str, Any]:
    counts = {"pass": 0, "warn": 0, "fail": 0, "planned": 0}
    for step in steps:
        counts[step.status] = counts.get(step.status, 0) + 1
    if counts["fail"]:
        status = "fail"
    elif counts["warn"] or counts["planned"]:
        status = "partial"
    else:
        status = "pass"
    return {"status": status, "counts": counts, "steps": [asdict(step) for step in steps]}


def run_runbook(
    *,
    instance_id: str,
    region: str,
    project_dir: str,
    env_file: str,
    compose_file: str,
    public_url: str,
    dry_run: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    script = build_runbook_script(
        project_dir=project_dir,
        env_file=env_file,
        compose_file=compose_file,
        public_url=public_url,
    )
    steps: list[RunbookStep] = [
        RunbookStep(
            "plan",
            "planned",
            "Runbook order: instance -> Cloud Assistant -> services/routes -> cron -> WeChat -> DB -> foundation verifier",
            output=script if dry_run else None,
        )
    ]

    if not instance_id:
        steps.append(RunbookStep("instance", "fail", "--instance-id or ALIYUN_SWAS_INSTANCE_ID is required"))
        return {"schema_version": "hermes_swas_runbook_v1", "generated_at": datetime.now(timezone.utc).isoformat(), **summarize_steps(steps)}

    if dry_run:
        steps.append(RunbookStep("cloud_assistant", "planned", "dry-run only; no Aliyun command executed", command="RunCommand", output=script))
    else:
        steps.append(describe_instance(instance_id=instance_id, region=region))
        if steps[-1].status != "fail":
            steps.append(
                invoke_cloud_assistant(
                    instance_id=instance_id,
                    region=region,
                    script=script,
                    timeout_seconds=timeout_seconds,
                )
            )

    return {
        "schema_version": "hermes_swas_runbook_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instance_id": instance_id,
        "region": region,
        "project_dir": project_dir,
        "dry_run": dry_run,
        **summarize_steps(steps),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Hermes SWAS Runbook",
        "",
        f"- Generated: `{summary['generated_at']}`",
        f"- Status: **{summary['status']}**",
        f"- Instance: `{summary.get('instance_id') or '<missing>'}`",
        f"- Region: `{summary.get('region') or '<missing>'}`",
        f"- Dry run: `{summary.get('dry_run')}`",
        "",
    ]
    for step in summary["steps"]:
        lines.extend([f"## {step['stage']}", "", f"- Status: `{step['status']}`", f"- Detail: {step['detail']}"])
        if step.get("command"):
            lines.append(f"- Command: `{step['command']}`")
        if step.get("output"):
            output = str(step["output"])
            if len(output) > 6000:
                output = output[:6000] + "\n... <truncated>"
            lines.extend(["", "```text", output, "```"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_summary(summary: dict[str, Any], output: Path | None) -> tuple[Path | None, Path | None]:
    if output is None:
        return None, None
    output.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    json_path = output / f"hermes-swas-runbook-{stamp}.json"
    md_path = output / f"hermes-swas-runbook-{stamp}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    return json_path, md_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the standard Hermes Aliyun SWAS read-only operations runbook.")
    parser.add_argument("--instance-id", default=os.getenv("ALIYUN_SWAS_INSTANCE_ID", ""))
    parser.add_argument("--region", default=os.getenv("ALIYUN_REGION", DEFAULT_REGION))
    parser.add_argument("--project-dir", default=os.getenv("HERMES_SWAS_PROJECT_DIR", DEFAULT_PROJECT_DIR))
    parser.add_argument("--env-file", default=os.getenv("HERMES_SWAS_ENV_FILE", DEFAULT_ENV_FILE))
    parser.add_argument("--compose-file", default=os.getenv("HERMES_SWAS_COMPOSE_FILE", DEFAULT_COMPOSE_FILE))
    parser.add_argument("--public-url", default=os.getenv("HERMES_PUBLIC_URL", "https://www.11office.top"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-output-files", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    summary = run_runbook(
        instance_id=args.instance_id,
        region=args.region,
        project_dir=args.project_dir,
        env_file=args.env_file,
        compose_file=args.compose_file,
        public_url=args.public_url,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout_seconds,
    )
    json_path, md_path = write_summary(summary, None if args.no_output_files else args.output_dir)
    if json_path and md_path:
        summary["artifact_paths"] = {"json": str(json_path), "markdown": str(md_path)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] in {"pass", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
