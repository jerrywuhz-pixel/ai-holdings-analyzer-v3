from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_server_compose_does_not_define_openclaw_service():
    compose = (ROOT / "docker-compose.server.yml").read_text(encoding="utf-8")
    assert "\n  openclaw:\n" not in compose
    assert "http://openclaw:8080" not in compose


def test_foundation_verifier_checks_hermes_not_openclaw_health():
    verifier = (ROOT / "scripts" / "verify-foundation-runtime.sh").read_text(encoding="utf-8")
    assert "/api/hermes/domain-tools" in verifier
    assert "openclaw_upstream_target" not in verifier


def test_hermes_foundation_init_is_the_user_facing_entrypoint():
    script = ROOT / "scripts" / "init-hermes-foundation.sh"
    assert script.exists()
    content = script.read_text(encoding="utf-8")
    assert "HERMES_DOMAIN_TOOLS_KEY" in content
    assert "OPENCLAW_SKILL_KEY" not in content


def test_lightweight_deploy_doc_uses_hermes_runtime_paths():
    doc = (ROOT / "docs" / "LIGHTWEIGHT_SERVER_DEPLOY.md").read_text(encoding="utf-8")
    assert "curl http://127.0.0.1:8000/api/hermes/domain-tools" in doc
    assert "curl http://127.0.0.1:8080/health" not in doc
    assert "build --network host webapp openclaw" not in doc
    assert "./scripts/init-hermes-foundation.sh" in doc
