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

export type HstMeasure = 'sales' | 'purchases' | 'tax_collected' | 'itc';

export interface HstRow {
  month: string;
  taxCode: string;
  taxName: string | null;
  ratePercent: number | null;
  measure: HstMeasure;
  amount: number;
}
