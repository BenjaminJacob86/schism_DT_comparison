"""Apply a new public S3/MinIO location and drop in-memory field caches."""

from __future__ import annotations

from app.config import apply_storage_fields, save_storage_override
from app.services import hydro, remote, vectors, zarr_store
from app.services.hydro import DEFAULT_MODEL_ID
from app.services.mesh_prep import ensure_surface_mesh, rebuild_surface_mesh
from app.services.vertical import reset_layered_cache


def apply_storage(
    payload: dict,
    persist: bool = True,
    rebuild: bool = True,
    mesh: bool = True,
) -> dict:
    apply_storage_fields(
        endpoint=str(payload.get("endpoint", "")),
        bucket=str(payload.get("bucket", "")),
        model_prefix=str(payload.get("modelPrefix", "")),
        zarr_prefix=str(payload.get("zarrPrefix", "")),
        buildings_prefix=str(payload.get("buildingsPrefix", "")),
    )
    if persist:
        save_storage_override()
        zarr_store.reset_all()
    else:
        zarr_store.reset_all()
    remote.reset_head_cache()
    hydro.reset_field_caches()
    vectors.reset_index_cache()
    reset_layered_cache()

    status = remote.status()
    if not mesh:
        status["meshRebuilt"] = False
        return status
    try:
        if rebuild:
            path = rebuild_surface_mesh(DEFAULT_MODEL_ID)
            print(f"Rebuilt surface mesh for new S3 source: {path}", flush=True)
        else:
            path = ensure_surface_mesh(DEFAULT_MODEL_ID)
            print(f"Surface mesh ready: {path}", flush=True)
        hydro.reset_field_caches()
        vectors.reset_index_cache()
        status["meshPath"] = str(path)
        status["meshError"] = None
        status["meshRebuilt"] = bool(rebuild)
    except Exception as exc:
        status["meshPath"] = None
        status["meshError"] = str(exc)
        status["meshRebuilt"] = False
    return status
