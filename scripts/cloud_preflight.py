#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.production_readiness import ENV_FILE, load_env_file, run_checks, summarize


@dataclass
class ToolProbe:
    name: str
    status: str
    detail: str
    required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "required": self.required,
        }


def _command_output(command: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or proc.stderr).strip()


def _installed_tool(name: str, *, required: bool, version_args: list[str] | None = None) -> ToolProbe:
    path = shutil.which(name)
    if not path:
        return ToolProbe(name, "fail" if required else "warn", "not installed", required)
    if version_args:
        code, output = _command_output([name, *version_args])
        if code == 0 and output:
            return ToolProbe(name, "pass", output.splitlines()[0], required)
    return ToolProbe(name, "pass", f"installed at {path}", required)


def _gcloud_context_probe() -> list[ToolProbe]:
    if not shutil.which("gcloud"):
        return [
            ToolProbe("gcloud_project", "fail", "gcloud is not installed", True),
            ToolProbe("gcloud_auth", "fail", "gcloud is not installed", True),
        ]

    project = os.getenv("GCP_PROJECT_ID", "").strip()
    if not project:
        code, output = _command_output(["gcloud", "config", "get-value", "project"])
        project = output.strip() if code == 0 else ""
    project_probe = ToolProbe(
        "gcloud_project",
        "pass" if project and project != "(unset)" else "fail",
        f"project={project}" if project and project != "(unset)" else "GCP project is not configured",
        True,
    )

    code, output = _command_output(["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"])
    auth_probe = ToolProbe(
        "gcloud_auth",
        "pass" if code == 0 and output.strip() else "fail",
        "active account configured" if code == 0 and output.strip() else "no active gcloud account",
        True,
    )
    return [project_probe, auth_probe]


def run_tool_probes() -> list[ToolProbe]:
    probes = [
        _installed_tool("gcloud", required=True, version_args=["--version"]),
        _installed_tool("bun", required=True, version_args=["--version"]),
        _installed_tool("node", required=True, version_args=["--version"]),
        _installed_tool("docker", required=False, version_args=["--version"]),
        _installed_tool("supabase", required=False, version_args=["--version"]),
    ]
    probes.extend(_gcloud_context_probe())
    return probes


def _next_actions(tool_probes: list[ToolProbe], readiness: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if any(probe.name == "gcloud" and probe.status == "fail" for probe in tool_probes):
        actions.append("Install Google Cloud CLI, then run `gcloud auth login` and `gcloud config set project <project-id>`.")
    if any(probe.name == "gcloud_project" and probe.status == "fail" for probe in tool_probes):
        actions.append("Set `GCP_PROJECT_ID` or run `gcloud config set project <project-id>`.")
    if any(probe.name == "gcloud_auth" and probe.status == "fail" for probe in tool_probes):
        actions.append("Run `gcloud auth login` and verify an active account with `gcloud auth list`.")

    failed_env = [
        check["name"]
        for check in readiness.get("checks", [])
        if check.get("status") == "fail"
    ]
    if failed_env:
        actions.append("Complete production env values for: " + ", ".join(failed_env) + ".")
    if not actions:
        actions.append("Run `./scripts/deploy-cloud.sh --target setup`, then deploy services and run `./scripts/deploy-cloud.sh --target monitor`.")
    return actions


def summarize_preflight(*, profile: str) -> dict[str, Any]:
    tool_probes = run_tool_probes()
    readiness = summarize(run_checks(profile=profile), profile=profile)
    tool_counts = {"pass": 0, "warn": 0, "fail": 0}
    for probe in tool_probes:
        tool_counts[probe.status] += 1
    status = "fail" if tool_counts["fail"] or readiness["status"] == "fail" else "pass"
    return {
        "profile": profile,
        "status": status,
        "tool_counts": tool_counts,
        "readiness_counts": readiness["counts"],
        "tools": [probe.to_dict() for probe in tool_probes],
        "readiness": readiness,
        "next_actions": _next_actions(tool_probes, readiness),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preflight cloud deployment prerequisites.")
    parser.add_argument("--profile", choices=["local", "production"], default="production")
    parser.add_argument("--env-file", default=str(ENV_FILE))
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    summary = summarize_preflight(profile=args.profile)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
