#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


EXPECTED_SCHEDULER_JOBS = [
    "daily-market-scan",
    "daily-profit-taking",
    "heartbeat-check",
    "stale-jobs-check",
]


@dataclass
class Probe:
    group: str
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "group": self.group,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }


def _run_json(command: list[str]) -> tuple[dict[str, Any] | list[Any] | None, str]:
    try:
        proc = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        return None, str(exc)
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip()
    try:
        return json.loads(proc.stdout or "{}"), ""
    except json.JSONDecodeError as exc:
        return None, f"invalid json from gcloud: {exc}"


def cloud_run_service_probe(name: str, *, project: str, region: str) -> tuple[Probe, str]:
    payload, error = _run_json(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            name,
            "--project",
            project,
            "--region",
            region,
            "--format=json",
        ]
    )
    if not isinstance(payload, dict):
        return Probe("cloud-run", name, "fail", error or "service describe failed"), ""

    conditions = payload.get("status", {}).get("conditions", [])
    ready = next((item for item in conditions if item.get("type") == "Ready"), {})
    url = str(payload.get("status", {}).get("url") or "")
    ready_status = str(ready.get("status") or "").lower()
    if ready_status == "true":
        return Probe("cloud-run", name, "pass", f"Ready=True url={url or '<none>'}"), url
    return Probe("cloud-run", name, "fail", f"Ready={ready.get('status')}; reason={ready.get('reason', '')}"), url


def http_health_probe(name: str, url: str, *, timeout: float) -> Probe:
    if not url:
        return Probe("health", name, "fail", "service URL is empty")
    health_url = url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(health_url, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            status_code = response.getcode()
    except urllib.error.HTTPError as exc:
        return Probe("health", name, "fail", f"{health_url} returned HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return Probe("health", name, "fail", f"{health_url} failed: {exc.reason}")
    except TimeoutError:
        return Probe("health", name, "fail", f"{health_url} timed out")

    if status_code >= 400:
        return Probe("health", name, "fail", f"{health_url} returned HTTP {status_code}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Probe("health", name, "warn", f"{health_url} returned non-json health body")
    status = str(payload.get("status") or "").lower()
    if status in {"ok", "healthy", "pass"}:
        return Probe("health", name, "pass", f"{health_url} status={status}")
    return Probe("health", name, "warn", f"{health_url} status={status or '<missing>'}")


def scheduler_probe(*, project: str, region: str) -> list[Probe]:
    payload, error = _run_json(
        [
            "gcloud",
            "scheduler",
            "jobs",
            "list",
            "--project",
            project,
            "--location",
            region,
            "--format=json",
        ]
    )
    if not isinstance(payload, list):
        return [Probe("scheduler", "jobs", "fail", error or "scheduler jobs list failed")]

    existing = {str(item.get("name", "")).split("/")[-1] for item in payload if isinstance(item, dict)}
    probes: list[Probe] = []
    for job_name in EXPECTED_SCHEDULER_JOBS:
        probes.append(
            Probe(
                "scheduler",
                job_name,
                "pass" if job_name in existing else "fail",
                "configured" if job_name in existing else "missing",
            )
        )
    return probes


def summarize(probes: list[Probe]) -> dict[str, Any]:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for probe in probes:
        counts[probe.status] += 1
    return {
        "status": "fail" if counts["fail"] else "pass",
        "counts": counts,
        "probes": [probe.to_dict() for probe in probes],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor AI holdings Cloud Run deployment health.")
    parser.add_argument("--project", default=os.getenv("GCP_PROJECT_ID", ""))
    parser.add_argument("--region", default=os.getenv("GCP_REGION", "asia-southeast1"))
    parser.add_argument("--gateway-service", default=os.getenv("GATEWAY_SERVICE", "openclaw-gateway"))
    parser.add_argument("--data-service", default=os.getenv("DATA_SERVICE", "data-service"))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("CLOUD_MONITOR_TIMEOUT_SECONDS", "8")))
    parser.add_argument("--skip-scheduler", action="store_true")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.project:
        print("GCP project is required: pass --project or set GCP_PROJECT_ID", file=sys.stderr)
        return 2

    probes: list[Probe] = []
    gateway_probe, gateway_url = cloud_run_service_probe(args.gateway_service, project=args.project, region=args.region)
    data_probe, _data_url = cloud_run_service_probe(args.data_service, project=args.project, region=args.region)
    probes.extend([gateway_probe, data_probe])

    if gateway_probe.status == "pass":
        probes.append(http_health_probe(args.gateway_service, gateway_url, timeout=args.timeout))
    else:
        probes.append(Probe("health", args.gateway_service, "fail", "skipped because Cloud Run service is not ready"))

    if not args.skip_scheduler:
        probes.extend(scheduler_probe(project=args.project, region=args.region))

    summary = summarize(probes)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    print(rendered)
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
