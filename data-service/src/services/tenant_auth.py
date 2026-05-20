from __future__ import annotations

import asyncio
import inspect
import os
import secrets
from typing import Annotated, Any, Optional

from fastapi import Header, HTTPException

try:
    from supabase import create_client

    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

_supabase_auth_client: Optional[Any] = None
_supabase_auth_config: Optional[tuple[str, str]] = None


def _auth_http_exception(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"ok": False, "message": message})


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def tenant_auth_required() -> bool:
    if _env_flag("DATA_SERVICE_TENANT_AUTH_REQUIRED", default=False):
        return True
    return os.getenv("DEPLOYMENT_MODE", "").strip().lower() == "cloud"


def _get_supabase_auth_client() -> Optional[Any]:
    global _supabase_auth_client, _supabase_auth_config

    if not SUPABASE_AVAILABLE:
        return None

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None

    config = (url, key)
    if _supabase_auth_client is not None and _supabase_auth_config == config:
        return _supabase_auth_client

    try:
        _supabase_auth_client = create_client(url, key)
        _supabase_auth_config = config
    except Exception:
        _supabase_auth_client = None
        _supabase_auth_config = None
    return _supabase_auth_client


async def _call_supabase_get_user(get_user: Any, token: str) -> Any:
    attempts = [((token,), {}), ((), {"jwt": token})]
    last_exc: Optional[TypeError] = None

    for args, kwargs in attempts:
        try:
            if inspect.iscoroutinefunction(get_user):
                return await get_user(*args, **kwargs)
            return await asyncio.to_thread(get_user, *args, **kwargs)
        except TypeError as exc:
            last_exc = exc

    raise RuntimeError("Supabase auth.get_user signature is unsupported") from last_exc


def _extract_user_id(user_response: Any) -> Optional[str]:
    user = getattr(user_response, "user", None)
    if user is None and isinstance(user_response, dict):
        user = user_response.get("user")

    if isinstance(user, dict):
        return user.get("id")

    return getattr(user, "id", None)


async def _authenticate_bearer_token(token: str) -> str:
    client = _get_supabase_auth_client()
    if client is None:
        raise _auth_http_exception(503, "Supabase auth is not configured")

    auth_client = getattr(client, "auth", None)
    get_user = getattr(auth_client, "get_user", None)
    if get_user is None:
        raise _auth_http_exception(503, "Supabase auth client is unavailable")

    try:
        user_response = await _call_supabase_get_user(get_user, token)
    except HTTPException:
        raise
    except Exception as exc:
        raise _auth_http_exception(401, f"Invalid or expired bearer token: {exc}")

    tenant_id = _extract_user_id(user_response)
    if not tenant_id:
        raise _auth_http_exception(401, "Invalid or expired bearer token")
    return tenant_id


def _authenticate_internal_token(token: str, tenant_id: Optional[str]) -> str:
    expected = os.getenv("DATA_SERVICE_INTERNAL_TOKEN", "").strip()
    if not expected:
        raise _auth_http_exception(503, "DATA_SERVICE_INTERNAL_TOKEN is not configured")
    if not secrets.compare_digest(token, expected):
        raise _auth_http_exception(401, "Invalid data service token")
    if not tenant_id:
        raise _auth_http_exception(401, "Missing X-Data-Service-Tenant-Id header")
    return tenant_id


async def get_authenticated_tenant_id_if_required(
    authorization: Annotated[Optional[str], Header()] = None,
    x_data_service_token: Annotated[Optional[str], Header(alias="X-Data-Service-Token")] = None,
    x_data_service_tenant_id: Annotated[Optional[str], Header(alias="X-Data-Service-Tenant-Id")] = None,
) -> Optional[str]:
    if x_data_service_token:
        return _authenticate_internal_token(x_data_service_token, x_data_service_tenant_id)

    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise _auth_http_exception(401, "Authorization header must use Bearer token")
        return await _authenticate_bearer_token(token.strip())

    if tenant_auth_required():
        raise _auth_http_exception(401, "Missing Authorization header")
    return None


def ensure_tenant_match(authenticated_tenant_id: Optional[str], requested_tenant_id: str) -> None:
    if authenticated_tenant_id is None:
        return
    if requested_tenant_id != authenticated_tenant_id:
        raise _auth_http_exception(403, "tenant_id does not match authenticated user")
