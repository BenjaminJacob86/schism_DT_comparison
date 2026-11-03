"""SCHISM hgrid.ll lon/lat — same convention as schismview.io.loader._load_hgrid_ll."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pyproj import Transformer


def load_hgrid_ll(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (lon, lat) node arrays.

    SCHISM ``hgrid.ll`` line 2 is ``ne np`` (elements, nodes). Node rows are
    ``id lon lat depth``.
    """
    header = np.loadtxt(path, skiprows=1, max_rows=1)
    n_nodes = int(header[1]) if np.ndim(header) else int(header)
    nodes = np.loadtxt(path, skiprows=2, max_rows=n_nodes, usecols=(0, 1, 2, 3))
    return np.asarray(nodes[:, 1], dtype=np.float64), np.asarray(nodes[:, 2], dtype=np.float64)


def load_hgrid(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return lon, lat, depth, and 0-based faces ``(n_elem, 4)`` with ``-1`` pad.

    SCHISM ``hgrid.gr3`` / ``hgrid.ll``:
    line 1 title, line 2 ``ne np``, then node rows ``id x y depth``,
    then element rows ``id i34 n1 n2 n3 [n4]`` (1-based node ids).
    """
    path = Path(path)
    header = np.loadtxt(path, skiprows=1, max_rows=1)
    n_elem = int(header[0])
    n_nodes = int(header[1]) if np.ndim(header) else int(header)
    nodes = np.loadtxt(path, skiprows=2, max_rows=n_nodes, usecols=(0, 1, 2, 3))
    lon = np.asarray(nodes[:, 1], dtype=np.float64)
    lat = np.asarray(nodes[:, 2], dtype=np.float64)
    depth = np.asarray(nodes[:, 3], dtype=np.float32)
    faces = np.full((n_elem, 4), -1, dtype=np.int64)
    with path.open(encoding="utf-8", errors="replace") as handle:
        handle.readline()
        handle.readline()
        for _ in range(n_nodes):
            handle.readline()
        for i in range(n_elem):
            parts = handle.readline().split()
            if len(parts) < 5:
                raise ValueError(f"{path}: expected element {i + 1}, got {parts!r}")
            nside = int(parts[1])
            for k in range(nside):
                faces[i, k] = int(parts[2 + k]) - 1
    return lon, lat, depth, faces


def looks_geographic(x: np.ndarray, y: np.ndarray) -> bool:
    """True when node x/y already look like lon/lat degrees."""
    finite_x = x[np.isfinite(x)]
    finite_y = y[np.isfinite(y)]
    if finite_x.size == 0 or finite_y.size == 0:
        return False
    return float(np.nanmax(np.abs(finite_x))) <= 180.5 and float(np.nanmax(np.abs(finite_y))) <= 90.5


def project_xy(x: np.ndarray, y: np.ndarray, crs: str) -> tuple[np.ndarray, np.ndarray, str]:
    lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(x, y)
    return np.asarray(lon, dtype=np.float64), np.asarray(lat, dtype=np.float64), f"{crs}->4326"


def resolve_lonlat(
    x: np.ndarray,
    y: np.ndarray,
    combined: Path,
    run_dir: Path | None = None,
    hgrid: Path | None = None,
    crs: str = "EPSG:25832",
) -> tuple[np.ndarray, np.ndarray, str]:
    """Prefer matching hgrid.ll (schismview plot_xy lonlat=True). Else geographic or --crs."""
    nnodes = int(x.size)
    candidates: list[Path] = []
    if hgrid is not None:
        candidates.append(Path(hgrid))
    if run_dir is not None:
        candidates.append(Path(run_dir) / "hgrid.ll")
    candidates.append(Path(combined) / "hgrid.ll")
    # SCHISM layout: hgrid.ll sits next to outputs/. Never walk a shared parent
    # (e.g. schismview-refactor) — that would mix sample_data hgrid.ll with sample_data2.
    if Path(combined).name.lower() == "outputs":
        candidates.append(Path(combined).parent / "hgrid.ll")
    seen: set[Path] = set()
    for path in candidates:
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        lon, lat = load_hgrid_ll(path)
        if lon.size != nnodes:
            print(
                f"skip {path}: {lon.size} nodes vs grid {nnodes} "
                "(schismview would warn of misaligned lon/lat)",
                flush=True,
            )
            continue
        print(f"lon/lat from {path} ({nnodes} nodes)", flush=True)
        return lon, lat, "hgrid.ll"
    if looks_geographic(x, y):
        print("lon/lat from grid node x/y (already geographic)", flush=True)
        return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64), "geographic"
    print(f"lon/lat via {crs} -> EPSG:4326 (no matching hgrid.ll)", flush=True)
    return project_xy(x, y, crs)
