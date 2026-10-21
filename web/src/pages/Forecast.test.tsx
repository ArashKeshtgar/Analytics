import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ForecastResponse, ForecastSeries, Me, OhipAnomaly } from '../api/types';
import { Layout } from '../components/Layout';
import { DashboardProvider } from '../state/Dashboard';
import { Forecast } from './Forecast';
import { Ohip } from './Ohip';

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

const month = (i: number): string => {
  const index = 2023 * 12 + 9 + i; // Oct 2023 onwards
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, '0')}-01`;
};

const clinicSeries: ForecastSeries = {
  business: 'HV',
  business_name: 'Harbourview',
  line_of_business: 'Clinic',
  status: 'forecast',
  model: 'ets',
  months: 36,
  first_month: month(0),
  backtests: [
    { model: 'ets', origins: 6, horizon: 6, mae: 410.5, mape: 2.1, mase: 0.412, chosen: true },
    { model: 'seasonal-naive', origins: 6, horizon: 6, mae: 990.0, mape: 5.0, mase: 1.0, chosen: false },
  ],
  history: Array.from({ length: 36 }, (_, i) => ({ month: month(i), revenue: 20000 + 100 * i })),
  forecast: Array.from({ length: 6 }, (_, i) => ({
    month: month(36 + i),
    forecast: 23700 + 100 * i,
    lower: 23000 + 100 * i,
    upper: 24400 + 100 * i,
  })),
};
const pharmacy: ForecastSeries = {
  ...clinicSeries,
  line_of_business: 'Pharmacy',
  status: 'too-short',
  model: null,
  months: 10,
  backtests: [],
  history: clinicSeries.history.slice(-10),
  forecast: [],
};
const forecast: ForecastResponse = {
  run: { runId: '20261016T030000Z', createdUtc: '2026-10-16T03:00:00', dataThrough: month(35) },
  series: [clinicSeries, pharmacy],
};
const anomaly: OhipAnomaly = {
  business: 'HV',
  provider: '123456',
  month: '2026-09-01',
  measure: 'short_paid',
  billed: 10000,
  amount: 1000,
  rate: 0.1,
  usual_rate: 0.0125,
  spread: 0.0015,
  z: 39.3,
  above_steady_history: false,
  history_months: 8,
};

function serve(me: Me, answers: { forecast?: ForecastResponse; anomalies?: OhipAnomaly[] }): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string) => {
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
        case '/api/models/revenue-forecast':
          return json(answers.forecast ?? { run: null, series: [] });
        case '/api/finance/ohip-providers':
          return json([{ provider: '123456', billed: 10000, short_paid: 1000, refused: 0, short_paid_rate: 0.1, refused_rate: 0 }]);
        case '/api/finance/ohip-anomalies':
          return json(answers.anomalies ?? []);
        default:
          return json([]);
      }
    }),
  );
}

const admin: Me = {
  name: 'A',
  clinicSlug: 'harbourview',
  permissions: ['analytics:dashboard.view', 'analytics:group.view', 'analytics:models.view'],
  scope: 'group',
};
const physician: Me = { name: 'P', clinicSlug: 'harbourview', permissions: ['analytics:dashboard.view'], scope: 'clinic' };

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <DashboardProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="forecast" element={<Forecast />} />
            <Route path="ohip" element={<Ohip />} />
            <Route index element={<p>overview page</p>} />
          </Route>
        </Routes>
      </DashboardProvider>
    </MemoryRouter>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe('the Forecast page', () => {
  it('is only in the menu with the models permission', async () => {
    serve(physician, {});
    renderAt('/');
    expect(await screen.findByText('overview page')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Forecast' })).toBeNull();
  });

  it('tells someone without the permission instead of asking the API', async () => {
    serve(physician, { forecast });
    renderAt('/forecast');
    expect(await screen.findByText(/models permission/)).toBeInTheDocument();
  });

  it('shows the chosen model, the forecast and every model’s backtest', async () => {
    serve(admin, { forecast });
    renderAt('/forecast');
    expect(await screen.findByRole('link', { name: 'Forecast' })).toBeInTheDocument();
    expect(await screen.findByText('Revenue and forecast')).toBeInTheDocument();
    expect(screen.getAllByText('Exponential smoothing (ETS)').length).toBeGreaterThan(0);
    expect(screen.getByText('0.41')).toBeInTheDocument(); // the tile: MASE of the chosen model
    expect(screen.getByText(/MASE 0.41 against 1.00/)).toBeInTheDocument();
    // The presets do not apply to a forecast.
    expect(screen.queryByRole('button', { name: 'Last 12 months' })).toBeNull();
    const backtest = screen.getByText('How each model did').closest('section') as HTMLElement;
    const rows = within(backtest).getAllByRole('row');
    expect(rows.map((r) => r.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining('Seasonal naive'), expect.stringContaining('Yes')]),
    );
    expect(screen.getByText('Not forecast yet')).toBeInTheDocument();
  });

  it('explains a series that is too short', async () => {
    serve(admin, { forecast });
    renderAt('/forecast');
    const select = await screen.findByRole('combobox', { name: 'Business and line of business' });
    await userEvent.selectOptions(select, 'HV|Pharmacy');
    expect(await screen.findByText(/has 10 months of revenue; a forecast needs 18/)).toBeInTheDocument();
    expect(screen.queryByText('How each model did')).toBeNull();
  });

  it('says what to run before the first forecast', async () => {
    serve(admin, {});
    renderAt('/forecast');
    expect(await screen.findByText(/No forecast yet/)).toBeInTheDocument();
  });
});

describe('unusual months on the OHIP page', () => {
  it('lists a flagged provider-month with the numbers behind it', async () => {
    serve(physician, { anomalies: [anomaly] });
    renderAt('/ohip');
    const card = (await screen.findByText('Unusual months')).closest('section') as HTMLElement;
    const row = within(card).getByRole('row', { name: /123456/ });
    expect(row).toHaveTextContent('Short-paid');
    expect(row).toHaveTextContent('10.0%');
    expect(row).toHaveTextContent('1.3%');
    expect(row).toHaveTextContent('39.3');
  });

  it('says how a month would be flagged when none is', async () => {
    serve(physician, { anomalies: [] });
    renderAt('/ohip');
    expect(await screen.findByText(/No provider-month stands out/)).toBeInTheDocument();
  });
});
