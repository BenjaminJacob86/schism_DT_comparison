"""SCHISM 3-D layers: temperature-style files, zCoordinates, z-interp, profiles.

Mirrors schismview (sigma layer k=0 bottom … k=nz-1 surface; CheckFixZ interpolation
via zCoordinates; profile_at_node). The browser never receives the 3-D cube.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

LAYER_DIM = "nSCHISM_vgrid_layers"
NODE_DIM = "nSCHISM_hgrid_node"
ZCOR_NAME = "zCoordinates"
SKIP_3D = frozenset({ZCOR_NAME, "zcor"})


def _stack_key(path: Path) -> int:
    return int(path.stem.split("_")[1])


def stack_files(source: Path, prefix: str) -> list[Path]:
    files = sorted(source.glob(f"{prefix}_*.nc"), key=_stack_key)
    if not files:
        raise FileNotFoundError(f"No {prefix}_*.nc in {source}")
    return files


def inspect_layered_nc(path: Path) -> list[dict]:
    """Read (time, node, layer) variables from one ``*_1.nc`` file."""
    prefix = path.name.rsplit("_", 1)[0]
    if prefix in {"out2d", "schout"}:
        return []
    from netCDF4 import Dataset

    found: list[dict] = []
    with Dataset(str(path)) as nc:
        if LAYER_DIM not in nc.dimensions:
            return []
        n_layers = int(nc.dimensions[LAYER_DIM].size)
        for name, var in nc.variables.items():
            if name in SKIP_3D:
                continue
            dims = tuple(var.dimensions)
            if (
                len(dims) == 3
                and "time" in dims
                and NODE_DIM in dims
                and LAYER_DIM in dims
            ):
                units = str(getattr(var, "units", "") or "")
                found.append(
                    {
                        "id": name,
                        "prefix": prefix,
                        "nc": name,
                        "nLayers": n_layers,
                        "units": units,
                    }
                )
    return found


@lru_cache(maxsize=8)
def discover_layered(source_str: str, stamp: float) -> tuple[dict, ...]:
    """Scan ``*_1.nc`` for (time, node, layer) variables. Skip zCoordinates."""
    del stamp
    source = Path(source_str)
    found: list[dict] = []
    for path in sorted(source.glob("*_1.nc")):
        found.extend(inspect_layered_nc(path))
    return tuple(found)


def reset_layered_cache() -> None:
    discover_layered.cache_clear()


def outputs_stamp(source: Path) -> float:
    times = [source.stat().st_mtime] if source.exists() else [0.0]
    for path in source.glob("*_1.nc"):
        times.append(path.stat().st_mtime)
    return max(times)


def resolve_layer(n_layers: int, layer: int | None) -> int:
    n = max(int(n_layers), 1)
    if layer is None:
        return n - 1
    k = int(layer)
    if k < 0:
        k = n + k
    return max(0, min(n - 1, k))


def interp_sigma_to_z(field: np.ndarray, zcor: np.ndarray, z_target: float) -> np.ndarray:
    """Linear interpolate (node, layer) to a constant elevation (SCHISM z, m)."""
    values = np.asarray(field, dtype=np.float64)
    z = np.asarray(zcor, dtype=np.float64)
    if values.ndim != 2 or z.shape != values.shape:
        raise ValueError(f"field/zcor shape mismatch {values.shape} vs {z.shape}")
    n_nodes, n_layers = values.shape
    out = np.full(n_nodes, np.nan, dtype=np.float32)
    if n_layers < 2:
        return out
    z0 = z[:, :-1]
    z1 = z[:, 1:]
    f0 = values[:, :-1]
    f1 = values[:, 1:]
    valid = np.isfinite(z0) & np.isfinite(z1) & np.isfinite(f0) & np.isfinite(f1) & (z1 != z0)
    lo = np.minimum(z0, z1)
    hi = np.maximum(z0, z1)
    hit = valid & (float(z_target) >= lo) & (float(z_target) <= hi)
    any_hit = hit.any(axis=1)
    if not np.any(any_hit):
        return out
    w = np.zeros_like(z0)
    dz = z1 - z0
    w[valid] = (float(z_target) - z0[valid]) / dz[valid]
    interp = f0 + w * (f1 - f0)
    idx = np.argmax(hit, axis=1)
    rows = np.arange(n_nodes)
    picked = interp[rows, idx]
    out[any_hit] = picked[any_hit].astype(np.float32)
    return out


def interp_column_to_z(values: np.ndarray, z: np.ndarray, z_target: float) -> float:
    field = np.asarray(values, dtype=np.float64).reshape(1, -1)
    zcor = np.asarray(z, dtype=np.float64).reshape(1, -1)
    out = interp_sigma_to_z(field, zcor, z_target)
    return float(out[0])


def mask_below_bottom(field: np.ndarray, bottom_index: np.ndarray | None) -> np.ndarray:
    """Zero-based layers k < (bottom_index - 1) are dry/garbage in SCHISM."""
    out = np.asarray(field, dtype=np.float32).copy()
    if bottom_index is None or out.ndim != 2:
        return out
    b = np.asarray(bottom_index, dtype=np.int32).reshape(-1)
    n_nodes, n_layers = out.shape
    if b.size != n_nodes:
        return out
    k = np.arange(n_layers, dtype=np.int32)[None, :]
    out[k < (b[:, None] - 1)] = np.nan
    return out
