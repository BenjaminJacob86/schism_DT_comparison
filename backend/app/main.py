"""Scientific API for the Hamburg Cesium viewer."""

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.api.assets import router as assets_router
from app.api.hub import router as hub_router
from app.api.models import router as models_router
from app.config import settings
from app.services import remote
from app.services.hydro import DEFAULT_MODEL_ID
from app.services.mesh_prep import ensure_surface_mesh
from app.services.storage import apply_storage


def _prepare_mesh_background() -> None:
    try:
        if settings.app_mode == "hub":
            from app.services.hub_compare import apply_hub_selection
            from app.services.hub_state import default_selection

            sel = default_selection()
            apply_hub_selection(a=sel.a, b=sel.b, view=sel.view, critical=sel.critical)
            print(f"Hub ready: A={sel.a} B={sel.b}", flush=True)
            return
        path = ensure_surface_mesh(DEFAULT_MODEL_ID)
        print(f"Surface mesh ready: {path}", flush=True)
    except Exception as exc:
        print(f"Surface mesh not ready at startup: {exc}", flush=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Do not block / or /health on S3 mesh build — Kubernetes probes fail otherwise.
    threading.Thread(target=_prepare_mesh_background, name="mesh-prep", daemon=True).start()
    yield


app = FastAPI(
    title="Hamburg 3D Hydro API",
    version="0.1.0",
    description="SCHISM overlay API. Full mesh/NetCDF/Zarr never leave the backend.",
    lifespan=lifespan,
)

_cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(models_router)
app.include_router(hub_router)
app.include_router(assets_router)


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "phase": "overlay",
        "dataSource": settings.data_source,
        "appMode": settings.app_mode,
    }


class StorageUpdate(BaseModel):
    endpoint: str
    bucket: str
    modelPrefix: str = Field(min_length=1)
    zarrPrefix: str = Field(min_length=1)
    buildingsPrefix: str = ""


@app.get("/api/storage")
def storage() -> dict:
    """Known-key S3/MinIO status. Does not list the bucket."""
    return remote.status()


@app.post("/api/storage")
def update_storage(body: StorageUpdate) -> dict:
    """Switch the public MinIO endpoint and object prefixes, then reload mesh/Zarr."""
    try:
        return apply_storage(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _frontend_dist() -> Path | None:
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if (dist / "index.html").is_file():
        return dist
    return None


_ui = _frontend_dist()


@app.get("/", include_in_schema=False)
def index():
    if _ui is not None:
        return FileResponse(_ui / "index.html")
    return HTMLResponse(
        "<html><body><p>API is up. Frontend dist is missing from this image.</p></body></html>",
        status_code=503,
    )


if _ui is not None:
    app.mount("/", StaticFiles(directory=_ui, html=True), name="ui")
    print(f"Serving UI from {_ui}", flush=True)
else:
    print("Frontend dist not found; container will serve API only", flush=True)
