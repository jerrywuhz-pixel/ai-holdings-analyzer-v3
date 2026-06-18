from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from openclaw.gateway.domain_tools import DomainToolError, DomainToolsFacade, domain_tool_manifest

router = APIRouter(prefix="/api/hermes/domain-tools", tags=["hermes-domain-tools"])
logger = logging.getLogger(__name__)


class DomainToolInvokeRequest(BaseModel):
    tool: str = Field(..., min_length=1)
    tenant_id: Optional[str] = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None


def _domain_tools(request: Request) -> DomainToolsFacade:
    facade = getattr(request.app.state, "domain_tools_facade", None)
    if facade is None:
        facade = DomainToolsFacade()
        request.app.state.domain_tools_facade = facade
    return facade


def _verify_internal_request(request: Request) -> None:
    expected = os.getenv("HERMES_DOMAIN_TOOLS_KEY") or os.getenv("OPENCLAW_SKILL_KEY", "")
    if not expected:
        return
    supplied = request.headers.get("X-Hermes-Domain-Tools-Key") or request.headers.get("X-OpenClaw-Skill-Key")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail={"ok": False, "message": "invalid domain tools key"})


@router.get("")
async def list_domain_tools(request: Request) -> dict[str, Any]:
    _verify_internal_request(request)
    return {"ok": True, "tools": domain_tool_manifest()}


@router.post("/invoke")
async def invoke_domain_tool(payload: DomainToolInvokeRequest, request: Request) -> dict[str, Any]:
    _verify_internal_request(request)
    arguments = dict(payload.arguments)
    if payload.tenant_id and "tenant_id" not in arguments:
        arguments["tenant_id"] = payload.tenant_id
    try:
        result = await _domain_tools(request).invoke(payload.tool, arguments)
        return {"ok": result.get("ok", False), "result": result, "run_id": payload.run_id}
    except DomainToolError as exc:
        return {
            "ok": False,
            "run_id": payload.run_id,
            "result": {
                "tool": payload.tool,
                "ok": False,
                "status": "error",
                "error": str(exc),
            },
        }
    except httpx.HTTPStatusError as exc:
        logger.warning("domain tool upstream HTTP error: %s", exc)
        return {
            "ok": False,
            "run_id": payload.run_id,
            "result": {
                "tool": payload.tool,
                "ok": False,
                "status": "upstream_error",
                "error": str(exc),
                "upstream_status_code": exc.response.status_code,
            },
        }
    except Exception as exc:
        logger.exception("domain tool invocation failed")
        return {
            "ok": False,
            "run_id": payload.run_id,
            "result": {
                "tool": payload.tool,
                "ok": False,
                "status": "error",
                "error": str(exc),
            },
        }
