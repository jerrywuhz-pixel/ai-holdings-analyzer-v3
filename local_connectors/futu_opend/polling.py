from __future__ import annotations

"""
Tenant-scoped Futu local connector polling contract.

P0 production shape keeps the cloud boundary read-only and token-free on the
broker side. A user's local connector may poll tenant-scoped work and upload a
sanitized snapshot, but the connector will not contact any cloud endpoint
unless that behavior is explicitly enabled.
"""

import os
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

import httpx
from pydantic import BaseModel, Field


READ_ONLY_SCOPE = "read_only"
RUNTIME_MODE_LOCAL_DEV_DIRECT = "local_dev_direct"
RUNTIME_MODE_USER_LOCAL_POLLING = "user_local_polling"
ConnectorRuntimeMode = Literal["local_dev_direct", "user_local_polling"]
HttpPost = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FutuConnectorPollingError(RuntimeError):
    """Raised when the local connector polling contract is misconfigured or fails."""


class LocalPollingSettings(BaseModel):
    tenant_id: str = "local-dev-tenant"
    connector_instance_id: str = "futu-local-connector"
    poll_endpoint: str = "http://127.0.0.1:0/connector/poll"
    upload_endpoint: str = "http://127.0.0.1:0/connector/upload"
    pairing_token: Optional[str] = None
    runtime_mode: ConnectorRuntimeMode = RUNTIME_MODE_USER_LOCAL_POLLING
    permission_scope: Literal["read_only"] = READ_ONLY_SCOPE
    cloud_enabled: bool = False
    poll_timeout_seconds: float = 5.0
    upload_timeout_seconds: float = 10.0


class ConnectorPollRequest(BaseModel):
    tenant_id: str
    connector_instance_id: str
    broker: Literal["futu"] = "futu"
    connector: Literal["futu_opend_local"] = "futu_opend_local"
    permission_scope: Literal["read_only"] = READ_ONLY_SCOPE
    runtime_mode: Literal["user_local_polling"] = RUNTIME_MODE_USER_LOCAL_POLLING
    read_only: Literal[True] = True
    requested_at: datetime = Field(default_factory=_utc_now)
    capabilities: dict[str, bool] = Field(
        default_factory=lambda: {
            "read_account_snapshot": True,
            "read_option_chain": True,
            "place_order": False,
            "modify_order": False,
            "cancel_order": False,
        }
    )


class ConnectorSnapshotUpload(BaseModel):
    tenant_id: str
    connector_instance_id: str
    broker: Literal["futu"] = "futu"
    connector: Literal["futu_opend_local"] = "futu_opend_local"
    permission_scope: Literal["read_only"] = READ_ONLY_SCOPE
    runtime_mode: Literal["user_local_polling"] = RUNTIME_MODE_USER_LOCAL_POLLING
    read_only: Literal[True] = True
    snapshot_kind: str = "account_snapshot"
    task_id: Optional[str] = None
    uploaded_at: datetime = Field(default_factory=_utc_now)
    snapshot: dict[str, Any] = Field(default_factory=dict)


def load_polling_settings() -> LocalPollingSettings:
    return LocalPollingSettings(
        tenant_id=os.getenv("FUTU_CONNECTOR_TENANT_ID", "local-dev-tenant"),
        connector_instance_id=os.getenv("FUTU_CONNECTOR_INSTANCE_ID", "futu-local-connector"),
        poll_endpoint=os.getenv("FUTU_CONNECTOR_POLL_ENDPOINT", "http://127.0.0.1:0/connector/poll"),
        upload_endpoint=os.getenv("FUTU_CONNECTOR_UPLOAD_ENDPOINT", "http://127.0.0.1:0/connector/upload"),
        pairing_token=os.getenv("FUTU_CONNECTOR_PAIRING_TOKEN") or None,
        runtime_mode=_normalize_runtime_mode(os.getenv("FUTU_CONNECTOR_RUNTIME_MODE", RUNTIME_MODE_USER_LOCAL_POLLING)),
        cloud_enabled=_env_flag("FUTU_CONNECTOR_CLOUD_ENABLED", default=False),
        poll_timeout_seconds=float(os.getenv("FUTU_CONNECTOR_POLL_TIMEOUT_SECONDS", "5")),
        upload_timeout_seconds=float(os.getenv("FUTU_CONNECTOR_UPLOAD_TIMEOUT_SECONDS", "10")),
    )


def build_poll_request_payload(settings: LocalPollingSettings) -> dict[str, Any]:
    _enforce_polling_mode(settings.runtime_mode)
    return ConnectorPollRequest(
        tenant_id=settings.tenant_id,
        connector_instance_id=settings.connector_instance_id,
    ).model_dump(mode="json")


