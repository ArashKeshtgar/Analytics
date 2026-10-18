import type { AgingRow, OhipRow, RevenueRow } from '../api/types';
import { Card, Empty } from '../components/Card';
import { HBarChart } from '../components/charts/HBarChart';
import { agingModel } from '../lib/aggregate';
import { money, money2, percent } from '../lib/format';
import { useDashboard, useFinance } from '../state/Dashboard';

export function Group() {
  const { me, businesses, range } = useDashboard();
  const enabled = me.scope === 'group';
  const revenue = useFinance<RevenueRow[]>('/api/finance/revenue', { params: { groupBy: 'business' }, business: false });
  const ohip = useFinance<OhipRow[]>('/api/finance/ohip-collection', { business: false });
  const aging = useFinance<AgingRow[]>('/api/finance/aging', { business: false, range: 'asOf' });
  if (!enabled) {
    return <Empty>The group view is for people with the group permission (analytics:group.view).</Empty>;
  }
  const error = revenue.error ?? ohip.error ?? aging.error;
  if (error) return <p className="error">{error}</p>;
  if (!revenue.data || !ohip.data || !aging.data) return <p className="empty">Loading…</p>;
  const stale = revenue.loading || ohip.loading || aging.loading;
  const revenueRows = revenue.data;
  const ohipRows = ohip.data;
  const agingRows = aging.data;

  const name = (code: string): string => businesses.find((b) => b.code === code)?.name ?? code;
  const codes = businesses.map((b) => b.code);
  const rows = codes.map((code) => {
    const billed = ohipRows.filter((r) => r.business === code).reduce((a, r) => a + r.billed, 0);
    const refused = ohipRows.filter((r) => r.business === code).reduce((a, r) => a + r.refused, 0);
    const open = agingModel(agingRows.filter((r) => r.business === code));
    return {
      business: name(code),
      revenue: revenueRows.filter((r) => r.business === code).reduce((a, r) => a + r.revenue, 0),
      billed,
      refusedRate: billed > 0 ? refused / billed : null,
      outstanding: open.total,
      overThirty: open.overThirty,
    };
  });
  const byRevenue = [...rows].sort((a, b) => b.revenue - a.revenue);

  return (
    <Card
      title="Businesses side by side"
      subtitle={`Revenue from ${range.from.slice(0, 7)} to ${range.to.slice(0, 7)}; receivables on the last snapshot up to the end of the range`}
      stale={stale}
      chart={
        <HBarChart
          mode="grouped"
          categories={byRevenue.map((r) => r.business)}
          ariaLabel="Revenue by business"
          format={money}
          series={[{ id: 'revenue', label: 'Revenue', color: 'var(--series-1)', values: byRevenue.map((r) => r.revenue) }]}
        />
      }
      table={{
        csvName: `businesses-${range.to.slice(0, 7)}`,
        columns: [
          { key: 'business', label: 'Business' },
          { key: 'revenue', label: 'Revenue', numeric: true, format: money2 },
          { key: 'billed', label: 'OHIP billed', numeric: true, format: money2 },
          { key: 'refusedRate', label: 'OHIP refused rate', numeric: true, format: (v) => percent(v) },
          { key: 'outstanding', label: 'Receivables', numeric: true, format: money2 },
          { key: 'overThirty', label: 'Over 30 days', numeric: true, format: money2 },
        ],
        rows: byRevenue,
      }}
    />
  );
}
