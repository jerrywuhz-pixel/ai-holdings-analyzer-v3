import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SYNC = ROOT / "scripts" / "hermes_sync_preset_cron.py"


def load_sync_module():
    spec = importlib.util.spec_from_file_location("hermes_sync_preset_cron_under_test", SYNC)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_jobs(path, jobs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"jobs": jobs}, ensure_ascii=False), encoding="utf-8")


def test_sync_profile_merges_presets_and_preserves_user_jobs(tmp_path):
    module = load_sync_module()
    source = tmp_path / "source"
    profile = tmp_path / "profiles" / "wx-test"
    source_script = source / "scripts" / "p0" / "p0-health-heartbeat.sh"
    source_script.parent.mkdir(parents=True)
    source_script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    write_jobs(
        source / "cron" / "jobs.json",
        [
            {"id": "p0a", "name": "p0-health-heartbeat", "script": "p0/p0-health-heartbeat.sh", "enabled": True},
            {"id": "other", "name": "not-preset", "script": "custom.py"},
        ],
    )
    write_jobs(
        profile / "cron" / "jobs.json",
        [
            {
                "id": "custom",
                "name": "用户任务",
                "script": "custom.py",
                "last_status": "ok",
            },
            {
                "id": "p0a",
                "name": "p0-health-heartbeat",
                "script": "p0/p0-health-heartbeat.sh",
                "enabled": False,
                "state": "paused",
                "last_run_at": "2026-06-18T12:00:00+08:00",
                "repeat": {"completed": 7},
            },
        ],
    )

    result = module.sync_profile(source, profile)

    data = json.loads((profile / "cron" / "jobs.json").read_text(encoding="utf-8"))
    by_id = {job["id"]: job for job in data["jobs"]}
    assert result["user_jobs"] == 1
    assert result["preset_jobs"] == 1
    assert set(by_id) == {"custom", "p0a"}
    assert by_id["custom"]["name"] == "用户任务"
    assert by_id["p0a"]["profile"] == "wx-test"
    assert by_id["p0a"]["enabled"] is False
    assert by_id["p0a"]["state"] == "paused"
    assert by_id["p0a"]["last_run_at"] == "2026-06-18T12:00:00+08:00"
    assert by_id["p0a"]["repeat"]["completed"] == 7
    assert (profile / "scripts" / "p0" / "p0-health-heartbeat.sh").exists()


def test_installer_shell_syntax_is_valid():
    import subprocess

    subprocess.run(["bash", "-n", str(ROOT / "scripts" / "install-hermes-profile-gateways.sh")], check=True)
