export type Preset = 'last12' | 'last6' | 'last3' | 'ytd' | 'lastYear';

export const PRESETS: { id: Preset; label: string }[] = [
  { id: 'last12', label: 'Last 12 months' },
  { id: 'last6', label: 'Last 6 months' },
  { id: 'last3', label: 'Last 3 months' },
  { id: 'ytd', label: 'Year to date' },
  { id: 'lastYear', label: 'Last year' },
];

const pad = (n: number): string => String(n).padStart(2, '0');

/** Add whole months to a month start: ('2026-10-01', -12) -> '2025-10-01'. */
export function addMonths(iso: string, months: number): string {
  const [y, m] = iso.split('-').map(Number) as [number, number];
  const index = y * 12 + (m - 1) + months;
  return `${Math.floor(index / 12)}-${pad((index % 12) + 1)}-01`;
}

/** Month starts from `from` to `to`, both included. */
export function monthsBetween(from: string, to: string): string[] {
  const result: string[] = [];
  for (let m = from; m <= to && result.length < 600; m = addMonths(m, 1)) result.push(m);
  return result;
}

/**
 * The months a preset covers, counted back from the latest month that has data (not from today:
 * the books lag, and a dashboard that is empty on the 1st of the month is no use).
 */
export function rangeFor(preset: Preset, lastMonth: string): { from: string; to: string } {
  const year = lastMonth.slice(0, 4);
  switch (preset) {
    case 'last12':
      return { from: addMonths(lastMonth, -11), to: lastMonth };
    case 'last6':
      return { from: addMonths(lastMonth, -5), to: lastMonth };
    case 'last3':
      return { from: addMonths(lastMonth, -2), to: lastMonth };
    case 'ytd':
      return { from: `${year}-01-01`, to: lastMonth };
    case 'lastYear':
      return { from: `${Number(year) - 1}-01-01`, to: `${Number(year) - 1}-12-01` };
  }
}

/** '2026-10-01' -> '2026 Q4'. */
export function quarterOf(iso: string): string {
  const [y, m] = iso.split('-').map(Number) as [number, number];
  return `${y} Q${Math.floor((m - 1) / 3) + 1}`;
}

/** The last day of a month, as an ISO date: '2026-10-01' -> '2026-10-31'. */
export function endOfMonth(iso: string): string {
  const next = addMonths(iso, 1);
  const [y, m] = next.split('-').map(Number) as [number, number];
  const last = new Date(Date.UTC(y, m - 1, 0));
  return last.toISOString().slice(0, 10);
}
