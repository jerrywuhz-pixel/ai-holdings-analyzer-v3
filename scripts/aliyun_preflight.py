#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

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


@dataclass
class AliyunCheck:
    group: str
    name: str
    status: str
    detail: str
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "missing": self.missing,
        }


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _missing(names: Iterable[str]) -> list[str]:
    return [name for name in names if not _env(name)]


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


def _aliyun_auth_probe() -> ToolProbe:
    if not shutil.which("aliyun"):
        return ToolProbe("aliyun_auth", "fail", "aliyun CLI is not installed", True)

    if _env("ALIYUN_ACCESS_KEY_ID") and _env("ALIYUN_ACCESS_KEY_SECRET"):
        return ToolProbe("aliyun_auth", "pass", "access key env configured", True)

    code, output = _command_output(["aliyun", "configure", "list"])
    normalized = output.lower()
    configured = code == 0 and output and "not configured" not in normalized and "error" not in normalized
    return ToolProbe(
        "aliyun_auth",
        "pass" if configured else "fail",
        "configured profile detected" if configured else "run `aliyun configure` or export ALIYUN_ACCESS_KEY_ID/ALIYUN_ACCESS_KEY_SECRET",
        True,
    )


def run_tool_probes() -> list[ToolProbe]:
    return [
        _installed_tool("aliyun", required=True, version_args=["version"]),
        _aliyun_auth_probe(),
        _installed_tool("bun", required=True, version_args=["--version"]),
        _installed_tool("node", required=True, version_args=["--version"]),
        _installed_tool("docker", required=True, version_args=["--version"]),
        _installed_tool("supabase", required=False, version_args=["--version"]),
    ]


def _required_check(group: str, name: str, names: list[str], detail: str, *, profile: str) -> AliyunCheck:
    missing = _missing(names)
    status = "pass" if not missing else ("warn" if profile == "local" else "fail")
    return AliyunCheck(
        group=group,
        name=name,
        status=status,
        detail=detail if not missing else f"missing required env: {', '.join(missing)}",
        missing=missing,
    )


def run_aliyun_checks(*, profile: str) -> list[AliyunCheck]:
    return [
        _required_check(
            "provider",
            "aliyun_region",
            ["ALIYUN_REGION"],
            "Alibaba Cloud mainland region is selected, for example cn-shanghai or cn-beijing",
            profile=profile,
        ),
        _required_check(
            "provider",
            "aliyun_account",
            ["ALIYUN_ACCOUNT_ID"],
            "Alibaba Cloud account id is configured for ACR/SAE resource naming",
            profile=profile,
        ),
        _required_check(
            "registry",
            "acr",
            ["ALIYUN_ACR_REGISTRY", "ALIYUN_ACR_NAMESPACE"],
            "ACR registry and namespace are configured for service images",
            profile=profile,
        ),
        _required_check(
            "runtime",
            "sae_apps",
            [
                "ALIYUN_SAE_NAMESPACE_ID",
                "ALIYUN_SAE_WEBAPP_APP_ID",
                "ALIYUN_SAE_GATEWAY_APP_ID",
                "ALIYUN_SAE_DATA_SERVICE_APP_ID",
            ],
            "SAE namespace and P0 application ids are configured",
            profile=profile,
        ),
        _required_check(
            "data",
            "managed_state",
            ["ALIYUN_RDS_INSTANCE_ID", "ALIYUN_REDIS_INSTANCE_ID"],
            "RDS PostgreSQL and Tair/Redis instances are identified",
            profile=profile,
        ),
        _required_check(
            "storage",
            "oss_buckets",
            ["ALIYUN_OSS_BUCKET_ARTIFACTS", "ALIYUN_OSS_BUCKET_MARKET_DATA"],
            "OSS buckets for Hermes artifacts and market data are configured",
            profile=profile,
        ),
        _required_check(
            "scheduler",
            "eventbridge",
            ["ALIYUN_EVENTBRIDGE_BUS"],
            "EventBridge bus/rules are configured for P0 cron jobs",
            profile=profile,
        ),
        _required_check(
            "compliance",
            "icp_beian",
            ["ICP_BEIAN_NUMBER"],
            "ICP filing number is configured before mainland production traffic cutover",
            profile=profile,
        ),
    ]


def _count_status(items: Iterable[Any]) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for item in items:
        counts[item.status] += 1
    return counts


def _next_actions(tool_probes: list[ToolProbe], readiness: dict[str, Any], aliyun_checks: list[AliyunCheck]) -> list[str]:
    actions: list[str] = []
    if any(probe.name == "aliyun" and probe.status == "fail" for probe in tool_probes):
        actions.append("Install Alibaba Cloud CLI with `brew install aliyun-cli`, then run `aliyun configure`.")
    if any(probe.name == "aliyun_auth" and probe.status == "fail" for probe in tool_probes):
        actions.append("Run `aliyun configure` or export ALIYUN_ACCESS_KEY_ID/ALIYUN_ACCESS_KEY_SECRET for deployment automation.")

    missing_aliyun = [
        missing
        for check in aliyun_checks
        if check.status == "fail"
        for missing in check.missing
    ]
    if missing_aliyun:
        actions.append("Complete Alibaba Cloud env values for: " + ", ".join(missing_aliyun) + ".")

    failed_env = [
        check["name"]
        for check in readiness.get("checks", [])
        if check.get("status") == "fail"
    ]
    if failed_env:
        actions.append("Complete production runtime env values for: " + ", ".join(failed_env) + ".")

    if not actions:
        actions.append("Run `python3 scripts/aliyun_deployment_monitor.py` after SAE/ACR/RDS/OSS/EventBridge resources are provisioned.")
    return actions


def summarize_preflight(*, profile: str) -> dict[str, Any]:
    tool_probes = run_tool_probes()
    aliyun_checks = run_aliyun_checks(profile=profile)
    readiness = summarize(run_checks(profile=profile), profile=profile)
    tool_counts = _count_status(tool_probes)
    aliyun_counts = _count_status(aliyun_checks)
    status = "fail" if tool_counts["fail"] or aliyun_counts["fail"] or readiness["status"] == "fail" else "pass"
    return {
        "profile": profile,
        "cloud_provider": "aliyun",
        "status": status,
        "tool_counts": tool_counts,
        "aliyun_counts": aliyun_counts,
        "readiness_counts": readiness["counts"],
        "tools": [probe.to_dict() for probe in tool_probes],
        "aliyun": [check.to_dict() for check in aliyun_checks],
        "readiness": readiness,
        "next_actions": _next_actions(tool_probes, readiness, aliyun_checks),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preflight Alibaba Cloud deployment prerequisites.")
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
