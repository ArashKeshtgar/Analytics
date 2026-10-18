import { useState } from 'react';
import type { ForecastResponse, ForecastSeries } from '../api/types';
import { Card, Empty, Notice } from '../components/Card';
import { LineChart } from '../components/charts/LineChart';
import { StatTile } from '../components/StatTile';
import { forecastChart, modelName, shortModelName } from '../lib/forecast';
import { money, money2, monthLabel, monthShort } from '../lib/format';
import { useDashboard, useFinance } from '../state/Dashboard';

export const MODELS_VIEW = 'analytics:models.view';

const label = (s: ForecastSeries): string => `${s.business_name} · ${s.line_of_business}`;
const key = (s: ForecastSeries): string => `${s.business}|${s.line_of_business}`;
const number = (digits: number) => (v: unknown) => (typeof v === 'number' ? v.toFixed(digits) : '–');

export function Forecast() {
  const { me } = useDashboard();
  const allowed = me.permissions.includes(MODELS_VIEW);
  // Every series in scope: the page has its own picker, and the filter bar is not shown here.
  const answer = useFinance<ForecastResponse>('/api/models/revenue-forecast', { range: 'none', business: false });
  const [picked, setPicked] = useState<string | undefined>(undefined);
  if (!allowed) {
    return <Empty>Forecasts are for people with the models permission (analytics:models.view).</Empty>;
  }
  if (answer.error) return <p className="error">{answer.error}</p>;
  if (!answer.data) return <p className="empty">Loading…</p>;
  const { run, series } = answer.data;
  if (!run) {
    return (
      <Empty>
        No forecast yet: run <code>analytics score</code> after <code>analytics build</code>.
      </Empty>
    );
  }
  const ready = series.filter((s) => s.status === 'forecast');
  const short = series.filter((s) => s.status !== 'forecast');
  const current = series.find((s) => key(s) === picked) ?? ready[0] ?? series[0];
  if (!current) return <Empty>No revenue in the businesses you can see.</Empty>;

  const chart = forecastChart(current);
  const labels = chart.months.map(monthLabel);
  const chosen = current.backtests.find((b) => b.chosen);
  const baseline = current.backtests.find((b) => b.model === 'seasonal-naive');
  const total = current.forecast.reduce((a, f) => a + f.forecast, 0);
  const stale = answer.loading;

  return (
    <>
      <div className="filters" role="group" aria-label="Series">
        <label>
          Business and line of business
          <select value={key(current)} onChange={(e) => setPicked(e.target.value)}>
            {series.map((s) => (
              <option key={key(s)} value={key(s)}>
                {label(s)}
                {s.status === 'forecast' ? '' : ' (too short)'}
              </option>
            ))}
          </select>
        </label>
        <span className="card-sub">
          Models fitted on complete months up to {monthLabel(run.dataThrough)}
        </span>
      </div>
      {current.status === 'forecast' ? (
        <div className={`tiles${stale ? ' stale' : ''}`}>
          <StatTile label={`Forecast, ${monthLabel(current.forecast[0]?.month ?? run.dataThrough)}`} value={money(current.forecast[0]?.forecast)} />
          <StatTile label="Next 6 months" value={money(total)} />
          <StatTile label="Model" value={shortModelName(current.model)} />
          <StatTile label="Backtest MASE" value={number(2)(chosen?.mase)} />
        </div>
      ) : (
        <Notice>
          {label(current)} has {current.months} months of revenue; a forecast needs 18 (a year to learn the
          season from, and six months to check it against).
        </Notice>
      )}
      <Card
        title="Revenue and forecast"
        subtitle={
          current.status === 'forecast'
            ? 'Monthly revenue and the next six months; the band is how far off the model was in its backtest'
            : 'Monthly revenue'
        }
        stale={stale}
        chart={
          <LineChart
            categories={labels}
            axisLabels={chart.months.map(monthShort)}
            ariaLabel={`Revenue and forecast, ${label(current)}`}
            format={money}
            series={[
              { id: 'actual', label: 'Revenue', color: 'var(--series-1)', values: chart.actual },
              ...(current.status === 'forecast'
                ? [{ id: 'forecast', label: 'Forecast', color: 'var(--series-2)', values: chart.forecast, dashed: true }]
                : []),
            ]}
            band={
              current.status === 'forecast'
                ? { seriesId: 'forecast', label: 'Backtest band', lower: chart.lower, upper: chart.upper }
                : undefined
            }
          />
        }
        table={{
          csvName: `forecast-${current.business}-${current.line_of_business}-${run.dataThrough.slice(0, 7)}`,
          columns: [
            { key: 'month', label: 'Month' },
            { key: 'revenue', label: 'Revenue', numeric: true, format: money2 },
            { key: 'forecast', label: 'Forecast', numeric: true, format: money2 },
            { key: 'lower', label: 'Band, low', numeric: true, format: money2 },
            { key: 'upper', label: 'Band, high', numeric: true, format: money2 },
          ],
          rows: [
            ...current.history.map((h) => ({ month: monthLabel(h.month), revenue: h.revenue, forecast: null, lower: null, upper: null })),
            ...current.forecast.map((f) => ({
              month: monthLabel(f.month),
              revenue: null,
              forecast: f.forecast,
              lower: f.lower,
              upper: f.upper,
            })),
          ],
        }}
      />
      {current.status === 'forecast' && (
        <Card
          title="How each model did"
          subtitle={`Rolling-origin backtest: ${chosen?.origins ?? 0} forecasts of ${chosen?.horizon ?? 6} months each, ending at the latest months. MASE below 1 beats the same-month-last-year guess on the training months.`}
          stale={stale}
          table={{
            csvName: `backtest-${current.business}-${current.line_of_business}-${run.dataThrough.slice(0, 7)}`,
            columns: [
              { key: 'model', label: 'Model' },
              { key: 'mase', label: 'MASE', numeric: true, format: number(3) },
              { key: 'mape', label: 'MAPE', numeric: true, format: (v) => (typeof v === 'number' ? `${v.toFixed(1)}%` : '–') },
              { key: 'mae', label: 'Mean abs. error', numeric: true, format: money2 },
              { key: 'chosen', label: 'Chosen' },
            ],
            rows: current.backtests.map((b) => ({
              model: modelName(b.model),
              mase: b.mase,
              mape: b.mape,
              mae: b.mae,
              chosen: b.chosen ? 'Yes' : '',
            })),
          }}
        />
      )}
      {short.length > 0 && (
        <Card
          title="Not forecast yet"
          subtitle="Too little history: a forecast needs 18 complete months"
          table={{
            csvName: `forecast-too-short-${run.dataThrough.slice(0, 7)}`,
            columns: [
              { key: 'series', label: 'Business and line of business' },
              { key: 'months', label: 'Months of revenue', numeric: true },
            ],
            rows: short.map((s) => ({ series: label(s), months: s.months })),
          }}
        />
      )}
      <Notice>
        Each series is forecast by the model that did best in its backtest (lowest MASE); the same-month-last-year guess
        is kept unless another model is better than it
        {baseline && chosen && chosen.model !== baseline.model && baseline.mase != null && chosen.mase != null
          ? ` (here ${modelName(chosen.model)}: MASE ${chosen.mase.toFixed(2)} against ${baseline.mase.toFixed(2)})`
          : ''}
        . The band is rough: the 80th percentile of the model&apos;s backtest errors, not a probability. Monthly totals only:
        no patient, provider or journal line is in any model. Run {run.runId}.
      </Notice>
    </>
  );
}
