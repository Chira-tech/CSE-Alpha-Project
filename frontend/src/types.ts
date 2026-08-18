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
  return_on_equity: string | null;
  return_on_equity_provenance: ProvenanceTier | null;
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

export interface RatioTrend {
  ratio_key: string;
  direction: "increasing" | "decreasing" | "no_trend" | "insufficient_history";
  significant: boolean;
  accelerating: boolean | null;
  fraction_same_direction: string | null;
  periods_used: number;
  first_period: string | null;
  last_period: string | null;
}

export interface Suppression {
  model: string;
  reason: string;
}

export interface UnansweredQuestion {
  question: string;
  missing_input: string;
}

export interface CostOfEquity {
  ke: string | null;
  risk_free_rate: string | null;
  beta: string | null;
  erp_effective: string;
  beta_times_erp: string | null;
  size_premium: string | null;
  illiquidity_premium: string | null;
  implied_erp_cross_check: string | null;
  is_lower_bound: boolean;
  missing_components: string[];
  note: string;
}

export interface ValuationRouting {
  in_published_table: boolean;
  primary_models: string[];
  suppressed: Suppression[];
  meaningless_metrics: string[];
  requires_earnings_normalisation: boolean;
  is_financial_firm: boolean;
  is_holding_company: boolean;
  note: string;
  unanswered_questions: UnansweredQuestion[];
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
  ratio_trends: RatioTrend[];
  valuation_routing: ValuationRouting;
  cost_of_equity: CostOfEquity;
  not_yet_built: string[];
}

export interface ValuationAnchorCategory {
  triangulation_category: string | null;
  anchors: never[];
  missing_categories: string[];
  blended_fair_value_per_share: string | null;
  dispersion_pct: string | null;
  warnings: string[];
}

export interface MarginOfSafetyOut {
  base_pct: string;
  dispersion_pct: string | null;
  liquidity_pct: string | null;
  regime_pct: string | null;
  quality_integrity_pct: string | null;
  data_completeness_pct: string | null;
  total_pct: string;
  is_lower_bound: boolean;
  missing_components: string[];
  note: string;
}

export interface PriceLadderOut {
  fair_value: string;
  margin_of_safety_pct: string;
  strong_accumulate_threshold: string;
  buy_below_price: string;
  trim_threshold: string;
  exit_threshold: string;
  current_price: string | null;
  current_zone: "strong_accumulate" | "accumulate" | "fair" | "trim" | "exit" | null;
  zone_meaning: string | null;
  gap_to_buy_below_pct: string | null;
}

export interface CompanyValuation {
  ticker: string;
  as_of: string;
  current_price: string | null;
  routing: {
    archetype: string | null;
    in_published_table: boolean;
    primary_models: string[];
    note: string;
  };
  justified_price_to_book_fair_value: string | null;
  justified_price_to_book_warnings: string[];
  residual_income_fair_value: string | null;
  residual_income_warnings: string[];
  triangulation: ValuationAnchorCategory;
  margin_of_safety: MarginOfSafetyOut;
  price_ladder: PriceLadderOut | null;
  note: string;
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

export interface PortfolioPosition {
  ticker: string;
  quantity: string;
  avg_price: string;
  total_cost: string;
  traded_price: string | null;
  market_value: string | null;
  unrealized_gain_loss: string | null;
}

export interface PortfolioSnapshotSummary {
  id: number;
  uploaded_at: string;
  source_filename: string;
  position_count: number;
  stated_total_cost: string | null;
  stated_total_market_value: string | null;
  identity_check_passed: boolean;
  identity_check_note: string;
}

export interface PortfolioSnapshotDetail extends PortfolioSnapshotSummary {
  positions: PortfolioPosition[];
  /** Real held tickers this system's `securities` table doesn't
   * currently carry — named, never silently dropped. */
  unrecognized_tickers: string[];
}

export type PriceLadderZone = "strong_accumulate" | "accumulate" | "fair" | "trim" | "exit";

export interface ValuedPosition {
  ticker: string;
  quantity: string;
  avg_price: string;
  total_cost: string;
  snapshot_traded_price: string | null;
  snapshot_market_value: string | null;
  snapshot_unrealized_gain_loss: string | null;
  live_current_price: string | null;
  live_market_value: string | null;
  live_unrealized_gain_loss: string | null;
  blended_fair_value_per_share: string | null;
  price_ladder_zone: PriceLadderZone | null;
  buy_below_price: string | null;
  margin_of_safety_pct: string | null;
  dispersion_pct: string | null;
  warnings: string[];
}

export interface ValuedPortfolio {
  snapshot_id: number;
  as_of: string;
  positions: ValuedPosition[];
  total_cost: string;
  total_live_market_value: string | null;
  positions_missing_a_live_price: string[];
}

export interface SensitivityEstimate {
  shock_name: string;
  coefficient: string;
  p_value: string;
  r_squared: string;
  observation_count: number;
  significant: boolean;
  direction_label: string;
}

export interface SectorSensitivityRow {
  sector: string;
  constituent_count: number;
  estimates: SensitivityEstimate[];
}

export interface SectorSensitivity {
  as_of: string;
  rows: SectorSensitivityRow[];
  /** `[sector, constituent_count]` pairs — real `cse_sector` assignment,
   * too few real tickers to estimate from. Named, not silently dropped. */
  thin_sectors: [string, number][];
  shocks_used: string[];
  warnings: string[];
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
