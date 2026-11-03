from pathlib import Path
import hashlib
import json
import os
import re


class Settings:
    """Local paths or public MinIO (EDITO). Object keys are known; listing is not required."""

    data_root: Path = Path(os.environ.get("DATA_ROOT", Path(__file__).resolve().parents[2] / "data"))
    cors_origins: str = os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
    )
    schism_dir: Path = Path(
        os.environ.get(
            "SCHISM_DIR",
            r"C:\Users\jacobb\Desktop\agent_dev_studio\schismview-refactor\sample_data\outputs",
        )
    )
    hgrid_ll: Path = Path(
        os.environ.get(
            "HGRID_LL",
            r"C:\Users\jacobb\Desktop\agent_dev_studio\schismview-refactor\sample_data\hgrid.ll",
        )
    )
    data_source: str = os.environ.get("DATA_SOURCE", "s3").strip().lower()
    s3_endpoint: str = os.environ.get("S3_ENDPOINT", "https://minio.dive.edito.eu").rstrip("/")
    s3_bucket: str = os.environ.get("S3_BUCKET", "project-foccus")
    s3_model_prefix: str = os.environ.get("S3_MODEL_PREFIX", "DigitalTwinTest/model").strip("/")
    s3_zarr_prefix: str = os.environ.get("S3_ZARR_PREFIX", "DigitalTwinTest/zarr/schism.zarr").strip("/")
    s3_buildings_prefix: str = os.environ.get(
        "S3_BUILDINGS_PREFIX",
        "DigitalTwinTest/Buildings/hamburg/area1",
    ).strip("/")
    s3_cache_dir: Path = Path(
        os.environ.get("S3_CACHE_DIR", str(data_root / "cache" / "s3" / "model"))
    )
    mesh_crs: str = os.environ.get("MESH_CRS", "EPSG:25832")
    app_mode: str = os.environ.get("APP_MODE", "hub").strip().lower() or "hub"


settings = Settings()

_ENV_ENDPOINT = settings.s3_endpoint
_ENV_BUCKET = settings.s3_bucket
_ENV_MODEL_PREFIX = settings.s3_model_prefix
_ENV_ZARR_PREFIX = settings.s3_zarr_prefix
_ENV_BUILDINGS_PREFIX = settings.s3_buildings_prefix
_ENV_CACHE_DIR = settings.s3_cache_dir


def storage_override_path() -> Path:
    return settings.data_root / "storage_override.json"


def storage_fields() -> dict[str, str]:
    return {
        "endpoint": settings.s3_endpoint,
        "bucket": settings.s3_bucket,
        "modelPrefix": settings.s3_model_prefix,
        "zarrPrefix": settings.s3_zarr_prefix,
        "buildingsPrefix": settings.s3_buildings_prefix,
    }


def normalize_endpoint(value: str) -> str:
    text = str(value or "").strip().rstrip("/")
    if not re.match(r"^https?://", text, re.I):
        raise ValueError("Endpoint must be an http(s) URL")
    return text


def normalize_bucket(value: str) -> str:
    text = str(value or "").strip().strip("/")
    if not text or "/" in text or ".." in text:
        raise ValueError("Bucket must be a single name")
    return text


def normalize_prefix(value: str, *, allow_empty: bool = False) -> str:
    text = str(value or "").strip().replace("\\", "/").strip("/")
    if ".." in text.split("/"):
        raise ValueError("Path must not contain '..'")
    if not text and not allow_empty:
        raise ValueError("Path is required")
    return text


def using_default_storage() -> bool:
    return (
        settings.s3_endpoint == _ENV_ENDPOINT
        and settings.s3_bucket == _ENV_BUCKET
        and settings.s3_model_prefix == _ENV_MODEL_PREFIX
        and settings.s3_zarr_prefix == _ENV_ZARR_PREFIX
        and settings.s3_buildings_prefix == _ENV_BUILDINGS_PREFIX
    )


def refresh_cache_dir() -> None:
    if using_default_storage():
        settings.s3_cache_dir = _ENV_CACHE_DIR
        return
    raw = "|".join(
        (
            settings.s3_endpoint,
            settings.s3_bucket,
            settings.s3_model_prefix,
            settings.s3_zarr_prefix,
            settings.s3_buildings_prefix,
        )
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    settings.s3_cache_dir = settings.data_root / "cache" / "s3" / digest


def apply_storage_fields(
    *,
    endpoint: str,
    bucket: str,
    model_prefix: str,
    zarr_prefix: str,
    buildings_prefix: str,
) -> None:
    settings.s3_endpoint = normalize_endpoint(endpoint)
    settings.s3_bucket = normalize_bucket(bucket)
    settings.s3_model_prefix = normalize_prefix(model_prefix)
    settings.s3_zarr_prefix = normalize_prefix(zarr_prefix)
    settings.s3_buildings_prefix = normalize_prefix(buildings_prefix, allow_empty=True)
    refresh_cache_dir()


def save_storage_override() -> None:
    path = storage_override_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(storage_fields(), indent=2) + "\n", encoding="utf-8")


def load_storage_override() -> None:
    if settings.app_mode == "hub":
        print("Hub mode: ignoring storage_override.json; using config/scenarios.json", flush=True)
        return
    path = storage_override_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Ignoring storage override {path}: {exc}", flush=True)
        return
    if not isinstance(data, dict):
        return
    try:
        apply_storage_fields(
            endpoint=str(data.get("endpoint", settings.s3_endpoint)),
            bucket=str(data.get("bucket", settings.s3_bucket)),
            model_prefix=str(data.get("modelPrefix", settings.s3_model_prefix)),
            zarr_prefix=str(data.get("zarrPrefix", settings.s3_zarr_prefix)),
            buildings_prefix=str(data.get("buildingsPrefix", settings.s3_buildings_prefix)),
        )
        print(f"Loaded storage override from {path}", flush=True)
    except ValueError as exc:
        print(f"Ignoring invalid storage override: {exc}", flush=True)


load_storage_override()
