/** Response shapes of the Analytics API (src/analytics/api.py). Field names are the API's own. */

export interface Me {
  name: string | null;
  clinicSlug: string | null;
  permissions: string[];
  scope: 'group' | 'clinic' | 'none';
}

export interface Business {
  code: string;
  name: string;
  kind: string;
  clinicSlug: string | null;
}

export interface DataRange {
  firstMonth: string | null;
  lastMonth: string | null;
}

export interface RevenueRow {
  month?: string;
  business?: string;
  line_of_business?: string;
  provider?: string;
  revenue: number;
}

/** /api/finance/days-to-pay: days from the item date to each payment, by payer type and payment month. */
export interface DaysToPayRow {
  business: string;
  payer: string;
  month: string;
  payments: number;
  amount: number;
  /** Weighted by the amount paid. */
  mean_days: number | null;
  max_days: number;
}

export interface OhipRow {
  business: string;
  month: string;
  billed: number;
  paid: number;
  adjusted: number;
  outstanding: number;
  short_paid: number;
  refused: number;
  short_paid_rate: number | null;
  refused_rate: number | null;
}

export interface OhipProviderRow {
  provider: string;
  billed: number;
  short_paid: number;
  refused: number;
  short_paid_rate: number | null;
  refused_rate: number | null;
}

export interface AgingRow {
  business: string;
  party_type: string;
  aging_bucket: string;
  snapshot_date: string;
  balance: number;
  items: number;
}

export interface TurnaroundRow {
  month?: string;
  clinic?: string;
  department?: string;
  test?: string;
  priority?: string;
  placed: number;
  resulted: number;
  cancelled: number;
  pending: number;
  median_minutes: number | null;
  p90_minutes: number | null;
}

export interface CancellationRow {
  month: string;
  department: string;
  placed: number;
  cancelled: number;
  cancel_refused: number;
}

/** /api/operations/lab-volumes: LabFlow's warehouse totals, by month (date-shifted), test or payer. */
export interface LabVolumeRow {
  month?: string;
  test_name?: string;
  loinc_code?: string | null;
  payer_type?: string;
  results: number;
  visits: number;
  abnormal: number;
  critical: number;
  turnaround_mean_days: number | null;
}

export type HstMeasure = 'sales' | 'purchases' | 'tax_collected' | 'itc';

export interface HstRow {
  month: string;
  taxCode: string;
  taxName: string | null;
  ratePercent: number | null;
  measure: HstMeasure;
  amount: number;
}

/** /api/models/revenue-forecast: the latest `analytics score` run. */
export interface ForecastRun {
  runId: string;
  createdUtc: string;
  /** The last complete month the models saw. */
  dataThrough: string;
}

export interface Backtest {
  model: string;
  origins: number;
  horizon: number;
  mae: number | null;
  mape: number | null;
  mase: number | null;
  chosen: boolean;
}

export interface ForecastSeries {
  business: string;
  business_name: string;
  line_of_business: string;
  status: 'forecast' | 'too-short';
  model: string | null;
  months: number;
  first_month: string;
  backtests: Backtest[];
  history: { month: string; revenue: number }[];
  forecast: { month: string; forecast: number; lower: number; upper: number }[];
}

export interface ForecastResponse {
  run: ForecastRun | null;
  series: ForecastSeries[];
}

/** /api/meta/runs: one `analytics run` report, as written to data/runs/ (group users only). */
export interface RunReport {
  run_id: string;
  started_utc: string;
  finished_utc: string;
  status: 'ok' | 'warning' | 'failed' | 'running';
  steps: { name: string; status: 'ok' | 'skipped' | 'failed'; seconds: number; detail: string }[];
  tables: { name: string; rows: number; previous: number | null }[];
  checks: { level: 'warning' | 'error'; kind: string; subject: string; message: string }[];
  warehouse_replaced: boolean;
  /** What the alert webhook was told about the run: failed, recovered, or nothing. */
  alert?: string;
}

/** /api/finance/ohip-anomalies: a flagged provider-month and the numbers behind the flag. */
export interface OhipAnomaly {
  business: string;
  provider: string;
  month: string;
  measure: 'short_paid' | 'refused';
  billed: number;
  amount: number;
  rate: number;
  usual_rate: number;
  spread: number;
  /** Null when the earlier months never varied (then above_steady_history is true). */
  z: number | null;
  above_steady_history: boolean;
  history_months: number;
}
