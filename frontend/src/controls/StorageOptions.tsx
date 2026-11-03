import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  applyStorage,
  fetchStorage,
  formFromStorage,
  previewObjectUrl,
  previewZarrUrl,
  type StorageForm,
} from "@/api/storage";
import { useCesiumApp } from "@/cesium/CesiumContext";
import { getViewer } from "@/cesium/viewerStore";
import { layerRegistry } from "@/layers/LayerRegistry";
import { BuildingTilesLayer } from "@/layers/buildings/BuildingTilesLayer";
import { ScientificLayer } from "@/layers/scientific/ScientificLayer";

const EMPTY_FORM: StorageForm = {
  endpoint: "",
  bucket: "",
  modelPrefix: "",
  zarrPrefix: "",
  buildingsPrefix: "",
};

function GearIcon() {
  return (
    <svg className="storage-gear-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M19.14 12.94c.04-.31.06-.63.06-.94s-.02-.63-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.61-.22l-2.39.96a7.03 7.03 0 0 0-1.63-.94l-.36-2.54A.5.5 0 0 0 13.89 2h-3.78a.5.5 0 0 0-.49.42l-.36 2.54c-.59.22-1.14.54-1.63.94l-2.39-.96a.5.5 0 0 0-.61.22L2.71 8.84a.5.5 0 0 0 .12.64l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94L2.83 14.52a.5.5 0 0 0-.12.64l1.92 3.32c.13.23.4.32.64.22l2.39-.96c.49.4 1.04.72 1.63.94l.36 2.54c.05.24.26.42.49.42h3.78c.23 0 .44-.18.49-.42l.36-2.54c.59-.22 1.14-.54 1.63-.94l2.39.96c.24.1.51 0 .64-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58zM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7z"
      />
    </svg>
  );
}

export function StorageOptions() {
  const { ready } = useCesiumApp();
  const [mount, setMount] = useState<HTMLElement | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<StorageForm>(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ready) {
      setMount(null);
      return;
    }
    const toolbar = document.querySelector(".cesium-viewer-toolbar");
    if (!(toolbar instanceof HTMLElement)) {
      return;
    }
    const host = document.createElement("span");
    host.className = "storage-options-host";
    toolbar.insertBefore(host, toolbar.firstChild);
    setMount(host);
    return () => {
      host.remove();
      setMount(null);
    };
  }, [ready]);

  useEffect(() => {
    if (!open) {
      return;
    }
    let cancelled = false;
    void fetchStorage()
      .then((config) => {
        if (!cancelled) {
          setForm(formFromStorage(config));
          setError(config.meshError || (config.zarrOk === false ? config.zarrError : "") || "");
          setNote("");
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load storage settings");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onPointer = (event: MouseEvent) => {
      const node = rootRef.current;
      if (node && event.target instanceof Node && !node.contains(event.target)) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const setField = useCallback(<K extends keyof StorageForm>(key: K, value: StorageForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setNote("");
  }, []);

  const onApply = useCallback(async () => {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const next = await applyStorage(form);
      setForm(formFromStorage(next));
      const hydro = layerRegistry.get("water-surface") as ScientificLayer | undefined;
      const buildings = layerRegistry.get("buildings") as BuildingTilesLayer | undefined;
      const viewer = getViewer();
      if (viewer && !viewer.isDestroyed()) {
        await buildings?.reload();
        await hydro?.reload();
      }
      if (next.meshError) {
        setError(next.meshError);
      } else if (next.zarrOk === false && next.zarrError) {
        setError(next.zarrError);
      } else {
        setNote("Loaded from the new S3 path.");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not apply S3 path");
    } finally {
      setBusy(false);
    }
  }, [form]);

  if (!mount) {
    return null;
  }

  const modelUrl = previewObjectUrl(form);
  const zarrUrl = previewZarrUrl(form);

  return createPortal(
    <div className="storage-options" ref={rootRef}>
      <button
        type="button"
        className="cesium-button cesium-toolbar-button storage-gear"
        aria-label="Storage options"
        title="Storage options"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <GearIcon />
      </button>
      {open ? (
        <form
          className="storage-panel"
          onSubmit={(event) => {
            event.preventDefault();
            void onApply();
          }}
        >
          <p className="eyebrow">Options</p>
          <h2>Object storage</h2>
          <p className="muted">
            Change the public MinIO endpoint and S3 paths, then apply. If the bucket has no
            surface_mesh.npz, the API rebuilds the mesh from hgrid.ll and Zarr.
          </p>
          <label>
            Endpoint URL
            <input
              type="url"
              autoComplete="off"
              spellCheck={false}
              value={form.endpoint}
              onChange={(event) => setField("endpoint", event.target.value)}
            />
          </label>
          <label>
            Bucket
            <input
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={form.bucket}
              onChange={(event) => setField("bucket", event.target.value)}
            />
          </label>
          <label>
            Model path
            <input
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={form.modelPrefix}
              onChange={(event) => setField("modelPrefix", event.target.value)}
            />
          </label>
          <label>
            Zarr path
            <input
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={form.zarrPrefix}
              onChange={(event) => setField("zarrPrefix", event.target.value)}
            />
          </label>
          <label>
            Buildings path
            <input
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={form.buildingsPrefix}
              onChange={(event) => setField("buildingsPrefix", event.target.value)}
            />
          </label>
          {modelUrl ? (
            <p className="storage-url" title={modelUrl}>
              {modelUrl}
            </p>
          ) : null}
          {zarrUrl ? (
            <p className="storage-url" title={zarrUrl}>
              {zarrUrl}
            </p>
          ) : null}
          {error ? <p className="storage-error">{error}</p> : null}
          {note ? <p className="storage-note">{note}</p> : null}
          <button type="submit" className="camera-reset" disabled={busy}>
            {busy ? "Rebuilding mesh…" : "Apply"}
          </button>
        </form>
      ) : null}
    </div>,
    mount,
  );
}
