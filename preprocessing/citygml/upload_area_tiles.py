"""Upload converted Hamburg 3D Tiles (not CityGML JPEGs) to EDITO MinIO.

Requires write credentials in AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.

    pip install s3fs
    python preprocessing/citygml/upload_area_tiles.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    try:
        import s3fs
    except ImportError:
        raise SystemExit("Install s3fs in this env: pip install s3fs") from None

    root = Path(__file__).resolve().parents[2] / "data" / "buildings" / "hamburg" / "area1"
    tileset = root / "tileset.json"
    tiles = root / "tiles"
    if not tileset.is_file() or not tiles.is_dir():
        raise SystemExit(f"Missing converted tiles at {root}")

    key = os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("S3_ACCESS_KEY")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("S3_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY (MinIO write keys).")

    endpoint = os.environ.get("S3_ENDPOINT", "https://minio.dive.edito.eu")
    bucket = os.environ.get("S3_BUCKET", "oidc-jacobb")
    prefix = os.environ.get("S3_BUILDINGS_PREFIX", "DigitalTwinTest/Buildings/hamburg/area1").strip("/")
    dest = f"{bucket}/{prefix}"
    fs = s3fs.S3FileSystem(key=key, secret=secret, client_kwargs={"endpoint_url": endpoint})
    print(f"{root} -> s3://{dest}/", flush=True)
    fs.put(str(root), dest, recursive=True)
    url = f"{endpoint.rstrip('/')}/{dest}/tileset.json"
    print(f"Uploaded. Public tileset URL (if the prefix is world-readable):\n  {url}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
