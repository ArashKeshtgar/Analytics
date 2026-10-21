import { describe, expect, it } from 'vitest';
import type { AgingRow, HstRow, OhipRow, RevenueRow } from '../api/types';
import { agingModel, hstModel, ohipByMonth, overviewModel } from './aggregate';

const rev = (month: string, line: string, revenue: number): RevenueRow => ({ month, line_of_business: line, revenue });

describe('overviewModel', () => {
  const rows = [
    rev('2025-10-01', 'Clinic', 90),
    rev('2025-10-01', 'Lab', 60),
    rev('2026-09-01', 'Clinic', 250),
    rev('2026-10-01', 'Clinic', 200),
    rev('2026-10-01', 'Lab', 70),
  ];
  const range = { from: '2025-11-01', to: '2026-10-01' };

  it('compares the latest month with the same month a year earlier, by line', () => {
    const m = overviewModel(rows, range);
    expect(m.endMonth).toBe('2026-10-01');
    expect(m.total).toBe(270);
    expect(m.totalLastYear).toBe(150);
    expect(m.change).toBeCloseTo(0.8);
    expect(m.lines).toEqual([
      { name: 'Clinic', thisMonth: 200, lastYear: 90 },
      { name: 'Lab', thisMonth: 70, lastYear: 60 },
    ]);
  });

  it('has one point per month and leaves months without books empty, not zero', () => {
    const m = overviewModel(rows, range);
    expect(m.trend).toHaveLength(12);
    expect(m.trend[0]).toEqual({ month: '2025-11-01', revenue: null, lastYear: null });
    expect(m.trend.at(-1)).toEqual({ month: '2026-10-01', revenue: 270, lastYear: 150 });
    expect(m.trend.at(-2)).toEqual({ month: '2026-09-01', revenue: 250, lastYear: null });
  });

  it('says nothing about last year when there are no books for it', () => {
    const m = overviewModel(rows.slice(2), range);
    expect(m.totalLastYear).toBeNull();
    expect(m.change).toBeNull();
    expect(m.lines.every((l) => l.lastYear === null)).toBe(true);
  });

  it('is about the last month that has revenue when the range ends in an empty month', () => {
    const m = overviewModel(rows, { from: '2025-01-01', to: '2025-12-01' });
    expect(m.endMonth).toBe('2025-10-01');
    expect(m.total).toBe(150);
    expect(m.trend.at(-1)?.month).toBe('2025-10-01');
  });

  it('keeps a line that has no revenue this month but had some last year', () => {
    const m = overviewModel([rev('2025-10-01', 'Echo', 40), rev('2026-10-01', 'Clinic', 10)], range);
    expect(m.lines.find((l) => l.name === 'Echo')).toEqual({ name: 'Echo', thisMonth: 0, lastYear: 40 });
  });

  it('does not divide by zero', () => {
    const m = overviewModel([rev('2025-10-01', 'Clinic', 0), rev('2026-10-01', 'Clinic', 10)], range);
    expect(m.change).toBeNull();
  });
});

describe('ohipByMonth', () => {
  const row = (month: string, b: number, billed: number, paid: number, short: number, refused: number): OhipRow => ({
    business: `B${b}`,
    month,
    billed,
    paid,
    adjusted: 0,
    outstanding: 0,
    short_paid: short,
    refused,
    short_paid_rate: null,
    refused_rate: null,
  });

  it('adds the businesses together and works out the rates from the sums', () => {
    const m = ohipByMonth([row('2026-10-01', 1, 100, 60, 5, 10), row('2026-10-01', 2, 100, 40, 5, 20)], {
      from: '2026-09-01',
      to: '2026-10-01',
    });
    expect(m).toHaveLength(2);
    expect(m[0]).toMatchObject({ month: '2026-09-01', billed: 0, refusedRate: null, shortPaidRate: null });
    expect(m[1]).toMatchObject({ billed: 200, paid: 100, refused: 30, shortPaid: 10 });
    expect(m[1]?.refusedRate).toBeCloseTo(0.15);
    expect(m[1]?.shortPaidRate).toBeCloseTo(0.05);
  });
});

