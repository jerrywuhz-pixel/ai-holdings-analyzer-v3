from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_local_native_webapp_uses_standalone_server_when_available():
    script = read("scripts/local-native-webapp.sh")

    assert ".next/standalone/server.js" in script
    assert "HOSTNAME=127.0.0.1" in script
