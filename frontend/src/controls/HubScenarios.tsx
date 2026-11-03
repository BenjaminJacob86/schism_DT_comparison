import { useEffect, useState } from "react";

import { applyHubSelection, fetchHub, type HubPayload } from "@/api/hub";
import { layerRegistry } from "@/layers/LayerRegistry";
import { ScientificLayer } from "@/layers/scientific/ScientificLayer";
import { waterSurface } from "@/layers/scientific/waterSurface";
import { polygonStore } from "@/layers/scientific/polygonTool";
import { seriesStore } from "@/layers/scientific/seriesPick";
import { getViewer } from "@/cesium/viewerStore";

export function HubScenarios() {
  const [hub, setHub] = useState<HubPayload | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      for (let attempt = 0; attempt < 40 && !cancelled; attempt += 1) {
        try {
          const payload = await fetchHub();
          if (cancelled) {
            return;
          }
          setHub(payload);
          setError(payload.selection.compareError || "");
          polygonStore.setHubView(payload.selection.view);
          seriesStore.setHubView(payload.selection.view);
          waterSurface.hubView = payload.selection.view;
          return;
        } catch (err: unknown) {
          if (attempt === 0) {
            setError("Waiting for hub API…");
          } else {
            setError(err instanceof Error ? err.message : "Hub catalog failed");
          }
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const apply = async (next: { a: string; b: string; view: string; critical: number }) => {
    setBusy(true);
    setError("");
    try {
      const payload = await applyHubSelection(next);
      setHub(payload);
      setError(payload.selection.compareError || "");
      polygonStore.setHubView(next.view);
      seriesStore.setHubView(next.view);
      const hydro = layerRegistry.get("water-surface") as ScientificLayer | undefined;
      const viewer = getViewer();
      if (viewer && !viewer.isDestroyed()) {
        await hydro?.reload();
      }
      waterSurface.applyHubView(next.view);
      if (next.view === "diff") {
        polygonStore.setThreshold(0);
      }
      void seriesStore.refresh();
      void polygonStore.refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not apply scenarios");
    } finally {
      setBusy(false);
    }
  };

  if (!hub) {
    return (
      <section>
        <h2>Scenarios</h2>
        <p className="muted">{error || "Loading catalog…"}</p>
      </section>
    );
  }

  const sel = hub.selection;
  const items = hub.catalog.scenarios;
  const views = [
    { id: "a", label: sel.a },
    { id: "b", label: sel.b },
    { id: "diff", label: `${sel.b} − ${sel.a}` },
  ];

  return (
    <section>
      <h2>Scenarios</h2>
      <p className="muted">{hub.catalog.tagline}</p>
      <label className="hub-label">
        A
        <select
          disabled={busy}
          value={sel.a}
          onChange={(event) => void apply({ ...sel, a: event.target.value, critical: sel.critical })}
        >
          {items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <label className="hub-label">
        B
        <select
          disabled={busy}
          value={sel.b}
          onChange={(event) => void apply({ ...sel, b: event.target.value, critical: sel.critical })}
        >
          {items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <div className="camera-row">
        {views.map((item) => (
          <button
            key={item.id}
            type="button"
            className="camera-reset"
            disabled={busy}
            onClick={() => void apply({ ...sel, view: item.id, critical: item.id === "diff" ? 0 : sel.critical })}
          >
            {sel.view === item.id ? `· ${item.label}` : item.label}
          </button>
        ))}
      </div>
      {busy ? <p className="muted">Updating scenarios…</p> : null}
      {error ? <p className="muted">{error}</p> : null}
      {sel.nodesA ? (
        <p className="muted">{sel.nodesA.toLocaleString()} nodes (shared mesh)</p>
      ) : null}
    </section>
  );
}
