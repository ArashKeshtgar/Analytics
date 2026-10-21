import type { LabVolumeRow } from '../api/types';
import { useResource } from '../api/useResource';
import { Card } from '../components/Card';
import { ColumnChart } from '../components/charts/ColumnChart';
import { monthLabel, monthShort, percent } from '../lib/format';
import { useDashboard } from '../state/Dashboard';

const count = (v: number): string => String(v);
const days = (v: number): string => `${v.toFixed(1)} d`;

/**
 * The legacy lab's history from LabFlow's warehouse (group users only). Not filtered by the dashboard's months: its
 * dates are shifted by up to 180 days to de-identify it, so they do not line up with the rest of the page.
 */
export function LabVolumes() {
  const { me, get } = useDashboard();
  const enabled = me.scope === 'group';
  const path = '/api/operations/lab-volumes';
  const months = useResource<LabVolumeRow[]>('lab-months', (s) => get<LabVolumeRow[]>(path, { groupBy: 'month' }, s), enabled);
  const tests = useResource<LabVolumeRow[]>('lab-tests', (s) => get<LabVolumeRow[]>(path, { groupBy: 'test' }, s), enabled);
  if (!enabled || !months.data || !tests.data || months.data.length === 0) return null;
  const monthRows = months.data;
  const keys = monthRows.map((m) => m.month ?? '');
  const columns = [
    { key: 'results', label: 'Results', numeric: true },
    { key: 'visits', label: 'Visits', numeric: true },
    { key: 'abnormal', label: 'Abnormal share', numeric: true, format: (v: number) => percent(v) },
    { key: 'critical', label: 'Critical', numeric: true },
    { key: 'turnaround', label: 'Mean turnaround', numeric: true, format: days },
  ];
  const row = (r: LabVolumeRow) => ({
    results: r.results,
    visits: r.visits,
    abnormal: r.results > 0 ? r.abnormal / r.results : null,
    critical: r.critical,
    turnaround: r.turnaround_mean_days,
  });
  return (
    <div className="grid-2">
      <Card
        title="Lab volumes (LabFlow history)"
        subtitle="The legacy lab's results from LabFlow's warehouse. Months are shifted by up to 180 days to de-identify it."
        chart={
          <ColumnChart
            categories={keys.map(monthLabel)}
            axisLabels={keys.map(monthShort)}
            ariaLabel="Lab results by month (date-shifted)"
            format={count}
            tickFormat={count}
            axis="integer"
            series={[{ id: 'results', label: 'Results', color: 'var(--series-1)', values: monthRows.map((m) => m.results) }]}
          />
        }
        table={{
          csvName: 'lab-volumes-by-month',
          columns: [{ key: 'month', label: 'Month (shifted)' }, ...columns],
          rows: monthRows.map((m) => ({ month: monthLabel(m.month ?? ''), ...row(m) })),
        }}
      />
      <Card
        title="Lab volumes by test"
        subtitle="Most requested first"
        table={{
          csvName: 'lab-volumes-by-test',
          columns: [{ key: 'test', label: 'Test' }, { key: 'loinc', label: 'LOINC' }, ...columns],
          rows: tests.data.slice(0, 25).map((t) => ({ test: t.test_name ?? '', loinc: t.loinc_code ?? '', ...row(t) })),
        }}
      />
    </div>
  );
}
