import type { AgingRow, HstRow, OhipRow, RevenueRow } from '../api/types';
import { addMonths, monthsBetween, quarterOf } from './periods';

const sum = (values: number[]): number => values.reduce((a, b) => a + b, 0);

// ---- Overview ----------------------------------------------------------------------------------

export interface OverviewModel {
  endMonth: string;
  total: number;
  /** null when the books have nothing for the same month a year earlier. */
  totalLastYear: number | null;
  /** Percent change as a fraction, null when last year is missing or zero. */
  change: number | null;
  lines: { name: string; thisMonth: number; lastYear: number | null }[];
  trend: { month: string; revenue: number | null; lastYear: number | null }[];
}

/** Revenue rows are by month and line of business; `range.to` is the month the dashboard is about. */
export function overviewModel(rows: RevenueRow[], range: { from: string; to: string }): OverviewModel {
  const byMonth = new Map<string, Map<string, number>>();
  for (const r of rows) {
    if (!r.month) continue;
    const lines = byMonth.get(r.month) ?? new Map<string, number>();
    const lob = r.line_of_business ?? 'Unassigned';
    lines.set(lob, (lines.get(lob) ?? 0) + r.revenue);
    byMonth.set(r.month, lines);
  }
  const total = (month: string): number | null => {
    const lines = byMonth.get(month);
    return lines ? sum([...lines.values()]) : null;
  };
  // The month the page is about: the latest one in the range that has revenue (a range that ends in a
  // month with no books, such as 'last year' ending in December, is about the last month with some).
  const withRevenue = [...byMonth.keys()].filter((m) => m >= range.from && m <= range.to).sort();
  const endMonth = withRevenue.at(-1) ?? range.to;
  const lastYearMonth = addMonths(endMonth, -12);
  const now = byMonth.get(endMonth) ?? new Map<string, number>();
  const before = byMonth.get(lastYearMonth);
  const names = new Set([...now.keys(), ...(before?.keys() ?? [])]);
  const lines = [...names]
    .map((name) => ({
      name,
      thisMonth: now.get(name) ?? 0,
      lastYear: before ? (before.get(name) ?? 0) : null,
    }))
    .sort((a, b) => b.thisMonth - a.thisMonth || a.name.localeCompare(b.name));
  const thisTotal = total(endMonth) ?? 0;
  const lastTotal = total(lastYearMonth);
  return {
    endMonth,
    total: thisTotal,
    totalLastYear: lastTotal,
    change: lastTotal ? (thisTotal - lastTotal) / Math.abs(lastTotal) : null,
    lines,
    trend: monthsBetween(range.from, endMonth).map((month) => ({
      month,
      revenue: total(month),
      lastYear: total(addMonths(month, -12)),
    })),
  };
}

// ---- OHIP --------------------------------------------------------------------------------------

export interface OhipMonth {
  month: string;
  billed: number;
  paid: number;
  shortPaid: number;
  refused: number;
  shortPaidRate: number | null;
  refusedRate: number | null;
}

/** All businesses added together, one row per month of the range (months without claims are zero). */
export function ohipByMonth(rows: OhipRow[], range: { from: string; to: string }): OhipMonth[] {
  return monthsBetween(range.from, range.to).map((month) => {
    const of = rows.filter((r) => r.month === month);
    const billed = sum(of.map((r) => r.billed));
    const shortPaid = sum(of.map((r) => r.short_paid));
    const refused = sum(of.map((r) => r.refused));
    return {
      month,
      billed,
      paid: sum(of.map((r) => r.paid)),
      shortPaid,
      refused,
      shortPaidRate: billed > 0 ? shortPaid / billed : null,
      refusedRate: billed > 0 ? refused / billed : null,
    };
  });
}

// ---- Receivables -------------------------------------------------------------------------------

export const AGING_BUCKETS = ['current', '1-30', '31-60', '61-90', '90+'] as const;
export const AGING_LABELS: Record<(typeof AGING_BUCKETS)[number], string> = {
  current: 'Current',
  '1-30': '1–30 days',
  '31-60': '31–60 days',
  '61-90': '61–90 days',
  '90+': 'Over 90 days',
};

