"""Apply hub A/B selection. Both scenarios share one mesh; B is fields only."""

from __future__ import annotations

from pathlib import Path

from app.services import hydro, hub_state, remote
from app.services.hub_catalog import catalog
from app.services.hub_state import HubSelection
from app.services.hydro import DEFAULT_MODEL_ID
from app.services.mesh_prep import existing_mesh_path, pin_surface_mesh
from app.services.storage import apply_storage


def _status_without_rebuild() -> dict:
    status = remote.status()
    status["meshRebuilt"] = False
    return status


def apply_hub_selection(
    *,
    a: str,
    b: str,
    view: str,
    critical: float | None = None,
) -> dict:
    cat = catalog()
    scen_a = cat.by_id(a)
    scen_b = cat.by_id(b)
    view_key = str(view or "a").strip().lower()
    if view_key not in {"a", "b", "diff"}:
        raise ValueError("view must be a, b, or diff")
    prev = hub_state.current()
    crit = float(cat.critical_default if critical is None else critical)
    if view_key == "diff":
        crit = float(critical if critical is not None else 0.0)

    a_changed = prev is None or prev.a != scen_a.id
    view_changed = prev is None or prev.view != view_key or prev.b != scen_b.id
    have_mesh = existing_mesh_path(DEFAULT_MODEL_ID) is not None
    nodes = int(prev.nodes_a) if prev is not None and have_mesh else 0
    sel = HubSelection(
        a=scen_a.id,
        b=scen_b.id,
        view=view_key,
        critical=crit,
        compare_ok=True,
        compare_error=None,
        nodes_a=nodes,
        nodes_b=nodes,
    )
    hub_state.set_current(sel)
    if a_changed:
        status = apply_storage(
            scen_a.storage_payload(),
            persist=False,
            rebuild=False,
            mesh=not have_mesh,
        )
        path = status.get("meshPath")
        if path:
            pin_surface_mesh(Path(path))
    elif view_changed:
        hydro.reset_field_caches()
        status = _status_without_rebuild()
    else:
        status = _status_without_rebuild()
    status.update(selection_payload())
    return status


def selection_payload() -> dict:
    cat = catalog()
    sel = hub_state.current() or hub_state.default_selection()
    return {
        "mode": "hub",
        "catalog": cat.as_dict(),
        "selection": {
            "a": sel.a,
            "b": sel.b,
            "view": sel.view,
            "critical": sel.critical,
            "compareOk": True,
            "compareError": None,
            "nodesA": sel.nodes_a,
            "nodesB": sel.nodes_b,
            "sharedMesh": True,
        },
    }
