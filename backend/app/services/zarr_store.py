"""Stream SCHISM fields from a public Zarr v3 store (HTTP, no bucket listing)."""

from __future__ import annotations

import threading
from collections import OrderedDict

import numpy as np
import zarr

from app.config import settings

_POOL_LOCK = threading.RLock()
_STORES: dict[tuple[str, str, str], "ZarrStore"] = {}
_CACHE_MAX = 96


def _cache_put(store: OrderedDict, key: tuple, value: np.ndarray) -> np.ndarray:
    store[key] = value
    store.move_to_end(key)
    while len(store) > _CACHE_MAX:
        store.popitem(last=False)
    return value


class ZarrStore:
    """One public Zarr root (endpoint + bucket + prefix)."""

    def __init__(self, prefix: str, endpoint: str | None = None, bucket: str | None = None):
        self.prefix = str(prefix or "").strip("/")
        self.endpoint = str(endpoint or settings.s3_endpoint).rstrip("/")
        self.bucket = str(bucket or settings.s3_bucket).strip("/")
        self._lock = threading.RLock()
        self._root = None
        self._inventory: dict[str, tuple[str, ...]] | None = None
        self._TIME_NODE: OrderedDict[tuple[str, int], np.ndarray] = OrderedDict()
        self._LAYER_NODE: OrderedDict[tuple[str, int, int], np.ndarray] = OrderedDict()

    def zarr_url(self) -> str:
        return f"{self.endpoint}/{self.bucket}/{self.prefix}"

    def reset(self) -> None:
        with self._lock:
            self._root = None
            self._inventory = None
            self._TIME_NODE.clear()
            self._LAYER_NODE.clear()

    def open_root(self):
        with self._lock:
            if self._root is None:
                url = self.zarr_url()
                print(f"Opening Zarr {url}", flush=True)
                store = zarr.storage.FsspecStore.from_url(url, read_only=True)
                self._root = zarr.open_group(store, mode="r")
            return self._root

    def has(self, name: str) -> bool:
        try:
            return name in self.open_root()
        except Exception:
            return False

    def _arr(self, name: str):
        cur = self.open_root()
        for part in str(name).split("/"):
            if part:
                cur = cur[part]
        return cur

    def n_times(self) -> int:
        return int(self._arr("time").shape[0]) if self.has("time") else int(self._arr("elevation").shape[0])

    def time_seconds(self) -> np.ndarray:
        with self._lock:
            if self.has("time"):
                return np.asarray(self._arr("time")[:], dtype=np.float64)
            n = self.n_times()
            return np.arange(1, n + 1, dtype=np.float64) * 3600.0

    def array_shape(self, name: str) -> tuple[int, ...]:
        return tuple(int(x) for x in self._arr(name).shape)

    def node_count(self) -> int:
        for probe in ("elevation", "depth"):
            if not self.has(probe):
                continue
            try:
                return int(self.array_shape(probe)[-1])
            except Exception:
                continue
        return 0

    def inventory(self) -> dict[str, tuple[str, ...]]:
        with self._lock:
            if self._inventory is not None:
                return dict(self._inventory)
            root = self.open_root()
            out: dict[str, tuple[str, ...]] = {}

            def add(path: str, item) -> None:
                ndim = getattr(item, "ndim", None)
                if ndim is None:
                    names_fn = getattr(item, "keys", None)
                    if callable(names_fn):
                        for child in list(names_fn()):
                            try:
                                add(f"{path}/{child}" if path else str(child), item[child])
                            except Exception:
                                continue
                    return
                try:
                    out[path] = _dim_names_of(item, path)
                except Exception:
                    return

            add("", root)
            out.pop("", None)
            self._inventory = out
            return dict(out)

    def clamp_time(self, time_index: int) -> int:
        n = self.n_times()
        return max(0, min(n - 1, int(time_index)))

    def read_time_node(self, name: str, time_index: int) -> np.ndarray:
        t = self.clamp_time(time_index)
        key = (name, t)
        with self._lock:
            cached = self._TIME_NODE.get(key)
            if cached is not None:
                return cached
            arr = self._arr(name)
            if arr.ndim == 1:
                data = np.asarray(arr[:], dtype=np.float32)
                return _cache_put(self._TIME_NODE, key, data)
            if arr.ndim != 2:
                raise KeyError(f"{name} is not a (time, node) array")
            t_chunk = _time_chunk(arr)
            t0 = (t // t_chunk) * t_chunk
            t1 = min(int(arr.shape[0]), t0 + t_chunk)
            block = np.asarray(arr[t0:t1, :], dtype=np.float32)
            for i in range(block.shape[0]):
                _cache_put(self._TIME_NODE, (name, t0 + i), np.ascontiguousarray(block[i]))
            return self._TIME_NODE[key]

    def read_layered_node(self, name: str, time_index: int, layer: int) -> np.ndarray:
        t = self.clamp_time(time_index)
        with self._lock:
            arr = self._arr(name)
            k = max(0, min(int(arr.shape[-1]) - 1, int(layer)))
            key = (name, t, k)
            cached = self._LAYER_NODE.get(key)
            if cached is not None:
                return cached
            data = np.asarray(arr[t, :, k], dtype=np.float32)
            return _cache_put(self._LAYER_NODE, key, data)

    def read_time_face(self, name: str, time_index: int) -> np.ndarray:
        t = self.clamp_time(time_index)
        with self._lock:
            return np.asarray(self._arr(name)[t, :], dtype=np.float32)

    def read_layered_cube(self, name: str, time_index: int) -> np.ndarray:
        t = self.clamp_time(time_index)
        with self._lock:
            return np.asarray(self._arr(name)[t, :, :], dtype=np.float32)

    def n_layers(self, name: str) -> int:
        with self._lock:
            arr = self._arr(name)
            return int(arr.shape[-1]) if arr.ndim >= 3 else 1

    def read_column(self, name: str, time_index: int, gnode: int) -> np.ndarray:
        t = self.clamp_time(time_index)
        with self._lock:
            arr = self._arr(name)
            if arr.ndim == 3:
                return np.asarray(arr[t, int(gnode), :], dtype=np.float64)
            return np.asarray(arr[t, int(gnode)], dtype=np.float64).reshape(1)

    def read_series_node(self, name: str, gnode: int) -> np.ndarray:
        n = self.n_times()
        g = int(gnode)
        out = np.empty(n, dtype=np.float32)
        for t in range(n):
            field = self.read_time_node(name, t)
            out[t] = float(field[g])
        return out

    def read_series_layered(self, name: str, gnode: int, layer: int) -> np.ndarray:
        n = self.n_times()
        g = int(gnode)
        out = np.empty(n, dtype=np.float32)
        for t in range(n):
            field = self.read_layered_node(name, t, layer)
            out[t] = float(field[g])
        return out

    def sample_time_node(self, name: str, gnodes: np.ndarray, time_index: int = 0) -> np.ndarray:
        field = self.read_time_node(name, time_index)
        return np.asarray(field)[np.asarray(gnodes, dtype=np.int64)]

    def sample_layered(self, name: str, gnodes: np.ndarray, layer: int, time_index: int = 0) -> np.ndarray:
        field = self.read_layered_node(name, time_index, layer)
        return np.asarray(field)[np.asarray(gnodes, dtype=np.int64)]

    def status(self) -> dict:
        ok = False
        n = None
        names: list[str] = []
        err = None
        try:
            names = sorted(self.inventory())
            n = self.n_times()
            ok = True
        except Exception as exc:
            err = str(exc)
        return {
            "zarrUrl": self.zarr_url(),
            "zarrOk": ok,
            "zarrNTimes": n,
            "zarrVariables": names,
            "zarrError": err,
            "hasTemperature": "temperature" in names,
            "hasZCoordinates": "zCoordinates" in names,
        }


def _dim_names_of(arr, name: str) -> tuple[str, ...]:
    meta = getattr(arr, "metadata", None)
    names = getattr(meta, "dimension_names", None) if meta is not None else None
    if names:
        return tuple(str(x) for x in names)
    if arr.ndim == 3:
        return ("time", "nSCHISM_hgrid_node", "nSCHISM_vgrid_layers")
    if arr.ndim == 2:
        if "face" in name.lower() or name.startswith("dryFlagElement"):
            return ("time", "nSCHISM_hgrid_face")
        return ("time", "nSCHISM_hgrid_node")
    if arr.ndim == 1:
        if name == "time" or name.endswith("/time"):
            return ("time",)
        return ("nSCHISM_hgrid_node",)
    return tuple(f"d{i}" for i in range(arr.ndim))


def _time_chunk(arr) -> int:
    chunks = getattr(arr, "chunks", None)
    if not chunks:
        return 1
    return max(1, int(chunks[0]))


def store_for(prefix: str | None = None, endpoint: str | None = None, bucket: str | None = None) -> ZarrStore:
    p = str(prefix if prefix is not None else settings.s3_zarr_prefix).strip("/")
    e = str(endpoint if endpoint is not None else settings.s3_endpoint).rstrip("/")
    b = str(bucket if bucket is not None else settings.s3_bucket).strip("/")
    key = (e, b, p)
    with _POOL_LOCK:
        found = _STORES.get(key)
        if found is None:
            found = ZarrStore(p, e, b)
            _STORES[key] = found
        return found


def _default() -> ZarrStore:
    return store_for()


def reset() -> None:
    _default().reset()


def reset_all() -> None:
    with _POOL_LOCK:
        for item in _STORES.values():
            item.reset()


def zarr_url() -> str:
    return _default().zarr_url()


def enabled() -> bool:
    return settings.data_source in {"s3", "zarr"}


def open_root():
    return _default().open_root()


def has(name: str) -> bool:
    return _default().has(name)


def _arr(name: str):
    return _default()._arr(name)


def n_times() -> int:
    return _default().n_times()


def time_seconds() -> np.ndarray:
    return _default().time_seconds()


def array_shape(name: str) -> tuple[int, ...]:
    return _default().array_shape(name)


def inventory() -> dict[str, tuple[str, ...]]:
    return _default().inventory()


def clamp_time(time_index: int) -> int:
    return _default().clamp_time(time_index)


def read_time_node(name: str, time_index: int) -> np.ndarray:
    return _default().read_time_node(name, time_index)


def read_layered_node(name: str, time_index: int, layer: int) -> np.ndarray:
    return _default().read_layered_node(name, time_index, layer)


def read_time_face(name: str, time_index: int) -> np.ndarray:
    return _default().read_time_face(name, time_index)


def read_layered_cube(name: str, time_index: int) -> np.ndarray:
    return _default().read_layered_cube(name, time_index)


def n_layers(name: str) -> int:
    return _default().n_layers(name)


def read_column(name: str, time_index: int, gnode: int) -> np.ndarray:
    return _default().read_column(name, time_index, gnode)


def read_series_node(name: str, gnode: int) -> np.ndarray:
    return _default().read_series_node(name, gnode)


def read_series_layered(name: str, gnode: int, layer: int) -> np.ndarray:
    return _default().read_series_layered(name, gnode, layer)


def sample_time_node(name: str, gnodes: np.ndarray, time_index: int = 0) -> np.ndarray:
    return _default().sample_time_node(name, gnodes, time_index)


def sample_layered(name: str, gnodes: np.ndarray, layer: int, time_index: int = 0) -> np.ndarray:
    return _default().sample_layered(name, gnodes, layer, time_index)


def status() -> dict:
    return _default().status()
