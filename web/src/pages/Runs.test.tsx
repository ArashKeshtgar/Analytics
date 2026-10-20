import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Me, RunReport } from '../api/types';
import { Layout } from '../components/Layout';
import { DashboardProvider } from '../state/Dashboard';
import { Runs } from './Runs';

const auth = {
  status: 'signed-in' as const,
  error: null,
  name: 'Test User',
  accessToken: async () => 'tok',
  expired: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
};
vi.mock('../auth/AuthProvider', () => ({ useAuth: () => auth }));

const good: RunReport = {
  run_id: '20261020T215956Z',
  started_utc: '2026-10-20T21:59:56+00:00',
  finished_utc: '2026-10-20T22:01:01+00:00',
  status: 'warning',
  steps: [
    { name: 'prepare', status: 'ok', seconds: 0, detail: 'copied the live warehouse' },
    { name: 'extract', status: 'ok', seconds: 0.5, detail: '12 tables, 189 rows' },
  ],
  tables: [
    { name: 'raw.gl_journalentry', rows: 80, previous: 100 },
    { name: 'raw.gl_account', rows: 5, previous: null },
  ],
  checks: [{ level: 'warning', kind: 'row-drop', subject: 'raw.gl_journalentry', message: '100 rows last time, 80 now' }],
  warehouse_replaced: true,
  alert: '',
};
const failed: RunReport = {
  ...good,
  run_id: '20261021T035956Z',
  started_utc: '2026-10-21T03:59:56+00:00',
  finished_utc: '2026-10-21T04:00:01+00:00',
  status: 'failed',
  steps: [{ name: 'extract', status: 'failed', seconds: 0.2, detail: 'ConnectionError: the finance server did not answer' }],
  tables: [],
  checks: [{ level: 'error', kind: 'step', subject: 'extract', message: 'ConnectionError: the finance server did not answer' }],
  warehouse_replaced: false,
  alert: 'failed',
};

function serve(me: Me, runs: RunReport[]): ReturnType<typeof vi.fn> {
  const fetcher = vi.fn(async (input: string) => {
    const url = new URL(input);
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
    switch (url.pathname) {
      case '/api/me':
        return json(me);
      case '/api/finance/businesses':
        return json([{ code: 'HV', name: 'Harbourview', kind: 'Clinic', clinicSlug: 'harbourview' }]);
      case '/api/finance/range':
        return json({ firstMonth: '2023-10-01', lastMonth: '2026-10-01' });
      case '/api/operations/range':
        return json({ firstMonth: null, lastMonth: null });
      case '/api/meta/runs':
        return json(runs);
      default:
        return json([]);
    }
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}

const admin: Me = {
  name: 'A',
  clinicSlug: 'harbourview',
  permissions: ['analytics:dashboard.view', 'analytics:group.view'],
  scope: 'group',
};
const physician: Me = { name: 'P', clinicSlug: 'harbourview', permissions: ['analytics:dashboard.view'], scope: 'clinic' };

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <DashboardProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="runs" element={<Runs />} />
            <Route index element={<p>overview page</p>} />
          </Route>
        </Routes>
      </DashboardProvider>
    </MemoryRouter>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe('the Runs page', () => {
  it('is only in the menu for the group permission, and does not ask the API without it', async () => {
    const fetcher = serve(physician, [good]);
    renderAt('/');
    expect(await screen.findByText('overview page')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Runs' })).toBeNull();
    renderAt('/runs');
    expect(await screen.findByText(/for people with the group permission/)).toBeInTheDocument();
    expect(fetcher.mock.calls.some(([u]) => String(u).includes('/api/meta/runs'))).toBe(false);
  });

  it('lists the runs and shows steps, checks and tables of the latest', async () => {
    serve(admin, [good]);
    renderAt('/runs');
    expect(await screen.findByRole('link', { name: 'Runs' })).toBeInTheDocument();
    expect(await screen.findByText('Steps of the latest run (20261020T215956Z)')).toBeInTheDocument();
    expect(screen.getAllByText('▲ warning').length).toBeGreaterThan(0);
    expect(screen.getByText('copied the live warehouse')).toBeInTheDocument();
    expect(screen.getByText('100 rows last time, 80 now')).toBeInTheDocument();
    expect(screen.getByText('-20%')).toBeInTheDocument(); // 100 -> 80
    expect(screen.getByText('1 min 05 s')).toBeInTheDocument();
  });

  it('says a failed latest run left the dashboard on the last good data, and what the alert did', async () => {
    serve(admin, [failed, good]);
    renderAt('/runs');
    const notice = await screen.findByText(/The latest run failed; the dashboard still shows the data of the run on/);
    expect(notice).toBeInTheDocument();
    const table = screen.getAllByRole('table')[0] as HTMLElement; // the runs list comes first
    const rows = within(table).getAllByRole('row');
    expect(within(rows[1] as HTMLElement).getByText('✕ failed')).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText('failed', { selector: 'td' })).toBeInTheDocument();
    // Once as the step's detail and once as the check it raised.
    expect(screen.getAllByText('ConnectionError: the finance server did not answer', { selector: 'td' })).toHaveLength(2);
  });

  it('says so when there is no run yet', async () => {
    serve(admin, []);
    renderAt('/runs');
    expect(await screen.findByText(/No run yet/)).toBeInTheDocument();
  });
});