describe('agingModel', () => {
  const row = (party: string, bucket: string, balance: number, date = '2026-10-31'): AgingRow => ({
    business: 'HV',
    party_type: party,
    aging_bucket: bucket,
    snapshot_date: date,
    balance,
    items: 1,
  });

  it('puts balances in the buckets in age order and adds up what is over 30 days', () => {
    const m = agingModel([
      row('OHIP', '90+', 5),
      row('OHIP', 'current', 200),
      row('OHIP', '1-30', 10),
      row('Patient', '31-60', 50),
      row('OHIP', '61-90', 7),
    ]);
    expect(m.payers[0]).toEqual({ party: 'OHIP', buckets: [200, 10, 0, 7, 5], total: 222 });
    expect(m.payers[1]).toEqual({ party: 'Patient', buckets: [0, 0, 50, 0, 0], total: 50 });
    expect(m.bucketTotals).toEqual([200, 10, 50, 7, 5]);
    expect(m.total).toBe(272);
    expect(m.overThirty).toBe(62);
  });

  it('adds businesses of the same payer type and reports the newest snapshot', () => {
    const m = agingModel([row('OHIP', '1-30', 4, '2026-10-31'), { ...row('OHIP', '1-30', 6, '2026-11-15'), business: 'LAB' }]);
    expect(m.payers[0]?.buckets[1]).toBe(10);
    expect(m.snapshotDate).toBe('2026-11-15');
  });

  it('ignores a bucket it does not know and handles no rows', () => {
    expect(agingModel([row('OHIP', 'mystery', 9)]).payers).toEqual([]);
    expect(agingModel([])).toMatchObject({ total: 0, snapshotDate: null, payers: [] });
  });
});

describe('hstModel', () => {
  const r = (month: string, measure: HstRow['measure'], taxCode: string, amount: number, name: string | null = null, rate: number | null = null): HstRow => ({
    month,
    taxCode,
    taxName: name,
    ratePercent: rate,
    measure,
    amount,
  });
  const rows = [
    r('2026-09-01', 'sales', 'EXEMPT', 150, 'Exempt', 0),
    r('2026-09-01', 'sales', 'HST13', 100, 'HST 13%', 13),
    r('2026-09-01', 'tax_collected', 'HST13', 13),
    r('2026-10-01', 'sales', 'EXEMPT', 270),
    r('2026-10-01', 'sales', '(none)', -40),
    r('2026-10-01', 'purchases', 'HST13', 200),
    r('2026-10-01', 'itc', 'HST13', 26),
  ];

  it('by month: lines per tax code, totals, and net tax as collected minus ITCs', () => {
    const m = hstModel(rows, 'month');
    expect(m.periods).toEqual(['2026-09-01', '2026-10-01']);
    const line = (id: string) => m.lines.find((l) => l.id === id)?.values;
    expect(line('sales:EXEMPT')).toEqual([150, 270]);
    expect(line('sales:HST13')).toEqual([100, 0]);
    expect(line('sales')).toEqual([250, 230]);
    expect(line('purchases')).toEqual([0, 200]);
    expect(line('collected')).toEqual([13, 0]);
    expect(line('itc')).toEqual([0, 26]);
    expect(m.net).toEqual([13, -26]);
    expect(m.totals).toEqual({ sales: 480, collected: 13, itc: 26, net: -13 });
  });

  it('names a line with its tax name and rate', () => {
    const labels = hstModel(rows, 'month').lines.map((l) => l.label);
    expect(labels).toContain('Sales — HST13 (HST 13% · 13%)');
    expect(labels).toContain('Sales — (none)');
  });

  it('by quarter: months of a quarter are one period', () => {
    const m = hstModel([...rows, r('2026-11-01', 'sales', 'EXEMPT', 10)], 'quarter');
    expect(m.periods).toEqual(['2026 Q3', '2026 Q4']);
    expect(m.lines.find((l) => l.id === 'sales:EXEMPT')?.values).toEqual([150, 280]);
    expect(m.net).toEqual([13, -26]);
  });

  it('copes with nothing', () => {
    expect(hstModel([], 'month')).toMatchObject({ periods: [], net: [], totals: { sales: 0, net: 0 } });
  });
});
