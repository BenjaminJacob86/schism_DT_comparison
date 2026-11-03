"""Resolve surface_mesh.npz: local, S3 cache, or build from hgrid.ll / Zarr / NetCDF."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from app.config import settings, using_default_storage

_LOCK = threading.Lock()
_PREP_DIR = Path(__file__).resolve().parents[3] / "preprocessing" / "model"
_PINNED: Path | None = None


def pin_surface_mesh(path: Path | str | None) -> None:
    """Keep one mesh for the process. Hub A/B pairs reuse it instead of rebuilding."""
    global _PINNED
    if path is None:
        _PINNED = None
        return
    candidate = Path(path)
    _PINNED = candidate if _ok(candidate) else None


def _shared_cached_mesh() -> Path | None:
    if _PINNED is not None and _ok(_PINNED):
        return _PINNED
    if settings.app_mode != "hub":
        return None
    root = settings.data_root / "cache" / "s3"
    if not root.is_dir():
        return None
    for path in root.rglob("surface_mesh.npz"):
        if _ok(path):
            return path
    return None


def _ok(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 1024
    except OSError:
        return False


def cache_mesh_path(model_id: str) -> Path:
    from app.services.remote import cache_dir

    return cache_dir() / model_id / "surface_mesh.npz"


def local_mesh_path(model_id: str) -> Path:
    return settings.data_root / "models" / model_id / "surface_mesh.npz"


def _use_remote() -> bool:
    return settings.data_source in {"s3", "zarr"}


def existing_mesh_path(model_id: str) -> Path | None:
    shared = _shared_cached_mesh()
    if shared is not None:
        return shared
    paths: tuple[Path, ...]
    if _use_remote() and not using_default_storage():
        paths = (cache_mesh_path(model_id), settings.s3_cache_dir / "surface_mesh.npz")
    else:
        paths = (
            local_mesh_path(model_id),
            cache_mesh_path(model_id),
            settings.s3_cache_dir / "surface_mesh.npz",
        )
    for path in paths:
        if _ok(path):
            return path
    return None


def _prepare_model():
    prep = str(_PREP_DIR)
    if prep not in sys.path:
        sys.path.insert(0, prep)
    import prepare_model

    return prepare_model


def _resolve_hgrid() -> Path | None:
    if _use_remote():
        from app.services import remote

        for key in ("hgrid.ll", "hgrid.gr3"):
            found = remote.fetch_known(key)
            if found is not None and _ok(found):
                print(f"hgrid from S3 {found}", flush=True)
                return found
        return None
    candidates = [settings.hgrid_ll]
    schism = settings.schism_dir
    if schism.name.lower() == "outputs":
        candidates.append(schism.parent / "hgrid.ll")
    candidates.append(schism / "hgrid.ll")
    seen: set[Path] = set()
    for path in candidates:
        path = Path(path)
        if path in seen:
            continue
        seen.add(path)
        if path.is_file():
            print(f"hgrid.ll from {path}", flush=True)
            return path
    return None


def _resolve_outputs() -> Path | None:
    if _use_remote():
        return None
    folder = settings.schism_dir
    if folder.is_dir() and any(folder.glob("out2d_*.nc")):
        return folder
    return None


def _zarr_url() -> str | None:
    if settings.data_source not in {"s3", "zarr"}:
        return None
    from app.services import zarr_store

    return zarr_store.zarr_url()


def _download_s3_mesh(model_id: str) -> Path | None:
    if not _use_remote():
        return None
    from app.services import remote

    for key in (f"{model_id}/surface_mesh.npz", "surface_mesh.npz"):
        found = remote.fetch_known(key)
        if found is not None and _ok(found):
            return found
    return None


def _build_mesh(model_id: str, dest: Path) -> Path:
    prep = _prepare_model()
    hgrid = _resolve_hgrid()
    combined = _resolve_outputs()
    zarr_path = _zarr_url()
    run_dir = combined.parent if combined is not None and combined.name.lower() == "outputs" else combined
    if hgrid is None and zarr_path is None and combined is None:
        raise FileNotFoundError(
            "No surface_mesh.npz, and cannot build one: need hgrid.ll and/or Zarr "
            f"(HGRID_LL={settings.hgrid_ll}, Zarr={zarr_path!r}, SCHISM_DIR={settings.schism_dir})"
        )
    print(
        f"Building surface_mesh.npz for {model_id} "
        f"(hgrid={hgrid}, zarr={zarr_path}, dir={combined}) -> {dest}",
        flush=True,
    )
    arrays = prep.extract(combined, run_dir, hgrid, zarr_path, settings.mesh_crs)
    prep._write(arrays, dest)
    print(f"Cached surface mesh {dest} ({dest.stat().st_size} bytes)", flush=True)
    return dest


def ensure_surface_mesh(model_id: str) -> Path:
    """Return a readable surface_mesh.npz, building it into the cache if needed."""
    with _LOCK:
        existing = existing_mesh_path(model_id)
        if existing is not None:
            return existing
        if settings.app_mode != "hub":
            downloaded = _download_s3_mesh(model_id)
            if downloaded is not None:
                return downloaded
        dest = cache_mesh_path(model_id)
        if _ok(dest):
            return dest
        built = _build_mesh(model_id, dest)
        pin_surface_mesh(built)
        return built


def rebuild_surface_mesh(model_id: str) -> Path:
    """Drop leftover local/old-cache meshes and rebuild from the current S3 hgrid/Zarr."""
    with _LOCK:
        from app.services import remote

        remote.discard_mesh_cache(model_id)
        downloaded = _download_s3_mesh(model_id)
        if downloaded is not None:
            print(f"Using S3 surface_mesh.npz {downloaded}", flush=True)
            return downloaded
        dest = cache_mesh_path(model_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        return _build_mesh(model_id, dest)


def cached_model_ids() -> set[str]:
    found: set[str] = set()
    cache = settings.s3_cache_dir
    if not cache.exists():
        return found
    if _ok(cache / "surface_mesh.npz"):
        found.add("sample_data")
    for path in cache.glob("*/surface_mesh.npz"):
        if _ok(path):
            found.add(path.parent.name)
    return found
