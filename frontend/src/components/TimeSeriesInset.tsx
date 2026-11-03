import { useEffect, useState } from "react";

import { formatHydroTime, waterSurface } from "@/layers/scientific/waterSurface";
import { seriesStore } from "@/layers/scientific/seriesPick";

const W = 300;
const H = 132;
const PAD = { l: 36, r: 10, t: 12, b: 22 };
const COLOR_A = "#4eb3c2";
const COLOR_B = "#e67e22";

type Trace = {
  id: string;
  label: string;
  values: Array<number | null>;
  color: string;
};

function seriesExtent(values: Array<number | null>): { min: number; max: number } {
  const nums = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (!nums.length) {
    return { min: -1, max: 1 };
  }
  let min = Math.min(...nums);
  let max = Math.max(...nums);
  if (max - min < 0.05) {
    const mid = (min + max) / 2;
    min = mid - 0.05;
    max = mid + 0.05;
  }
  const pad = (max - min) * 0.12;
  return { min: min - pad, max: max + pad };
}

function polylinePoints(
  values: Array<number | null>,
  xAt: (i: number) => number,
  yAt: (v: number) => number,
): string {
  return values
    .map((v, i) => (v === null ? null : `${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`))
    .filter((p): p is string => p !== null)
    .join(" ");
}

