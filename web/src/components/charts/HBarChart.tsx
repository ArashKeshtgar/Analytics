import { useState } from 'react';
import { compact } from '../../lib/format';
import { Legend, niceScale, rowPath, type Series, Tooltip, type TipState, useHidden, useWidth } from './common';

interface Props {
  categories: string[];
  series: Series[];
  /** Grouped: one bar per series in each row. Stacked: the series add up to a total. */
  mode: 'grouped' | 'stacked';
  format(value: number): string;
  ariaLabel: string;
}

const MARGIN = { top: 4, right: 76, bottom: 26 };
const GAP = 2;

const truncate = (text: string, max: number): string => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

/** Horizontal bars: <= 20px thick, rounded at the tip, a 2px surface gap between neighbours. */
export function HBarChart({ categories, series, mode, format, ariaLabel }: Props) {
  const [ref, width] = useWidth();
  const [hidden, toggle] = useHidden();
  const [tip, setTip] = useState<TipState | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const all = series.map((s) => s.id);
  const shown = series.filter((s) => !hidden.has(s.id));

  const left = Math.min(168, Math.max(64, Math.max(0, ...categories.map((c) => Math.min(c.length, 24))) * 7 + 12));
  const barH = mode === 'stacked' ? 20 : shown.length > 1 ? 14 : 20;
  const rowH = mode === 'stacked' ? 36 : shown.length * barH + GAP * Math.max(0, shown.length - 1) + 16;
  const height = MARGIN.top + categories.length * rowH + MARGIN.bottom;

  const rowValues = (i: number): number[] => shown.map((s) => s.values[i] ?? 0);
  const totals = categories.map((_, i) => rowValues(i).reduce((a, b) => a + b, 0));
  const highs = mode === 'stacked' ? totals : categories.flatMap((_, i) => rowValues(i));
  const scale = niceScale(Math.min(0, ...(mode === 'stacked' ? [0] : highs)), Math.max(0, ...highs));
  const plotW = Math.max(40, width - left - MARGIN.right);
  const x = (v: number) => left + (plotW * (v - scale.min)) / (scale.max - scale.min);

  function show(i: number) {
    const rows = shown.map((s) => ({
      color: s.color,
      label: s.label,
      value: s.values[i] == null ? '–' : format(s.values[i] as number),
    }));
    if (mode === 'stacked') rows.push({ color: 'var(--axis)', label: 'Total', value: format(totals[i] ?? 0) });
    setActive(i);
    setTip({
      x: x(Math.max(0, mode === 'stacked' ? (totals[i] ?? 0) : Math.max(0, ...rowValues(i)))) ,
      y: MARGIN.top + rowH * i - 4,
      title: categories[i] ?? '',
      rows,
    });
  }
  function hide() {
    setActive(null);
    setTip(null);
  }

  return (
    <div>
      <Legend items={series} hidden={hidden} onToggle={(id) => toggle(id, all)} />
      <div className={`chart${active != null ? ' has-hover' : ''}`} ref={ref}>
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
          {scale.ticks.map((t) => (
            <g key={t}>
              <line className="grid-line" x1={x(t)} x2={x(t)} y1={MARGIN.top} y2={height - MARGIN.bottom} />
              <text className="axis-text" x={x(t)} y={height - 8} textAnchor="middle">
                {compact(t)}
              </text>
            </g>
          ))}
          <line className="axis-line" x1={x(0)} x2={x(0)} y1={MARGIN.top} y2={height - MARGIN.bottom} />
          {categories.map((c, i) => {
            const rowTop = MARGIN.top + rowH * i;
            const mid = rowTop + rowH / 2;
            let cursor = 0;
            return (
              <g key={c}>
                <text className="value-text" x={left - 10} y={mid} textAnchor="end" dominantBaseline="middle">
                  <title>{c}</title>
                  {truncate(c, 24)}
                </text>
                {shown.map((s, k) => {
                  const v = s.values[i];
                  if (v == null) return null;
                  const cls = `mark${active === i ? ' on' : ''}`;
                  if (mode === 'stacked') {
                    if (v <= 0) return null;
                    const start = cursor;
                    cursor += v;
                    const last = k === shown.length - 1 || shown.slice(k + 1).every((n) => (n.values[i] ?? 0) <= 0);
                    const from = x(start) + (start === 0 ? 0 : GAP / 2);
                    const to = x(cursor) - (last ? 0 : GAP / 2);
                    return (
                      <path key={s.id} className={cls} d={rowPath(from, to, mid - barH / 2, barH, 4, last)} fill={s.color} />
                    );
                  }
                  const y0 = rowTop + 8 + k * (barH + GAP);
                  return <path key={s.id} className={cls} d={rowPath(x(0), x(v), y0, barH, 4)} fill={s.color} />;
                })}
                {(() => {
                  // The value at the tip: of the first series when grouped, of the total when stacked.
                  const first = shown[0];
                  const value = mode === 'stacked' ? (totals[i] ?? 0) : (first?.values[i] ?? null);
                  if (value == null) return null;
                  const tipX = x(Math.max(value, 0)) + 8;
                  const y0 = mode === 'stacked' ? mid : rowTop + 8 + barH / 2;
                  return tipX + 56 <= width ? (
                    <text className="value-text" x={tipX} y={y0} dominantBaseline="middle">
                      {format(value)}
                    </text>
                  ) : null;
                })()}
                <rect
                  className="hit"
                  x={0}
                  y={rowTop}
                  width={width}
                  height={rowH}
                  tabIndex={0}
                  aria-label={`${c}: ${shown.map((s) => `${s.label} ${s.values[i] == null ? 'none' : format(s.values[i] as number)}`).join(', ')}`}
                  onPointerEnter={() => show(i)}
                  onPointerMove={() => show(i)}
                  onPointerLeave={hide}
                  onFocus={() => show(i)}
                  onBlur={hide}
                />
              </g>
            );
          })}
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>
    </div>
  );
}
