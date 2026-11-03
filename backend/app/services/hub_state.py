"""In-memory A/B compare selection for the scenario hub. Does not persist the viewer's gear JSON."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.hub_catalog import catalog


@dataclass
class HubSelection:
    a: str
    b: str
    view: str  # a | b | diff
    critical: float
    compare_ok: bool = True
    compare_error: str | None = None
    nodes_a: int = 0
    nodes_b: int = 0


_selection: HubSelection | None = None


def current() -> HubSelection | None:
    return _selection


def set_current(sel: HubSelection) -> HubSelection:
    global _selection
    _selection = sel
    return sel


def default_selection() -> HubSelection:
    cat = catalog()
    return HubSelection(
        a=cat.default_a,
        b=cat.default_b,
        view="a",
        critical=float(cat.critical_default),
        compare_ok=True,
    )
