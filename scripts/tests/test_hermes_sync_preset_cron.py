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


def test_installer_does_not_sync_preset_cron_by_default(tmp_path):
    import os
    import shutil
    import subprocess

    home = tmp_path / "hermes"
    profile = home / "profiles" / "wx-test"
    profile.mkdir(parents=True)
    source_script = home / "scripts" / "p0" / "p0-health-heartbeat.sh"
    source_script.parent.mkdir(parents=True)
    source_script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    write_jobs(
        home / "cron" / "jobs.json",
        [{"id": "p0a", "name": "p0-health-heartbeat", "script": "p0/p0-health-heartbeat.sh", "enabled": True}],
    )

    env = {
        **os.environ,
        "HERMES_HOME": str(home),
        "HERMES_PROFILES_DIR": str(home / "profiles"),
        "HERMES_BIN": shutil.which("true") or "/usr/bin/true",
        "SYNC_TARGET": str(tmp_path / "hermes-sync-preset-cron"),
    }
    subprocess.run(
        [
            "bash",
            str(ROOT / "scripts" / "install-hermes-profile-gateways.sh"),
            "--no-units",
            "--no-start",
            "--no-shared-auth",
        ],
        check=True,
        env=env,
    )

    assert not (profile / "cron" / "jobs.json").exists()


def test_installer_syncs_preset_cron_only_when_requested(tmp_path):
    import os
    import shutil
    import subprocess

    home = tmp_path / "hermes"
    profile = home / "profiles" / "wx-test"
    profile.mkdir(parents=True)
    source_script = home / "scripts" / "p0" / "p0-health-heartbeat.sh"
    source_script.parent.mkdir(parents=True)
    source_script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    write_jobs(
        home / "cron" / "jobs.json",
        [{"id": "p0a", "name": "p0-health-heartbeat", "script": "p0/p0-health-heartbeat.sh", "enabled": True}],
    )

    env = {
        **os.environ,
        "HERMES_HOME": str(home),
        "HERMES_PROFILES_DIR": str(home / "profiles"),
        "HERMES_BIN": shutil.which("true") or "/usr/bin/true",
        "SYNC_TARGET": str(tmp_path / "hermes-sync-preset-cron"),
    }
    subprocess.run(
        [
            "bash",
            str(ROOT / "scripts" / "install-hermes-profile-gateways.sh"),
            "--sync-preset-cron",
            "--no-units",
            "--no-start",
            "--no-shared-auth",
        ],
        check=True,
        env=env,
    )

    data = json.loads((profile / "cron" / "jobs.json").read_text(encoding="utf-8"))
    assert [job["id"] for job in data["jobs"]] == ["p0a"]
    assert data["jobs"][0]["profile"] == "wx-test"


def test_installer_links_shared_codex_auth_from_credential_pool(tmp_path):
    import os
    import shutil
    import subprocess

    home = tmp_path / "hermes"
    profile = home / "profiles" / "wx-test"
    profile.mkdir(parents=True)
    (home / "auth.json").write_text(
        json.dumps(
            {
                "version": 1,
                "providers": {},
                "credential_pool": {
                    "openai-codex": [
                        {
                            "label": "openai-codex-oauth-1",
                            "access_token": "token",
                            "refresh_token": "refresh",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    (profile / "auth.json").write_text(json.dumps({"providers": {}, "credential_pool": {}}), encoding="utf-8")

    env = {
        **os.environ,
        "HERMES_HOME": str(home),
        "HERMES_PROFILES_DIR": str(home / "profiles"),
        "HERMES_BIN": shutil.which("true") or "/usr/bin/true",
        "SYNC_TARGET": str(tmp_path / "hermes-sync-preset-cron"),
    }
    subprocess.run(
        [
            "bash",
            str(ROOT / "scripts" / "install-hermes-profile-gateways.sh"),
            "--no-sync",
            "--no-units",
            "--no-start",
        ],
        check=True,
        env=env,
    )

    shared_auth = home / "shared-auth" / "auth.json"
    assert shared_auth.exists()
    assert (home / "auth.json").resolve() == shared_auth
    assert (profile / "auth.json").resolve() == shared_auth
