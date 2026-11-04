import { useEffect, useState } from "react";

import { fetchColormaps, type ColormapMeta } from "@/api/client";
import { subscribeStorage } from "@/api/storage";
import { formatHydroTime, waterSurface } from "@/layers/scientific/waterSurface";
import { animationExport } from "@/layers/scientific/animationExport";
import { seriesStore } from "@/layers/scientific/seriesPick";
import { polygonStore } from "@/layers/scientific/polygonTool";
import { CameraControls } from "./CameraControls";
import { ColorRangeSlider } from "./ColorRangeSlider";
import { HubScenarios } from "./HubScenarios";
import { LayerToggles } from "./LayerToggles";
import { useAppMode } from "@/config/appMode";

const KIND_LABEL: Record<string, string> = {
  sequential: "Sequential",
  diverging: "Diverging",
  cyclic: "Cyclic",
};

export function ControlPanel() {
  const appMode = useAppMode();
  const [colormaps, setColormaps] = useState<ColormapMeta[]>([]);
  const [, setTick] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [analyseOpen, setAnalyseOpen] = useState(false);

  useEffect(() => {
    void fetchColormaps()
      .then((list) => {
        setColormaps(list);
        waterSurface.registerColormaps(list);
        const current = list.find((item) => item.id === waterSurface.colormap) ?? list[0];
        if (current) {
          waterSurface.setColormap(current.id, current.css);
        }
      })
      .catch(() => setColormaps([]));
    const unsubWater = waterSurface.subscribe(() => setTick((n) => n + 1));
    const unsubPoly = polygonStore.subscribe(() => setTick((n) => n + 1));
    const unsubExport = animationExport.subscribe(() => setTick((n) => n + 1));
    const unsubStorage = subscribeStorage(() => {
      setPlaying(false);
    });
    setTick((n) => n + 1);
    return () => {
      unsubWater();
      unsubPoly();
      unsubExport();
      unsubStorage();
    };
  }, []);

  const nTimes = waterSurface.nTimes;
  const timeIndex = Math.min(waterSurface.timeIndex, Math.max(0, nTimes - 1));
  const seconds = waterSurface.timeSeconds[timeIndex] ?? 0;
  const ready = nTimes > 0 && (waterSurface.ready || waterSurface.nTimes > 0);
  const scaleMin = waterSurface.colorScaleMin;
  const scaleMax = waterSurface.colorScaleMax;
  const rangeLo = waterSurface.colorMin ?? scaleMin;
  const rangeHi = waterSurface.colorMax ?? scaleMax;
  const colormapGroups = ["sequential", "diverging", "cyclic"].map((kind) => ({
    kind,
    label: KIND_LABEL[kind] ?? kind,
    items: colormaps.filter((item) => item.kind === kind),
  }));

  useEffect(() => {
    if (playing && !waterSurface.buffering && !waterSurface.playbackBuffered) {
      setPlaying(false);
    }
  }, [playing, waterSurface.buffering, waterSurface.playbackBuffered]);

  useEffect(() => {
    if (!playing || !ready || nTimes < 2 || waterSurface.buffering || animationExport.active) {
      return;
    }
    let cancelled = false;
    const run = async () => {
      while (!cancelled) {
        const started = performance.now();
        await waterSurface.advancePlayback();
        if (cancelled) {
          return;
        }
        const hold = waterSurface.playHoldMs - (performance.now() - started);
        if (hold > 0) {
          await new Promise((resolve) => window.setTimeout(resolve, hold));
        }
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [playing, ready, nTimes, waterSurface.buffering, animationExport.active]);

  return (
    <aside className="control-panel">
      <header className="panel-brand" tabIndex={0}>
        <p className="eyebrow">{appMode === "hub" ? "Scenario hub" : "Digital twin"}</p>
        <h1>{appMode === "hub" ? "Compare SCHISM runs" : "Hamburg hydrodynamics"}</h1>
        <p className="panel-brand-tip" role="tooltip">
          {appMode === "hub"
            ? "Pick two named MinIO scenarios, then view A, B, or live B minus A."
            : "Pick a variable and colormap, then click the water for a time series."}
        </p>
      </header>

      {appMode === "hub" ? <HubScenarios /> : null}

      <section>
        <div className="section-heading-row">
          <h2>Variable</h2>
          {waterSurface.buffering ? (
            <span className="fetch-data" aria-live="polite">
              buffering
            </span>
          ) : waterSurface.fetching || !waterSurface.ready ? (
            <span className="fetch-data" aria-live="polite">
              fetch data
            </span>
          ) : null}
        </div>
        <select
          disabled={nTimes < 1}
          value={waterSurface.variable}
          onChange={(event) => {
            waterSurface.setVariable(event.target.value);
            void seriesStore.refresh();
            void polygonStore.refresh();
          }}
        >
          {(waterSurface.variables.length
            ? waterSurface.variables
            : [{ id: "elevation", label: "Water level", unit: "m" }]
          ).map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
              {item.unit ? ` (${item.unit})` : ""}
            </option>
          ))}
        </select>
      </section>

      {waterSurface.isVertical ? (
        <section>
          <h2>Vertical</h2>
          <p className="muted">
            {waterSurface.zInterp
              ? `Interpolated to z = ${waterSurface.zMeters} m`
              : `k = ${waterSurface.overlayLayerIndex} of 0…${waterSurface.nLayers - 1} (${
                  waterSurface.overlayLayerIndex === 0
                    ? "bottom"
                    : waterSurface.overlayLayerIndex === waterSurface.nLayers - 1
                      ? "surface"
                      : "layer"
                })`}
          </p>
          <div className="vert-row">
            <span className="muted">bottom</span>
            <input
              type="range"
              min={0}
              max={Math.max(0, waterSurface.nLayers - 1)}
              step={1}
              value={waterSurface.overlayLayerIndex ?? waterSurface.nLayers - 1}
              disabled={waterSurface.zInterp}
              aria-label="Vertical layer"
              onChange={(event) => waterSurface.setLayer(Number(event.target.value))}
            />
            <span className="muted">surface</span>
          </div>
          <label className="z-interp-row">
            <input
              type="checkbox"
              checked={waterSurface.zInterp}
              onChange={(event) => waterSurface.setZInterp(event.target.checked)}
            />
            Interp to z (m)
            <input
              type="number"
              step={0.5}
              value={waterSurface.zMeters}
              disabled={!waterSurface.zInterp}
              aria-label="z elevation metres"
              onChange={(event) => waterSurface.setZMeters(Number(event.target.value))}
            />
          </label>
        </section>
      ) : null}

      <section>
        <h2>Time</h2>
        {nTimes > 0 ? (
          <p className="muted">{formatHydroTime(seconds, timeIndex, nTimes)}</p>
        ) : (
          <p className="muted">Loading hydro times…</p>
        )}
        <div className="time-row">
          <button
            type="button"
            disabled={nTimes < 2 || animationExport.active}
            onClick={() => {
              if (playing) {
                setPlaying(false);
                return;
              }
              if (waterSurface.buffering) {
                waterSurface.cancelPlaybackBuffer();
                return;
              }
              void (async () => {
                const ok = await waterSurface.prefetchPlayback();
                if (ok) {
                  setPlaying(true);
                }
              })();
            }}
          >
            {playing ? "Pause" : waterSurface.buffering ? "Buffering…" : "Play"}
          </button>
          <input
            type="range"
            min={0}
            max={Math.max(0, nTimes - 1)}
            step={1}
            value={timeIndex}
            disabled={nTimes < 2 || animationExport.active}
            onChange={(event) => {
              setPlaying(false);
              if (waterSurface.buffering) {
                waterSurface.cancelPlaybackBuffer();
              }
              waterSurface.setTime(Number(event.target.value));
            }}
          />
        </div>
        <div className="speed-row">
          <span className="muted">slow</span>
          <input
            type="range"
            min={1}
            max={10}
            step={1}
            value={waterSurface.playSpeed}
            disabled={nTimes < 2}
            aria-label="Animation speed"
            onChange={(event) => waterSurface.setPlaySpeed(Number(event.target.value))}
          />
          <span className="muted">fast</span>
        </div>
        <p className="muted">
          {(waterSurface.playHoldMs / 1000).toFixed(1)} s per model hour
        </p>
        <button
          type="button"
          className="camera-reset"
          disabled={
            nTimes < 2 ||
            (!animationExport.pendingBlob && (waterSurface.buffering || !animationExport.supported))
          }
          onClick={() => {
            if (animationExport.pendingBlob) {
              animationExport.savePending();
              return;
            }
            if (animationExport.active) {
              animationExport.cancel();
              return;
            }
            setPlaying(false);
            void (async () => {
              const buffered =
                waterSurface.playbackBuffered || (await waterSurface.prefetchPlayback());
              if (!buffered) {
                return;
              }
              await animationExport.exportVideo();
            })();
          }}
        >
          {animationExport.active
            ? `Exporting ${animationExport.index + 1}/${animationExport.total}…`
            : animationExport.pendingBlob
              ? "Save video"
              : "Export video"}
        </button>
        {animationExport.pendingBlob ? (
          <p className="muted">Recording ready. Click Save video if the file did not download.</p>
        ) : null}
        {animationExport.error ? <p className="muted">{animationExport.error}</p> : null}
        {ready && scaleMin !== null && scaleMax !== null && rangeLo !== null && rangeHi !== null ? (
          <>
            <div className="color-range-heading-row">
              <h2 className="color-range-heading">Color range</h2>
              <select
                className="colormap-select"
                disabled={!colormaps.length}
                value={waterSurface.colormap}
                aria-label="Colormap"
                onChange={(event) => {
                  const next = colormaps.find((item) => item.id === event.target.value);
                  waterSurface.setColormap(event.target.value, next?.css);
                }}
              >
                {colormapGroups.map((group) =>
                  group.items.length ? (
                    <optgroup key={group.kind} label={group.label}>
                      {group.items.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label}
                        </option>
                      ))}
                    </optgroup>
                  ) : null,
                )}
              </select>
            </div>
            <ColorRangeSlider
              key={`${waterSurface.variable}:${waterSurface.colormap}:${waterSurface.hubView}`}
              dataMin={scaleMin}
              dataMax={scaleMax}
              vmin={rangeLo}
              vmax={rangeHi}
              unit={waterSurface.variableUnit}
              label={waterSurface.variableLabel}
              gradient={waterSurface.colormapCss}
              onChange={(lo, hi) => waterSurface.setColorRange(lo, hi)}
              onReset={() => waterSurface.resetColorRange()}
            />
            {waterSurface.activeVariable?.vector ? (
              <p className="muted">Arrows: 50×50 nearest nodes in a square of the current view.</p>
            ) : null}
          </>
        ) : null}
      </section>

      <section>
        <h2>Layers</h2>
        <LayerToggles />
      </section>

      <section>
        <h2>Analyse</h2>
        <button
          type="button"
          className="camera-reset"
          onClick={() => setAnalyseOpen((open) => !open)}
        >
          {analyseOpen ? "· Close submenu" : "Analyse"}
        </button>
        {analyseOpen ? (
          <>
            <p className="muted">
              Draw a target area, set the exceedance threshold, then run Analyse.
            </p>
            <div className="camera-row">
              <button
                type="button"
                className="camera-reset"
                disabled={!ready}
                onClick={() => {
                  seriesStore.clear();
                  polygonStore.start();
                }}
              >
                {polygonStore.drawing ? "Drawing…" : "Draw polygon"}
              </button>
              <button
                type="button"
                className="camera-reset"
                disabled={!polygonStore.drawing || polygonStore.vertices.length < 3}
                onClick={() => void polygonStore.finish()}
              >
                Finish
              </button>
              <button
                type="button"
                className="camera-reset"
                disabled={!polygonStore.drawing && !polygonStore.closed}
                onClick={() => polygonStore.clear()}
              >
                Clear
              </button>
            </div>
            <label className="hub-label">
              Threshold
              <input
                type="number"
                step={0.05}
                value={polygonStore.threshold}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (Number.isFinite(value)) {
                    polygonStore.setThreshold(value);
                  }
                }}
              />
            </label>
            <button
              type="button"
              className="camera-reset"
              disabled={!ready || polygonStore.vertices.length < 3 || polygonStore.loading}
              onClick={() => void polygonStore.analyse()}
            >
              {polygonStore.loading ? "Analysing…" : "Analyse"}
            </button>
            <p className="muted">
              {polygonStore.drawing
                ? "Left-click vertices. Right-click undoes. Enter finishes, Esc cancels."
                : "Below threshold = light blue triangles, above = red. Charts open beside the map."}
            </p>
          </>
        ) : null}
      </section>

      <section>
        <h2>Camera</h2>
        <CameraControls />
      </section>
    </aside>
  );
}
