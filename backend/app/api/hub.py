"""Scenario hub: named MinIO runs and live A/B/difference overlays."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.hub_compare import apply_hub_selection, selection_payload

router = APIRouter(prefix="/api/hub", tags=["hub"])


def _require_hub() -> None:
    if settings.app_mode != "hub":
        raise HTTPException(status_code=404, detail="Scenario hub is not enabled in this app")


class HubSelectionBody(BaseModel):
    a: str = Field(min_length=1)
    b: str = Field(min_length=1)
    view: str = "a"
    critical: float | None = None


@router.get("/scenarios")
def get_scenarios() -> dict:
    _require_hub()
    try:
        return selection_payload()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/selection")
def post_selection(body: HubSelectionBody) -> dict:
    _require_hub()
    try:
        return apply_hub_selection(a=body.a, b=body.b, view=body.view, critical=body.critical)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