def build_snapshot_upload_payload(
    settings: LocalPollingSettings,
    *,
    snapshot: dict[str, Any],
    snapshot_kind: str = "account_snapshot",
    task_id: Optional[str] = None,
) -> dict[str, Any]:
    _enforce_polling_mode(settings.runtime_mode)
    return ConnectorSnapshotUpload(
        tenant_id=settings.tenant_id,
        connector_instance_id=settings.connector_instance_id,
        snapshot=snapshot,
        snapshot_kind=snapshot_kind,
        task_id=task_id,
    ).model_dump(mode="json")


class FutuUserLocalPollingClient:
    def __init__(self, settings: Optional[LocalPollingSettings] = None) -> None:
        self._settings = settings or load_polling_settings()

    @property
    def settings(self) -> LocalPollingSettings:
        return self._settings

    def build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Connector-Tenant-Id": self._settings.tenant_id,
            "X-Connector-Instance-Id": self._settings.connector_instance_id,
        }
        if self._settings.pairing_token:
            headers["X-Connector-Pairing-Token"] = self._settings.pairing_token
        return headers

    def build_poll_request_payload(self) -> dict[str, Any]:
        return build_poll_request_payload(self._settings)

    def build_snapshot_upload_payload(
        self,
        *,
        snapshot: dict[str, Any],
        snapshot_kind: str = "account_snapshot",
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return build_snapshot_upload_payload(
            self._settings,
            snapshot=snapshot,
            snapshot_kind=snapshot_kind,
            task_id=task_id,
        )

    def poll_once(self, *, http_post: Optional[HttpPost] = None) -> dict[str, Any]:
        if self._settings.runtime_mode == RUNTIME_MODE_LOCAL_DEV_DIRECT:
            return _skipped_result("runtime_mode_bypasses_cloud_polling", self._settings)
        if not self._settings.cloud_enabled:
            return _skipped_result("cloud_disabled", self._settings)
        request_payload = self.build_poll_request_payload()
        response = self._post(
            self._settings.poll_endpoint,
            payload=request_payload,
            timeout=self._settings.poll_timeout_seconds,
            http_post=http_post,
        )
        return {"ok": True, "request": request_payload, "response": response}

    def upload_snapshot(
        self,
        *,
        snapshot: dict[str, Any],
        snapshot_kind: str = "account_snapshot",
        task_id: Optional[str] = None,
        http_post: Optional[HttpPost] = None,
    ) -> dict[str, Any]:
        if self._settings.runtime_mode == RUNTIME_MODE_LOCAL_DEV_DIRECT:
            return _skipped_result("runtime_mode_bypasses_cloud_polling", self._settings)
        if not self._settings.cloud_enabled:
            return _skipped_result("cloud_disabled", self._settings)
        request_payload = self.build_snapshot_upload_payload(
            snapshot=snapshot,
            snapshot_kind=snapshot_kind,
            task_id=task_id,
        )
        response = self._post(
            self._settings.upload_endpoint,
            payload=request_payload,
            timeout=self._settings.upload_timeout_seconds,
            http_post=http_post,
        )
        return {"ok": True, "request": request_payload, "response": response}

    def _post(
        self,
        url: str,
        *,
        payload: dict[str, Any],
        timeout: float,
        http_post: Optional[HttpPost],
    ) -> dict[str, Any]:
        headers = self.build_headers()
        if http_post is None:
            response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise FutuConnectorPollingError("connector control plane returned non-JSON response") from exc
        else:
            data = http_post(url, payload, headers, timeout)
        if not isinstance(data, dict):
            raise FutuConnectorPollingError("connector control plane response must be an object")
        return data


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_runtime_mode(value: str) -> ConnectorRuntimeMode:
    normalized = value.strip().lower().replace("-", "_")
    if normalized == RUNTIME_MODE_LOCAL_DEV_DIRECT:
        return RUNTIME_MODE_LOCAL_DEV_DIRECT
    return RUNTIME_MODE_USER_LOCAL_POLLING


def _enforce_polling_mode(runtime_mode: ConnectorRuntimeMode) -> None:
    if runtime_mode != RUNTIME_MODE_USER_LOCAL_POLLING:
        raise FutuConnectorPollingError("polling payloads are only valid for runtime_mode=user_local_polling")


def _skipped_result(reason: str, settings: LocalPollingSettings) -> dict[str, Any]:
    return {
        "ok": False,
        "skipped": True,
        "reason": reason,
        "tenant_id": settings.tenant_id,
        "connector_instance_id": settings.connector_instance_id,
        "permission_scope": settings.permission_scope,
        "runtime_mode": settings.runtime_mode,
    }
