import importlib
import sys
import types

from fastapi.testclient import TestClient


def _load_app():
    fake_module = types.ModuleType("openclaw.gateway.supabase_client")
    fake_module.create_skill_client = lambda *args, **kwargs: None
    sys.modules["openclaw.gateway.supabase_client"] = fake_module

    gateway_app = importlib.import_module("openclaw.gateway_app")
    return gateway_app.app


def test_openclaw_root_returns_service_metadata():
    client = TestClient(_load_app())

    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["service"] == "OpenClaw Gateway"


def test_openclaw_health_returns_ok_status():
    client = TestClient(_load_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
