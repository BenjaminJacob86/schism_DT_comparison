"""Convert Hamburg CityGML (EPSG:25832) to Cesium 3D Tiles 1.1 (glTF).

LoD3 wall/roof geometry is triangulated. Textures are omitted in this pass
(11 GB of JPEGs); surface-type colours give a readable city model.

Example:

    python preprocessing/citygml/convert_area.py
    python preprocessing/citygml/convert_area.py --limit 4
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pyproj import Transformer

SURFACE_KEEP = {
    "RoofSurface": np.array([0.72, 0.42, 0.34], dtype=np.float32),
    "WallSurface": np.array([0.90, 0.88, 0.84], dtype=np.float32),
    "ClosureSurface": np.array([0.84, 0.82, 0.78], dtype=np.float32),
    "OuterFloorSurface": np.array([0.78, 0.76, 0.72], dtype=np.float32),
    "OuterCeilingSurface": np.array([0.80, 0.78, 0.74], dtype=np.float32),
}

WGS84_A = 6378137.0
WGS84_E2 = 6.69437999014e-3


@dataclass
class TileMesh:
    tile_id: str
    positions_enu: np.ndarray  # float32 (N, 3) glTF Y-up
    normals: np.ndarray
    colors: np.ndarray
    indices: np.ndarray
    lon0: float
    lat0: float
    h0: float
    west: float
    south: float
    east: float
    north: float
    min_h: float
    max_h: float
    buildings: int
    triangles: int


def localname(elem: ET.Element) -> str:
    tag = elem.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def parse_poslist(text: str) -> np.ndarray | None:
    if not text:
        return None
    nums = np.fromstring(text, sep=" ", dtype=np.float64)
    if nums.size < 9 or nums.size % 3:
        return None
    pts = nums.reshape(-1, 3)
    if len(pts) >= 2 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 3:
        return None
    return pts


def clean_ring(pts: np.ndarray) -> np.ndarray | None:
    if pts is None or len(pts) < 3 or not np.isfinite(pts).all():
        return None
    kept: list[np.ndarray] = [pts[0]]
    for p in pts[1:]:
        if np.linalg.norm(p - kept[-1]) > 1e-3:
            kept.append(p)
    if len(kept) >= 2 and np.linalg.norm(kept[0] - kept[-1]) < 1e-3:
        kept.pop()
    if len(kept) < 3:
        return None
    return np.asarray(kept, dtype=np.float64)


def triangulate_polygon(pts: np.ndarray) -> np.ndarray:
    pts = clean_ring(pts)
    if pts is None:
        return np.zeros((0, 3), dtype=np.int32)
    n = len(pts)
    if n == 3:
        return np.array([[0, 1, 2]], dtype=np.int32)
    if n == 4:
        return np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
    return np.column_stack(
        (
            np.zeros(n - 2, dtype=np.int32),
            np.arange(1, n - 1, dtype=np.int32),
            np.arange(2, n, dtype=np.int32),
        )
    )


def geodetic_to_ecef(lon_deg: float, lat_deg: float, h: float) -> np.ndarray:
    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    slat, clat = math.sin(lat), math.cos(lat)
    slon, clon = math.sin(lon), math.cos(lon)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * slat * slat)
    return np.array(
        [
            (n + h) * clat * clon,
            (n + h) * clat * slon,
            (n * (1.0 - WGS84_E2) + h) * slat,
        ],
        dtype=np.float64,
    )


def enu_axes(lon_deg: float, lat_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    slat, clat = math.sin(lat), math.cos(lat)
    slon, clon = math.sin(lon), math.cos(lon)
    east = np.array([-slon, clon, 0.0])
    north = np.array([-slat * clon, -slat * slon, clat])
    up = np.array([clat * clon, clat * slon, slat])
    return east, north, up


def enu_to_ecef_matrix(lon_deg: float, lat_deg: float, h: float) -> list[float]:
    """Column-major 4x4: glTF Y-up (e, u, -n) after Cesium Y_UP_TO_Z_UP -> ENU."""
    east, north, up = enu_axes(lon_deg, lat_deg)
    origin = geodetic_to_ecef(lon_deg, lat_deg, h)
    cols = np.column_stack((east, north, up, origin))
    mat = np.eye(4, dtype=np.float64)
    mat[:3, :] = cols
    return mat.T.reshape(-1).tolist()  # column-major for 3D Tiles


def utm_to_gltf_yup(
    xyz: np.ndarray,
    transformer: Transformer,
    lon0: float,
    lat0: float,
    h0: float,
) -> np.ndarray:
    lon, lat, h = transformer.transform(xyz[:, 0], xyz[:, 1], xyz[:, 2])
    east, north, up = enu_axes(lon0, lat0)
    origin = geodetic_to_ecef(lon0, lat0, h0)
    lon_r = np.radians(lon)
    lat_r = np.radians(lat)
    slat, clat = np.sin(lat_r), np.cos(lat_r)
    slon, clon = np.sin(lon_r), np.cos(lon_r)
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * slat * slat)
    ecef = np.column_stack(
        (
            (n + h) * clat * clon,
            (n + h) * clat * slon,
            (n * (1.0 - WGS84_E2) + h) * slat,
        )
    )
    d = ecef - origin
    e = d[:, 0] * east[0] + d[:, 1] * east[1] + d[:, 2] * east[2]
    n_c = d[:, 0] * north[0] + d[:, 1] * north[1] + d[:, 2] * north[2]
    u = d[:, 0] * up[0] + d[:, 1] * up[1] + d[:, 2] * up[2]
    return np.column_stack((e, u, -n_c)).astype(np.float32)


def parse_envelope(path: Path) -> tuple[np.ndarray, np.ndarray] | None:
    head = path.read_bytes()[:12000].decode("utf-8", errors="ignore")
    low = re.search(r"<gml:lowerCorner>([^<]+)</gml:lowerCorner>", head)
    high = re.search(r"<gml:upperCorner>([^<]+)</gml:upperCorner>", head)
    if not low or not high:
        return None
    lo = np.fromstring(low.group(1), sep=" ")
    hi = np.fromstring(high.group(1), sep=" ")
    if lo.size < 3 or hi.size < 3:
        return None
    return lo[:3], hi[:3]


def convert_gml_file(gml: Path, transformer: Transformer) -> TileMesh | None:
    env = parse_envelope(gml)
    if env is None:
        return None
    lo, hi = env
    mid = (lo + hi) / 2.0
    lon0, lat0, h0 = transformer.transform(mid[0], mid[1], mid[2])
    west, south, zmin = transformer.transform(lo[0], lo[1], lo[2])
    east, north, zmax = transformer.transform(hi[0], hi[1], hi[2])
    if west > east:
        west, east = east, west
    if south > north:
        south, north = north, south

    print(f"    envelope lon={lon0:.5f} lat={lat0:.5f}", flush=True)
    positions: list[np.ndarray] = []
    colors: list[np.ndarray] = []
    buildings = 0
    surface: str | None = None
    in_interior = False
    skip_terrain = 0

    for event, elem in ET.iterparse(gml, events=("start", "end")):
        name = localname(elem)
        if event == "start":
            if name in ("Building", "BuildingPart"):
                buildings += 1
            if name in SURFACE_KEEP:
                surface = name
            if name == "interior":
                in_interior = True
            if name == "lod3TerrainIntersection":
                skip_terrain += 1
            continue

        if name == "interior":
            in_interior = False
        elif name == "lod3TerrainIntersection":
            skip_terrain = max(0, skip_terrain - 1)
        elif name in SURFACE_KEEP:
            surface = None
        elif (
            name == "posList"
            and surface is not None
            and not in_interior
            and skip_terrain == 0
        ):
            pts = parse_poslist(elem.text or "")
            ring = clean_ring(pts) if pts is not None else None
            if ring is not None:
                tris = triangulate_polygon(ring)
                if tris.size:
                    color = SURFACE_KEEP[surface]
                    for i0, i1, i2 in tris:
                        if max(i0, i1, i2) >= len(ring):
                            continue
                        tri = np.stack((ring[i0], ring[i1], ring[i2]))
                        positions.append(tri.astype(np.float64))
                        colors.append(np.repeat(color[None, :], 3, axis=0))
                if len(positions) and len(positions) % 40000 == 0:
                    print(f"    {len(positions)} tris", flush=True)
        elem.clear()

    if not positions:
        return None
    utm = np.vstack(positions)
    local = utm_to_gltf_yup(utm, transformer, lon0, lat0, h0)
    col = np.vstack(colors)
    # Flat normals per triangle (3 shared vertices).
    tri = local.reshape(-1, 3, 3)
    nrmv = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(nrmv, axis=1, keepdims=True)
    ln = np.maximum(ln, 1e-10)
    nrmv = (nrmv / ln).astype(np.float32)
    nrm = np.repeat(nrmv, 3, axis=0)
    return TileMesh(
        tile_id=gml.stem,
        positions_enu=local,
        normals=nrm,
        colors=col,
        indices=np.arange(len(local), dtype=np.uint32),
        lon0=float(lon0),
        lat0=float(lat0),
        h0=float(h0),
        west=float(west),
        south=float(south),
        east=float(east),
        north=float(north),
        min_h=float(min(zmin, zmax)),
        max_h=float(max(zmin, zmax)),
        buildings=buildings,
        triangles=len(local) // 3,
    )


def pad4(n: int) -> int:
    return (4 - (n % 4)) % 4


def write_glb(mesh: TileMesh, path: Path) -> None:
    pos = np.ascontiguousarray(mesh.positions_enu, dtype=np.float32)
    nrm = np.ascontiguousarray(mesh.normals, dtype=np.float32)
    col = np.clip(mesh.colors * 255.0, 0, 255).astype(np.uint8)
    col = np.ascontiguousarray(np.column_stack((col, np.full(len(col), 255, dtype=np.uint8))))
    idx = np.ascontiguousarray(mesh.indices, dtype=np.uint32)

    blobs = [pos.tobytes(), nrm.tobytes(), col.tobytes(), idx.tobytes()]
    views: list[dict] = []
    offset = 0
    for i, blob in enumerate(blobs):
        view: dict = {"buffer": 0, "byteOffset": offset, "byteLength": len(blob)}
        if i < 3:
            view["byteStride"] = 12 if i < 2 else 4
        views.append(view)
        offset += len(blob)

    mins = pos.min(axis=0).tolist()
    maxs = pos.max(axis=0).tolist()
    gltf = {
        "asset": {"version": "2.0", "generator": "hamburg-citygml-tiler"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2},
                        "indices": 3,
                        "material": 0,
                    }
                ]
            }
        ],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "metallicFactor": 0.05,
                    "roughnessFactor": 0.82,
                },
                "doubleSided": True,
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(pos),
                "type": "VEC3",
                "min": mins,
                "max": maxs,
            },
            {"bufferView": 1, "componentType": 5126, "count": len(nrm), "type": "VEC3"},
            {
                "bufferView": 2,
                "componentType": 5121,
                "count": len(col),
                "type": "VEC4",
                "normalized": True,
            },
            {
                "bufferView": 3,
                "componentType": 5125,
                "count": len(idx),
                "type": "SCALAR",
            },
        ],
        "bufferViews": [
            {k: v for k, v in views[0].items() if v is not None},
            {k: v for k, v in views[1].items() if v is not None},
            {k: v for k, v in views[2].items() if v is not None},
            {k: v for k, v in views[3].items() if v is not None},
        ],
        "buffers": [{"byteLength": offset}],
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * pad4(len(json_bytes))
    bin_bytes = b"".join(blobs)
    bin_bytes += b"\x00" * pad4(len(bin_bytes))

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(struct.pack("<4sII", b"glTF", 2, total))
        fh.write(struct.pack("<I4s", len(json_bytes), b"JSON"))
        fh.write(json_bytes)
        fh.write(struct.pack("<I4s", len(bin_bytes), b"BIN\x00"))
        fh.write(bin_bytes)


def region_of(mesh: TileMesh) -> list[float]:
    pad = 1.5
    return [
        math.radians(mesh.west) - 1e-7,
        math.radians(mesh.south) - 1e-7,
        math.radians(mesh.east) + 1e-7,
        math.radians(mesh.north) + 1e-7,
        mesh.min_h - pad,
        mesh.max_h + pad,
    ]


def local_enu_box(mesh: TileMesh) -> list[float]:
    """AABB in Z-up ENU (east, north, up), the space after Cesium's glTF Y-up conversion."""
    pos = mesh.positions_enu
    east, up, north = pos[:, 0], pos[:, 1], -pos[:, 2]
    min_e, max_e = float(east.min()), float(east.max())
    min_n, max_n = float(north.min()), float(north.max())
    min_u, max_u = float(up.min()), float(up.max())
    cx, cy, cz = (min_e + max_e) / 2, (min_n + max_n) / 2, (min_u + max_u) / 2
    hx = max((max_e - min_e) / 2, 1.0) + 2.0
    hy = max((max_n - min_n) / 2, 1.0) + 2.0
    hz = max((max_u - min_u) / 2, 1.0) + 2.0
    return [cx, cy, cz, hx, 0.0, 0.0, 0.0, hy, 0.0, 0.0, 0.0, hz]


