"""Public MinIO objects by known key. Never ListBucket — HEAD/GET only."""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from pathlib import Path

from app.config import settings

_LOCK = threading.Lock()
_HEAD_OK: dict[str, bool] = {}


def reset_head_cache() -> None:
    with _LOCK:
        _HEAD_OK.clear()


def cache_dir() -> Path:
    path = settings.s3_cache_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def object_url(filename: str) -> str:
    prefix = settings.s3_model_prefix.strip("/")
    name = filename.replace("\\", "/").lstrip("/")
    if prefix:
        return f"{settings.s3_endpoint.rstrip('/')}/{settings.s3_bucket}/{prefix}/{name}"
    return f"{settings.s3_endpoint.rstrip('/')}/{settings.s3_bucket}/{name}"


def _object_prefixes() -> list[str]:
    prefixes: list[str] = []

    def add(value: str) -> None:
        text = str(value or "").strip().replace("\\", "/").strip("/")
        if text not in prefixes:
            prefixes.append(text)

    add(settings.s3_model_prefix)
    zarr = settings.s3_zarr_prefix.strip("/")
    if zarr.endswith(".zarr") and "/" in zarr:
        add(zarr.rsplit("/", 1)[0])
    elif zarr:
        add(zarr)
    if "/" in settings.s3_model_prefix.strip("/"):
        add(settings.s3_model_prefix.strip("/").rsplit("/", 1)[0])
    add("")
    return prefixes


def candidate_urls(filename: str) -> list[str]:
    name = filename.replace("\\", "/").lstrip("/")
    ep = settings.s3_endpoint.rstrip("/")
    bucket = settings.s3_bucket
    urls: list[str] = []
    for prefix in _object_prefixes():
        url = f"{ep}/{bucket}/{prefix}/{name}" if prefix else f"{ep}/{bucket}/{name}"
        if url not in urls:
            urls.append(url)
    return urls


def download_url(url: str, dest: Path) -> Path | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        print(f"Downloading {url} -> {dest}", flush=True)
        req = _request(url, "GET")
        with urllib.request.urlopen(req, timeout=3600) as resp, tmp.open("wb") as out:
            while True:
                chunk = resp.read(8 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(dest)
        print(f"Cached {dest} ({dest.stat().st_size} bytes)", flush=True)
        return dest
    except urllib.error.HTTPError as exc:
        if tmp.exists():
            tmp.unlink()
        if exc.code in {403, 404, 405}:
            print(f"S3 GET {exc.code} {url}", flush=True)
            return None
        raise
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def fetch_known(filename: str) -> Path | None:
    """HEAD/GET a known object under model prefix, dataset root, or bucket root."""
    dest = cache_dir() / Path(filename.replace("\\", "/").lstrip("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        for url in candidate_urls(filename):
            found = download_url(url, dest)
            if found is not None and found.stat().st_size > 0:
                return found
        return None


def discard_mesh_cache(model_id: str) -> None:
    root = cache_dir()
    for rel in ("hgrid.ll", "hgrid.gr3", "surface_mesh.npz", f"{model_id}/surface_mesh.npz"):
        path = root / rel
        if path.is_file():
            print(f"Dropping cached {path}", flush=True)
            path.unlink()


def buildings_object_url(relative: str) -> str:
    prefix = settings.s3_buildings_prefix.strip("/")
    rel = relative.replace("\\", "/").lstrip("/")
    return f"{settings.s3_endpoint.rstrip('/')}/{settings.s3_bucket}/{prefix}/{rel}"


def buildings_tileset_url() -> str:
    return buildings_object_url("tileset.json")


def local_building_file(relative: str) -> Path | None:
    rel = relative.replace("\\", "/").lstrip("/")
    parts = Path(rel).parts
    if not rel or ".." in parts:
        return None
    path = (settings.data_root / "buildings" / "hamburg" / "area1").joinpath(*parts)
    if path.is_file():
        return path
    return None


def iter_opened(resp):
    try:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        resp.close()


def open_http(url: str):
    req = _request(url, "GET")
    return urllib.request.urlopen(req, timeout=120)


def _request(url: str, method: str, timeout: float | None = 30.0) -> urllib.request.Request:
    return urllib.request.Request(url, method=method, headers={"User-Agent": "hamburg-3d-hydro/0.1"})


def head_ok(url: str) -> bool:
    if url in _HEAD_OK:
        return _HEAD_OK[url]
    try:
        req = _request(url, "HEAD")
        with urllib.request.urlopen(req, timeout=30) as resp:
            ok = 200 <= int(resp.status) < 300
    except urllib.error.HTTPError as exc:
        ok = False
        if exc.code not in {403, 404, 405}:
            print(f"S3 HEAD {exc.code} {url}", flush=True)
    except Exception as exc:
        ok = False
        print(f"S3 HEAD failed {url}: {exc}", flush=True)
    _HEAD_OK[url] = ok
    return ok


def remote_exists(filename: str) -> bool:
    return head_ok(object_url(filename))


def ensure_file_if_exists(filename: str) -> Path | None:
    if not remote_exists(filename):
        return None
    return ensure_file(filename)


def ensure_file(filename: str) -> Path:
    dest = cache_dir() / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = object_url(filename)
    with _LOCK:
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        if not head_ok(url):
            raise FileNotFoundError(f"S3 object not found (no listing): {url}")
        tmp = dest.with_suffix(dest.suffix + ".part")
        print(f"Downloading {url} -> {dest}", flush=True)
        try:
            req = _request(url, "GET")
            with urllib.request.urlopen(req, timeout=3600) as resp, tmp.open("wb") as out:
                total = resp.headers.get("Content-Length")
                n = int(total) if total and total.isdigit() else None
                copied = 0
                while True:
                    chunk = resp.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    copied += len(chunk)
                    if n:
                        pct = 100.0 * copied / n
                        print(f"  {filename} {copied / 1e6:.0f}/{n / 1e6:.0f} MB ({pct:.0f}%)", flush=True)
            tmp.replace(dest)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
        print(f"Cached {dest} ({dest.stat().st_size} bytes)", flush=True)
        return dest


def status() -> dict:
    cached = []
    root = settings.s3_cache_dir
    if root.exists():
        cached = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p.suffix in {".nc", ".npz"})
    tileset = buildings_tileset_url()
    zarr_info = {}
    try:
        from app.services import zarr_store

        zarr_info = zarr_store.status()
    except Exception as exc:
        zarr_info = {"zarrError": str(exc)}
    return {
        "dataSource": settings.data_source,
        "endpoint": settings.s3_endpoint,
        "bucket": settings.s3_bucket,
        "modelPrefix": settings.s3_model_prefix,
        "zarrPrefix": settings.s3_zarr_prefix,
        "exampleObject": object_url("surface_mesh.npz"),
        "cacheDir": str(cache_dir()) if settings.data_source == "s3" else None,
        "cachedFiles": cached,
        "buildingsPrefix": settings.s3_buildings_prefix,
        "buildingsTileset": tileset,
        "buildingsTilesetOk": head_ok(tileset) if settings.data_source == "s3" else None,
        **zarr_info,
    }
