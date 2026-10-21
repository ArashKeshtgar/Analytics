import type { RevenueRow } from '../api/types';
import { Card, Empty } from '../components/Card';
import { HBarChart } from '../components/charts/HBarChart';
import { LineChart } from '../components/charts/LineChart';
import { StatTile } from '../components/StatTile';
import { money, money2, monthLabel, monthShort, percent, signedPercent } from '../lib/format';
import { overviewModel } from '../lib/aggregate';
import { addMonths } from '../lib/periods';
import { useDashboard, useFinance } from '../state/Dashboard';

export function Overview() {
  const { range } = useDashboard();
  const earliest = addMonths(range.to, -12) < range.from ? addMonths(range.to, -12) : range.from;
  const res = useFinance<RevenueRow[]>('/api/finance/revenue', {
    params: { groupBy: 'month,lineOfBusiness' },
    from: earliest,
  });
  if (res.error) return <p className="error">{res.error}</p>;
  if (!res.data) return <p className="empty">Loading…</p>;
  const m = overviewModel(res.data, range);
  const stale = res.loading;
  const end = monthLabel(m.endMonth);
  const before = monthLabel(addMonths(m.endMonth, -12));
  if (m.trend.every((t) => t.revenue == null)) {
    return <Empty>No revenue in the selected months.</Empty>;
  }

  const direction = m.change == null ? 'flat' : m.change > 0 ? 'up' : m.change < 0 ? 'down' : 'flat';
  const delta =
    m.change == null
      ? undefined
      : { text: `${signedPercent(m.change)} vs ${before}`, direction } as const;

  return (
    <>
      <div className={stale ? 'stale' : undefined}>
        <StatTile hero label={`Revenue, ${end}`} value={money(m.total)} delta={delta} />
        {m.totalLastYear == null && <p className="card-sub" style={{ marginTop: 6 }}>No books for {before}, so there is nothing to compare with.</p>}
      </div>
      <div className="grid-2">
        <Card
          title="Revenue by line of business"
          subtitle={`${end} compared with ${before}`}
          stale={stale}
          chart={
            <HBarChart
              mode="grouped"
              categories={m.lines.map((l) => l.name)}
              ariaLabel={`Revenue by line of business, ${end} compared with ${before}`}
              format={money}
              series={[
                { id: 'thisMonth', label: end, color: 'var(--series-1)', values: m.lines.map((l) => l.thisMonth) },
                { id: 'lastYear', label: before, color: 'var(--series-other)', values: m.lines.map((l) => l.lastYear) },
              ]}
            />
          }
          table={{
            csvName: `revenue-by-line-of-business-${m.endMonth.slice(0, 7)}`,
            columns: [
              { key: 'name', label: 'Line of business' },
              { key: 'thisMonth', label: end, numeric: true, format: money2 },
              { key: 'lastYear', label: before, numeric: true, format: money2 },
              { key: 'change', label: 'Change', numeric: true, format: money2 },
              { key: 'changePct', label: 'Change %', numeric: true, format: (v) => percent(v) },
            ],
            rows: m.lines.map((l) => ({
              name: l.name,
              thisMonth: l.thisMonth,
              lastYear: l.lastYear,
              change: l.lastYear == null ? null : l.thisMonth - l.lastYear,
              changePct: l.lastYear ? (l.thisMonth - l.lastYear) / Math.abs(l.lastYear) : null,
            })),
            totals: {
              name: 'Total',
              thisMonth: m.total,
              lastYear: m.totalLastYear,
              change: m.totalLastYear == null ? null : m.total - m.totalLastYear,
              changePct: m.change,
            },
          }}
        />
        <Card
          title="Monthly revenue"
          subtitle="Each month with the same month a year earlier"
          stale={stale}
          chart={
            <LineChart
              categories={m.trend.map((t) => monthLabel(t.month))}
              axisLabels={m.trend.map((t) => monthShort(t.month))}
              ariaLabel="Monthly revenue and the same month a year earlier"
              format={money}
              tickFormat={undefined}
              series={[
                { id: 'revenue', label: 'Revenue', color: 'var(--series-1)', values: m.trend.map((t) => t.revenue) },
                { id: 'lastYear', label: 'A year earlier', color: 'var(--series-other)', values: m.trend.map((t) => t.lastYear) },
              ]}
            />
          }
          table={{
            csvName: `monthly-revenue-${m.endMonth.slice(0, 7)}`,
            columns: [
              { key: 'month', label: 'Month' },
              { key: 'revenue', label: 'Revenue', numeric: true, format: money2 },
              { key: 'lastYear', label: 'A year earlier', numeric: true, format: money2 },
              { key: 'change', label: 'Change %', numeric: true, format: (v) => percent(v) },
            ],
            rows: m.trend.map((t) => ({
              month: monthLabel(t.month),
              revenue: t.revenue,
              lastYear: t.lastYear,
              change: t.revenue != null && t.lastYear ? (t.revenue - t.lastYear) / Math.abs(t.lastYear) : null,
            })),
          }}
        />
      </div>
    </>
  );
}
