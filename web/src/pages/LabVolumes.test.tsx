import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LabVolumeRow, Me } from '../api/types';
import { Layout } from '../components/Layout';
import { DashboardProvider } from '../state/Dashboard';
import { LabVolumes } from './LabVolumes';

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

const byMonth: LabVolumeRow[] = [
  { month: '2022-03-01', results: 15, visits: 14, abnormal: 3, critical: 1, turnaround_mean_days: 2 },
  { month: '2022-04-01', results: 9, visits: 9, abnormal: 3, critical: 0, turnaround_mean_days: 3 },
];
const byTest: LabVolumeRow[] = [
  { test_name: 'Glucose, fasting', loinc_code: '14771-0', results: 21, visits: 20, abnormal: 3, critical: 1, turnaround_mean_days: 2.29 },
];

function serve(me: Me, months: LabVolumeRow[]): ReturnType<typeof vi.fn> {
  const fetcher = vi.fn(async (input: string) => {
    const url = new URL(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    switch (url.pathname) {
      case '/api/me':
        return json(me);
      case '/api/finance/businesses':
        return json([{ code: 'HV', name: 'Harbourview', kind: 'Clinic', clinicSlug: 'harbourview' }]);
      case '/api/finance/range':
        return json({ firstMonth: '2023-10-01', lastMonth: '2026-10-01' });
      case '/api/operations/range':
        return json({ firstMonth: null, lastMonth: null });
      case '/api/operations/lab-volumes':
        return json(url.searchParams.get('groupBy') === 'test' ? byTest : months);
      default:
        return json([]);
    }
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}

const admin: Me = { name: 'A', clinicSlug: 'harbourview', permissions: ['analytics:group.view'], scope: 'group' };
const physician: Me = { name: 'P', clinicSlug: 'harbourview', permissions: ['analytics:dashboard.view'], scope: 'clinic' };

function renderIt() {
  return render(
    <MemoryRouter initialEntries={['/operations']}>
      <DashboardProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="operations" element={<><p>operations page</p><LabVolumes /></>} />
          </Route>
        </Routes>
      </DashboardProvider>
    </MemoryRouter>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe('the lab volumes cards', () => {
  it('show the warehouse totals to group users and say the months are shifted', async () => {
    serve(admin, byMonth);
    renderIt();
    expect(await screen.findByText('Lab volumes (LabFlow history)')).toBeInTheDocument();
    expect(screen.getByText(/shifted by up to 180 days/)).toBeInTheDocument();
    expect(screen.getByText('Lab volumes by test')).toBeInTheDocument();
  });

  it('are not shown, and not asked for, without the group permission', async () => {
    const fetcher = serve(physician, byMonth);
    renderIt();
    expect(await screen.findByText('operations page')).toBeInTheDocument();
    expect(screen.queryByText('Lab volumes (LabFlow history)')).toBeNull();
    expect(fetcher.mock.calls.some(([u]) => String(u).includes('lab-volumes'))).toBe(false);
  });

  it('are left out when LabFlow’s warehouse is not read', async () => {
    serve(admin, []);
    renderIt();
    expect(await screen.findByText('operations page')).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText('Lab volumes (LabFlow history)')).toBeNull();
  });
});
