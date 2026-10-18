import { type RefObject, useEffect, useRef, useState } from 'react';

/** One series. `color` is a CSS color, always a token (var(--series-1)); it follows the entity, not its rank. */
export interface Series {
  id: string;
  label: string;
  color: string;
  values: (number | null)[];
}

export interface TipRow {
  color: string;
  label: string;
  value: string;
}

export interface TipState {
  x: number;
  y: number;
  title: string;
  rows: TipRow[];
}

/** Width of an element, kept up to date. `fallback` is used where nothing is measured (tests). */
export function useWidth(fallback = 640): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      const w = el.getBoundingClientRect().width;
      if (w > 0) setWidth(Math.round(w));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

export interface Scale {
  min: number;
  max: number;
  ticks: number[];
}

/** What the axis counts: plain numbers, whole numbers (counts), or minutes (ticks on natural time steps). */
export type AxisKind = 'number' | 'integer' | 'duration';

// Minutes: 15 min, 30 min, 1 h, 2 h, 3 h, 6 h, 12 h, 1 d, 2 d, 3 d, 1 week, 2 weeks, 30 days, 1 year.
const DURATION_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1440, 2880, 4320, 10080, 20160, 43200, 525600];

/** A scale that always includes zero, with round tick values (for `duration`, natural time steps). */
export function niceScale(low: number, high: number, count = 4, kind: AxisKind = 'number'): Scale {
  const lo = Math.min(0, low);
  let hi = Math.max(0, high);
  if (hi === lo) hi = lo + 1;
  const raw = (hi - lo) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  let step =
    kind === 'duration'
      ? (DURATION_STEPS.find((s) => s >= raw) ?? raw)
      : ([1, 2, 2.5, 5, 10].map((f) => f * magnitude).find((s) => s >= raw) ?? 10 * magnitude);
  if (kind === 'integer') step = Math.max(1, Math.ceil(step));
  const min = Math.floor(lo / step + 1e-9) * step;
  const max = Math.ceil(hi / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let t = min; t <= max + step / 1000; t += step) ticks.push(Math.round(t * 1e6) / 1e6);
  return { min, max, ticks };
}

/** A column or bar whose data end is rounded (r) and whose baseline end is square. `up` = grows upward. */
export function columnPath(x: number, base: number, tip: number, w: number, r: number): string {
  const h = Math.abs(base - tip);
  if (h < 0.5) return '';
  const rr = Math.min(r, h, w / 2);
  if (tip <= base) {
    return `M${x},${base}V${tip + rr}Q${x},${tip} ${x + rr},${tip}H${x + w - rr}Q${x + w},${tip} ${x + w},${tip + rr}V${base}Z`;
  }
  return `M${x},${base}V${tip - rr}Q${x},${tip} ${x + rr},${tip}H${x + w - rr}Q${x + w},${tip} ${x + w},${tip - rr}V${base}Z`;
}

/** Horizontal bar from `base` to `tip` along x; rounded at the tip only. `roundTip` false = square both ends. */
export function rowPath(base: number, tip: number, y: number, h: number, r: number, roundTip = true): string {
  const w = Math.abs(tip - base);
  if (w < 0.5) return '';
  const rr = roundTip ? Math.min(r, w, h / 2) : 0;
  if (rr === 0) return `M${base},${y}H${tip}V${y + h}H${base}Z`;
  if (tip >= base) {
    return `M${base},${y}H${tip - rr}Q${tip},${y} ${tip},${y + rr}V${y + h - rr}Q${tip},${y + h} ${tip - rr},${y + h}H${base}Z`;
  }
  return `M${base},${y}H${tip + rr}Q${tip},${y} ${tip},${y + rr}V${y + h - rr}Q${tip},${y + h} ${tip + rr},${y + h}H${base}Z`;
}

export function Legend({
  items,
  hidden,
  onToggle,
  kind = 'bar',
}: {
  items: { id: string; label: string; color: string }[];
  hidden: Set<string>;
  onToggle(id: string): void;
  kind?: 'bar' | 'line';
}) {
  if (items.length < 2) return null; // one series: the title already says what it is
  return (
    <ul className="legend" aria-label="Legend">
      {items.map((item) => (
        <li key={item.id}>
          <button type="button" aria-pressed={!hidden.has(item.id)} onClick={() => onToggle(item.id)}>
            <span className={`swatch${kind === 'line' ? ' line' : ''}`} style={{ background: item.color }} />
            {item.label}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Hides or shows series; at least one stays visible. */
export function useHidden(): [Set<string>, (id: string, all: string[]) => void] {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const toggle = (id: string, all: string[]) =>
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else if (all.filter((s) => !next.has(s)).length > 1) next.add(id);
      return next;
    });
  return [hidden, toggle];
}

/** The readout of every series at one position. Texts go in as text, never as HTML. */
export function Tooltip({ tip, width }: { tip: TipState | null; width: number }) {
  if (!tip) return null;
  const x = Math.min(Math.max(tip.x, 80), Math.max(80, width - 80));
  const below = tip.y < 70;
  return (
    <div className={`tooltip${below ? ' below' : ''}`} style={{ left: x, top: below ? tip.y + 16 : tip.y }} role="tooltip">
      <div className="tooltip-title">{tip.title}</div>
      {tip.rows.map((row) => (
        <div className="tooltip-row" key={row.label}>
          <span className="key" style={{ background: row.color }} />
          <span className="name">{row.label}</span>
          <span className="val">{row.value}</span>
        </div>
      ))}
    </div>
  );
}
