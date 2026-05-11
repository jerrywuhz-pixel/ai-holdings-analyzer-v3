import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_SERVICE_ROOT = Path(__file__).resolve().parents[1]
for candidate in (PROJECT_ROOT, DATA_SERVICE_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from adapters.futu import FutuReadOnlyConnector, FutuSnapshotReadRequest  # noqa: E402
from local_connectors.futu_opend.polling import (  # noqa: E402
    FutuUserLocalPollingClient,
    build_poll_request_payload,
    build_snapshot_upload_payload,
    load_polling_settings,
)


def test_user_local_polling_payloads_include_tenant_and_read_only_contract(monkeypatch):
    monkeypatch.setenv("FUTU_CONNECTOR_TENANT_ID", "tenant-prod-1")
    monkeypatch.setenv("FUTU_CONNECTOR_INSTANCE_ID", "connector-prod-9")
    monkeypatch.setenv("FUTU_CONNECTOR_POLL_ENDPOINT", "https://control.example/poll")
    monkeypatch.setenv("FUTU_CONNECTOR_UPLOAD_ENDPOINT", "https://control.example/upload")
    monkeypatch.setenv("FUTU_CONNECTOR_PAIRING_TOKEN", "pairing-token-abc")

    settings = load_polling_settings()
    client = FutuUserLocalPollingClient(settings)
    poll_payload = build_poll_request_payload(settings)
    upload_payload = build_snapshot_upload_payload(
        settings,
        snapshot={"positions": [], "cash_balances": []},
        task_id="task-42",
    )

    assert settings.runtime_mode == "user_local_polling"
    assert poll_payload["tenant_id"] == "tenant-prod-1"
    assert poll_payload["connector_instance_id"] == "connector-prod-9"
    assert poll_payload["permission_scope"] == "read_only"
    assert poll_payload["runtime_mode"] == "user_local_polling"
    assert poll_payload["capabilities"]["place_order"] is False
    assert upload_payload["tenant_id"] == "tenant-prod-1"
    assert upload_payload["connector_instance_id"] == "connector-prod-9"
    assert upload_payload["permission_scope"] == "read_only"
    assert upload_payload["runtime_mode"] == "user_local_polling"
    assert upload_payload["task_id"] == "task-42"
    assert client.build_headers()["X-Connector-Pairing-Token"] == "pairing-token-abc"


def test_user_local_polling_client_is_offline_by_default():
    settings = load_polling_settings()
    client = FutuUserLocalPollingClient(settings)
    calls: list[tuple[str, dict, dict, float]] = []

    def fake_post(url, payload, headers, timeout):
        calls.append((url, payload, headers, timeout))
        return {"ok": True}

    poll_result = client.poll_once(http_post=fake_post)
    upload_result = client.upload_snapshot(snapshot={"positions": []}, http_post=fake_post)

    assert poll_result["skipped"] is True
    assert poll_result["reason"] == "cloud_disabled"
    assert upload_result["skipped"] is True
    assert upload_result["reason"] == "cloud_disabled"
    assert calls == []


def test_local_dev_direct_runtime_bypasses_polling_cloud_contract(monkeypatch):
    monkeypatch.setenv("FUTU_CONNECTOR_RUNTIME_MODE", "local_dev_direct")
    monkeypatch.setenv("FUTU_CONNECTOR_CLOUD_ENABLED", "true")

    settings = load_polling_settings()
    client = FutuUserLocalPollingClient(settings)
    calls: list[tuple[str, dict, dict, float]] = []

    def fake_post(url, payload, headers, timeout):
        calls.append((url, payload, headers, timeout))
        return {"ok": True}

    result = client.poll_once(http_post=fake_post)

    assert settings.runtime_mode == "local_dev_direct"
    assert result["skipped"] is True
    assert result["reason"] == "runtime_mode_bypasses_cloud_polling"
    assert result["permission_scope"] == "read_only"
    assert calls == []


@pytest.mark.asyncio
async def test_local_dev_direct_snapshot_http_contract_remains_unchanged():
    connector = FutuReadOnlyConnector(
        mode="local_connector",
        base_url="http://localhost:8765",
        snapshot_path="/api/v1/snapshots",
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = {
            "ok": True,
            "data": {
                "tenant_id": "tenant-1",
                "broker_connection_id": "bc-1",
                "connector_mode": "local_connector",
                "permission_scope": "read_only",
                "positions": [],
                "cash_balances": [],
            },
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        await connector.read_account_snapshot(
            FutuSnapshotReadRequest(
                tenant_id="tenant-1",
                broker_connection_id="bc-1",
                connector_mode="local_connector",
            )
        )

    outbound_payload = mock_post.call_args.kwargs["json"]
    assert outbound_payload["tenant_id"] == "tenant-1"
    assert outbound_payload["permission_scope"] == "read_only"
    assert outbound_payload["connector_mode"] == "local_connector"
    assert "connector_instance_id" not in outbound_payload
    assert "runtime_mode" not in outbound_payload
