import { useState } from 'react';
import { columnPath, Legend, niceScale, type AxisKind, type Series, Tooltip, type TipState, useHidden, useWidth } from './common';
import { compact } from '../../lib/format';

interface Props {
  /** One entry per column group, e.g. each month. */
  categories: string[];
  /** Short text under each group; defaults to the category. */
  axisLabels?: string[];
  series: Series[];
  format(value: number): string;
  /** Format of the y-axis ticks; defaults to compact numbers. */
  tickFormat?(value: number): string;
  /** Whole numbers (counts) or minutes (durations): picks the tick steps. */
  axis?: AxisKind;
  ariaLabel: string;
  height?: number;
}

const MARGIN = { top: 12, right: 8, bottom: 28, left: 52 };
const MAX_BAR = 24;
const GAP = 2;

/** Grouped columns: <= 24px thick, rounded data end, square baseline, a 2px gap between neighbours. */
export function ColumnChart({ categories, axisLabels, series, format, tickFormat, axis, ariaLabel, height = 260 }: Props) {
  const [ref, width] = useWidth();
  const [hidden, toggle] = useHidden();
  const [tip, setTip] = useState<TipState | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const all = series.map((s) => s.id);
  const shown = series.filter((s) => !hidden.has(s.id));

  const values = shown.flatMap((s) => s.values.filter((v): v is number => v != null));
  const scale = niceScale(Math.min(0, ...values), Math.max(0, ...values), 4, axis);
  const plotW = Math.max(40, width - MARGIN.left - MARGIN.right);
  const plotH = height - MARGIN.top - MARGIN.bottom;
  const y = (v: number) => MARGIN.top + (plotH * (scale.max - v)) / (scale.max - scale.min);
  const band = plotW / Math.max(1, categories.length);
  const barW = Math.max(2, Math.min(MAX_BAR, (band * 0.8 - GAP * (shown.length - 1)) / Math.max(1, shown.length)));
  const groupW = barW * shown.length + GAP * Math.max(0, shown.length - 1);
  const step = Math.max(1, Math.ceil(categories.length / Math.max(1, Math.floor(plotW / 44))));

  function show(i: number) {
    const rows = shown.map((s) => ({
      color: s.color,
      label: s.label,
      value: s.values[i] == null ? '–' : format(s.values[i] as number),
    }));
    const tops = shown.map((s) => s.values[i]).filter((v): v is number => v != null).map((v) => y(Math.max(v, 0)));
    setActive(i);
    setTip({
      x: MARGIN.left + band * i + band / 2,
      y: (tops.length ? Math.min(...tops) : y(0)) - 8,
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
              <line className="grid-line" x1={MARGIN.left} x2={width - MARGIN.right} y1={y(t)} y2={y(t)} />
              <text className="axis-text" x={MARGIN.left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle">
                {(tickFormat ?? compact)(t)}
              </text>
            </g>
          ))}
          <line className="axis-line" x1={MARGIN.left} x2={width - MARGIN.right} y1={y(0)} y2={y(0)} />
          {categories.map((c, i) => (
            <g key={c}>
              {shown.map((s, k) => {
                const v = s.values[i];
                if (v == null) return null;
                const x = MARGIN.left + band * i + (band - groupW) / 2 + k * (barW + GAP);
                return (
                  <path
                    key={s.id}
                    className={`mark${active === i ? ' on' : ''}`}
                    d={columnPath(x, y(0), y(v), barW, 4)}
                    fill={s.color}
                  />
                );
              })}
              {(categories.length - 1 - i) % step === 0 && (
                <text
                  className="axis-text"
                  x={MARGIN.left + band * i + band / 2}
                  y={height - 8}
                  textAnchor="middle"
                >
                  {axisLabels?.[i] ?? c}
                </text>
              )}
              <rect
                className="hit"
                x={MARGIN.left + band * i}
                y={MARGIN.top}
                width={band}
                height={plotH}
                tabIndex={0}
                aria-label={`${c}: ${shown.map((s) => `${s.label} ${s.values[i] == null ? 'none' : format(s.values[i] as number)}`).join(', ')}`}
                onPointerEnter={() => show(i)}
                onPointerMove={() => show(i)}
                onPointerLeave={hide}
                onFocus={() => show(i)}
                onBlur={hide}
              />
            </g>
          ))}
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>
    </div>
  );
}
