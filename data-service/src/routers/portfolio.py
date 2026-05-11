from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from services.portfolio_read_model import (
    PortfolioReadModelConfigurationError,
    PortfolioReadModelService,
    PortfolioSnapshotNotFoundError,
    create_portfolio_read_model_service_from_env,
)

router = APIRouter(tags=["portfolio"])

_portfolio_read_model_service: PortfolioReadModelService | None = None


def _get_portfolio_read_model_service() -> PortfolioReadModelService:
    global _portfolio_read_model_service
    if _portfolio_read_model_service is None:
        _portfolio_read_model_service = create_portfolio_read_model_service_from_env()
    return _portfolio_read_model_service


@router.get("/v3/portfolio/overview")
async def get_portfolio_overview(
    tenant_id: str = Query(..., min_length=1),
) -> dict:
    try:
        overview = await _get_portfolio_read_model_service().get_overview(tenant_id)
        return {"ok": True, "data": overview.model_dump(mode="json")}
    except PortfolioSnapshotNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "message": str(exc)},
        )
    except PortfolioReadModelConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "message": str(exc)},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to load portfolio overview: {exc}"},
        )


@router.get("/v3/portfolio/positions")
async def get_portfolio_positions(
    tenant_id: str = Query(..., min_length=1),
) -> dict:
    try:
        positions = await _get_portfolio_read_model_service().get_positions(tenant_id)
        return {"ok": True, "data": positions.model_dump(mode="json")}
    except PortfolioSnapshotNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "message": str(exc)},
        )
    except PortfolioReadModelConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "message": str(exc)},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to load portfolio positions: {exc}"},
        )