export function TimeSeriesInset() {
  const [, setTick] = useState(0);

  useEffect(() => {
    const a = seriesStore.subscribe(() => setTick((n) => n + 1));
    const b = waterSurface.subscribe(() => setTick((n) => n + 1));
    return () => {
      a();
      b();
    };
  }, []);

  const series = seriesStore.current;
  const hour = waterSurface.timeIndex;
  if (!series && !seriesStore.loading && !seriesStore.error) {
    return null;
  }

  const compare = series?.compare;
  const view = series?.view ?? seriesStore.hubView;
  const traces: Trace[] =
    view === "diff" && series
      ? [
          {
            id: "diff",
            label: series.label || "Difference",
            values: series.values ?? series.elevation ?? [],
            color: COLOR_A,
          },
        ]
      : compare
        ? [
            { id: "a", label: compare.a.label, values: compare.a.values, color: COLOR_A },
            { id: "b", label: compare.b.label, values: compare.b.values, color: COLOR_B },
          ]
        : series
          ? [
              {
                id: series.variable,
                label: series.label || "Water level",
                values: series.values ?? series.elevation ?? [],
                color: COLOR_A,
              },
            ]
          : [];
  const values = traces[0]?.values ?? [];
  const n = Math.max(...traces.map((item) => item.values.length), values.length);
  const yRange = series
    ? seriesExtent(traces.flatMap((item) => item.values))
    : { min: 0, max: 1 };
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const xAt = (i: number) => PAD.l + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const yAt = (v: number) =>
    PAD.t + innerH - ((v - yRange.min) / (yRange.max - yRange.min || 1)) * innerH;

  const currentTime = series
    ? formatHydroTime(series.timeSeconds[hour] ?? 0, hour, n)
    : "";
  const unit = series?.unit || "m";
  const label = series?.label || "Water level";
  const profile = seriesStore.profile;
  const layerNote =
    series?.zMeters != null
      ? `z = ${series.zMeters} m`
      : series?.layer != null
        ? `k = ${series.layer}`
        : "";

  const pz = profile?.z ?? [];
  const pv = profile?.values ?? [];
  const pk = profile?.layers ?? [];
  const pPairs = pz
    .map((z, i) => {
      const v = pv[i];
      const k = pk[i];
      return z !== null && v !== null && Number.isFinite(z) && Number.isFinite(v)
        ? { z, v, k }
        : null;
    })
    .filter((p): p is { z: number; v: number; k: number } => p !== null);
  const pValRange = seriesExtent(pPairs.map((p) => p.v));
  const pZRange = seriesExtent(pPairs.map((p) => p.z));
  const pInnerW = W - PAD.l - PAD.r;
  const pInnerH = H - PAD.t - PAD.b;
  const pX = (v: number) =>
    PAD.l + ((v - pValRange.min) / (pValRange.max - pValRange.min || 1)) * pInnerW;
  const pY = (z: number) =>
    PAD.t + ((pZRange.max - z) / (pZRange.max - pZRange.min || 1)) * pInnerH;
  const pPoints = pPairs.map((p) => `${pX(p.v).toFixed(1)},${pY(p.z).toFixed(1)}`).join(" ");
  const activeLayer = waterSurface.overlayLayerIndex;
  const activePair =
    activeLayer != null
      ? (pPairs.find((p) => p.k === activeLayer) ?? pPairs[pPairs.length - 1])
      : pPairs[pPairs.length - 1];
  const hasCurrent = traces.some((item) => item.values[hour] != null);

  return (
    <aside className="series-inset" aria-label={`${label} time series`}>
      <header className="series-inset-head">
        <div>
          <p className="eyebrow">{label}</p>
          <h2>
            {series
              ? `${series.lat.toFixed(3)}°N ${series.lon.toFixed(3)}°E`
              : seriesStore.loading
                ? "fetch data"
                : "No water here"}
          </h2>
          {series ? (
            <p className="muted">
              Node {series.nodeIndex.toLocaleString()} · {series.distanceMeters.toFixed(0)} m from
              click
              {layerNote ? ` · ${layerNote}` : ""}
            </p>
          ) : seriesStore.error ? (
            <p className="muted">{seriesStore.error}</p>
          ) : (
            <p className="muted">Streaming hours from Zarr…</p>
          )}
        </div>
        <button type="button" className="series-inset-close" onClick={() => seriesStore.clear()}>
          Close
        </button>
      </header>
      {series && n > 1 ? (
        <svg className="series-chart" viewBox={`0 0 ${W} ${H}`} role="img">
          <line
            x1={PAD.l}
            x2={PAD.l}
            y1={PAD.t}
            y2={PAD.t + innerH}
            className="series-axis"
          />
          <line
            x1={PAD.l}
            x2={PAD.l + innerW}
            y1={PAD.t + innerH}
            y2={PAD.t + innerH}
            className="series-axis"
          />
          <text x={4} y={PAD.t + 8} className="series-label">
            {yRange.max.toFixed(2)}
          </text>
          <text x={4} y={PAD.t + innerH} className="series-label">
            {yRange.min.toFixed(2)}
          </text>
          <text x={PAD.l} y={H - 4} className="series-label">
            t1
          </text>
          <text x={PAD.l + innerW - 16} y={H - 4} className="series-label">
            t{n}
          </text>
          {hour >= 0 && hour < n ? (
            <line
              x1={xAt(hour)}
              x2={xAt(hour)}
              y1={PAD.t}
              y2={PAD.t + innerH}
              className="series-now"
            />
          ) : null}
          {traces.map((item) => (
            <polyline
              key={item.id}
              className="series-line"
              points={polylinePoints(item.values, xAt, yAt)}
              fill="none"
              style={{ stroke: item.color }}
            />
          ))}
          {traces.map((item) => {
            const value = item.values[hour];
            if (value == null) {
              return null;
            }
            return (
              <circle
                key={`${item.id}-dot`}
                cx={xAt(hour)}
                cy={yAt(value)}
                r={4}
                className="series-dot"
                style={{ stroke: item.color }}
              />
            );
          })}
        </svg>
      ) : null}
      {traces.length > 1 ? (
        <ul className="series-legend">
          {traces.map((item) => (
            <li key={item.id}>
              <span className="series-swatch" style={{ background: item.color }} />
              {item.label}
            </li>
          ))}
        </ul>
      ) : null}
      {series && hasCurrent ? (
        <div className="series-current">
          <p>{currentTime}</p>
          {traces.map((item) => {
            const value = item.values[hour];
            if (value == null) {
              return null;
            }
            return (
              <p key={item.id} style={{ color: item.color }}>
                {item.label}: {value.toFixed(3)} {unit}
              </p>
            );
          })}
        </div>
      ) : null}
      {profile && pPairs.length > 1 ? (
        <>
          <p className="muted" style={{ marginTop: 10 }}>
            Vertical profile · z up
          </p>
          <svg className="series-chart" viewBox={`0 0 ${W} ${H}`} role="img">
            <line
              x1={PAD.l}
              x2={PAD.l}
              y1={PAD.t}
              y2={PAD.t + pInnerH}
              className="series-axis"
            />
            <line
              x1={PAD.l}
              x2={PAD.l + pInnerW}
              y1={PAD.t + pInnerH}
              y2={PAD.t + pInnerH}
              className="series-axis"
            />
            <text x={4} y={PAD.t + 8} className="series-label">
              {pZRange.max.toFixed(1)}
            </text>
            <text x={4} y={PAD.t + pInnerH} className="series-label">
              {pZRange.min.toFixed(1)}
            </text>
            <text x={PAD.l} y={H - 4} className="series-label">
              {pValRange.min.toFixed(2)}
            </text>
            <text x={PAD.l + pInnerW - 28} y={H - 4} className="series-label">
              {pValRange.max.toFixed(2)}
            </text>
            <polyline className="series-line" points={pPoints} fill="none" />
            {activePair ? (
              <circle cx={pX(activePair.v)} cy={pY(activePair.z)} r={4} className="series-dot" />
            ) : null}
          </svg>
        </>
      ) : null}
    </aside>
  );
}
