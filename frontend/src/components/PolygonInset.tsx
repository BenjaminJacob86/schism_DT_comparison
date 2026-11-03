import { useEffect, useState } from "react";

import { formatHydroTime, waterSurface } from "@/layers/scientific/waterSurface";
import { polygonStore } from "@/layers/scientific/polygonTool";

const DONUT = 168;
const HIST_W = 300;
const HIST_H = 118;
const PAD = { l: 36, r: 8, t: 8, b: 22 };
const BELOW = "#2b6cb0";
const ABOVE = "#e53e3e";

function polar(cx: number, cy: number, r: number, angle: number): { x: number; y: number } {
  return { x: cx + r * Math.sin(angle), y: cy - r * Math.cos(angle) };
}

function donutSlice(
  cx: number,
  cy: number,
  r0: number,
  r1: number,
  start: number,
  end: number,
): string {
  const span = end - start;
  if (span <= 1e-6) {
    return "";
  }
  const large = span > Math.PI ? 1 : 0;
  const a0 = polar(cx, cy, r1, start);
  const a1 = polar(cx, cy, r1, end);
  const b1 = polar(cx, cy, r0, end);
  const b0 = polar(cx, cy, r0, start);
  return [
    `M ${a0.x.toFixed(2)} ${a0.y.toFixed(2)}`,
    `A ${r1} ${r1} 0 ${large} 1 ${a1.x.toFixed(2)} ${a1.y.toFixed(2)}`,
    `L ${b1.x.toFixed(2)} ${b1.y.toFixed(2)}`,
    `A ${r0} ${r0} 0 ${large} 0 ${b0.x.toFixed(2)} ${b0.y.toFixed(2)}`,
    "Z",
  ].join(" ");
}

