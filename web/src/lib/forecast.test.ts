import { describe, expect, it } from 'vitest';
import type { ForecastSeries } from '../api/types';
import { forecastChart, modelName, shortModelName } from './forecast';

const series = (history: number, ahead: number): ForecastSeries => ({
  business: 'HV',
  business_name: 'Harbourview',
  line_of_business: 'Clinic',
  status: ahead ? 'forecast' : 'too-short',
  model: ahead ? 'ets' : null,
  months: history,
  first_month: '2024-01-01',
  backtests: [],
  history: Array.from({ length: history }, (_, i) => ({
    month: `20${24 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}-01`,
    revenue: 100 + i,
  })),
  forecast: Array.from({ length: ahead }, (_, i) => ({
    month: `2099-${String(i + 1).padStart(2, '0')}-01`,
    forecast: 500 + i,
    lower: 400 + i,
    upper: 600 + i,
  })),
});

describe('forecastChart', () => {
  it('keeps the last months of history and joins the forecast at the last actual month', () => {
    const chart = forecastChart(series(30, 6), 24);
    expect(chart.months).toHaveLength(30);
    expect(chart.months[0]).toBe('2024-07-01');
    expect(chart.actual[23]).toBe(129);
    expect(chart.actual[24]).toBeNull();
    expect(chart.forecast.slice(22, 25)).toEqual([null, 129, 500]);
    expect([chart.lower[23], chart.upper[23]]).toEqual([129, 129]);
    expect(chart.upper[29]).toBe(605);
  });

  it('has no forecast line for a series that is too short', () => {
    const chart = forecastChart(series(10, 0));
    expect(chart.months).toHaveLength(10);
    expect(chart.forecast.every((v) => v === null)).toBe(true);
  });

  it('names the models', () => {
    expect(modelName('seasonal-naive')).toMatch(/same month last year/);
    expect(modelName(null)).toBe('–');
    expect(modelName('other')).toBe('other');
    expect(shortModelName('gradient-boosting')).toBe('Gradient boosting');
    expect(shortModelName('ets')).toBe('ETS');
  });
});
