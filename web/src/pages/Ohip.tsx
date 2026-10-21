import type { DaysToPayRow, OhipAnomaly, OhipProviderRow, OhipRow } from '../api/types';
import { Card, Empty, Notice } from '../components/Card';
import { ColumnChart } from '../components/charts/ColumnChart';
import { LineChart } from '../components/charts/LineChart';
import { StatTile } from '../components/StatTile';
import { ohipByMonth } from '../lib/aggregate';
import { money, money2, monthLabel, monthShort, percent } from '../lib/format';
import { useDashboard, useFinance } from '../state/Dashboard';

const sum = (values: number[]): number => values.reduce((a, b) => a + b, 0);

export function Ohip() {
  const { range } = useDashboard();
  const collection = useFinance<OhipRow[]>('/api/finance/ohip-collection');
  const providers = useFinance<OhipProviderRow[]>('/api/finance/ohip-providers');
  const anomalies = useFinance<OhipAnomaly[]>('/api/finance/ohip-anomalies');
  const waits = useFinance<DaysToPayRow[]>('/api/finance/days-to-pay', { params: { payer: 'OHIP' } });
  const error = collection.error ?? providers.error ?? anomalies.error;
  if (error) return <p className="error">{error}</p>;
  if (!collection.data || !providers.data || !anomalies.data) return <p className="empty">Loading…</p>;
  const stale = collection.loading || providers.loading || anomalies.loading;
  const months = ohipByMonth(collection.data, range);
  const billed = sum(months.map((m) => m.billed));
  if (billed === 0 && providers.data.length === 0) return <Empty>No OHIP claims in the selected months.</Empty>;
  const outstanding = sum(collection.data.map((r) => r.outstanding));
  const refused = sum(months.map((m) => m.refused));
  const shortPaid = sum(months.map((m) => m.shortPaid));
  const labels = months.map((m) => monthLabel(m.month));
  const axis = months.map((m) => monthShort(m.month));

  return (
    <>
      <div className={`tiles${stale ? ' stale' : ''}`}>
        <StatTile label="Billed" value={money(billed)} />
        <StatTile label="Paid" value={money(sum(months.map((m) => m.paid)))} />
        <StatTile label="Outstanding" value={money(outstanding)} />
        <StatTile label="Refused rate" value={percent(billed > 0 ? refused / billed : null)} />
        <StatTile label="Short-paid rate" value={percent(billed > 0 ? shortPaid / billed : null)} />
      </div>
      <div className="grid-2">
        <Card
          title="Billed and paid"
          subtitle="Receivable items billed to OHIP, by the month of the item"
          stale={stale}
          chart={
            <ColumnChart
              categories={labels}
              axisLabels={axis}
              ariaLabel="OHIP billed and paid by month"
              format={money}
              series={[
                { id: 'billed', label: 'Billed', color: 'var(--series-1)', values: months.map((m) => m.billed) },
                { id: 'paid', label: 'Paid', color: 'var(--series-2)', values: months.map((m) => m.paid) },
              ]}
            />
          }
          table={{
            csvName: `ohip-billed-and-paid-${range.to.slice(0, 7)}`,
            columns: [
              { key: 'month', label: 'Month' },
              { key: 'billed', label: 'Billed', numeric: true, format: money2 },
              { key: 'paid', label: 'Paid', numeric: true, format: money2 },
              { key: 'shortPaid', label: 'Short-paid', numeric: true, format: money2 },
              { key: 'refused', label: 'Refused', numeric: true, format: money2 },
              { key: 'shortPaidRate', label: 'Short-paid rate', numeric: true, format: (v) => percent(v) },
              { key: 'refusedRate', label: 'Refused rate', numeric: true, format: (v) => percent(v) },
            ],
            rows: months.map((m, i) => ({ ...m, month: labels[i] })),
            totals: {
              month: 'Total',
              billed,
              paid: sum(months.map((m) => m.paid)),
              shortPaid,
              refused,
              shortPaidRate: billed > 0 ? shortPaid / billed : null,
              refusedRate: billed > 0 ? refused / billed : null,
            },
          }}
        />
        <Card
          title="Refused and short-paid rate"
          subtitle="As a share of what was billed in the same month"
          stale={stale}
          chart={
            <LineChart
              categories={labels}
              axisLabels={axis}
              ariaLabel="Refused and short-paid rate by month"
              format={(v) => percent(v)}
              tickFormat={(v) => percent(v, 0)}
              series={[
                { id: 'refused', label: 'Refused', color: 'var(--series-2)', values: months.map((m) => m.refusedRate) },
                { id: 'shortPaid', label: 'Short-paid', color: 'var(--series-1)', values: months.map((m) => m.shortPaidRate) },
              ]}
            />
          }
          table={{
            csvName: `ohip-rates-${range.to.slice(0, 7)}`,
            columns: [
              { key: 'month', label: 'Month' },
              { key: 'refusedRate', label: 'Refused rate', numeric: true, format: (v) => percent(v) },
              { key: 'shortPaidRate', label: 'Short-paid rate', numeric: true, format: (v) => percent(v) },
            ],
            rows: months.map((m, i) => ({ month: labels[i], refusedRate: m.refusedRate, shortPaidRate: m.shortPaidRate })),
          }}
        />
      </div>
      <Card
        title="By provider"
        subtitle="Billed, short-paid and refused per OHIP billing number, from the journal"
        stale={stale}
        table={{
          csvName: `ohip-by-provider-${range.to.slice(0, 7)}`,
          columns: [
            { key: 'provider', label: 'Provider' },
            { key: 'billed', label: 'Billed', numeric: true, format: money2 },
            { key: 'short_paid', label: 'Short-paid', numeric: true, format: money2 },
            { key: 'refused', label: 'Refused', numeric: true, format: money2 },
            { key: 'short_paid_rate', label: 'Short-paid rate', numeric: true, format: (v) => percent(v) },
            { key: 'refused_rate', label: 'Refused rate', numeric: true, format: (v) => percent(v) },
          ],
          rows: providers.data.map((p) => ({ ...p })),
        }}
      />
      {anomalies.data.length > 0 ? (
        <Card
          title="Unusual months"
          subtitle="A provider's short-paid or refused rate far above the same provider's earlier months"
          stale={stale}
          table={{
            csvName: `ohip-unusual-months-${range.to.slice(0, 7)}`,
            columns: [
              { key: 'month', label: 'Month' },
              { key: 'provider', label: 'Provider' },
              { key: 'measure', label: 'What' },
              { key: 'rate', label: 'Rate', numeric: true, format: (v) => percent(v as number) },
              { key: 'usual_rate', label: 'Usual rate', numeric: true, format: (v) => percent(v as number) },
              { key: 'amount', label: 'Amount', numeric: true, format: money2 },
              { key: 'billed', label: 'Billed', numeric: true, format: money2 },
              { key: 'z', label: 'How far (z)', numeric: true },
              { key: 'history_months', label: 'Earlier months', numeric: true },
            ],
            rows: anomalies.data.map((a) => ({
              month: monthLabel(a.month),
              provider: a.provider,
              measure: a.measure === 'refused' ? 'Refused' : 'Short-paid',
              rate: a.rate,
              usual_rate: a.usual_rate,
              amount: a.amount,
              billed: a.billed,
              z: a.z == null ? 'Never varied before' : a.z.toFixed(1),
              history_months: a.history_months,
            })),
          }}
        />
      ) : (
        <Notice>
          No provider-month stands out in these months. A month is flagged when its short-paid or refused rate is far
          above the provider&apos;s own earlier months (robust z-score of 3.5 or more, at least 2 points higher, on $500 or
          more billed); it needs six earlier months and a run of <code>analytics score</code>.
        </Notice>
      )}
      {waits.data && waits.data.length > 0 && (
        <Card
          title="Days to pay"
          subtitle="From the claim date to each OHIP payment, by the month paid; the mean is weighted by the amount"
          stale={waits.loading}
          table={{
            csvName: `days-to-pay-${range.to.slice(0, 7)}`,
            columns: [
              { key: 'month', label: 'Month paid' },
              { key: 'business', label: 'Business' },
              { key: 'payments', label: 'Payments', numeric: true },
              { key: 'amount', label: 'Amount', numeric: true, format: money2 },
              { key: 'mean_days', label: 'Mean days', numeric: true, format: (v) => v.toFixed(1) },
              { key: 'max_days', label: 'Longest', numeric: true },
            ],
            rows: waits.data.map((w) => ({
              month: monthLabel(w.month),
              business: w.business,
              payments: w.payments,
              amount: w.amount,
              mean_days: w.mean_days,
              max_days: w.max_days,
            })),
          }}
        />
      )}
      <Notice>
        “Paid” is by business, not by provider. Days to pay comes from the receipts FinancePowerApp posted, so it is empty
        until a remittance has been posted against a claim. The
        monthly figures are by the date of the receivable item, the provider table by the month the journal was posted,
        so their totals can differ.
      </Notice>
    </>
  );
}
