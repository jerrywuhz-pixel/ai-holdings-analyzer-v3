import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_tenant_auth_is_optional_for_local_profile(monkeypatch):
    from services.tenant_auth import get_authenticated_tenant_id_if_required

    monkeypatch.delenv("DATA_SERVICE_TENANT_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("DEPLOYMENT_MODE", raising=False)

    tenant_id = await get_authenticated_tenant_id_if_required()

    assert tenant_id is None


@pytest.mark.asyncio
async def test_tenant_auth_accepts_internal_service_token(monkeypatch):
    from services.tenant_auth import get_authenticated_tenant_id_if_required

    monkeypatch.setenv("DATA_SERVICE_TENANT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("DATA_SERVICE_INTERNAL_TOKEN", "service-token")

    tenant_id = await get_authenticated_tenant_id_if_required(
        x_data_service_token="service-token",
        x_data_service_tenant_id="tenant-1",
    )

    assert tenant_id == "tenant-1"


def test_tenant_auth_rejects_mismatched_tenant():
    from services.tenant_auth import ensure_tenant_match

    with pytest.raises(HTTPException) as exc_info:
        ensure_tenant_match("tenant-1", "tenant-2")

    assert exc_info.value.status_code == 403
    assert "tenant_id does not match authenticated user" in exc_info.value.detail["message"]
