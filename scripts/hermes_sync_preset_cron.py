#!/usr/bin/env python3
"""Sync global Hermes preset cron jobs into profile homes.

The global Hermes home remains the preset source. Profile-specific user jobs are
preserved; preset jobs are merged by stable job id.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME_KEYS = {
    "next_run_at",
    "last_run_at",
    "last_status",
    "last_error",
    "last_delivery_error",
    "paused_at",
    "paused_reason",
}

PRESERVE_ON_UPDATE = RUNTIME_KEYS | {"created_at", "enabled", "state"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load_jobs(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not path.exists():
        return {"jobs": [], "updated_at": now_iso()}, []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"jobs": data, "updated_at": now_iso()}, data
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} has invalid JSON shape: {type(data).__name__}")
    jobs = data.get("jobs", [])
    if not isinstance(jobs, list):
        raise RuntimeError(f"{path} field 'jobs' is not a list")
    return data, jobs


def write_jobs(path: Path, jobs: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"jobs": jobs, "updated_at": now_iso()}
    fd, tmp = tempfile.mkstemp(prefix=".jobs_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def is_preset_job(job: dict[str, Any]) -> bool:
    name = str(job.get("name") or "")
    script = str(job.get("script") or "")
    return name.startswith("p0-") or script.startswith("p0/")


def prepare_new_preset(job: dict[str, Any], profile_name: str) -> dict[str, Any]:
    prepared = copy.deepcopy(job)
    for key in RUNTIME_KEYS:
        prepared[key] = None
    repeat = prepared.get("repeat")
    if isinstance(repeat, dict):
        repeat["completed"] = 0
    prepared["state"] = "scheduled"
    prepared["enabled"] = bool(prepared.get("enabled", True))
    prepared["profile"] = profile_name
    return prepared


def merge_existing_preset(
    template: dict[str, Any],
    existing: dict[str, Any],
    profile_name: str,
) -> dict[str, Any]:
    merged = prepare_new_preset(template, profile_name)
    for key in PRESERVE_ON_UPDATE:
        if key in existing:
            merged[key] = existing.get(key)
    if isinstance(existing.get("repeat"), dict):
        merged.setdefault("repeat", {})
        if isinstance(merged["repeat"], dict):
            merged["repeat"]["completed"] = existing["repeat"].get(
                "completed",
                merged["repeat"].get("completed", 0),
            )
    return merged


def copy_assets(source_home: Path, profile_home: Path) -> None:
    src = source_home / "scripts" / "p0"
    if not src.exists():
        return
    dst = profile_home / "scripts" / "p0"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)
    for path in dst.rglob("*"):
        try:
            if path.is_dir():
                path.chmod(0o700)
            elif path.is_file():
                path.chmod(0o700 if path.suffix == ".sh" else 0o600)
        except OSError:
            pass


def sync_profile(source_home: Path, profile_home: Path) -> dict[str, Any]:
    source_jobs_path = source_home / "cron" / "jobs.json"
    if not source_jobs_path.exists():
        raise RuntimeError(f"preset jobs file not found: {source_jobs_path}")
    _, source_jobs = load_jobs(source_jobs_path)
    presets = [job for job in source_jobs if is_preset_job(job)]
    if not presets:
        raise RuntimeError(f"no preset p0 jobs found in {source_jobs_path}")

    profile_name = profile_home.name
    dest_jobs_path = profile_home / "cron" / "jobs.json"
    profile_home.mkdir(parents=True, exist_ok=True)
    dest_jobs_path.parent.mkdir(parents=True, exist_ok=True)

    _, dest_jobs = load_jobs(dest_jobs_path)
    by_id = {str(job.get("id")): job for job in dest_jobs if job.get("id")}
    preset_ids = {str(job.get("id")) for job in presets}

    merged_presets = []
    added = 0
    updated = 0
    for preset in presets:
        jid = str(preset.get("id"))
        if not jid:
            continue
        if jid in by_id:
            merged_presets.append(merge_existing_preset(preset, by_id[jid], profile_name))
            updated += 1
        else:
            merged_presets.append(prepare_new_preset(preset, profile_name))
            added += 1

    user_jobs = [job for job in dest_jobs if str(job.get("id")) not in preset_ids]
    new_jobs = user_jobs + merged_presets

    backup = None
    if dest_jobs_path.exists():
        backup = dest_jobs_path.with_name(
            dest_jobs_path.name + ".bak_" + datetime.now().strftime("%Y%m%d%H%M%S")
        )
        shutil.copy2(dest_jobs_path, backup)

    write_jobs(dest_jobs_path, new_jobs)
    copy_assets(source_home, profile_home)
    return {
        "profile": profile_name,
        "user_jobs": len(user_jobs),
        "preset_jobs": len(merged_presets),
        "added": added,
        "updated": updated,
        "total": len(new_jobs),
        "backup": str(backup) if backup else None,
    }


def main(argv: list[str]) -> int:
    source_home = Path(os.environ.get("HERMES_PRESET_CRON_HOME", "/root/.hermes")).expanduser().resolve()
    profiles = [Path(arg).expanduser().resolve() for arg in argv]
    if not profiles:
        profiles_root = source_home / "profiles"
        profiles = sorted(p for p in profiles_root.glob("wx-*") if p.is_dir())
    results = [sync_profile(source_home, profile) for profile in profiles]
    print(json.dumps({"ok": True, "source_home": str(source_home), "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
