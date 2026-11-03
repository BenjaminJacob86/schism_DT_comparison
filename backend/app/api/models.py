from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.services.colormaps import list_colormaps
from app.services.hydro import (
    available_model_ids,
    load_surface,
    list_model_metadata,
    mesh_payload,
    model_metadata,
    overlay_png_for,
    overlay_tile_for,
    polygon_stats,
    polygon_threshold_png,
    profile_payload,
    series_payload,
    step_payload,
    surface_payload,
    time_seconds_for,
)
from app.services.vectors import DEFAULT_N_ARROWS, vector_payload

router = APIRouter(prefix="/api/models", tags=["models"])

# Full-domain SCHISM meshes must not be sent as one Cesium JSON primitive.
_MAX_JSON_MESH_NODES = 25_000


def _refuse_full_mesh_json(meta: dict) -> None:
    n_nodes = int(meta.get("nNodes") or 0)
    if n_nodes > _MAX_JSON_MESH_NODES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Full-domain mesh is too large for a Cesium JSON primitive. "
                "Use GET /overlay/{t} or GET /tiles/{t}/{z}/{x}/{y}.png."
            ),
        )


def _list_or_503() -> list[dict]:
    try:
        return list_model_metadata()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _require_model(model_id: str) -> dict:
    try:
        if model_id not in available_model_ids():
            raise HTTPException(status_code=404, detail="Unknown model")
        return model_metadata(model_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("")
def list_models() -> list[dict]:
    return _list_or_503()


@router.get("/colormaps")
def get_colormaps() -> list[dict]:
    return list_colormaps()


@router.get("/", include_in_schema=False)
def list_models_slash() -> list[dict]:
    return list_models()


@router.get("/{model_id}")
def get_model(model_id: str) -> dict:
    return _require_model(model_id)


@router.get("/{model_id}/times")
def get_times(model_id: str) -> dict:
    _require_model(model_id)
    surf = load_surface(model_id)
    return {"id": model_id, "timeSeconds": time_seconds_for(model_id).astype(float).tolist()}


@router.get("/{model_id}/mesh")
def get_mesh(model_id: str) -> dict:
    meta = _require_model(model_id)
    _refuse_full_mesh_json(meta)
    return mesh_payload(model_id)


@router.get("/{model_id}/step/{time_index}")
def get_step(model_id: str, time_index: int) -> dict:
    _require_model(model_id)
    try:
        return step_payload(model_id, time_index)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{model_id}/series")
def get_series(
    model_id: str,
    lon: float = Query(...),
    lat: float = Query(...),
    variable: str | None = Query(default=None),
    layer: int | None = Query(default=None),
    z: float | None = Query(default=None),
) -> dict:
    _require_model(model_id)
    try:
        return series_payload(model_id, lon, lat, variable, layer, z)
    except LookupError as exc:
        detail = str(exc)
        code = 400 if "Unknown variable" in detail or "no vertical" in detail else 404
        raise HTTPException(status_code=code, detail=detail) from exc
    except (IndexError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{model_id}/profile")
def get_profile(
    model_id: str,
    lon: float = Query(...),
    lat: float = Query(...),
    timeIndex: int = Query(default=0),
    variable: str | None = Query(default=None),
) -> dict:
    _require_model(model_id)
    try:
        return profile_payload(model_id, lon, lat, timeIndex, variable)
    except LookupError as exc:
        detail = str(exc)
        code = 400 if "Unknown variable" in detail or "no vertical" in detail else 404
        raise HTTPException(status_code=code, detail=detail) from exc
    except (IndexError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class PolygonStatsRequest(BaseModel):
    ring: list[list[float]] = Field(min_length=3)
    variable: str | None = None
    timeIndex: int = 0
    layer: int | None = None
    z: float | None = None
    critical: float | None = None


@router.post("/{model_id}/polygon-stats")
def post_polygon_stats(model_id: str, body: PolygonStatsRequest) -> dict:
    _require_model(model_id)
    try:
        return polygon_stats(
            model_id,
            body.ring,
            body.timeIndex,
            body.variable,
            body.layer,
            body.z,
            body.critical,
        )
    except LookupError as exc:
        detail = str(exc)
        code = 400 if "Unknown variable" in detail else 404
        raise HTTPException(status_code=code, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (IndexError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{model_id}/polygon-threshold.png")
def post_polygon_threshold(model_id: str, body: PolygonStatsRequest) -> Response:
    _require_model(model_id)
    try:
        png, extent = polygon_threshold_png(
            model_id,
            body.ring,
            body.timeIndex,
            body.variable,
            body.layer,
            body.z,
            body.critical,
        )
    except LookupError as exc:
        detail = str(exc)
        code = 400 if "Unknown variable" in detail else 404
        raise HTTPException(status_code=code, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (IndexError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _png_overlay(png, extent)


def _png_overlay(png: bytes, extent: tuple[float, float, float, float]) -> Response:
    west, south, east, north = extent
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "Access-Control-Expose-Headers": "X-West, X-South, X-East, X-North",
            "X-West": f"{west:.8f}",
            "X-South": f"{south:.8f}",
            "X-East": f"{east:.8f}",
            "X-North": f"{north:.8f}",
        },
    )


@router.get("/{model_id}/overlay/{time_index}")
def get_overlay(
    model_id: str,
    time_index: int,
    vmin: float | None = Query(default=None),
    vmax: float | None = Query(default=None),
    variable: str | None = Query(default=None),
    colormap: str | None = Query(default=None),
    layer: int | None = Query(default=None),
    z: float | None = Query(default=None),
) -> Response:
    _require_model(model_id)
    try:
        png, extent = overlay_png_for(model_id, time_index, vmin, vmax, variable, colormap, layer, z)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (IndexError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _png_overlay(png, extent)


@router.get("/{model_id}/tiles/{time_index}/{level}/{x}/{y}.png")
def get_overlay_tile(
    model_id: str,
    time_index: int,
    level: int,
    x: int,
    y: int,
    vmin: float | None = Query(default=None),
    vmax: float | None = Query(default=None),
    variable: str | None = Query(default=None),
    colormap: str | None = Query(default=None),
    layer: int | None = Query(default=None),
    z: float | None = Query(default=None),
) -> Response:
    _require_model(model_id)
    try:
        png, extent = overlay_tile_for(
            model_id, time_index, level, x, y, vmin, vmax, variable, colormap, layer, z
        )
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (IndexError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _png_overlay(png, extent)


@router.get("/{model_id}/vectors/{time_index}")
def get_vectors(
    model_id: str,
    time_index: int,
    west: float = Query(...),
    south: float = Query(...),
    east: float = Query(...),
    north: float = Query(...),
    n: int = Query(default=DEFAULT_N_ARROWS),
    variable: str | None = Query(default=None),
    layer: int | None = Query(default=None),
    z: float | None = Query(default=None),
) -> dict:
    _require_model(model_id)
    try:
        return vector_payload(model_id, time_index, west, south, east, north, n, variable, layer, z)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (IndexError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{model_id}/surface")
def get_surface(model_id: str) -> dict:
    meta = _require_model(model_id)
    _refuse_full_mesh_json(meta)
    return surface_payload(model_id)
