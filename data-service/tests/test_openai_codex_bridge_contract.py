from fastapi.testclient import TestClient

from local_connectors.openai_codex_bridge.server import app


def test_codex_bridge_health_and_stub_chat(monkeypatch):
    monkeypatch.setenv("CODEX_BRIDGE_MODE", "stub")
    monkeypatch.setenv("CODEX_BRIDGE_AUTH_PROFILE", "system-pro")
    monkeypatch.delenv("CODEX_BRIDGE_API_KEY", raising=False)

    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["mode"] == "stub"
    assert health.json()["auth_profile_configured"] is True

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "openai-codex/gpt-5.5",
            "messages": [{"role": "user", "content": "Summarize NVDA."}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"].startswith("provider=openai-codex")


def test_codex_bridge_requires_inbound_authorization_when_configured(monkeypatch):
    monkeypatch.setenv("CODEX_BRIDGE_MODE", "stub")
    monkeypatch.setenv("CODEX_BRIDGE_API_KEY", "bridge-secret")

    client = TestClient(app)

    rejected = client.post(
        "/v1/chat/completions",
        json={"model": "openai-codex/gpt-5.5", "messages": []},
    )
    assert rejected.status_code == 401

    accepted = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer bridge-secret"},
        json={"model": "openai-codex/gpt-5.5", "messages": []},
    )
    assert accepted.status_code == 200
