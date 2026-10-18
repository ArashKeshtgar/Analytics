import type { ForecastSeries } from '../api/types';

export interface ForecastChart {
  months: string[];
  actual: (number | null)[];
  forecast: (number | null)[];
  lower: (number | null)[];
  upper: (number | null)[];
}

/**
 * The last `historyMonths` actual months followed by the forecast. The forecast line and its band
 * start at the last actual month (band width zero there), so the projection visibly continues the line.
 */
export function forecastChart(series: ForecastSeries, historyMonths = 24): ForecastChart {
  const history = series.history.slice(-historyMonths);
  const ahead = series.forecast;
  const months = [...history.map((h) => h.month), ...ahead.map((f) => f.month)];
  const last = history.length - 1;
  const lastValue = last >= 0 ? (history[last] as { revenue: number }).revenue : null;
  const joined = <T,>(pick: (f: (typeof ahead)[number]) => T): (T | number | null)[] =>
    ahead.length === 0
      ? history.map(() => null)
      : [...history.map((_, i) => (i === last ? lastValue : null)), ...ahead.map(pick)];
  return {
    months,
    actual: [...history.map((h) => h.revenue), ...ahead.map(() => null)],
    forecast: joined((f) => f.forecast),
    lower: joined((f) => f.lower),
    upper: joined((f) => f.upper),
  };
}

/** How a model is named on the page. */
export const MODEL_NAMES: Record<string, string> = {
  'seasonal-naive': 'Seasonal naive (same month last year)',
  ets: 'Exponential smoothing (ETS)',
  sarima: 'SARIMA',
  'gradient-boosting': 'Gradient boosting',
};

export const modelName = (id: string | null): string => (id == null ? '–' : (MODEL_NAMES[id] ?? id));
