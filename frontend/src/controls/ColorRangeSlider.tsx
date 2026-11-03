import { useEffect, useState } from "react";

type ColorRangeSliderProps = {
  dataMin: number;
  dataMax: number;
  vmin: number;
  vmax: number;
  unit?: string;
  label?: string;
  gradient?: string;
  disabled?: boolean;
  onChange: (vmin: number, vmax: number) => void;
  onReset: () => void;
};

const MIN_SPAN = 0.02;

function clampRange(lo: number, hi: number, floor: number, ceil: number): [number, number] {
  const low = Math.min(floor, ceil);
  const high = Math.max(floor, ceil);
  let a = Math.min(Math.max(lo, low), high);
  let b = Math.min(Math.max(hi, low), high);
  if (b - a < MIN_SPAN) {
    const mid = (a + b) / 2;
    a = Math.max(low, mid - MIN_SPAN / 2);
    b = Math.min(high, a + MIN_SPAN);
    a = Math.max(low, b - MIN_SPAN);
  }
  return [Math.round(a * 100) / 100, Math.round(b * 100) / 100];
}

function parseLimit(text: string): number | null {
  const value = Number(text.trim().replace(",", "."));
  return Number.isFinite(value) ? value : null;
}

export function ColorRangeSlider({
  dataMin,
  dataMax,
  vmin,
  vmax,
  unit = "m",
  label = "water level",
  gradient,
  disabled = false,
  onChange,
  onReset,
}: ColorRangeSliderProps) {
  const [limitsOpen, setLimitsOpen] = useState(false);
  const [trackMin, setTrackMin] = useState(dataMin);
  const [trackMax, setTrackMax] = useState(dataMax);
  const [draftLo, setDraftLo] = useState(String(vmin));
  const [draftHi, setDraftHi] = useState(String(vmax));

  useEffect(() => {
    setTrackMin(dataMin);
    setTrackMax(dataMax);
    setLimitsOpen(false);
  }, [dataMin, dataMax, label]);

  const floor = Math.min(trackMin, vmin);
  const ceil = Math.max(trackMax, vmax);
  const [lo, hi] = clampRange(vmin, vmax, floor, ceil);
  const span = Math.max(ceil - floor, MIN_SPAN);
  const reset = Math.abs(lo - dataMin) < 0.005 && Math.abs(hi - dataMax) < 0.005;
  const step = span > 20 ? 0.1 : 0.01;
  const digits = span > 20 ? 1 : 2;

  const applyTyped = () => {
    const a = parseLimit(draftLo);
    const b = parseLimit(draftHi);
    if (a === null || b === null) {
      return;
    }
    const nextLo = Math.min(a, b);
    const nextHi = Math.max(nextLo + MIN_SPAN, Math.max(a, b));
    setTrackMin(nextLo);
    setTrackMax(nextHi);
    onChange(nextLo, nextHi);
  };

  return (
    <div className="color-range">
      <div className="color-range-track">
        <div className="hydro-scale" style={gradient ? { background: gradient } : undefined} />
        <input
          type="range"
          className="color-range-thumb color-range-thumb-min"
          min={floor}
          max={ceil}
          step={step}
          value={lo}
          disabled={disabled}
          aria-label="Color minimum"
          onChange={(event) => {
            const next = Number(event.target.value);
            onChange(...clampRange(next, Math.max(next + MIN_SPAN, hi), floor, ceil));
          }}
        />
        <input
          type="range"
          className="color-range-thumb color-range-thumb-max"
          min={floor}
          max={ceil}
          step={step}
          value={hi}
          disabled={disabled}
          aria-label="Color maximum"
          onChange={(event) => {
            const next = Number(event.target.value);
            onChange(...clampRange(Math.min(lo, next - MIN_SPAN), next, floor, ceil));
          }}
        />
      </div>
      <div className="hydro-scale-labels">
        <span>
          {lo.toFixed(digits)} {unit}
        </span>
        <span>{label}</span>
        <span>
          {hi.toFixed(digits)} {unit}
        </span>
      </div>
      <button
        type="button"
        className="color-range-reset"
        disabled={disabled}
        aria-expanded={limitsOpen}
        onClick={() => {
          setDraftLo(lo.toFixed(digits));
          setDraftHi(hi.toFixed(digits));
          setLimitsOpen((open) => !open);
        }}
      >
        {limitsOpen ? "Hide typed limits" : "Type limits"}
      </button>
      {limitsOpen ? (
        <form
          className="color-range-limits"
          onSubmit={(event) => {
            event.preventDefault();
            applyTyped();
          }}
        >
          <label>
            Lower
            <input
              type="number"
              step="any"
              disabled={disabled}
              value={draftLo}
              aria-label="Color lower limit"
              onChange={(event) => setDraftLo(event.target.value)}
            />
          </label>
          <label>
            Upper
            <input
              type="number"
              step="any"
              disabled={disabled}
              value={draftHi}
              aria-label="Color upper limit"
              onChange={(event) => setDraftHi(event.target.value)}
            />
          </label>
          <button type="submit" className="color-range-reset" disabled={disabled}>
            Apply
          </button>
        </form>
      ) : null}
      <p className="muted">
        Scale {floor.toFixed(digits)} … {ceil.toFixed(digits)} {unit}
        {span > 0 ? ` · ${(((hi - lo) / span) * 100).toFixed(0)}% of bar` : ""}
      </p>
      <button
        type="button"
        className="color-range-reset"
        disabled={disabled || reset}
        onClick={() => {
          setTrackMin(dataMin);
          setTrackMax(dataMax);
          setLimitsOpen(false);
          onReset();
        }}
      >
        Reset range
      </button>
    </div>
  );
}
