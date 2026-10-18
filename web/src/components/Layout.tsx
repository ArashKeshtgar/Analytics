import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';
import { monthLabel } from '../lib/format';
import { PRESETS } from '../lib/periods';
import { MODELS_VIEW } from '../pages/Forecast';
import { useDashboard } from '../state/Dashboard';

type Theme = 'system' | 'light' | 'dark';
const NEXT: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' };

function readTheme(): Theme {
  try {
    const stored = window.localStorage.getItem('analytics.theme');
    return stored === 'light' || stored === 'dark' ? stored : 'system';
  } catch {
    return 'system';
  }
}

function applyTheme(theme: Theme): void {
  if (theme === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
  try {
    window.localStorage.setItem('analytics.theme', theme);
  } catch {
    // storage blocked: the choice only lasts for this page
  }
}

import { useState } from 'react';

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => {
    const t = readTheme();
    applyTheme(t);
    return t;
  });
  return (
    <button
      type="button"
      className="btn"
      aria-label={`Theme: ${theme}. Switch to ${NEXT[theme]}`}
      onClick={() => {
        const next = NEXT[theme];
        applyTheme(next);
        setTheme(next);
      }}
    >
      Theme: {theme}
    </button>
  );
}

function FilterBar() {
  const { preset, setPreset, business, setBusiness, businesses, me, lastMonth } = useDashboard();
  const { pathname } = useLocation();
  const showBusiness = me.scope === 'group' && pathname !== '/group' && businesses.length > 1;
  // The forecast has its own months (the models' history and the six ahead): the presets do not apply.
  const showPresets = pathname !== '/forecast';
  return (
    <div className="filters" role="group" aria-label="Filters">
      {showPresets && (
        <div className="presets">
          {PRESETS.map((p) => (
            <button key={p.id} type="button" className="btn" aria-pressed={preset === p.id} onClick={() => setPreset(p.id)}>
              {p.label}
            </button>
          ))}
        </div>
      )}
      {showBusiness && (
        <label>
          Business
          <select value={business ?? ''} onChange={(e) => setBusiness(e.target.value || undefined)}>
            <option value="">All businesses</option>
            {businesses.map((b) => (
              <option key={b.code} value={b.code}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <span className="card-sub">Data up to {monthLabel(lastMonth)}</span>
    </div>
  );
}

export function Layout() {
  const auth = useAuth();
  const { me } = useDashboard();
  const links = [
    { to: '/', label: 'Overview', end: true },
    { to: '/ohip', label: 'OHIP' },
    { to: '/receivables', label: 'Receivables' },
    { to: '/hst', label: 'HST' },
    { to: '/operations', label: 'Operations' },
    ...(me.scope === 'group' ? [{ to: '/group', label: 'Group' }] : []),
    ...(me.permissions.includes(MODELS_VIEW) ? [{ to: '/forecast', label: 'Forecast' }] : []),
  ];
  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="header-top">
            <span className="brand">Analytics</span>
            <span className="who">{me.name ?? auth.name ?? ''}{me.scope === 'clinic' && me.clinicSlug ? ` · ${me.clinicSlug}` : ''}</span>
            <ThemeToggle />
            <button type="button" className="btn" onClick={() => auth.signOut()}>
              Sign out
            </button>
          </div>
          <nav className="nav" aria-label="Pages">
            {links.map((l) => (
              <NavLink key={l.to} to={l.to} end={l.end}>
                {l.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="main">
        <FilterBar />
        <Outlet />
      </main>
    </div>
  );
}
