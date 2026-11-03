"""Serve 3D Tiles. Prefer public MinIO keys; fall back to local converted tiles."""

from __future__ import annotations

import urllib.error

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.services import remote

router = APIRouter(prefix="/api/assets/buildings", tags=["assets"])

_MIME = {
    ".json": "application/json",
    ".glb": "model/gltf-binary",
    ".b3dm": "application/octet-stream",
}


def _safe_relative(path: str) -> str:
    rel = path.replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(status_code=400, detail="Invalid building asset path")
    return rel


def _content_type(name: str) -> str:
    lower = name.lower()
    for ext, mime in _MIME.items():
        if lower.endswith(ext):
            return mime
    return "application/octet-stream"


@router.get("/{path:path}")
def building_asset(path: str):
    rel = _safe_relative(path)
    url = remote.buildings_object_url(rel)
    mime = _content_type(rel)
    try:
        resp = remote.open_http(url)
    except urllib.error.HTTPError as exc:
        if exc.code not in {403, 404}:
            raise HTTPException(status_code=502, detail=f"S3 building fetch failed ({exc.code})") from exc
        local = remote.local_building_file(rel)
        if local is None:
            raise HTTPException(status_code=404, detail=f"Building asset not found: {rel}") from exc
        return FileResponse(local, media_type=mime)
    except urllib.error.URLError as exc:
        local = remote.local_building_file(rel)
        if local is None:
            raise HTTPException(status_code=502, detail=str(exc.reason)) from exc
        return FileResponse(local, media_type=mime)
    return StreamingResponse(
        remote.iter_opened(resp),
        media_type=mime,
        headers={"Cache-Control": "public, max-age=86400"},
    )
