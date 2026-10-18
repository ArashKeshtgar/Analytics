import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Me } from '../api/types';
import { Layout } from '../components/Layout';
import { Ohip } from '../pages/Ohip';
import { Receivables } from '../pages/Receivables';
import { DashboardProvider } from './Dashboard';

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

interface World {
  me: Me | { status: number; detail: string };
  lastMonth: string | null;
}
const businesses = [
  { code: 'HV', name: 'Harbourview Clinic', kind: 'Clinic', clinicSlug: 'harbourview' },
  { code: 'LAB', name: 'Group Lab', kind: 'Lab', clinicSlug: null },
];
let calls: URL[] = [];

function serve(world: World): void {
  calls = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string) => {
      const url = new URL(input);
      calls.push(url);
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
      switch (url.pathname) {
        case '/api/me':
          return 'status' in world.me ? json({ detail: world.me.detail }, world.me.status) : json(world.me);
        case '/api/finance/businesses':
          return json(businesses);
        case '/api/finance/range':
          return json({ firstMonth: world.lastMonth && '2025-10-01', lastMonth: world.lastMonth });
        default:
          return json([]);
      }
    }),
  );
}

const group: Me = { name: 'G', clinicSlug: null, permissions: ['analytics:group.view'], scope: 'group' };
const clinic: Me = { name: 'C', clinicSlug: 'harbourview', permissions: ['analytics:dashboard.view'], scope: 'clinic' };

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <DashboardProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="ohip" element={<Ohip />} />
            <Route path="receivables" element={<Receivables />} />
            <Route index element={<p>overview page</p>} />
          </Route>
        </Routes>
      </DashboardProvider>
    </MemoryRouter>,
  );
}

const callsTo = (path: string): URL[] => calls.filter((u) => u.pathname === path);
const lastCall = (path: string): URL => callsTo(path).at(-1) as URL;

beforeEach(() => auth.expired.mockClear());
afterEach(() => vi.unstubAllGlobals());

describe('what each kind of user sees', () => {
  it('a group user has the Group page and the business filter', async () => {
    serve({ me: group, lastMonth: '2026-10-01' });
    renderAt('/');
    expect(await screen.findByRole('link', { name: 'Group' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Business' })).toBeInTheDocument();
    expect(screen.getByText('Books up to Oct 2026')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Group Lab' })).toBeInTheDocument();
  });

  it('a clinic user has neither, and their clinic is in the header', async () => {
    serve({ me: clinic, lastMonth: '2026-10-01' });
    renderAt('/');
    expect(await screen.findByText('overview page')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Group' })).toBeNull();
    expect(screen.queryByRole('combobox', { name: 'Business' })).toBeNull();
    expect(screen.getByText(/C · harbourview/)).toBeInTheDocument();
  });

  it('a user with no Analytics permission is told so, and nothing else is requested', async () => {
    serve({ me: { ...clinic, permissions: [], scope: 'none' }, lastMonth: '2026-10-01' });
    renderAt('/');
    expect(await screen.findByText('No access to Analytics')).toBeInTheDocument();
    expect(callsTo('/api/finance/range')).toHaveLength(0);
    expect(callsTo('/api/finance/businesses')).toHaveLength(0);
  });

  it('says what to do when the warehouse has no revenue yet', async () => {
    serve({ me: group, lastMonth: null });
    renderAt('/');
    expect(await screen.findByText('No finance data yet')).toBeInTheDocument();
  });

  it('shows the API’s own message when it cannot answer', async () => {
    serve({ me: { status: 503, detail: 'The warehouse is not built yet. Run `analytics build`.' }, lastMonth: null });
    renderAt('/');
    expect(await screen.findByText('The warehouse is not built yet. Run `analytics build`.')).toBeInTheDocument();
  });
});

describe('the filter row scopes every request', () => {
  it('counts the presets back from the latest month with data', async () => {
    serve({ me: group, lastMonth: '2026-10-01' });
    renderAt('/ohip');
    await waitFor(() => expect(callsTo('/api/finance/ohip-collection')).not.toHaveLength(0));
    expect(Object.fromEntries(lastCall('/api/finance/ohip-collection').searchParams)).toEqual({ from: '2025-11-01', to: '2026-10-01' });

    await userEvent.click(screen.getByRole('button', { name: 'Last 3 months' }));
    await waitFor(() => expect(lastCall('/api/finance/ohip-collection').searchParams.get('from')).toBe('2026-08-01'));
    expect(lastCall('/api/finance/ohip-providers').searchParams.get('from')).toBe('2026-08-01');

    await userEvent.click(screen.getByRole('button', { name: 'Year to date' }));
    await waitFor(() => expect(lastCall('/api/finance/ohip-collection').searchParams.get('from')).toBe('2026-01-01'));

    await userEvent.click(screen.getByRole('button', { name: 'Last year' }));
    await waitFor(() => expect(lastCall('/api/finance/ohip-collection').searchParams.get('to')).toBe('2025-12-01'));
  });

  it('passes the chosen business to every query and not before', async () => {
    serve({ me: group, lastMonth: '2026-10-01' });
    renderAt('/ohip');
    await waitFor(() => expect(callsTo('/api/finance/ohip-collection')).not.toHaveLength(0));
    expect(lastCall('/api/finance/ohip-collection').searchParams.has('business')).toBe(false);

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Business' }), 'LAB');
    await waitFor(() => expect(lastCall('/api/finance/ohip-collection').searchParams.get('business')).toBe('LAB'));
    expect(lastCall('/api/finance/ohip-providers').searchParams.get('business')).toBe('LAB');
  });

  it('asks for ageing up to the LAST DAY of the last month, not its first (a bug seen in the browser)', async () => {
    serve({ me: group, lastMonth: '2026-10-01' });
    renderAt('/receivables');
    await waitFor(() => expect(callsTo('/api/finance/aging')).not.toHaveLength(0));
    const first = lastCall('/api/finance/aging').searchParams;
    expect(first.get('asOf')).toBe('2026-10-31');
    expect(first.has('from')).toBe(false);
    expect(first.get('side')).toBe('receivable');

    await userEvent.click(screen.getByRole('button', { name: 'Last year' }));
    await waitFor(() => expect(lastCall('/api/finance/aging').searchParams.get('asOf')).toBe('2025-12-31'));

    await userEvent.click(screen.getByRole('button', { name: 'Payables' }));
    await waitFor(() => expect(lastCall('/api/finance/aging').searchParams.get('side')).toBe('payable'));
  });
});
