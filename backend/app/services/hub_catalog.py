"""Named digital-twin scenarios on public MinIO. JSON so the hub needs no extra YAML parser."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import settings


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    endpoint: str
    bucket: str
    model_prefix: str
    zarr_prefix: str
    buildings_prefix: str

    def storage_payload(self) -> dict[str, str]:
        return {
            "endpoint": self.endpoint,
            "bucket": self.bucket,
            "modelPrefix": self.model_prefix,
            "zarrPrefix": self.zarr_prefix,
            "buildingsPrefix": self.buildings_prefix,
        }


@dataclass(frozen=True)
class ScenarioCatalog:
    title: str
    tagline: str
    default_a: str
    default_b: str
    critical_default: float
    scenarios: tuple[Scenario, ...]

    def by_id(self, key: str) -> Scenario:
        for item in self.scenarios:
            if item.id == key:
                return item
        raise LookupError(f"Unknown scenario {key}")

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "tagline": self.tagline,
            "defaultA": self.default_a,
            "defaultB": self.default_b,
            "criticalDefault": self.critical_default,
            "scenarios": [
                {
                    "id": item.id,
                    "label": item.label,
                    **item.storage_payload(),
                }
                for item in self.scenarios
            ],
        }


def catalog_path() -> Path:
    env = str(__import__("os").environ.get("SCENARIOS_FILE", "")).strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "config" / "scenarios.json"


@lru_cache(maxsize=1)
def load_catalog(stamp: float = 0.0) -> ScenarioCatalog:
    del stamp
    path = catalog_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for raw in data.get("scenarios") or []:
        items.append(
            Scenario(
                id=str(raw["id"]).strip(),
                label=str(raw.get("label") or raw["id"]).strip(),
                endpoint=str(raw.get("endpoint") or settings.s3_endpoint).rstrip("/"),
                bucket=str(raw.get("bucket") or settings.s3_bucket).strip("/"),
                model_prefix=str(raw["modelPrefix"]).strip("/"),
                zarr_prefix=str(raw["zarrPrefix"]).strip("/"),
                buildings_prefix=str(raw.get("buildingsPrefix") or "").strip("/"),
            )
        )
    if len(items) < 2:
        raise ValueError(f"{path} needs at least two scenarios")
    ids = {item.id for item in items}
    default_a = str(data.get("defaultA") or items[0].id)
    default_b = str(data.get("defaultB") or items[1].id)
    if default_a not in ids:
        default_a = items[0].id
    if default_b not in ids:
        default_b = items[1].id
    return ScenarioCatalog(
        title=str(data.get("title") or "Scenario hub"),
        tagline=str(data.get("tagline") or ""),
        default_a=default_a,
        default_b=default_b,
        critical_default=float(data.get("criticalDefault") or 0.0),
        scenarios=tuple(items),
    )


def catalog() -> ScenarioCatalog:
    path = catalog_path()
    mtime = path.stat().st_mtime if path.is_file() else 0.0
    return load_catalog(mtime)
