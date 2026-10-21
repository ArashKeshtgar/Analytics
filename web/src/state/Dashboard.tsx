import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from 'react';
import { apiGet, type Params } from '../api/client';
import type { Business, DataRange, Me } from '../api/types';
import { type Resource, useResource } from '../api/useResource';
import { useAuth } from '../auth/AuthProvider';
import { endOfMonth, type Preset, rangeFor } from '../lib/periods';

export interface Range {
  from: string;
  to: string;
}

interface DashboardValue {
  me: Me;
  businesses: Business[];
  /** The latest month with finance or operations data in the caller's scope; presets count back from it. */
  lastMonth: string;
  preset: Preset;
  setPreset(preset: Preset): void;
  /** Business code, or undefined for all the caller may see. */
  business: string | undefined;
  setBusiness(code: string | undefined): void;
  range: Range;
  get<T>(path: string, params?: Params, signal?: AbortSignal): Promise<T>;
}

const Context = createContext<DashboardValue | null>(null);

export function useDashboard(): DashboardValue {
  const value = useContext(Context);
  if (!value) throw new Error('useDashboard outside DashboardProvider');
  return value;
}

/** A finance query scoped by the filter row. The answer is replaced when the filters change. */
export function useFinance<T>(
  path: string,
  options: { params?: Params; business?: boolean; range?: 'both' | 'asOf' | 'none'; from?: string } = {},
): Resource<T> {
  const { get, range, business } = useDashboard();
  const params: Params = { ...options.params };
  if (options.business !== false && business) params.business = business;
  if ((options.range ?? 'both') === 'both') {
    params.from = options.from ?? range.from;
    params.to = range.to;
  } else if (options.range === 'asOf') {
    // The last day of the last month of the range: 'up to October' includes the whole of October.
    params.asOf = endOfMonth(range.to);
  }
  const key = `${path}?${new URLSearchParams(params as Record<string, string>).toString()}`;
  return useResource<T>(key, (signal) => get<T>(path, params, signal));
}

/**
 * An operations query (IntegrationHub's events) scoped by the filter row. The business filter is by
 * business code; events know clinics, so it is turned into the clinic slug, and a business with no
 * clinic (the lab) matches nothing.
 */
export function useOps<T>(
  path: string,
  options: { params?: Params; department?: string } = {},
): Resource<T> {
  const { get, range, business, businesses } = useDashboard();
  const params: Params = { ...options.params, from: range.from, to: range.to };
  if (business) params.clinic = businesses.find((b) => b.code === business)?.clinicSlug ?? '-';
  if (options.department) params.department = options.department;
  const key = `${path}?${new URLSearchParams(params as Record<string, string>).toString()}`;
  return useResource<T>(key, (signal) => get<T>(path, params, signal));
}

function Message({ children }: { children: ReactNode }) {
  return <div className="center">{children}</div>;
}

export function DashboardProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const get = useCallback(<T,>(path: string, params?: Params, signal?: AbortSignal) => apiGet<T>(auth, path, params, signal), [auth]);
  const me = useResource<Me>('me', (signal) => get<Me>('/api/me', {}, signal));
  const allowed = me.data !== undefined && me.data.scope !== 'none';
  const businesses = useResource<Business[]>('businesses', (signal) => get<Business[]>('/api/finance/businesses', {}, signal), allowed);
  const bounds = useResource<DataRange>('range', (signal) => get<DataRange>('/api/finance/range', {}, signal), allowed);
  const opsBounds = useResource<DataRange>('opsRange', (signal) => get<DataRange>('/api/operations/range', {}, signal), allowed);
  const [preset, setPreset] = useState<Preset>('last12');
  const [business, setBusiness] = useState<string | undefined>(undefined);

  const financeLast = bounds.data?.lastMonth ?? null;
  const opsLast = opsBounds.data?.lastMonth ?? null;
  const lastMonth = financeLast && opsLast && opsLast > financeLast ? opsLast : financeLast;
  const range = useMemo(() => (lastMonth ? rangeFor(preset, lastMonth) : null), [preset, lastMonth]);

  if (me.error) return <Message><p className="error">{me.error}</p></Message>;
  if (!me.data) return <Message><p>Loading…</p></Message>;
  if (me.data.scope === 'none') {
    return (
      <Message>
        <h1>No access to Analytics</h1>
        <p>Your account has no Analytics permission. Ask an administrator for analytics:dashboard.view.</p>
        <button type="button" className="btn" onClick={() => auth.signOut()}>Sign out</button>
      </Message>
    );
  }
  const failed = bounds.error ?? businesses.error ?? opsBounds.error;
  if (failed) return <Message><p className="error">{failed}</p></Message>;
  if (!bounds.data || !businesses.data || !opsBounds.data) return <Message><p>Loading…</p></Message>;
  if (!lastMonth || !range) {
    return (
      <Message>
        <h1>No finance data yet</h1>
        <p>Run <code>analytics extract finance</code> and then <code>analytics build</code>.</p>
      </Message>
    );
  }
  const value: DashboardValue = {
    me: me.data,
    businesses: businesses.data,
    lastMonth,
    preset,
    setPreset,
    business,
    setBusiness,
    range,
    get,
  };
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
