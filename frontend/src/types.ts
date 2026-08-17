/**
 * Mirrors the FastAPI response models exactly (backend/app/api/routes/*).
 * Decimal fields come over the wire as strings (pydantic v2's default JSON
 * encoding for Decimal, which preserves precision a JS number would
 * silently round) — never parse them to `number` for display; only for
 * arithmetic you actually need.
 */

export type CorporateActionType =
  | "dividend_cash"
  | "bonus_issue"
  | "rights_issue"
  | "stock_split"
  | "consolidation"
  | "delisting"
  | "suspension";

export interface CorporateAction {
  id: number;
  ticker: string;
  ex_date: string;
  type: CorporateActionType;
  ratio: string | null;
  cash_amount: string | null;
  subscription_price: string | null;
  cum_rights_price: string | null;
  terp: string | null;
  source_url: string | null;
  notes: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
}

export type ProvenanceTier = "R" | "D" | "N" | "E" | "F" | "A" | "-";

export interface Fundamental {
  id: number;
  ticker: string;
  period_end: string;
  period_type: string;
  first_available_date: string;
  version: number;
  statement_line: string;
  value: string;
  currency: string;
  provenance_tier: ProvenanceTier;
  restated_flag: boolean;
  source_url: string | null;
  source_page: number | null;
  source_snippet: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
}

export interface IndexSnapshot {
  value: number | null;
  change: number | null;
  percentage: number | null;
  low: number | null;
  high: number | null;
}

export interface SectorSnapshot {
  name: string;
  symbol: string | null;
  index_value: number | null;
  change: number | null;
  percentage: number | null;
  turnover_today: number | null;
}

export interface UnavailableSection {
  section: string;
  reason: string;
}

export interface MarketOverview {
  status: string | null;
  aspi: IndexSnapshot | null;
  sectors: SectorSnapshot[];
  unavailable: UnavailableSection[];
  fetched_at: string;
  cached: boolean;
  source: string;
}

export interface SecurityListItem {
  ticker: string;
  name: string;
  instrument_type: string | null;
  issuer_code: string | null;
  cse_sector: string | null;
  archetype: string | null;
  last_close: string | null;
  last_price_date: string | null;
  turnover: string | null;
  volume: number | null;
  quarantined: boolean;
}

export interface PricePoint {
  date: string;
  close: string | null;
  open: string | null;
  high: string | null;
  low: string | null;
  volume: number | null;
  turnover: string | null;
  adj_factor: string;
}

export interface CorporateActionSummary {
  id: number;
  ex_date: string;
  type: string;
  confirmed: boolean;
  rejected: boolean;
}

export interface FundamentalSummary {
  id: number;
  period_end: string;
  period_type: string;
  statement_line: string;
  value: string;
  provenance_tier: ProvenanceTier;
  confirmed: boolean;
}

export interface Ratio {
  key: string;
  label: string;
  formula: string;
  unit: "percent" | "times" | string;
  value: string | null;
  provenance: ProvenanceTier | null;
  inputs_used: string[];
  missing_inputs: string[];
  note: string | null;
}

export interface UncomputableRatio {
  key: string;
  label: string;
  missing_inputs: string[];
}

export interface SecurityDetail {
  ticker: string;
  name: string;
  instrument_type: string | null;
  issuer_code: string | null;
  sibling_tickers: string[];
  isin: string | null;
  cse_sector: string | null;
  archetype: string | null;
  listing_date: string | null;
  delisting_date: string | null;
  fiscal_year_end: string | null;
  shares_issued: number | null;
  shares_issued_as_of: string | null;
  public_float_pct: string | null;
  quarantined: boolean;
  price_history: PricePoint[];
  corporate_actions: CorporateActionSummary[];
  fundamentals: FundamentalSummary[];
  ratio_period_end: string | null;
  ratios: Ratio[];
  ratios_not_yet_computable: UncomputableRatio[];
  not_yet_built: string[];
}

export interface QuarantinedTicker {
  ticker: string;
  alert_type: string;
  detail: string;
  raised_at: string;
}

export interface DataHealth {
  securities_count: number;
  issuer_count: number;
  registry_issuers: number;
  registry_delisted: number;
  registry_unknown_status: number;
  price_rows: number;
  latest_price_date: string | null;
  price_feed_age_days: number | null;
  securities_with_no_price: number;
  corporate_actions_total: number;
  corporate_actions_pending: number;
  corporate_actions_confirmed: number;
  corporate_actions_rejected: number;
  fundamentals_total: number;
  fundamentals_pending_confirmation: number;
  fundamentals_confirmed: number;
  quarantined: QuarantinedTicker[];
}

export interface SpreadPoint {
  obs_date: string;
  earnings_yield: string;
  tbill_yield: string;
  spread: string;
}

export interface Spread {
  available: boolean;
  missing: string[];
  obs_date: string | null;
  market_per: string | null;
  earnings_yield: string | null;
  tbill_yield: string | null;
  tbill_obs_date: string | null;
  tbill_source: string | null;
  spread: string | null;
  history: SpreadPoint[];
}

export interface IndexPoint {
  obs_date: string;
  value: string;
  source: string;
}

export interface IndexHistory {
  series_id: string;
  points: IndexPoint[];
  /** Rows whose close was reconstructed from the feed's percentage
   * change rather than read directly. The distinction is load-bearing:
   * the feed's raw level is NOT the close on ~38% of days. */
  recovered: number;
}
