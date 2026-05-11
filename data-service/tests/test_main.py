from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_returns_ok_and_version():
    """GET /health 返回增强版响应，包含 status、version、gateway 和 data_sources。"""
    response = client.get("/health")
    assert response.status_code == 200, "Health endpoint should return 200"
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "2.0.0"
    # Phase 8 增强字段
    assert "gateway" in data
    assert "data_sources" in data


def test_root_returns_service_metadata():
    """GET / 返回包含 service name 和 version 的 JSON."""
    response = client.get("/")
    assert response.status_code == 200, "Root endpoint should return 200"
    data = response.json()
    assert data["service"] == "AI Holdings Data Service"
    assert data["version"] == "2.0.0"
    assert "docs" in data
    assert "health" in data
