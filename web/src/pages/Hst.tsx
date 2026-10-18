import { useState } from 'react';
import type { HstRow } from '../api/types';
import { Card, Empty, Notice } from '../components/Card';
import { ColumnChart } from '../components/charts/ColumnChart';
import { StatTile } from '../components/StatTile';
import { type Grain, hstModel } from '../lib/aggregate';
import { money, money2, monthLabel } from '../lib/format';
import { useFinance } from '../state/Dashboard';

export function Hst() {
  const [grain, setGrain] = useState<Grain>('month');
  const res = useFinance<HstRow[]>('/api/finance/hst');
  if (res.error) return <p className="error">{res.error}</p>;
  if (!res.data) return <p className="empty">Loading…</p>;
  const m = hstModel(res.data, grain);
  const label = (p: string): string => (grain === 'month' ? monthLabel(p) : p);

  return (
    <>
      <div className="presets" role="group" aria-label="Period">
        <button type="button" className="btn" aria-pressed={grain === 'month'} onClick={() => setGrain('month')}>
          By month
        </button>
        <button type="button" className="btn" aria-pressed={grain === 'quarter'} onClick={() => setGrain('quarter')}>
          By quarter
        </button>
      </div>
      {m.periods.length === 0 ? (
        <Empty>No sales, purchases or HST in the selected months.</Empty>
      ) : (
        <>
          <div className={`tiles${res.loading ? ' stale' : ''}`}>
            <StatTile label="Sales" value={money(m.totals.sales)} />
            <StatTile label="HST collected" value={money(m.totals.collected)} />
            <StatTile label="ITCs" value={money(m.totals.itc)} />
            <StatTile label={m.totals.net >= 0 ? 'Net tax to remit' : 'Net tax refundable'} value={money(Math.abs(m.totals.net))} />
          </div>
          <Card
            title="Net tax by period"
            subtitle="HST collected minus input tax credits; below the line is a refund"
            stale={res.loading}
            chart={
              <ColumnChart
                categories={m.periods.map(label)}
                ariaLabel="Net tax by period"
                format={money}
                series={[{ id: 'net', label: 'Net tax', color: 'var(--series-1)', values: m.net }]}
              />
            }
            table={{
              csvName: `hst-${grain}`,
              emphasis: (row) => String(row.label).includes('total') || String(row.label).startsWith('Net'),
              columns: [
                { key: 'label', label: 'Line' },
                ...m.periods.map((p) => ({ key: p, label: label(p), numeric: true, format: money2 })),
              ],
              rows: m.lines.map((l) => ({
                label: l.label,
                ...Object.fromEntries(m.periods.map((p, i) => [p, l.values[i] ?? 0])),
              })),
            }}
          />
        </>
      )}
      <Notice>
        Read from the journal: sales are the revenue accounts and purchases the expense accounts by tax code, HST
        collected is the tax payable accounts and ITCs the tax recoverable accounts. The GST34 line numbers are not
        mapped, and these figures have not been compared with FinancePowerApp’s own HST report; do that before you
        file anything.
      </Notice>
    </>
  );
}
