import { useState } from 'react';
import type { CancellationRow, TurnaroundRow } from '../api/types';
import { Card, Empty, Notice } from '../components/Card';
import { ColumnChart } from '../components/charts/ColumnChart';
import { HBarChart } from '../components/charts/HBarChart';
import { LineChart } from '../components/charts/LineChart';
import { StatTile } from '../components/StatTile';
import { duration, durationTick, monthLabel, monthShort, percent } from '../lib/format';
import { useDashboard, useOps } from '../state/Dashboard';

type Department = 'Lab' | 'Diagnostics' | undefined;

const minutes = (v: number | null | undefined): number | null => v ?? null;
const durationCell = (v: number): string => duration(v);

export function Operations() {
  const { range } = useDashboard();
  const [department, setDepartment] = useState<Department>(undefined);
  const totals = useOps<TurnaroundRow[]>('/api/operations/turnaround', { params: { groupBy: 'none' }, department });
  const monthly = useOps<TurnaroundRow[]>('/api/operations/turnaround', { params: { groupBy: 'month' }, department });
  const byTest = useOps<TurnaroundRow[]>('/api/operations/turnaround', { params: { groupBy: 'test' }, department });
  const byPriority = useOps<TurnaroundRow[]>('/api/operations/turnaround', { params: { groupBy: 'priority' }, department });
  const byDepartment = useOps<TurnaroundRow[]>('/api/operations/turnaround', { params: { groupBy: 'department' } });
  const cancels = useOps<CancellationRow[]>('/api/operations/cancellations', { department });

  const error = totals.error ?? monthly.error ?? byTest.error ?? byPriority.error ?? byDepartment.error ?? cancels.error;
  if (error) return <p className="error">{error}</p>;
  if (!totals.data || !monthly.data || !byTest.data || !byPriority.data || !byDepartment.data || !cancels.data) {
    return <p className="empty">Loading…</p>;
  }
  const cancelRows = cancels.data;
  const stale = [totals, monthly, byTest, byPriority, byDepartment, cancels].some((r) => r.loading);
  const all = totals.data[0];
  const picker = (
    <div className="presets" role="group" aria-label="Department">
      {([undefined, 'Lab', 'Diagnostics'] as const).map((d) => (
        <button key={d ?? 'all'} type="button" className="btn" aria-pressed={department === d} onClick={() => setDepartment(d)}>
          {d ?? 'All departments'}
        </button>
      ))}
    </div>
  );
  if (!all || all.placed === 0) {
    return (
      <>
        {picker}
        <Empty>No orders placed in the selected months.</Empty>
      </>
    );
  }

  const tests = [...byTest.data].sort((a, b) => (b.median_minutes ?? -1) - (a.median_minutes ?? -1) || (a.test ?? '').localeCompare(b.test ?? ''));
  const shownTests = tests.filter((t) => t.resulted > 0).slice(0, 12);
  const months = [...monthly.data].sort((a, b) => (a.month ?? '').localeCompare(b.month ?? ''));
  const cancelMonths = [...new Set(cancelRows.map((c) => c.month))].sort();
  const cancelledBy = (month: string, key: 'cancelled' | 'cancel_refused' | 'placed'): number =>
    cancelRows.filter((c) => c.month === month).reduce((a, c) => a + c[key], 0);
  const cancelledTotal = cancelRows.reduce((a, c) => a + c.cancelled, 0);
  const refusedTotal = cancelRows.reduce((a, c) => a + c.cancel_refused, 0);
  const suffix = range.to.slice(0, 7);

  const turnaroundColumns = [
    { key: 'placed', label: 'Placed', numeric: true },
    { key: 'resulted', label: 'With a result', numeric: true },
    { key: 'pending', label: 'Waiting', numeric: true },
    { key: 'cancelled', label: 'Cancelled', numeric: true },
    { key: 'median', label: 'Median', numeric: true, format: durationCell },
    { key: 'p90', label: '90th percentile', numeric: true, format: durationCell },
  ];
  const turnaroundRow = (r: TurnaroundRow, label: string, key: string) => ({
    [key]: label,
    placed: r.placed,
    resulted: r.resulted,
    pending: r.pending,
    cancelled: r.cancelled,
    median: r.median_minutes,
    p90: r.p90_minutes,
  });

  return (
    <>
      {picker}
      <div className={`tiles${stale ? ' stale' : ''}`}>
        <StatTile label="Orders placed" value={String(all.placed)} />
        <StatTile label="With a final result" value={String(all.resulted)} />
        <StatTile label="Still waiting" value={String(all.pending)} />
        <StatTile label="Median turnaround" value={duration(all.median_minutes)} />
        <StatTile label="90th percentile" value={duration(all.p90_minutes)} />
        <StatTile label="Cancelled" value={String(all.cancelled)} />
      </div>
      <div className="grid-2">
        <Card
          title="Turnaround by test"
          subtitle="Order placed to first final result; tests with at least one result"
          stale={stale}
          chart={
            shownTests.length === 0 ? (
              <Empty>No results yet.</Empty>
            ) : (
              <HBarChart
                mode="grouped"
                categories={shownTests.map((t) => t.test ?? 'unknown')}
                ariaLabel="Median and 90th percentile turnaround by test"
                format={duration}
                tickFormat={durationTick}
                axis="duration"
                series={[
                  { id: 'median', label: 'Median', color: 'var(--series-1)', values: shownTests.map((t) => minutes(t.median_minutes)) },
                  { id: 'p90', label: '90th percentile', color: 'var(--series-2)', values: shownTests.map((t) => minutes(t.p90_minutes)) },
                ]}
              />
            )
          }
          table={{
            csvName: `turnaround-by-test-${suffix}`,
            columns: [{ key: 'test', label: 'Test code' }, ...turnaroundColumns],
            rows: tests.map((t) => turnaroundRow(t, t.test ?? 'unknown', 'test')),
          }}
        />
        <Card
          title="Turnaround by month"
          subtitle="By the month the order was placed"
          stale={stale}
          chart={
            <LineChart
              categories={months.map((m) => monthLabel(m.month ?? ''))}
              axisLabels={months.map((m) => monthShort(m.month ?? ''))}
              ariaLabel="Median and 90th percentile turnaround by month"
              format={duration}
              tickFormat={durationTick}
              axis="duration"
              series={[
                { id: 'median', label: 'Median', color: 'var(--series-1)', values: months.map((m) => minutes(m.median_minutes)) },
                { id: 'p90', label: '90th percentile', color: 'var(--series-2)', values: months.map((m) => minutes(m.p90_minutes)) },
              ]}
            />
          }
          table={{
            csvName: `turnaround-by-month-${suffix}`,
            columns: [{ key: 'month', label: 'Month' }, ...turnaroundColumns],
            rows: months.map((m) => turnaroundRow(m, monthLabel(m.month ?? ''), 'month')),
          }}
        />
      </div>
      <>
        <Card
          title="By priority"
          stale={stale}
          table={{
            csvName: `turnaround-by-priority-${suffix}`,
            columns: [{ key: 'priority', label: 'Priority' }, ...turnaroundColumns],
            rows: byPriority.data.map((r) => turnaroundRow(r, r.priority ?? 'unknown', 'priority')),
          }}
        />
        <Card
          title="Lab and diagnostics"
          subtitle="Lab is LabFlow, diagnostics is ClinicReport (echo, ECG)"
          stale={stale}
          table={{
            csvName: `turnaround-by-department-${suffix}`,
            columns: [{ key: 'department', label: 'Department' }, ...turnaroundColumns],
            rows: byDepartment.data.map((r) => turnaroundRow(r, r.department ?? 'unknown', 'department')),
          }}
        />
      </>
      <Card
        title="Cancellations"
        subtitle={`${cancelledTotal} cancelled and ${refusedTotal} refused by the lab (results already entered or the report started)`}
        stale={stale}
        chart={
          <ColumnChart
            categories={cancelMonths.map(monthLabel)}
            axisLabels={cancelMonths.map(monthShort)}
            ariaLabel="Cancelled orders and refused cancels by month"
            format={(v) => String(v)}
            tickFormat={(v) => String(v)}
            axis="integer"
            series={[
              { id: 'cancelled', label: 'Cancelled', color: 'var(--series-1)', values: cancelMonths.map((m) => cancelledBy(m, 'cancelled')) },
              { id: 'refused', label: 'Cancel refused', color: 'var(--series-2)', values: cancelMonths.map((m) => cancelledBy(m, 'cancel_refused')) },
            ]}
          />
        }
        table={{
          csvName: `cancellations-${suffix}`,
          columns: [
            { key: 'month', label: 'Month' },
            { key: 'department', label: 'Department' },
            { key: 'placed', label: 'Orders placed', numeric: true },
            { key: 'cancelled', label: 'Cancelled', numeric: true },
            { key: 'refused', label: 'Cancel refused', numeric: true },
            { key: 'rate', label: 'Cancelled share of placed', numeric: true, format: (v) => percent(v) },
          ],
          rows: cancelRows.map((c) => ({
            month: monthLabel(c.month),
            department: c.department,
            placed: c.placed,
            cancelled: c.cancelled,
            refused: c.cancel_refused,
            rate: c.placed > 0 ? c.cancelled / c.placed : null,
          })),
        }}
      />
      <Notice>
        From IntegrationHub’s event feed: orders placed before the hub was switched on have no turnaround. Times are
        when the hub relayed each call. “Waiting” is placed or accepted without a final result. Tests are shown by
        code (LOINC, or ClinicReport’s template key); the events carry no names. The cancel counts are by the month
        of the cancel, the share is of the orders placed in that month, so it can pass 100% for a month with few
        orders. No patient is identifiable here: patients are pseudonyms and are not shown.
      </Notice>
    </>
  );
}
