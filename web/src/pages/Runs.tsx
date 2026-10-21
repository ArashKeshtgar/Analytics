import type { RunReport } from '../api/types';
import { useResource } from '../api/useResource';
import { Card, Empty, Notice } from '../components/Card';
import { StatTile } from '../components/StatTile';
import { useDashboard } from '../state/Dashboard';

const MARK = { ok: '● ok', warning: '▲ warning', failed: '✕ failed', running: '… running' } as const;

const status = (s: RunReport['status']): string => MARK[s] ?? s;

/** "2026-10-20T21:59:56+00:00" as the viewer's local date and time; the raw text if it is not a date. */
function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('en-CA', { dateStyle: 'medium', timeStyle: 'short' });
}

function took(r: RunReport): string {
  const seconds = Math.round((Date.parse(r.finished_utc) - Date.parse(r.started_utc)) / 1000);
  if (!Number.isFinite(seconds) || seconds < 0) return '–';
  return seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, '0')} s`;
}

export function Runs() {
  const { me, get } = useDashboard();
  const enabled = me.scope === 'group';
  const runs = useResource<RunReport[]>('runs', (signal) => get<RunReport[]>('/api/meta/runs', { limit: '50' }, signal), enabled);
  if (!enabled) {
    return <Empty>The run reports are for people with the group permission (analytics:group.view).</Empty>;
  }
  if (runs.error) return <p className="error">{runs.error}</p>;
  if (!runs.data) return <p className="empty">Loading…</p>;
  const rows = runs.data;
  const latest = rows[0];
  if (!latest) return <Empty>No run yet. `analytics run` or `analytics schedule` writes the first report.</Empty>;
  const lastGood = rows.find((r) => r.warehouse_replaced);
  const failedRecently = rows.filter((r) => r.status === 'failed').length;

  const runColumns = [
    { key: 'started', label: 'Started' },
    { key: 'status', label: 'Status' },
    { key: 'took', label: 'Took' },
    { key: 'rows', label: 'Rows', numeric: true },
    { key: 'checks', label: 'Checks', numeric: true },
    { key: 'told', label: 'Told' },
  ];
  const runRows = rows.map((r) => ({
    started: when(r.started_utc),
    status: status(r.status),
    took: took(r),
    rows: r.tables.reduce((a, t) => a + t.rows, 0),
    checks: r.checks.length,
    told: r.alert || '–',
  }));
  const stepRows = latest.steps.map((s) => ({ step: s.name, status: s.status, seconds: s.seconds, detail: s.detail }));
  const checkRows = latest.checks.map((c) => ({ level: c.level, kind: c.kind, subject: c.subject, message: c.message }));
  const tableRows = latest.tables.map((t) => ({
    table: t.name,
    rows: t.rows,
    previous: t.previous,
    change: t.previous ? (t.rows - t.previous) / t.previous : null,
  }));

  return (
    <>
      <div className="tiles">
        <StatTile label="Latest run" value={status(latest.status)} />
        <StatTile label="Started" value={when(latest.started_utc)} />
        <StatTile label="Dashboard reads" value={lastGood ? when(lastGood.started_utc) : 'no good run yet'} />
        <StatTile label={`Failed of the last ${rows.length}`} value={String(failedRecently)} />
      </div>
      {latest.status === 'failed' && (
        <Notice>
          The latest run failed; the dashboard still shows the data of the run on {lastGood ? when(lastGood.started_utc) : 'no date (none yet)'}.
        </Notice>
      )}
      <Card
        title="Runs"
        subtitle="Newest first. “Told” is what the alert webhook was sent about the run."
        table={{ columns: runColumns, rows: runRows, csvName: 'analytics-runs' }}
      />
      <Card
        title={`Steps of the latest run (${latest.run_id})`}
        table={{
          columns: [
            { key: 'step', label: 'Step' },
            { key: 'status', label: 'Status' },
            { key: 'seconds', label: 'Seconds', numeric: true, format: (v) => v.toFixed(1) },
            { key: 'detail', label: 'Detail' },
          ],
          rows: stepRows,
          csvName: 'analytics-run-steps',
        }}
      />
      {checkRows.length > 0 && (
        <Card
          title="Checks of the latest run"
          subtitle="Failed dbt tests and models, tables that emptied or shrank, steps that failed."
          table={{
            columns: [
              { key: 'level', label: 'Level' },
              { key: 'kind', label: 'Kind' },
              { key: 'subject', label: 'Subject' },
              { key: 'message', label: 'Message' },
            ],
            rows: checkRows,
            csvName: 'analytics-run-checks',
          }}
        />
      )}
      {tableRows.length > 0 && (
        <Card
          title="Tables of the latest run"
          subtitle="Rows now against the last run the dashboard read."
          table={{
            columns: [
              { key: 'table', label: 'Table' },
              { key: 'rows', label: 'Rows', numeric: true },
              { key: 'previous', label: 'Before', numeric: true },
              { key: 'change', label: 'Change', numeric: true, format: (v) => `${v > 0 ? '+' : ''}${(v * 100).toFixed(0)}%` },
            ],
            rows: tableRows,
            csvName: 'analytics-run-tables',
          }}
        />
      )}
    </>
  );
}
