import { type KeyboardEvent, type PointerEvent, useState } from 'react';
import { compact } from '../../lib/format';
import { Legend, niceScale, type AxisKind, type Series, Tooltip, type TipState, useHidden, useWidth } from './common';

interface Props {
  categories: string[];
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

const BASE_MARGIN = { top: 12, bottom: 28, left: 52 };

/** 2px lines, an end dot with a surface ring, a crosshair that snaps to the nearest position. */
export function LineChart({ categories, axisLabels, series, format, tickFormat, axis, ariaLabel, height = 260 }: Props) {
  const [ref, width] = useWidth();
  const [hidden, toggle] = useHidden();
  const [index, setIndex] = useState<number | null>(null);
  const all = series.map((s) => s.id);
  const shown = series.filter((s) => !hidden.has(s.id));

  const values = shown.flatMap((s) => s.values.filter((v): v is number => v != null));
  const scale = niceScale(Math.min(0, ...values), Math.max(0, ...values), 4, axis);
  const tick = tickFormat ?? compact;

  // End labels ride the lines when there is room and they do not collide; otherwise the legend and the
  // tooltip carry the identity (nudging labels apart would detach them from their lines).
  const lastPoint = (s: Series): { i: number; v: number } | null => {
    for (let i = s.values.length - 1; i >= 0; i--) {
      const v = s.values[i];
      if (v != null) return { i, v };
    }
    return null;
  };
  const ys = (v: number, bottom = BASE_MARGIN.bottom) =>
    BASE_MARGIN.top + ((height - BASE_MARGIN.top - bottom) * (scale.max - v)) / (scale.max - scale.min);
  const ends = shown.map((s) => ({ s, p: lastPoint(s) })).filter((e) => e.p != null);
  const sorted = ends.map((e) => ys((e.p as { v: number }).v)).sort((a, b) => a - b);
  const collide = sorted.some((y, i) => i > 0 && y - (sorted[i - 1] as number) < 16);
  const direct = shown.length >= 2 && shown.length <= 4 && width >= 520 && !collide;
  const right = direct ? 88 : 12;

  const plotW = Math.max(40, width - BASE_MARGIN.left - right);
  const x = (i: number) => BASE_MARGIN.left + (categories.length <= 1 ? plotW / 2 : (plotW * i) / (categories.length - 1));
  const y = (v: number) => ys(v);
  const step = Math.max(1, Math.ceil(categories.length / Math.max(1, Math.floor(plotW / 48))));

  function pathFor(s: Series): string {
    let d = '';
    let open = false;
    s.values.forEach((v, i) => {
      if (v == null) {
        open = false;
        return;
      }
      d += `${open ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      open = true;
    });
    return d;
  }

  const nearest = (clientX: number, rect: DOMRect) => {
    if (categories.length <= 1) return 0;
    const px = ((clientX - rect.left) / rect.width) * width - BASE_MARGIN.left;
    return Math.min(categories.length - 1, Math.max(0, Math.round((px / plotW) * (categories.length - 1))));
  };
  const onPointer = (e: PointerEvent<SVGRectElement>) =>
    setIndex(nearest(e.clientX, e.currentTarget.getBoundingClientRect()));
  const onKey = (e: KeyboardEvent<SVGRectElement>) => {
    if (e.key === 'ArrowRight') setIndex((i) => Math.min(categories.length - 1, (i ?? -1) + 1));
    else if (e.key === 'ArrowLeft') setIndex((i) => Math.max(0, (i ?? categories.length) - 1));
    else if (e.key === 'Escape') setIndex(null);
    else return;
    e.preventDefault();
  };

  const tip: TipState | null =
    index == null
      ? null
      : {
          x: x(index),
          y: Math.min(...shown.map((s) => (s.values[index] == null ? height : y(s.values[index] as number)))) - 10,
          title: categories[index] ?? '',
          rows: shown.map((s) => ({
            color: s.color,
            label: s.label,
            value: s.values[index] == null ? '–' : format(s.values[index] as number),
          })),
        };

  return (
    <div>
      <Legend items={series} hidden={hidden} onToggle={(id) => toggle(id, all)} kind="line" />
      <div className="chart" ref={ref}>
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
          {scale.ticks.map((t) => (
            <g key={t}>
              <line className="grid-line" x1={BASE_MARGIN.left} x2={width - right} y1={y(t)} y2={y(t)} />
              <text className="axis-text" x={BASE_MARGIN.left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle">
                {tick(t)}
              </text>
            </g>
          ))}
          <line className="axis-line" x1={BASE_MARGIN.left} x2={width - right} y1={y(0)} y2={y(0)} />
          {categories.map((c, i) =>
            (categories.length - 1 - i) % step === 0 ? (
              <text key={c} className="axis-text" x={x(i)} y={height - 8} textAnchor="middle">
                {axisLabels?.[i] ?? c}
              </text>
            ) : null,
          )}
          {shown.length === 1 && shown[0] && (
            <path
              d={`${pathFor(shown[0])}L${x(categories.length - 1)},${y(0)}L${x(0)},${y(0)}Z`}
              fill={shown[0].color}
              opacity={0.1}
            />
          )}
          {shown.map((s) => (
            <path key={s.id} d={pathFor(s)} fill="none" stroke={s.color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          ))}
          {ends.map(({ s, p }) => {
            const point = p as { i: number; v: number };
            return (
              <g key={s.id}>
                <circle cx={x(point.i)} cy={y(point.v)} r={6} style={{ fill: 'var(--surface)' }} />
                <circle cx={x(point.i)} cy={y(point.v)} r={4} fill={s.color} />
                {direct && (
                  <text className="value-text" x={x(point.i) + 12} y={y(point.v)} dominantBaseline="middle">
                    {s.label}
                  </text>
                )}
              </g>
            );
          })}
          {index != null && (
            <g>
              <line className="axis-line" x1={x(index)} x2={x(index)} y1={BASE_MARGIN.top} y2={height - BASE_MARGIN.bottom} />
              {shown.map((s) =>
                s.values[index] == null ? null : (
                  <g key={s.id}>
                    <circle cx={x(index)} cy={y(s.values[index] as number)} r={6} style={{ fill: 'var(--surface)' }} />
                    <circle cx={x(index)} cy={y(s.values[index] as number)} r={4} fill={s.color} />
                  </g>
                ),
              )}
            </g>
          )}
          <rect
            className="hit"
            x={BASE_MARGIN.left}
            y={BASE_MARGIN.top}
            width={plotW}
            height={height - BASE_MARGIN.top - BASE_MARGIN.bottom}
            tabIndex={0}
            aria-label={`${ariaLabel}. Use the arrow keys to move along the months.`}
            onPointerMove={onPointer}
            onPointerDown={onPointer}
            onPointerLeave={() => setIndex(null)}
            onKeyDown={onKey}
            onFocus={() => setIndex((i) => i ?? categories.length - 1)}
            onBlur={() => setIndex(null)}
          />
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>
    </div>
  );
}
