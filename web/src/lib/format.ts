const cad = new Intl.NumberFormat('en-CA', {
  style: 'currency',
  currency: 'CAD',
  maximumFractionDigits: 0,
});
const cad2 = new Intl.NumberFormat('en-CA', {
  style: 'currency',
  currency: 'CAD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const compactFormat = new Intl.NumberFormat('en-CA', { notation: 'compact', maximumFractionDigits: 1 });

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Whole dollars, for tiles and axes. */
export const money = (n: number | null | undefined): string => (n == null ? '–' : cad.format(n));

/** Dollars and cents, for tables. */
export const money2 = (n: number | null | undefined): string => (n == null ? '–' : cad2.format(n));

/** 0, 1.2K, 3.4M: axis ticks. */
export const compact = (n: number): string => (n === 0 ? '0' : compactFormat.format(n));

/** A fraction as a percentage: 0.153 -> 15.3%. */
export const percent = (fraction: number | null | undefined, digits = 1): string =>
  fraction == null ? '–' : `${(fraction * 100).toFixed(digits)}%`;

/** '2026-10-01' -> 'Oct 2026'. Read as a calendar date: no time zone shift. */
export function monthLabel(iso: string): string {
  const [year, month] = iso.split('-');
  return `${MONTHS[Number(month) - 1] ?? '?'} ${year}`;
}

/** '2026-10-01' -> 'Oct'. */
export const monthShort = (iso: string): string => MONTHS[Number(iso.split('-')[1]) - 1] ?? '?';

/** A change with its sign: +12.5% / −3.0%. */
export function signedPercent(fraction: number): string {
  const sign = fraction > 0 ? '+' : fraction < 0 ? '−' : '';
  return `${sign}${Math.abs(fraction * 100).toFixed(1)}%`;
}