export interface AgingModel {
  snapshotDate: string | null;
  payers: { party: string; buckets: number[]; total: number }[];
  bucketTotals: number[];
  total: number;
  /** Past due by more than 30 days. */
  overThirty: number;
}

export function agingModel(rows: AgingRow[]): AgingModel {
  const byParty = new Map<string, number[]>();
  for (const r of rows) {
    const index = AGING_BUCKETS.indexOf(r.aging_bucket as (typeof AGING_BUCKETS)[number]);
    if (index < 0) continue;
    const buckets = byParty.get(r.party_type) ?? AGING_BUCKETS.map(() => 0);
    buckets[index] = (buckets[index] ?? 0) + r.balance;
    byParty.set(r.party_type, buckets);
  }
  const payers = [...byParty.entries()]
    .map(([party, buckets]) => ({ party, buckets, total: sum(buckets) }))
    .sort((a, b) => b.total - a.total || a.party.localeCompare(b.party));
  const bucketTotals = AGING_BUCKETS.map((_, i) => sum(payers.map((p) => p.buckets[i] ?? 0)));
  return {
    snapshotDate: rows.map((r) => r.snapshot_date).sort().at(-1) ?? null,
    payers,
    bucketTotals,
    total: sum(bucketTotals),
    overThirty: sum(bucketTotals.slice(2)),
  };
}

// ---- HST ---------------------------------------------------------------------------------------

export type Grain = 'month' | 'quarter';

export interface HstLine {
  id: string;
  label: string;
  kind: 'detail' | 'total';
  values: number[];
}

export interface HstModel {
  periods: string[];
  lines: HstLine[];
  net: number[];
  totals: { sales: number; collected: number; itc: number; net: number };
}

export function hstModel(rows: HstRow[], grain: Grain): HstModel {
  const key = (month: string): string => (grain === 'month' ? month : quarterOf(month));
  const periods = [...new Set(rows.map((r) => key(r.month)))].sort();
  const at = (period: string): number => periods.indexOf(period);
  const zeros = (): number[] => periods.map(() => 0);

  const detail = new Map<string, HstLine>();
  const totals = { sales: zeros(), purchases: zeros(), tax_collected: zeros(), itc: zeros() };
  for (const r of rows) {
    const i = at(key(r.month));
    totals[r.measure][i] = (totals[r.measure][i] ?? 0) + r.amount;
    if (r.measure === 'sales' || r.measure === 'purchases') {
      const id = `${r.measure}:${r.taxCode}`;
      const rate = r.ratePercent == null ? '' : ` · ${r.ratePercent}%`;
      const name = r.taxName ? `${r.taxCode} (${r.taxName}${rate})` : r.taxCode;
      const line = detail.get(id) ?? {
        id,
        label: `${r.measure === 'sales' ? 'Sales' : 'Purchases'} — ${name}`,
        kind: 'detail' as const,
        values: zeros(),
      };
      line.values[i] = (line.values[i] ?? 0) + r.amount;
      detail.set(id, line);
    }
  }
  const byLabel = (a: HstLine, b: HstLine): number => a.label.localeCompare(b.label);
  const sales = [...detail.values()].filter((l) => l.id.startsWith('sales:')).sort(byLabel);
  const purchases = [...detail.values()].filter((l) => l.id.startsWith('purchases:')).sort(byLabel);
  const net = periods.map((_, i) => (totals.tax_collected[i] ?? 0) - (totals.itc[i] ?? 0));
  const total = (id: string, label: string, values: number[]): HstLine => ({ id, label, kind: 'total', values });
  return {
    periods,
    lines: [
      ...sales,
      total('sales', 'Sales — total', totals.sales),
      ...purchases,
      total('purchases', 'Purchases — total', totals.purchases),
      total('collected', 'HST collected (tax payable accounts)', totals.tax_collected),
      total('itc', 'ITCs (tax recoverable accounts)', totals.itc),
      total('net', 'Net tax (collected − ITCs)', net),
    ],
    net,
    totals: {
      sales: sum(totals.sales),
      collected: sum(totals.tax_collected),
      itc: sum(totals.itc),
      net: sum(net),
    },
  };
}