def write_tileset(meshes: list[TileMesh], out_dir: Path) -> dict:
    west = min(m.west for m in meshes)
    south = min(m.south for m in meshes)
    east = max(m.east for m in meshes)
    north = max(m.north for m in meshes)
    min_h = min(m.min_h for m in meshes)
    max_h = max(m.max_h for m in meshes)
    children = []
    for mesh in meshes:
        children.append(
            {
                "boundingVolume": {"box": local_enu_box(mesh)},
                "geometricError": 24,
                "refine": "REPLACE",
                "content": {"uri": f"tiles/{mesh.tile_id}.glb"},
                "transform": enu_to_ecef_matrix(mesh.lon0, mesh.lat0, mesh.h0),
            }
        )
    tileset = {
        "asset": {"version": "1.1", "gltfUpAxis": "Y"},
        "geometricError": 500,
        "root": {
            "boundingVolume": {
                "region": [
                    math.radians(west),
                    math.radians(south),
                    math.radians(east),
                    math.radians(north),
                    min_h - 2,
                    max_h + 2,
                ]
            },
            "geometricError": 120,
            "refine": "ADD",
            "children": children,
        },
    }
    (out_dir / "tileset.json").write_text(json.dumps(tileset, indent=2), encoding="utf-8")
    meta = {
        "crs_in": "EPSG:25832",
        "area": "area1",
        "tiles": len(meshes),
        "buildings": sum(m.buildings for m in meshes),
        "triangles": sum(m.triangles for m in meshes),
        "center": {
            "longitude": (west + east) / 2,
            "latitude": (south + north) / 2,
            "height": 1800,
        },
        "extent": {
            "west": west,
            "south": south,
            "east": east,
            "north": north,
            "minHeight": min_h,
            "maxHeight": max_h,
        },
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def discover_gml(source: Path) -> list[Path]:
    files = sorted(source.glob("*/*.gml"))
    if not files:
        files = sorted(source.rglob("*.gml"))
    return files


def convert(
    source: Path,
    output: Path,
    limit: int | None = None,
    only: set[str] | None = None,
) -> None:
    files = discover_gml(source)
    if only:
        files = [p for p in files if p.stem in only]
    if limit is not None:
        files = files[:limit]
    if not files:
        raise SystemExit(f"No CityGML files in {source}")

    transformer = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
    output.mkdir(parents=True, exist_ok=True)
    tiles_dir = output / "tiles"
    tiles_dir.mkdir(exist_ok=True)

    meshes: list[TileMesh] = []
    for i, gml in enumerate(files, start=1):
        print(f"[{i}/{len(files)}] {gml.parent.name}", flush=True)
        try:
            mesh = convert_gml_file(gml, transformer)
        except Exception as exc:
            print(f"  skip ({type(exc).__name__}: {exc})", flush=True)
            continue
        if mesh is None:
            print("  skip (no mesh)", flush=True)
            continue
        write_glb(mesh, tiles_dir / f"{mesh.tile_id}.glb")
        meshes.append(mesh)
        print(
            f"  buildings={mesh.buildings} tris={mesh.triangles} "
            f"lon={mesh.lon0:.5f} lat={mesh.lat0:.5f}",
            flush=True,
        )

    if not meshes:
        raise SystemExit("No tiles produced")
    meta = write_tileset(meshes, output)
    print(
        f"Wrote {len(meshes)} tiles to {output / 'tileset.json'} "
        f"center={meta['center']['longitude']:.5f},{meta['center']['latitude']:.5f}",
        flush=True,
    )


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=root / "lod3-hh_area1_2023_12_14_180710_snap_1",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data" / "buildings" / "hamburg" / "area1",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", type=str, default="", help="Comma-separated tile ids")
    args = parser.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    convert(args.source, args.output, limit=args.limit, only=only)


if __name__ == "__main__":
    main()
