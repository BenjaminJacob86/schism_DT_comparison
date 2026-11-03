"""cmocean palettes for SCHISM overlay tiles and the colorbar."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

DEFAULT_COLORMAP = "haline"

# Standard cmocean maps, grouped for the UI dropdown.
COLORMAP_CATALOG: tuple[dict[str, str], ...] = (
    {"id": "haline", "label": "Haline", "kind": "sequential"},
    {"id": "thermal", "label": "Thermal", "kind": "sequential"},
    {"id": "ice", "label": "Ice", "kind": "sequential"},
    {"id": "deep", "label": "Deep", "kind": "sequential"},
    {"id": "dense", "label": "Dense", "kind": "sequential"},
    {"id": "algae", "label": "Algae", "kind": "sequential"},
    {"id": "speed", "label": "Speed", "kind": "sequential"},
    {"id": "matter", "label": "Matter", "kind": "sequential"},
    {"id": "amp", "label": "Amp", "kind": "sequential"},
    {"id": "tempo", "label": "Tempo", "kind": "sequential"},
    {"id": "solar", "label": "Solar", "kind": "sequential"},
    {"id": "gray", "label": "Gray", "kind": "sequential"},
    {"id": "balance", "label": "Balance (red–blue)", "kind": "diverging"},
    {"id": "delta", "label": "Delta", "kind": "diverging"},
    {"id": "curl", "label": "Curl", "kind": "diverging"},
    {"id": "diff", "label": "Diff", "kind": "diverging"},
    {"id": "tarn", "label": "Tarn", "kind": "diverging"},
    {"id": "phase", "label": "Phase (cyclic)", "kind": "cyclic"},
)

_FALLBACK_STOPS = {
    "haline": np.array(
        [
            [0.16, 0.09, 0.42],
            [0.12, 0.38, 0.64],
            [0.13, 0.64, 0.66],
            [0.50, 0.79, 0.45],
            [0.99, 0.91, 0.40],
        ],
        dtype=np.float64,
    ),
    "balance": np.array(
        [
            [0.09, 0.19, 0.52],
            [0.35, 0.55, 0.80],
            [0.97, 0.97, 0.97],
            [0.84, 0.38, 0.30],
            [0.45, 0.06, 0.11],
        ],
        dtype=np.float64,
    ),
    "phase": np.array(
        [
            [0.69, 0.18, 0.35],
            [0.90, 0.55, 0.20],
            [0.95, 0.90, 0.30],
            [0.20, 0.65, 0.45],
            [0.20, 0.35, 0.70],
            [0.55, 0.20, 0.55],
            [0.69, 0.18, 0.35],
        ],
        dtype=np.float64,
    ),
}


def _resample_stops(stops: np.ndarray, n: int) -> np.ndarray:
    x = np.linspace(0.0, 1.0, n)
    pos = np.linspace(0.0, 1.0, len(stops))
    out = np.empty((n, 3), dtype=np.float64)
    for i in range(3):
        out[:, i] = np.interp(x, pos, stops[:, i])
    return out


@lru_cache(maxsize=64)
def colormap_lut(name: str, n: int = 256) -> np.ndarray:
    key = name if name in {item["id"] for item in COLORMAP_CATALOG} else DEFAULT_COLORMAP
    try:
        import cmocean

        cmap = getattr(cmocean.cm, key)
        return np.asarray(cmap(np.linspace(0.0, 1.0, n))[:, :3], dtype=np.float64)
    except Exception:
        stops = _FALLBACK_STOPS.get(key, _FALLBACK_STOPS[DEFAULT_COLORMAP])
        return _resample_stops(stops, n)


def resolve_colormap(name: str | None) -> str:
    if not name:
        return DEFAULT_COLORMAP
    ids = {item["id"] for item in COLORMAP_CATALOG}
    if name not in ids:
        raise LookupError(f"Unknown colormap {name}")
    return name


def _hex(rgb: np.ndarray) -> str:
    r, g, b = np.clip(rgb * 255.0, 0, 255).astype(np.int32)
    return f"#{r:02x}{g:02x}{b:02x}"


def colormap_payload(name: str | None = None) -> dict:
    cmap_id = resolve_colormap(name)
    lut = colormap_lut(cmap_id)
    n_stops = 9
    idx = np.linspace(0, len(lut) - 1, n_stops).astype(int)
    meta = next(item for item in COLORMAP_CATALOG if item["id"] == cmap_id)
    stops = [_hex(lut[i]) for i in idx]
    return {
        **meta,
        "stops": stops,
        "css": f"linear-gradient(90deg, {', '.join(stops)})",
    }


def list_colormaps() -> list[dict]:
    return [colormap_payload(item["id"]) for item in COLORMAP_CATALOG]
