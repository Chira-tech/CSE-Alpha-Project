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
  /** R1 T2.5: an independently-sourced (different source_url) row
   * already carries REPORTED provenance for this exact same figure —
   * real corroboration, the one case safe for one-click bulk confirm. */
  corroborated: boolean;
}

/** One page of the confirm queue, most-recent-period-first — backs the
 * Fundamentals tab's own table. Paged with SQL LIMIT/OFFSET server-side
 * (mirrors `PriceHistoryPage`), not the whole queue shipped and sliced
 * client-side — a real backfill grew this queue past 11,000 rows. */
export interface FundamentalsPage {
  items: Fundamental[];
  total: number;
  limit: number;
  offset: number;
}

export interface ConfirmBatchFailure {
  id: number;
  reason: string;
}

export interface ConfirmBatchResult {
  confirmed: number[];
  failed: ConfirmBatchFailure[];
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
  return_on_equity_sector_percentile: string | null;
  /** R1 T4.4.1: real trading-SESSION price appreciation (raw close, not
   * adjustment-factor-adjusted). `null` when fewer real sessions of
   * history exist than the window claims. */
  price_change_5d_pct: string | null;
  price_change_10d_pct: string | null;
  price_change_15d_pct: string | null;
  price_change_30d_pct: string | null;
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

/** One page of `GET /securities/{ticker}/prices`, most-recent-first —
 * backs the company file's price-history table, paged server-side with
 * limit/offset rather than sliced from a fully-loaded array. */
export interface PriceHistoryPage {
  items: PricePoint[];
  total: number;
  limit: number;
  offset: number;
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

/** §12's sector-relative percentile — see the backend's `app.domain.
 * sector_percentiles` module docstring for the grouping, winsorization
 * and ranking-direction rules (ascending: the highest raw value gets
 * the highest percentile). `percentile === null` means `reason` says
 * why — usually too few peers in the sector to rank meaningfully. */
export interface RatioSeriesPoint {
  period_end: string;
  value: string;
}

export interface RatioPercentile {
  ratio_key: string;
  percentile: string | null;
  group_label: string | null;
  group_size: number;
  used_wider_sector: boolean;
  reason: string | null;
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
  /** R1 T2.6: when the scheduled daily scan (`app.jobs.scheduler.
   * _job_corporate_actions_scan`) last covered this ticker — `null` means
   * the sweep hasn't reached it yet, never that scanning must be run by
   * hand. */
  corporate_actions_last_scanned_at: string | null;
  fundamentals: FundamentalSummary[];
  ratio_period_end: string | null;
  ratios: Ratio[];
  ratios_not_yet_computable: UncomputableRatio[];
  ratio_trends: RatioTrend[];
  ratio_percentiles: RatioPercentile[];
  /** R1 T4.3.1: raw `(period_end, value)` history behind each ratio's
   * own `ratio_trends` verdict, oldest first, keyed by ratio key —
   * enough to draw a real path where >=3 periods exist. */
  ratio_series: Record<string, RatioSeriesPoint[]>;
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

export interface SanityOut {
  /** TASK 0.1's plausibility gate (backend `app.domain.sanity`) — present
   * whenever a blended fair value existed to check, even when nothing
   * failed, so a caller can show which rules actually ran. */
  blocked: boolean;
  blocked_by: string[];
  block_reasons: string[];
  warned_by: string[];
  warn_reasons: string[];
  skipped: string[];
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
  dcf: {
    fair_value_per_share: string | null;
    warnings: string[];
  };
  gordon_growth_ddm: {
    value_per_share: string | null;
    warnings: string[];
  };
  hard_book: {
    hard_book_per_share: string | null;
    warnings: string[];
  };
  /** §20.2's justified P/E and justified P/S — real "relative"
   * triangulation anchors alongside justified P/B as of 23 Aug 2026 (see
   * `app.domain.valuation_view.RelativeValuationView`'s own docstring).
   * `ev_to_ebit` fields stay `null` — needs ROIC, not extractable
   * anywhere in this system yet. */
  relative_valuation: {
    eps: string | null;
    sales_per_share: string | null;
    payout_ratio: string | null;
    justified_price_to_earnings: string | null;
    justified_price_to_sales: string | null;
    fair_value_per_share_pe: string | null;
    fair_value_per_share_ps: string | null;
    trading: {
      price_to_earnings: string | null;
      price_to_book: string | null;
      ev_to_ebit: string | null;
      price_to_sales: string | null;
    };
    warnings: string[];
  };
  triangulation: ValuationAnchorCategory;
  margin_of_safety: MarginOfSafetyOut;
  sanity: SanityOut | null;
  price_ladder: PriceLadderOut | null;
  note: string;
}

/** §23's Bear/Base/Bull scenario set — `GET /valuation/{ticker}/scenarios`. */
export interface ScenarioSet {
  period_end: string | null;
  scenarios: {
    bear_value_per_share: string;
    base_value_per_share: string;
    bull_value_per_share: string;
    note: string;
  } | null;
  distribution_note: string | null;
  warnings: string[];
}

/** §23's sensitivity tornado — `GET /valuation/{ticker}/tornado`. */
export interface Tornado {
  period_end: string | null;
  bars: {
    assumption_name: string;
    low_value_per_share: string;
    high_value_per_share: string;
    spread: string;
  }[];
  warnings: string[];
}

/** §23's 10,000-draw Monte Carlo overlay — `GET
 * /valuation/{ticker}/monte-carlo`, fetched lazily (opt-in) since it's a
 * heavier call than the rest of the fair-value page. */
export interface MonteCarlo {
  period_end: string | null;
  draws: number | null;
  p10: string | null;
  p25: string | null;
  p50: string | null;
  p75: string | null;
  p90: string | null;
  probability_fair_value_exceeds_price: string | null;
  note: string | null;
  warnings: string[];
}

// --- Composite score (§38) ------------------------------------------------

export interface PillarScore {
  key: string;
  label: string;
  weight_pct: string;
  /** 0-100, or `null` when `included` is false. */
  score: string | null;
  included: boolean;
  /** Set whenever `included` is false — either a fixed, design-level
   * reason (Valuation/Growth's own real cost constraint) or a per-ticker
   * reason (e.g. no sector-relative percentile available for this
   * ticker's own ratios). */
  reason: string | null;
}

export interface CompositeIntegrity {
  evaluable: boolean;
  vetoed: boolean;
  reason: string;
}

/** Real Valuation-pillar figures, shown but never ranked (§38's own cost
 * constraint) — the same numbers the Fair value (§18-26) section above
 * already shows for this ticker, repeated here only as pillar evidence. */
export interface CompositeValuationEvidence {
  blended_fair_value_per_share: string | null;
  dispersion_pct: string | null;
  margin_of_safety_pct: string | null;
  price_ladder_zone: PriceLadderZone | null;
  current_price: string | null;
  regime_label: string | null;
}

export interface CompositeGrowthTrend {
  ratio_key: string;
  direction: "increasing" | "decreasing" | "no_trend" | "insufficient_history";
  significant: boolean;
  accelerating: boolean | null;
  fraction_same_direction: string | null;
  periods_used: number;
}

export interface CompositeProjectImpact {
  project_id: number;
  impact_metric: string;
  quantified_impact_pct: string | null;
  notes: string | null;
}

export interface TimingSignal {
  key: string;
  value: string | null;
  weight_pct: string;
  included: boolean;
  reason: string | null;
}

export interface ContrarianCheck {
  rev_1m_bottom_decile: boolean | null;
  business_quality_ge_70: boolean | null;
  no_integrity_red_flag: boolean | null;
  no_adverse_disclosure_60d: string;
  no_active_sector_macro_shock: boolean | null;
  all_conditions_met: boolean;
}

export interface TimingBattery {
  signals: TimingSignal[];
  crash_guard_active: boolean;
  contrarian: ContrarianCheck;
}

export interface CompositeScore {
  ticker: string;
  as_of: string;
  pillars: PillarScore[];
  total_score: string | null;
  weight_used_pct: Record<string, string>;
  /** Always true today — Valuation and Growth are permanently excluded
   * from the number by a real, disclosed cost constraint, not a bug. */
  is_partial: boolean;
  integrity: CompositeIntegrity;
  valuation_evidence: CompositeValuationEvidence;
  growth_ratio_trends: CompositeGrowthTrend[];
  growth_project_impacts: CompositeProjectImpact[];
  timing_battery: TimingBattery;
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
  /** R1 T4.1.5: top tickers by pending-figure count — real, cheap
   * proxy for where confirming pays off most. See the backend's own
   * `DataHealth.fundamentals_pending_by_ticker` docstring for why this
   * is NOT the brief's literal "unblocks fair value for N companies"
   * claim (that needs a full universe valuation pass, too slow for a
   * screen meant to load in under two minutes). */
  fundamentals_pending_by_ticker: { ticker: string; count: number }[];
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
  /** R1 T4.5.3: the take-profit ceiling (§26's `exit_threshold`) — the
   * right signal for a position you already hold, unlike buy-below. */
  sell_above_price: string | null;
  margin_of_safety_pct: string | null;
  dispersion_pct: string | null;
  warnings: string[];
  /** R1 T4.5.4: real, calmly-styled flags — never a fabricated
   * "thesis break" (needs §45's decision record, not built yet). */
  attention_flags: AttentionFlag[];

