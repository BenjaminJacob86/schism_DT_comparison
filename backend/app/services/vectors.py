"""View-window velocity quiver: n×n sample, nearest unstructured-grid node (schismview)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

DEFAULT_N_ARROWS = 50
MAX_N_ARROWS = 80


def reset_index_cache() -> None:
    _coord_index.cache_clear()


def _square_window(west: float, south: float, east: float, north: float) -> tuple[float, float, float, float]:
    if east < west:
        west, east = east, west
    if north < south:
        south, north = north, south
    cx = 0.5 * (west + east)
    cy = 0.5 * (south + north)
    half = 0.5 * max(east - west, north - south, 1e-6)
    return cx - half, cy - half, cx + half, cy + half


def _clip_to_mesh(
    west: float, south: float, east: float, north: float, bbox: np.ndarray
) -> tuple[float, float, float, float] | None:
    west = max(west, float(bbox[0]))
    south = max(south, float(bbox[1]))
    east = min(east, float(bbox[2]))
    north = min(north, float(bbox[3]))
    if east <= west or north <= south:
        return None
    return west, south, east, north


@lru_cache(maxsize=4)
def _coord_index(model_id: str, mtime: float) -> dict:
    del mtime
    from app.services.hydro import load_surface

    surf = load_surface(model_id)
    lon = np.asarray(surf["lon"], dtype=np.float64)
    lat = np.asarray(surf["lat"], dtype=np.float64)
    finite = np.isfinite(lon) & np.isfinite(lat)
    idx = np.flatnonzero(finite)
    lo = lon[idx]
    la = lat[idx]
    xmin = float(lo.min())
    ymin = float(la.min())
    xmax = float(lo.max())
    ymax = float(la.max())
    cell = 0.02
    nx = int(np.ceil((xmax - xmin) / cell)) + 1
    ny = int(np.ceil((ymax - ymin) / cell)) + 1
    bx = np.clip(((lo - xmin) / cell).astype(np.int32), 0, nx - 1)
    by = np.clip(((la - ymin) / cell).astype(np.int32), 0, ny - 1)
    keys = bx.astype(np.int64) * ny + by
    order = np.argsort(keys, kind="mergesort")
    keys_s = keys[order]
    uniq, start, count = np.unique(keys_s, return_index=True, return_counts=True)
    lookup = {int(u): (int(s), int(c)) for u, s, c in zip(uniq, start, count)}
    tree = None
    try:
        from scipy.spatial import cKDTree

        tree = cKDTree(np.column_stack([lo, la]))
    except Exception:
        tree = None
    return {
        "idx": idx,
        "order": order,
        "lon": lo,
        "lat": la,
        "xmin": xmin,
        "ymin": ymin,
        "cell": cell,
        "nx": nx,
        "ny": ny,
        "lookup": lookup,
        "tree": tree,
    }


def _query_nearest(index: dict, qx: np.ndarray, qy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    nq = int(qx.size)
    out = np.full(nq, -1, dtype=np.int64)
    dist = np.full(nq, np.inf, dtype=np.float64)
    xmin = float(index["xmin"])
    ymin = float(index["ymin"])
    cell = float(index["cell"])
    nx = int(index["nx"])
    ny = int(index["ny"])
    lookup: dict[int, tuple[int, int]] = index["lookup"]
    order = index["order"]
    mesh_idx = index["idx"]
    lo = index["lon"]
    la = index["lat"]
    tree = index.get("tree")
    if tree is not None:
        d, ii = tree.query(np.column_stack([qx, qy]))
        out[:] = mesh_idx[np.asarray(ii, dtype=np.int64)]
        dist[:] = d
        return out, dist
    for k in range(nq):
        ix = int(np.floor((float(qx[k]) - xmin) / cell))
        iy = int(np.floor((float(qy[k]) - ymin) / cell))
        best = np.inf
        best_i = -1
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cx = ix + dx
                cy = iy + dy
                if cx < 0 or cy < 0 or cx >= nx or cy >= ny:
                    continue
                sl = lookup.get(cx * ny + cy)
                if sl is None:
                    continue
                s, c = sl
                local = mesh_idx[order[s : s + c]]
                d2 = (lo[order[s : s + c]] - qx[k]) ** 2 + (la[order[s : s + c]] - qy[k]) ** 2
                j = int(np.argmin(d2))
                val = float(d2[j])
                if val < best:
                    best = val
                    best_i = int(local[j])
        out[k] = best_i
        dist[k] = float(np.sqrt(best)) if best_i >= 0 else np.inf
    return out, dist


def _wet_nodes(surf: dict, dry: np.ndarray | None) -> np.ndarray:
    tris = np.asarray(surf["tris"])
    if tris.ndim == 1:
        tris = tris.reshape(-1, 3)
    n_tri = int(tris.shape[0])
    wet = np.ones(n_tri, dtype=bool)
    if dry is not None:
        flag = np.asarray(dry).reshape(-1)
        if flag.size >= n_tri:
            wet = flag[:n_tri] < 0.5
    nodes = np.zeros(int(np.asarray(surf["lon"]).size), dtype=bool)
    if wet.any():
        nodes[tris[wet].reshape(-1)] = True
    return nodes


def vector_payload(
    model_id: str,
    time_index: int,
    west: float,
    south: float,
    east: float,
    north: float,
    n_arrows: int = DEFAULT_N_ARROWS,
    variable: str | None = None,
    layer: int | None = None,
    z_meters: float | None = None,
) -> dict:
    from app.services.hydro import (
        _cached_pair_xy,
        _field_cached,
        _full_path,
        _resolve_spec,
        _slice_args,
        load_surface,
        model_metadata,
    )

    spec = _resolve_spec(model_id, variable)
    if spec.get("kind") != "pair":
        return {"id": model_id, "variable": spec.get("id"), "nArrows": 0, "lon": [], "lat": [], "u": [], "v": []}
    n = max(2, min(MAX_N_ARROWS, int(n_arrows or DEFAULT_N_ARROWS)))
    meta = model_metadata(model_id)
    t = max(0, min(int(meta["nTimes"]) - 1, int(time_index)))
    surf = load_surface(model_id)
    squared = _square_window(float(west), float(south), float(east), float(north))
    clipped = _clip_to_mesh(*squared, np.asarray(surf["bbox"], dtype=np.float64))
    if clipped is None:
        return {
            "id": model_id,
            "variable": spec["id"],
            "nArrows": n,
            "lon": [],
            "lat": [],
            "u": [],
            "v": [],
        }
    xmin, ymin, xmax, ymax = clipped
    cell = max(xmax - xmin, ymax - ymin) / max(n - 1, 1)
    gx = np.linspace(xmin, xmax, n)
    gy = np.linspace(ymin, ymax, n)
    xx, yy = np.meshgrid(gx, gy)
    qx = xx.ravel()
    qy = yy.ravel()
    path = _full_path(model_id)
    mtime = path.stat().st_mtime if path.exists() else 0.0
    index = _coord_index(model_id, mtime)
    qloc, dist = _query_nearest(index, qx, qy)
    uv = _cached_pair_xy(model_id, t, mtime, spec["id"])
    if uv is None:
        return {"id": model_id, "variable": spec["id"], "nArrows": n, "lon": [], "lat": [], "u": [], "v": []}
    u, v = uv
    k, zcode = _slice_args(spec, layer, z_meters)
    _, dry = _field_cached(model_id, t, mtime, spec["id"], k, zcode)
    wet = _wet_nodes(surf, dry)
    lon = np.asarray(surf["lon"], dtype=np.float64)
    lat = np.asarray(surf["lat"], dtype=np.float64)
    keep = (
        (qloc >= 0)
        & np.isfinite(dist)
        & (dist <= 0.75 * cell)
        & wet[qloc]
        & np.isfinite(u[qloc])
        & np.isfinite(v[qloc])
    )
    qloc = qloc[keep]
    if qloc.size == 0:
        return {
            "id": model_id,
            "variable": spec["id"],
            "timeIndex": t,
            "nArrows": n,
            "cell": cell,
            "west": xmin,
            "south": ymin,
            "east": xmax,
            "north": ymax,
            "lon": [],
            "lat": [],
            "u": [],
            "v": [],
        }
    _, first = np.unique(qloc, return_index=True)
    qloc = qloc[np.sort(first)]
    return {
        "id": model_id,
        "variable": spec["id"],
        "timeIndex": t,
        "nArrows": n,
        "cell": float(cell),
        "west": xmin,
        "south": ymin,
        "east": xmax,
        "north": ymax,
        "lon": np.asarray(lon[qloc], dtype=float).tolist(),
        "lat": np.asarray(lat[qloc], dtype=float).tolist(),
        "u": np.asarray(u[qloc], dtype=float).tolist(),
        "v": np.asarray(v[qloc], dtype=float).tolist(),
    }