export function PolygonInset() {
  const [, setTick] = useState(0);

  useEffect(() => {
    const a = polygonStore.subscribe(() => setTick((n) => n + 1));
    const b = waterSurface.subscribe(() => setTick((n) => n + 1));
    return () => {
      a();
      b();
    };
  }, []);

  const stats = polygonStore.stats;
  if (
    !polygonStore.drawing &&
    !polygonStore.closed &&
    !polygonStore.loading &&
    !polygonStore.error
  ) {
    return null;
  }

  const unit = stats?.unit || waterSurface.variableUnit;
  const label = stats?.label || waterSurface.variableLabel;
  const hour = stats?.timeIndex ?? waterSurface.timeIndex;
  const nTimes = waterSurface.nTimes;
  const timeLabel = formatHydroTime(
    stats?.timeSeconds ?? waterSurface.timeSeconds[hour] ?? 0,
    hour,
    nTimes,
  );
  const analysed = polygonStore.analysed && stats != null;
  const area = stats?.areaKm2 ?? 0;
  const areaAbove = stats?.areaAboveKm2 ?? 0;
  const areaBelow = stats?.areaBelowKm2 ?? Math.max(0, area - areaAbove);
  const nAbove = stats?.nAbove ?? 0;
  const nBelow = stats?.nBelow ?? 0;
  const totalFaces = Math.max(1, nAbove + nBelow);
  const fracAbove = area > 0 ? areaAbove / area : nAbove / totalFaces;
  const fracBelow = 1 - fracAbove;
  const crit = stats?.critical ?? polygonStore.threshold;
  const histArea = stats?.histArea ?? [];
  const histEdges = stats?.histEdges ?? [];
  const maxBar = Math.max(0, ...histArea);
  const innerW = HIST_W - PAD.l - PAD.r;
  const innerH = HIST_H - PAD.t - PAD.b;
  const xMin = histEdges[0] ?? 0;
  const xMax = histEdges[histEdges.length - 1] ?? 1;
  const xAt = (v: number) => PAD.l + ((v - xMin) / (xMax - xMin || 1)) * innerW;

  return (
    <aside
      className={`series-inset polygon-inset${analysed ? " analysed" : ""}`}
      aria-label="Threshold exceedance analysis"
    >
      <header className="series-inset-head">
        <div>
          <p className="eyebrow">{analysed ? "Area statistics" : "Target area"}</p>
          <h2>{label}</h2>
          {polygonStore.drawing ? (
            <p className="muted">
              {polygonStore.vertices.length} vertices · click to add, right-click to undo,
              Finish when you have 3+
            </p>
          ) : polygonStore.loading ? (
            <p className="muted">Computing exceedance…</p>
          ) : polygonStore.error ? (
            <p className="muted">{polygonStore.error}</p>
          ) : analysed ? (
            <p className="muted">
              {timeLabel} · {(stats?.nFaces ?? 0).toLocaleString()} triangles
            </p>
          ) : (
            <p className="muted">Set a threshold and click Analyse in the submenu</p>
          )}
        </div>
        <button type="button" className="series-inset-close" onClick={() => polygonStore.clear()}>
          Close
        </button>
      </header>

      {analysed && stats ? (
        <>
          <div className="analyse-metrics">
            <p>
              <strong>{area.toFixed(2)}</strong> km²
            </p>
            {stats.mean !== null ? (
              <p>
                mean {stats.mean.toFixed(3)} {unit}
              </p>
            ) : null}
            {stats.min !== null && stats.max !== null ? (
              <p>
                {stats.min.toFixed(3)} … {stats.max.toFixed(3)} {unit}
              </p>
            ) : null}
          </div>
          <div className="analyse-donut-row">
            <svg className="analyse-donut" viewBox={`0 0 ${DONUT} ${DONUT}`} role="img">
              {fracBelow > 0.001 ? (
                <path
                  d={donutSlice(DONUT / 2, DONUT / 2, 38, 72, 0, fracBelow * Math.PI * 2)}
                  fill={BELOW}
                />
              ) : null}
              {fracAbove > 0.001 ? (
                <path
                  d={donutSlice(
                    DONUT / 2,
                    DONUT / 2,
                    38,
                    72,
                    fracBelow * Math.PI * 2,
                    Math.PI * 2,
                  )}
                  fill={ABOVE}
                />
              ) : null}
              <text x={DONUT / 2} y={DONUT / 2 - 4} className="analyse-donut-pct" textAnchor="middle">
                {(fracAbove * 100).toFixed(0)}%
              </text>
              <text x={DONUT / 2} y={DONUT / 2 + 14} className="analyse-donut-sub" textAnchor="middle">
                above
              </text>
            </svg>
            <ul className="analyse-legend">
              <li>
                <span className="swatch below" />
                ≤ {crit} · {areaBelow.toFixed(2)} km² · {nBelow.toLocaleString()} faces
              </li>
              <li>
                <span className="swatch above" />
                &gt; {crit} · {areaAbove.toFixed(2)} km² · {nAbove.toLocaleString()} faces
              </li>
            </ul>
          </div>
          {histArea.length > 1 && maxBar > 0 ? (
            <>
              <p className="muted">Value distribution — area (km²)</p>
              <svg className="series-chart" viewBox={`0 0 ${HIST_W} ${HIST_H}`} role="img">
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
                {histArea.map((value, i) => {
                  const left = histEdges[i] ?? xMin;
                  const right = histEdges[i + 1] ?? left;
                  const x = xAt(left);
                  const w = Math.max(1, xAt(right) - x - 1);
                  const h = (value / maxBar) * innerH;
                  const mid = (left + right) / 2;
                  return (
                    <rect
                      key={i}
                      x={x}
                      y={PAD.t + innerH - h}
                      width={w}
                      height={h}
                      fill={mid > crit ? ABOVE : BELOW}
                      opacity={0.88}
                    />
                  );
                })}
                <line
                  x1={xAt(crit)}
                  x2={xAt(crit)}
                  y1={PAD.t}
                  y2={PAD.t + innerH}
                  className="series-now"
                />
                <text x={4} y={PAD.t + 8} className="series-label">
                  {maxBar.toFixed(2)}
                </text>
                <text x={PAD.l} y={HIST_H - 4} className="series-label">
                  {xMin.toFixed(2)}
                </text>
                <text x={PAD.l + innerW - 28} y={HIST_H - 4} className="series-label">
                  {xMax.toFixed(2)}
                </text>
              </svg>
            </>
          ) : null}
        </>
      ) : null}
    </aside>
  );
}
