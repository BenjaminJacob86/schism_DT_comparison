"""Drape SCHISM elevation from the unstructured mesh (wet triangles, UGRID holes)."""

from __future__ import annotations

from io import BytesIO
from threading import Lock

import matplotlib

matplotlib.use("Agg", force=True)
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.tri import LinearTriInterpolator, Triangulation
from PIL import Image, ImageDraw, ImageFilter

from app.services.colormaps import DEFAULT_COLORMAP, colormap_lut

# Full-domain snapshot (kept as the coarse start). Tiles use 256².
OVERLAY_WIDTH = 2048
TILE_SIZE = 256
TILE_PAD_PX = 4
# Above this triangle count, splat wet nodes instead of drawing every face.
TRIANGLE_DRAW_HARD_MAX = 180_000
_TRIPCOLOR_LOCK = Lock()

_empty_tile: bytes | None = None


def empty_png(width: int, height: int) -> bytes:
    global _empty_tile
    if width == TILE_SIZE and height == TILE_SIZE and _empty_tile is not None:
        return _empty_tile
    buf = BytesIO()
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(buf, format="PNG", compress_level=1)
    data = buf.getvalue()
    if width == TILE_SIZE and height == TILE_SIZE:
        _empty_tile = data
    return data


def cesium_geographic_tile_bbox(level: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Match Cesium GeographicTilingScheme: 2×1 tiles at level 0, y=0 is north."""
    tiles_x = 2 << int(level)
    tiles_y = 1 << int(level)
    west = -180.0 + x * (360.0 / tiles_x)
    east = -180.0 + (x + 1) * (360.0 / tiles_x)
    north = 90.0 - y * (180.0 / tiles_y)
    south = 90.0 - (y + 1) * (180.0 / tiles_y)
    return west, south, east, north


def _cmap_rgba(t: np.ndarray, visible: np.ndarray, lut: np.ndarray) -> np.ndarray:
    x = np.clip(t, 0.0, 1.0)
    pos = x * (len(lut) - 1)
    i0 = np.floor(pos).astype(np.int32)
    i1 = np.minimum(i0 + 1, len(lut) - 1)
    u = (pos - i0)[..., None]
    rgb = lut[i0] * (1.0 - u) + lut[i1] * u
    rgba = np.zeros(t.shape + (4,), dtype=np.uint8)
    rgba[..., :3] = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    rgba[..., 3] = np.where(visible, 220, 0).astype(np.uint8)
    return rgba


def _as_tris(tris: np.ndarray) -> np.ndarray:
    t = np.asarray(tris)
    if t.ndim == 1:
        t = t.reshape(-1, 3)
    return np.ascontiguousarray(t, dtype=np.int64)


def _wet_tri_mask(n_tri: int, dry: np.ndarray | None) -> np.ndarray:
    if dry is None:
        return np.ones(n_tri, dtype=bool)
    flag = np.asarray(dry).reshape(-1)
    if flag.size < n_tri:
        return np.ones(n_tri, dtype=bool)
    return flag[:n_tri] < 0.5


def _expand_wet_to_neighbors(
    tris: np.ndarray, wet: np.ndarray, n_nodes: int, limit: np.ndarray | None = None
) -> np.ndarray:
    """Fill dry faces that touch wet water. Optional limit keeps this O(tile), not O(mesh)."""
    if wet.all() or not bool(wet.any()):
        return wet
    work = np.ones(wet.shape[0], dtype=bool) if limit is None else np.asarray(limit, dtype=bool)
    idx = np.nonzero(work)[0]
    if idx.size == 0:
        return wet
    local = tris[idx]
    out_local = wet[idx]
    nodes = np.zeros(int(n_nodes), dtype=bool)
    for _ in range(2):
        hit = local[out_local]
        if hit.size == 0:
            break
        nodes.fill(False)
        nodes[hit.reshape(-1)] = True
        out_local = out_local | nodes[local[:, 0]] | nodes[local[:, 1]] | nodes[local[:, 2]]
    out = wet.copy()
    out[idx] = out_local
    return out


def _expand_triangle(
    x0: float, y0: float, x1: float, y1: float, x2: float, y2: float, pad: float = 1.25
) -> list[tuple[float, float]]:
    """Grow a triangle slightly so shared edges and sub-pixel faces still fill."""
    cx = (x0 + x1 + x2) / 3.0
    cy = (y0 + y1 + y2) / 3.0

    def grow(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - cx, y - cy
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1e-6:
            return x, y
        s = (length + pad) / length
        return cx + dx * s, cy + dy * s

    return [grow(x0, y0), grow(x1, y1), grow(x2, y2)]


def _png_bytes(image: Image.Image) -> bytes:
    arr = np.array(image, dtype=np.uint8, copy=True)
    if arr.ndim == 3 and arr.shape[2] == 4:
        alpha = arr[..., 3:4].astype(np.float32) / 255.0
        arr[..., :3] = np.clip(arr[..., :3].astype(np.float32) * alpha, 0, 255).astype(np.uint8)
    image = Image.fromarray(arr, mode="RGBA")
    buf = BytesIO()
    image.save(buf, format="PNG", compress_level=3)
    return buf.getvalue()


def _crop_pad(png: bytes, pad: int, nx: int, ny: int) -> bytes:
    if pad <= 0:
        return png
    image = Image.open(BytesIO(png))
    if image.size != (nx + 2 * pad, ny + 2 * pad):
        return png
    return _png_bytes(image.crop((pad, pad, pad + nx, pad + ny)))


def _wet_triangle_arrays(
    lon: np.ndarray,
    lat: np.ndarray,
    tris: np.ndarray,
    elev: np.ndarray,
    keep: np.ndarray,
    valid_abs: float | None,
) -> tuple[np.ndarray, np.ndarray] | None:
    idx = np.nonzero(keep)[0]
    if idx.size == 0:
        return None
    tri = tris[idx]
    mean = (elev[tri[:, 0]] + elev[tri[:, 1]] + elev[tri[:, 2]]) / 3.0
    ok = np.isfinite(mean)
    if valid_abs is not None:
        ok &= np.abs(mean) < valid_abs
    tri = tri[ok]
    mean = mean[ok]
    if tri.shape[0] == 0:
        return None
    return tri, mean


def _tripcolor_wet_triangles(
    lon: np.ndarray,
    lat: np.ndarray,
    tris: np.ndarray,
    elev: np.ndarray,
    keep: np.ndarray,
    west: float,
    south: float,
    east: float,
    north: float,
    nx: int,
    ny: int,
    vmin: float,
    vmax: float,
    valid_abs: float | None,
    lut: np.ndarray,
) -> bytes | None:
    """Rasterize triangle faces (not pixel-center samples) so sub-pixel Weser cells still paint."""
    packed = _wet_triangle_arrays(lon, lat, tris, elev, keep, valid_abs)
    if packed is None:
        return empty_png(nx, ny)
    tri, mean = packed
    scale = 2 if min(nx, ny) <= 512 and tri.shape[0] <= 40_000 else 1
    width, height = nx * scale, ny * scale
    try:
        mesh = Triangulation(lon, lat, triangles=tri)
        norm = (mean - vmin) / max(vmax - vmin, 1e-6)
        face = _cmap_rgba(norm, np.ones(mean.shape, dtype=bool), lut).astype(np.float64) / 255.0
        dpi = 100.0
        with _TRIPCOLOR_LOCK:
            fig = Figure(dpi=dpi)
            fig.set_size_inches(width / dpi, height / dpi, forward=True)
            fig.patch.set_facecolor((0.0, 0.0, 0.0, 0.0))
            canvas = FigureCanvasAgg(fig)
            ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
            ax.set_axis_off()
            ax.set_facecolor((0.0, 0.0, 0.0, 0.0))
            ax.set_xlim(west, east)
            ax.set_ylim(south, north)
            ax.tripcolor(
                mesh,
                facecolors=face,
                shading="flat",
                edgecolors=face,
                linewidths=1.0,
                antialiased=False,
            )
            canvas.draw()
            rgba = np.asarray(canvas.buffer_rgba()).copy()
            fig.clear()
        image = Image.fromarray(rgba, mode="RGBA")
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.NEAREST)
        if scale > 1:
            image = image.resize((nx, ny), Image.Resampling.BOX)
    except (ValueError, RuntimeError, TypeError):
        return None
    return _png_bytes(image)


def _coverage_wet_triangles(
    lon: np.ndarray,
    lat: np.ndarray,
    tris: np.ndarray,
    elev: np.ndarray,
    keep: np.ndarray,
    west: float,
    south: float,
    east: float,
    north: float,
    nx: int,
    ny: int,
    vmin: float,
    vmax: float,
    valid_abs: float | None,
    lut: np.ndarray,
) -> bytes | None:
    """Fast overview fill: stamp vertices/centroids so sub-pixel Weser cells still paint."""
    packed = _wet_triangle_arrays(lon, lat, tris, elev, keep, valid_abs)
    if packed is None:
        return empty_png(nx, ny)
    tri, mean = packed
    span_w = max(east - west, 1e-6)
    span_h = max(north - south, 1e-6)
    xs = (lon[tri] - west) / span_w * nx
    ys = (north - lat[tri]) / span_h * ny
    colors = _cmap_rgba(
        (mean - vmin) / max(vmax - vmin, 1e-6),
        np.ones(mean.shape, dtype=bool),
        lut,
    )
    stamps_x = np.concatenate(
        [
            xs[:, 0],
            xs[:, 1],
            xs[:, 2],
            xs.mean(axis=1),
            (xs[:, 0] + xs[:, 1]) * 0.5,
            (xs[:, 1] + xs[:, 2]) * 0.5,
            (xs[:, 2] + xs[:, 0]) * 0.5,
        ]
    )
    stamps_y = np.concatenate(
        [
            ys[:, 0],
            ys[:, 1],
            ys[:, 2],
            ys.mean(axis=1),
            (ys[:, 0] + ys[:, 1]) * 0.5,
            (ys[:, 1] + ys[:, 2]) * 0.5,
            (ys[:, 2] + ys[:, 0]) * 0.5,
        ]
    )
    stamps_c = np.tile(colors, (7, 1))
    in_tile = (
        (stamps_x >= -1.5)
        & (stamps_x <= nx + 0.5)
        & (stamps_y >= -1.5)
        & (stamps_y <= ny + 0.5)
    )
    stamps_x = stamps_x[in_tile]
    stamps_y = stamps_y[in_tile]
    stamps_c = stamps_c[in_tile]
    if stamps_x.size == 0:
        return empty_png(nx, ny)
    rgba = np.zeros((ny, nx, 4), dtype=np.uint8)
    ix = np.clip(np.rint(stamps_x).astype(np.int32), 0, nx - 1)
    iy = np.clip(np.rint(stamps_y).astype(np.int32), 0, ny - 1)
    for dyy in (-1, 0, 1):
        for dxx in (-1, 0, 1):
            rgba[np.clip(iy + dyy, 0, ny - 1), np.clip(ix + dxx, 0, nx - 1)] = stamps_c
    image = Image.fromarray(rgba, mode="RGBA")
    image = image.filter(ImageFilter.MaxFilter(3))
    return _png_bytes(image)


def _rasterize_faces(xs: np.ndarray, ys: np.ndarray, colors: np.ndarray, nx: int, ny: int) -> np.ndarray:
    """Conservative triangle fill in pixel space (1 px outward grow, then barycentric)."""
    rgba = np.zeros((ny, nx, 4), dtype=np.uint8)
    cx = xs.mean(axis=1, keepdims=True)
    cy = ys.mean(axis=1, keepdims=True)
    dx = xs - cx
    dy = ys - cy
    length = np.maximum(np.hypot(dx, dy), 1e-6)
    grow = (length + 1.0) / length
    xs = cx + dx * grow
    ys = cy + dy * grow
    x0, x1, x2 = xs[:, 0], xs[:, 1], xs[:, 2]
    y0, y1, y2 = ys[:, 0], ys[:, 1], ys[:, 2]
    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    minx = np.maximum(np.floor(xs.min(axis=1) - 0.5).astype(np.int32), 0)
    maxx = np.minimum(np.ceil(xs.max(axis=1) + 0.5).astype(np.int32), nx - 1)
    miny = np.maximum(np.floor(ys.min(axis=1) - 0.5).astype(np.int32), 0)
    maxy = np.minimum(np.ceil(ys.max(axis=1) + 0.5).astype(np.int32), ny - 1)
    n = int(xs.shape[0])
    for k in range(n):
        xlo, xhi = int(minx[k]), int(maxx[k])
        ylo, yhi = int(miny[k]), int(maxy[k])
        if xhi < xlo or yhi < ylo:
            ix = int(np.clip(np.rint(cx[k, 0]), 0, nx - 1))
            iy = int(np.clip(np.rint(cy[k, 0]), 0, ny - 1))
            rgba[iy, ix] = colors[k]
            continue
        a = float(area[k])
        if abs(a) < 1e-8:
            ix = int(np.clip(np.rint(cx[k, 0]), 0, nx - 1))
            iy = int(np.clip(np.rint(cy[k, 0]), 0, ny - 1))
            rgba[iy, ix] = colors[k]
            continue
        px = np.arange(xlo, xhi + 1, dtype=np.float64) + 0.5
        py = np.arange(ylo, yhi + 1, dtype=np.float64) + 0.5
        gx, gy = np.meshgrid(px, py)
        xa, xb, xc = float(x0[k]), float(x1[k]), float(x2[k])
        ya, yb, yc = float(y0[k]), float(y1[k]), float(y2[k])
        w0 = ((xb - gx) * (yc - gy) - (xc - gx) * (yb - gy)) / a
        w1 = ((xc - gx) * (ya - gy) - (xa - gx) * (yc - gy)) / a
        w2 = ((xa - gx) * (yb - gy) - (xb - gx) * (ya - gy)) / a
        inside = (w0 >= 0.0) & (w1 >= 0.0) & (w2 >= 0.0)
        if bool(inside.any()):
            rgba[ylo : yhi + 1, xlo : xhi + 1][inside] = colors[k]
        else:
            ix = int(np.clip(np.rint(cx[k, 0]), 0, nx - 1))
            iy = int(np.clip(np.rint(cy[k, 0]), 0, ny - 1))
            rgba[iy, ix] = colors[k]
    return rgba


def _triangle_area_px(
    lon: np.ndarray,
    lat: np.ndarray,
    tri: np.ndarray,
    west: float,
    south: float,
    east: float,
    north: float,
    nx: int,
    ny: int,
) -> np.ndarray:
    span_w = max(east - west, 1e-6)
    span_h = max(north - south, 1e-6)
    xs = (lon[tri] - west) / span_w * nx
    ys = (north - lat[tri]) / span_h * ny
    return 0.5 * np.abs(
        (xs[:, 1] - xs[:, 0]) * (ys[:, 2] - ys[:, 0]) - (xs[:, 2] - xs[:, 0]) * (ys[:, 1] - ys[:, 0])
    )


def _interp_wet_triangles(
    lon: np.ndarray,
    lat: np.ndarray,
    tris: np.ndarray,
    elev: np.ndarray,
    keep: np.ndarray,
    west: float,
    south: float,
    east: float,
    north: float,
    nx: int,
    ny: int,
    vmin: float,
    vmax: float,
    valid_abs: float | None,
    lut: np.ndarray,
) -> bytes | None:
    """Fill the tile from the unstructured mesh so zoom levels share a continuous field."""
    idx = np.nonzero(keep)[0]
    if idx.size == 0:
        return empty_png(nx, ny)
    tri = tris[idx]
    mean = (elev[tri[:, 0]] + elev[tri[:, 1]] + elev[tri[:, 2]]) / 3.0
    ok = np.isfinite(mean)
    if valid_abs is not None:
        ok &= np.abs(mean) < valid_abs
    tri = tri[ok]
    if tri.shape[0] == 0:
        return empty_png(nx, ny)
    try:
        used = np.unique(tri)
        inv = np.full(lon.size, -1, dtype=np.int64)
        inv[used] = np.arange(used.size, dtype=np.int64)
        mesh = Triangulation(lon[used], lat[used], triangles=inv[tri])
        interp = LinearTriInterpolator(mesh, elev[used])
    except (ValueError, RuntimeError):
        return None
    scale = 2 if min(nx, ny) <= 512 and tri.shape[0] <= 20_000 else 1
    sx, sy = nx * scale, ny * scale
    xs = west + (np.arange(sx, dtype=np.float64) + 0.5) * ((east - west) / sx)
    ys = north - (np.arange(sy, dtype=np.float64) + 0.5) * ((north - south) / sy)
    grid_x, grid_y = np.meshgrid(xs, ys)
    z = np.ma.filled(interp(grid_x, grid_y), np.nan)
    visible = np.isfinite(z)
    if valid_abs is not None:
        visible &= np.abs(z) < valid_abs
    if not bool(visible.any()):
        return empty_png(nx, ny)
    t = (np.where(visible, z, vmin) - vmin) / max(vmax - vmin, 1e-6)
    rgba = _cmap_rgba(t, visible, lut)
    image = Image.fromarray(rgba, mode="RGBA")
    if scale > 1:
        image = image.resize((nx, ny), Image.Resampling.BOX)
    return _png_bytes(image)


def _draw_wet_triangles(
    lon: np.ndarray,
    lat: np.ndarray,
    tris: np.ndarray,
    elev: np.ndarray,
    keep: np.ndarray,
    west: float,
    south: float,
    east: float,
    north: float,
    nx: int,
    ny: int,
    vmin: float,
    vmax: float,
    valid_abs: float | None,
    lut: np.ndarray,
) -> bytes:
    span_w = max(east - west, 1e-6)
    span_h = max(north - south, 1e-6)
    xs = (lon - west) / span_w * nx
    ys = (north - lat) / span_h * ny
    idx = np.nonzero(keep)[0]
    i0 = tris[idx, 0]
    i1 = tris[idx, 1]
    i2 = tris[idx, 2]
    mean = (elev[i0] + elev[i1] + elev[i2]) / 3.0
    finite = np.isfinite(mean)
    if valid_abs is not None:
        finite &= np.abs(mean) < valid_abs
    idx = idx[finite]
    i0, i1, i2, mean = i0[finite], i1[finite], i2[finite], mean[finite]
    if idx.size == 0:
        return empty_png(nx, ny)
    norm = (mean - vmin) / max(vmax - vmin, 1e-6)
    colors = _cmap_rgba(norm, np.ones(norm.shape, dtype=bool), lut)
    image = Image.new("RGBA", (nx, ny), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for k in range(idx.size):
        color = (int(colors[k, 0]), int(colors[k, 1]), int(colors[k, 2]), int(colors[k, 3]))
        pts = _expand_triangle(
            float(xs[i0[k]]),
            float(ys[i0[k]]),
            float(xs[i1[k]]),
            float(ys[i1[k]]),
            float(xs[i2[k]]),
            float(ys[i2[k]]),
        )
        draw.polygon(pts, fill=color)
        draw.line(pts + [pts[0]], fill=color, width=2)
    image = image.filter(ImageFilter.MaxFilter(3))
    alpha = np.asarray(image.getchannel("A"), dtype=np.uint8)
    if alpha.size and float((alpha > 0).mean()) < 0.18:
        image = image.filter(ImageFilter.MaxFilter(5))
    return _png_bytes(image)


def _splat_wet_nodes(
    lon: np.ndarray,
    lat: np.ndarray,
    tris: np.ndarray,
    elev: np.ndarray,
    keep: np.ndarray,
    west: float,
    south: float,
    east: float,
    north: float,
    nx: int,
    ny: int,
    vmin: float,
    vmax: float,
    valid_abs: float | None,
    lut: np.ndarray,
) -> bytes:
    """Overview splat: wet vertices + wet-triangle centroids. Does not flood islands."""
    span_w = max(east - west, 1e-6)
    span_h = max(north - south, 1e-6)
    pad_w = span_w / max(nx, 1)
    pad_h = span_h / max(ny, 1)
    wet_nodes = np.zeros(lon.size, dtype=bool)
    wet_tris = tris[keep]
    if wet_tris.size == 0:
        return empty_png(nx, ny)
    wet_nodes[wet_tris.reshape(-1)] = True
    finite = wet_nodes & np.isfinite(elev)
    if valid_abs is not None:
        finite &= np.abs(elev) < valid_abs
    slon = lon[finite]
    slat = lat[finite]
    selev = elev[finite]
    clon = wet_tris.astype(np.int64)
    c_lon = lon[clon].mean(axis=1)
    c_lat = lat[clon].mean(axis=1)
    c_elev = elev[clon].mean(axis=1)
    c_ok = np.isfinite(c_elev)
    if valid_abs is not None:
        c_ok &= np.abs(c_elev) < valid_abs
    slon = np.concatenate([slon, c_lon[c_ok]])
    slat = np.concatenate([slat, c_lat[c_ok]])
    selev = np.concatenate([selev, c_elev[c_ok]])
    in_view = (
        (slon >= west - pad_w)
        & (slon <= east + pad_w)
        & (slat >= south - pad_h)
        & (slat <= north + pad_h)
    )
    slon, slat, selev = slon[in_view], slat[in_view], selev[in_view]
    if slon.size == 0:
        return empty_png(nx, ny)
    ix = np.clip(((slon - west) / span_w * nx).astype(np.int32), 0, nx - 1)
    iy = np.clip(((north - slat) / span_h * ny).astype(np.int32), 0, ny - 1)
    sums = np.zeros((ny, nx), dtype=np.float64)
    counts = np.zeros((ny, nx), dtype=np.float64)
    n_hit = int(slon.size)
    typical_deg = float(np.sqrt((span_w * span_h) / max(n_hit, 1)))
    edge_px = typical_deg / span_w * nx
    radius = int(np.clip(np.round(max(2.0, edge_px * 0.9)), 2, 12))
    if n_hit > 0:
        density = max(n_hit / float(nx * ny), 1e-6)
        radius = max(radius, int(np.clip(np.round(0.75 / np.sqrt(density)), 2, 12)))
    if radius <= 1:
        np.add.at(sums, (iy, ix), selev)
        np.add.at(counts, (iy, ix), 1.0)
    else:
        yy, xx = np.mgrid[-radius : radius + 1, -radius : radius + 1]
        disk = (xx * xx + yy * yy) <= radius * radius
        dy, dx = np.nonzero(disk)
        for dyy, dxx in zip(dy - radius, dx - radius):
            np.add.at(sums, (np.clip(iy + dyy, 0, ny - 1), np.clip(ix + dxx, 0, nx - 1)), selev)
            np.add.at(counts, (np.clip(iy + dyy, 0, ny - 1), np.clip(ix + dxx, 0, nx - 1)), 1.0)
    hit = counts > 0
    grid = np.zeros((ny, nx), dtype=np.float64)
    grid[hit] = sums[hit] / counts[hit]
    t = (grid - vmin) / max(vmax - vmin, 1e-6)
    rgba = _cmap_rgba(t, hit, lut)
    image = Image.fromarray(rgba, mode="RGBA")
    image = image.filter(ImageFilter.MaxFilter(3))
    if float(hit.mean()) < 0.2:
        image = image.filter(ImageFilter.MaxFilter(5))
    return _png_bytes(image)


def render_elevation_png(
    lon: np.ndarray,
    lat: np.ndarray,
    tris: np.ndarray,
    elev: np.ndarray,
    dry: np.ndarray | None,
    vmin: float,
    vmax: float,
    west: float,
    south: float,
    east: float,
    north: float,
    width: int | None = None,
    height: int | None = None,
    valid_abs: float | None = 30.0,
    colormap: str = DEFAULT_COLORMAP,
) -> bytes:
    """Paint wet UGRID triangles. Dry cells and island holes stay transparent."""
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    elev = np.asarray(elev, dtype=np.float64)
    tris_i = _as_tris(tris)
    n_tri = int(tris_i.shape[0])
    span_w = max(east - west, 1e-6)
    span_h = max(north - south, 1e-6)
    nx = int(width) if width else OVERLAY_WIDTH
    ny = int(height) if height else max(512, int(round(OVERLAY_WIDTH * span_h / span_w)))
    if n_tri == 0:
        return empty_png(nx, ny)

    lon3 = lon[tris_i]
    lat3 = lat[tris_i]
    pad_w = span_w / max(nx, 1)
    pad_h = span_h / max(ny, 1)
    in_view = (
        (lon3.max(axis=1) >= west - pad_w)
        & (lon3.min(axis=1) <= east + pad_w)
        & (lat3.max(axis=1) >= south - pad_h)
        & (lat3.min(axis=1) <= north + pad_h)
    )
    wet = _expand_wet_to_neighbors(tris_i, _wet_tri_mask(n_tri, dry), lon.size, limit=in_view)
    keep = wet & in_view
    n_keep = int(keep.sum())
    if n_keep == 0:
        return empty_png(nx, ny)
    lut = colormap_lut(colormap)
    if n_keep <= TRIANGLE_DRAW_HARD_MAX:
        packed = _wet_triangle_arrays(lon, lat, tris_i, elev, keep, valid_abs)
        small_cells = False
        if packed is not None:
            tri, _mean = packed
            area_px = _triangle_area_px(lon, lat, tri, west, south, east, north, nx, ny)
            small_cells = bool(area_px.size) and (
                float(np.median(area_px)) < 10.0 or float((area_px < 2.0).mean()) > 0.02
            )
        if small_cells:
            filled = _coverage_wet_triangles(
                lon, lat, tris_i, elev, keep, west, south, east, north, nx, ny, vmin, vmax, valid_abs, lut
            )
            if filled is not None:
                return filled
        filled = _interp_wet_triangles(
            lon, lat, tris_i, elev, keep, west, south, east, north, nx, ny, vmin, vmax, valid_abs, lut
        )
        if filled is not None:
            return filled
        return _draw_wet_triangles(
            lon, lat, tris_i, elev, keep, west, south, east, north, nx, ny, vmin, vmax, valid_abs, lut
        )
    return _splat_wet_nodes(
        lon, lat, tris_i, elev, keep, west, south, east, north, nx, ny, vmin, vmax, valid_abs, lut
    )


def render_cesium_tile(
    lon: np.ndarray,
    lat: np.ndarray,
    tris: np.ndarray,
    elev: np.ndarray,
    dry: np.ndarray | None,
    vmin: float,
    vmax: float,
    west: float,
    south: float,
    east: float,
    north: float,
    valid_abs: float | None = 30.0,
    colormap: str = DEFAULT_COLORMAP,
) -> bytes:
    """256² Cesium tile with a 2 px overlap so adjacent zoom levels do not crack."""
    pad = TILE_PAD_PX
    span_w = max(east - west, 1e-6)
    span_h = max(north - south, 1e-6)
    pw = span_w / TILE_SIZE * pad
    ph = span_h / TILE_SIZE * pad
    png = render_elevation_png(
        lon,
        lat,
        tris,
        elev,
        dry,
        vmin,
        vmax,
        west - pw,
        south - ph,
        east + pw,
        north + ph,
        width=TILE_SIZE + 2 * pad,
        height=TILE_SIZE + 2 * pad,
        valid_abs=valid_abs,
        colormap=colormap,
    )
    return _crop_pad(png, pad, TILE_SIZE, TILE_SIZE)


THRESHOLD_BELOW_FILL = (190, 227, 248, 224)
THRESHOLD_BELOW_EDGE = (43, 108, 176, 240)
THRESHOLD_ABOVE_FILL = (229, 62, 62, 235)
THRESHOLD_ABOVE_EDGE = (197, 48, 48, 240)


def render_threshold_png(
    lon: np.ndarray,
    lat: np.ndarray,
    tris: np.ndarray,
    values: np.ndarray,
    keep: np.ndarray,
    west: float,
    south: float,
    east: float,
    north: float,
    critical: float,
    max_size: int = 1024,
) -> bytes:
    """Sharp triangle raster: below = light blue, above = red. Transparent elsewhere."""
    span_w = max(east - west, 1e-6)
    span_h = max(north - south, 1e-6)
    aspect = span_w / span_h
    if aspect >= 1.0:
        nx = int(max_size)
        ny = max(1, int(round(max_size / aspect)))
    else:
        ny = int(max_size)
        nx = max(1, int(round(max_size * aspect)))
    idx = np.nonzero(keep)[0]
    if idx.size == 0:
        return empty_png(nx, ny)
    faces = tris[idx]
    mean = values[idx]
    xs = (lon - west) / span_w * nx
    ys = (north - lat) / span_h * ny
    image = Image.new("RGBA", (nx, ny), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    crit = float(critical)
    for k in range(idx.size):
        i0, i1, i2 = int(faces[k, 0]), int(faces[k, 1]), int(faces[k, 2])
        pts = [
            (float(xs[i0]), float(ys[i0])),
            (float(xs[i1]), float(ys[i1])),
            (float(xs[i2]), float(ys[i2])),
        ]
        above = float(mean[k]) > crit
        fill = THRESHOLD_ABOVE_FILL if above else THRESHOLD_BELOW_FILL
        edge = THRESHOLD_ABOVE_EDGE if above else THRESHOLD_BELOW_EDGE
        draw.polygon(pts, fill=fill, outline=edge)
    return _png_bytes(image)
