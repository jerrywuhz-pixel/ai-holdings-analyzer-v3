import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install-hermes-ima-gateway-hook.sh"


def test_ima_gateway_hook_installer_shell_syntax_is_valid():
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)


def test_ima_gateway_hook_installer_writes_valid_handler(tmp_path):
    env = {
        **os.environ,
        "HERMES_HOME": str(tmp_path / "hermes"),
        "HERMES_IMA_ARCHIVE_HOOK_DATA_SERVICE_URL": "http://127.0.0.1:8000",
    }

    subprocess.run(["bash", str(INSTALLER), "--no-restart"], check=True, env=env)

    hook_dir = tmp_path / "hermes" / "hooks" / "ima-archive"
    assert (hook_dir / "HOOK.yaml").read_text(encoding="utf-8").splitlines() == [
        "name: ima-archive",
        "description: Archive real Hermes gateway replies into the data-service IMA archive pipeline.",
        "events:",
        "  - agent:end",
    ]
    handler = hook_dir / "handler.py"
    compile(handler.read_text(encoding="utf-8"), str(handler), "exec")
