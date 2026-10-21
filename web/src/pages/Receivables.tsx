import { useState } from 'react';
import type { AgingRow } from '../api/types';
import { Card, Empty } from '../components/Card';
import { HBarChart } from '../components/charts/HBarChart';
import { StatTile } from '../components/StatTile';
import { AGING_BUCKETS, AGING_LABELS, agingModel } from '../lib/aggregate';
import { money, money2, monthLabel, percent } from '../lib/format';
import { useDashboard, useFinance } from '../state/Dashboard';

export function Receivables() {
  const { range } = useDashboard();
  const [side, setSide] = useState<'receivable' | 'payable'>('receivable');
  const res = useFinance<AgingRow[]>('/api/finance/aging', { params: { side }, range: 'asOf' });
  if (res.error) return <p className="error">{res.error}</p>;
  if (!res.data) return <p className="empty">Loading…</p>;
  const m = agingModel(res.data);
  const noun = side === 'receivable' ? 'Receivables' : 'Payables';

  return (
    <>
      <div className="presets" role="group" aria-label="Receivables or payables">
        <button type="button" className="btn" aria-pressed={side === 'receivable'} onClick={() => setSide('receivable')}>
          Receivables
        </button>
        <button type="button" className="btn" aria-pressed={side === 'payable'} onClick={() => setSide('payable')}>
          Payables
        </button>
      </div>
      {m.payers.length === 0 ? (
        <Empty>No open {noun.toLowerCase()} up to {monthLabel(range.to)}.</Empty>
      ) : (
        <>
          <div className={`tiles${res.loading ? ' stale' : ''}`}>
            <StatTile label={`${noun} outstanding`} value={money(m.total)} />
            <StatTile label="Over 30 days past due" value={money(m.overThirty)} />
            <StatTile label="Share over 30 days" value={percent(m.total > 0 ? m.overThirty / m.total : null)} />
          </div>
          <Card
            title={`${noun} by ${side === 'receivable' ? 'payer' : 'supplier'} type and age`}
            subtitle={m.snapshotDate ? `Open items on ${m.snapshotDate}, by days past the due date` : undefined}
            stale={res.loading}
            chart={
              <HBarChart
                mode="stacked"
                categories={m.payers.map((p) => p.party)}
                ariaLabel={`${noun} by payer type and days past due`}
                format={money}
                series={AGING_BUCKETS.map((b, i) => ({
                  id: b,
                  label: AGING_LABELS[b],
                  color: `var(--age-${i + 1})`,
                  values: m.payers.map((p) => p.buckets[i] ?? 0),
                }))}
              />
            }
            table={{
              csvName: `${side}-aging-${m.snapshotDate ?? range.to}`,
              columns: [
                { key: 'party', label: side === 'receivable' ? 'Payer type' : 'Supplier type' },
                ...AGING_BUCKETS.map((b) => ({ key: b, label: AGING_LABELS[b], numeric: true, format: money2 })),
                { key: 'total', label: 'Total', numeric: true, format: money2 },
              ],
              rows: m.payers.map((p) => ({
                party: p.party,
                ...Object.fromEntries(AGING_BUCKETS.map((b, i) => [b, p.buckets[i] ?? 0])),
                total: p.total,
              })),
              totals: {
                party: 'Total',
                ...Object.fromEntries(AGING_BUCKETS.map((b, i) => [b, m.bucketTotals[i] ?? 0])),
                total: m.total,
              },
            }}
          />
        </>
      )}
    </>
  );
}
