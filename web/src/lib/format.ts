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

/** 165 -> '2 h 45 min', 1740 -> '1 d 5 h', 45 -> '45 min'. Minutes in, whole units out. */
export function duration(minutes: number | null | undefined): string {
  if (minutes == null) return '–';
  const total = Math.round(minutes);
  if (total < 60) return `${total} min`;
  if (total < 1440) {
    const h = Math.floor(total / 60);
    const m = total % 60;
    return m ? `${h} h ${m} min` : `${h} h`;
  }
  let d = Math.floor(total / 1440);
  let h = Math.round((total % 1440) / 60);
  if (h === 24) {
    d += 1;
    h = 0;
  }
  return h ? `${d} d ${h} h` : `${d} d`;
}

/** Axis ticks of a duration: 0, 30 min, 1.5 h, 2 d. */
export function durationTick(minutes: number): string {
  if (minutes === 0) return '0';
  if (Math.abs(minutes) < 60) return `${+minutes.toFixed(0)} min`;
  if (Math.abs(minutes) < 1440) return `${+(minutes / 60).toFixed(1)} h`;
  return `${+(minutes / 1440).toFixed(1)} d`;
}

/** A change with its sign: +12.5% / −3.0%. */
export function signedPercent(fraction: number): string {
  const sign = fraction > 0 ? '+' : fraction < 0 ? '−' : '';
  return `${sign}${Math.abs(fraction * 100).toFixed(1)}%`;
}