  /** TASK 2.2 (product-owner brief): the exit plan. */
  trim_above_price: string | null;
  /** (price / fair value) - 1 — worded plainly on screen, e.g. "14%
   * above fair value" / "22% below fair value". */
  overvaluation_pct: string | null;
  /** The nearest of the price ladder's own four thresholds to the
   * current price — a real, disclosed substitute for §28's own
   * not-yet-built five-trigger framework (see the backend's own
   * `ValuedPosition.nearest_trigger_label` docstring). */
  nearest_trigger_label: string | null;
  nearest_trigger_price: string | null;
  nearest_trigger_distance_pct: string | null;
  /** `app.domain.decision.compute_decision`'s own verdict/confidence —
   * the same call the company file shows for this ticker. */
  decision_verdict: string | null;
  decision_confidence: string | null;
  /** "intact" (no attention flags) / "weakening" (one or more) — NOT
   * §42's own drift-vs-purchase-baseline monitor, which doesn't exist;
   * see the backend's own docstring for why this is a disclosed,
   * honest substitute rather than a fabricated three-state ladder. */
  thesis_status: string | null;
}

export interface AttentionFlag {
  key: string;
  label: string;
  detail: string;
}

export interface ValuedPortfolio {
  snapshot_id: number;
  as_of: string;
  positions: ValuedPosition[];
  total_cost: string;
  total_live_market_value: string | null;
  positions_missing_a_live_price: string[];
  /** R1 T4.1.6/T4.5.1 — keyed "15d"/"30d"/"45d"/"60d". Today's exact
   * holdings priced at each past real close, NOT a real historical
   * portfolio replay (no transaction log yet) — see the backend's own
   * `portfolio_value_trend` docstring. */
  value_trend_pct: Record<string, string | null>;
}

export type DecisionAction = "buy" | "watchlist" | "pass" | "partial" | "sell" | "trim";

export interface Outcome {
  id: number;
  exit_date: string;
  exit_price: string;
  exit_trigger: string;
  gross_return: string;
  net_return: string;
  holding_days: number;
  max_adverse_excursion: string | null;
  max_favourable_excursion: string | null;
  attribution_json: Record<string, unknown> | null;
}

export interface Decision {
  id: number;
  ticker: string;
  timestamp: string;
  config_hash: string | null;
  action: DecisionAction;
  size_pct: string | null;
  limit_price: string | null;
  conviction_1_5: number | null;
  reasoning_text: string;
  falsification_text: string | null;
  fundamental_score: string | null;
  pillar_scores_json: Record<string, unknown> | null;
  integrity_flags_json: Record<string, unknown> | null;
  fv_by_method_json: Record<string, string> | null;
  fv_blended: string | null;
  dispersion: string | null;
  mos_components_json: Record<string, unknown> | null;
  buy_below: string | null;
  fair_value: string | null;
  trim_above: string | null;
  timing_score: string | null;
  timing_branch: string | null;
  timing_signals_json: Record<string, unknown> | null;
  macro_regime: string | null;
  macro_prob: string | null;
  sector_fit: string | null;
  alpha: string | null;
  alpha_tstat: string | null;
  betas_json: Record<string, unknown> | null;
  residual_vol: string | null;
  market_price_at_decision: string | null;
  data_completeness_pct: string | null;
  agreement_score: string | null;
  override_flag: boolean | null;
  outcome: Outcome | null;
}

export interface OpportunityCandidate {
  ticker: string;
  name: string;
  archetype: string | null;
  current_price: string | null;
  blended_fair_value_per_share: string | null;
  margin_of_safety_pct: string;
  price_ladder_zone: PriceLadderZone | null;
  buy_below_price: string | null;
  gap_to_buy_below_pct: string | null;
  dispersion_pct: string | null;
  warnings: string[];
}

export interface OpportunityRanking {
  as_of: string;
  ranked: OpportunityCandidate[];
  excluded: OpportunityCandidate[];
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

/** R1 T4.6.4's sector drill-down panel. */
export interface SectorCompany {
  ticker: string;
  name: string;
  market_cap: string | null;
  market_cap_reason: string | null;
  pct_of_sector: string | null;
  fair_value_gap_pct: string | null;
  gap_reason: string | null;
}

export interface SectorDrilldown {
  sector: string;
  as_of: string;
  companies: SectorCompany[];
  total_market_cap: string | null;
  excluded_from_market_cap_pct: number;
  composite_score_omitted_reason: string;
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

// --- Jobs (P1.1 "Run Capture") --------------------------------------------

export type JobKey =
  | "capture_prices"
  | "capture_market"
  | "capture_macro"
  | "capture_filings"
  | "capture_corporate_actions"
  | "enrich_securities"
  | "recompute"
  | "refresh_stale_fundamentals"
  | "capture_all";

export type JobRunStatus = "queued" | "running" | "success" | "failed" | "cancelled";

export interface JobRun {
  id: number;
  job: JobKey;
  label: string;
  trigger: "manual" | "scheduled";
  status: JobRunStatus;
  started_at: string | null;
  finished_at: string | null;
  progress_pct: string;
  progress_note: string | null;
  rows_written: number;
  error: string | null;
  cancel_requested: boolean;
  created_at: string;
}

export interface JobStatusEntry {
  job: JobKey;
  label: string;
  est_seconds: number;
  last_run: JobRun | null;
  next_scheduled_at: string | null;
}

export interface JobsStatus {
  jobs: JobStatusEntry[];
}

/** §31's regime gauge — see `GET /market/regime`. */
export interface RegimeSubRead {
  kind: string;
  label: string | null;
  detail: string;
}

export interface RegimeConsequence {
  margin_of_safety_add_pct: string | null;
  erp_add_pct: string | null;
  note: string;
}

export interface SectorTilt {
  sector: string;
  shock: string;
  direction: string;
  coefficient: string;
  p_value: string;
  constituent_count: number;
}

export interface RegimeGauge {
  as_of: string;
  label: string | null;
  probabilities: Record<string, string>;
  note: string;
  sub_reads: RegimeSubRead[];
  consequence: RegimeConsequence;
  half_life_periods: string | null;
  half_life_note: string;
  sector_tilts: SectorTilt[];
  sector_tilt_note: string;
  not_built: string[];
}
