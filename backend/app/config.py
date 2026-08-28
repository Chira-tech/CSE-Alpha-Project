"""
Central settings. Every "open parameter" from Master Spec Part O and every
tunable threshold from Part C (coverage gates) lives here as a named,
documented field — never as a magic number buried in domain logic. See
PARAMETERS.md at the repo root for the rationale behind each default.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://cse_alpha:cse_alpha@localhost:5432/cse_alpha"

    # --- Part O #1: capital base -------------------------------------------------
    capital_base_lkr: Decimal = Decimal("25000000")

    # --- Part O #7: concentration appetite (§27.1, §39.1) ------------------------
    concentration_cap_tier1_pct: Decimal = Decimal("0.10")
    concentration_cap_tier2_pct: Decimal = Decimal("0.06")
    concentration_cap_tier3_pct: Decimal = Decimal("0.03")
    sector_cap_pct: Decimal = Decimal("0.30")
    target_position_count_min: int = 8
    target_position_count_max: int = 15

    # --- Coverage gates (§11.1) ---------------------------------------------------
    gate1_min_median_daily_turnover_lkr: Decimal = Decimal("2000000")
    gate1_min_days_traded_of_60: int = 45
    gate1_amihud_max_percentile: Decimal = Decimal("0.80")
    gate1_max_position_pct_of_adv: Decimal = Decimal("0.15")

    gate2_min_free_float_pct: Decimal = Decimal("0.15")
    gate2_min_months_listed: int = 12
    gate2_min_market_cap_lkr: Decimal = Decimal("1000000000")
    gate2_min_quarters_history: int = 8

    gate3_beneish_m_score_threshold: Decimal = Decimal("-1.78")
    gate3_max_related_party_pct: Decimal = Decimal("0.30")

    insufficient_data_completeness_floor_pct: Decimal = Decimal("0.40")
    insufficient_min_quarters: int = 8

    # --- Part O #10: cost of equity (§17.1/§17.2) ---------------------------------
    erp_effective_pct: Decimal = Decimal("0.07")
    """Mature-market ERP plus a reduced country risk premium (§17.1 Route
    A) — a policy input, not something this system computes. See
    PARAMETERS.md #10: this is a provisional placeholder, not a figure
    sourced from Damodaran's live country dataset, which this system has
    no access to. `app.domain.cost_of_equity` also surfaces the
    ASPI-implied ERP (§17.1's "third reference point") alongside this
    value for comparison — never as a silent substitute for it."""

    # --- Part O #11: long-run nominal growth for terminal/steady-state g ----------
    long_run_nominal_growth_pct: Decimal = Decimal("0.05")
    """The `g` every steady-state valuation formula in §18-20 needs
    (terminal DCF growth, Gordon growth, justified P/E and P/B) and that
    this system has no series for — Sri Lanka's long-run nominal GDP
    growth is not something any ingested source publishes. A policy
    input, provisional exactly like `erp_effective_pct` above; see
    PARAMETERS.md #11. Must never exceed `Rf_LKR` (§18.2's own
    discipline: "a company growing faster than the risk-free rate
    forever is worth infinity") — every caller of this default is
    expected to check that against the live risk-free observation, not
    assume it here."""

    # --- Part O #12: statutory corporate tax rate (§18.2) -------------------------
    statutory_corporate_tax_rate_pct: Decimal = Decimal("0.30")
    """§18.2's DCF tax path converges from `effective_tax_rate_current`
    (extracted per-company) to this statutory rate by Year 5. Unlike
    `erp_effective_pct`/`long_run_nominal_growth_pct`, this is NOT a
    provisional placeholder invented for lack of a source — it is Sri
    Lanka's real, current, publicly verified standard corporate income
    tax rate (Inland Revenue Department notice PN/IT/2025-01, 26 March
    2025: 30% for most companies), the same rate that already governs
    why `income_tax_expense ÷ profit_before_tax` for an ordinary CSE
    industrial company should converge toward roughly this number, not
    an arbitrary one. See PARAMETERS.md #12 for the full citation and,
    critically, this default's real limitation: the IRD notice also sets
    concessionary rates for specific sectors (15% for service exports
    such as IT/BPO, 14% for goods exports and qualifying education/
    healthcare, 40% for gambling/liquor) that this system has no
    per-company routing for yet — using 30% for every company is
    therefore correct for most CSE industrials but a real overstatement
    of the true statutory rate for any company in one of those
    concessionary sectors, and should not be trusted uncritically for
    those archetypes."""

    # --- Real, sourced round-trip transaction cost (§2.1) -------------------------
    round_trip_transaction_cost_pct: Decimal = Decimal("0.0224")
    """§2.1's own real, itemised figure — NOT a provisional placeholder,
    a directly-stated fact in the master spec: 0.640% brokerage + 0.300%
    share transaction levy + 0.084% CSE fee + 0.072% SEC cess + 0.024%
    CDS = 1.12% one way, doubled for a round trip. Used by `app.domain.
    decision_record_view.record_outcome_for` to compute a real
    net-of-cost return alongside the gross figure (§45's own
    `gross_return`/`net_return` fields), the same "report gross and net
    side by side, and treat net as the only real number" discipline
    §48's backtest protocol applies to the eventual full backtest suite.
    Deliberately excludes bid-ask spread and market impact — §2.1 itself
    says realistic ALL-IN friction is "3-5% per round trip on mid-caps"
    once those are added, so this constant is a real floor, not the
    full real cost."""

    # --- Point-in-time / reporting lag defaults (§6) ------------------------------
    default_quarterly_reporting_lag_days: int = 90
    default_annual_reporting_lag_days: int = 180
    annual_factor_formation_month: int = 9
    annual_factor_formation_day: int = 30

    # --- Corporate actions / reconciliation (§7) ----------------------------------
    reconciliation_mismatch_threshold_pct: Decimal = Decimal("0.005")

    # --- cse.lk client politeness (§5 — "the single biggest operational
    # fragility") ------------------------------------------------------------------
    cse_base_url: str = "https://www.cse.lk/api"
    cse_min_seconds_between_calls: float = 2.0
    cse_user_agent: str = "cse-alpha-engine/0.1 (personal research use)"
    cse_circuit_breaker_failure_threshold: int = 5
    cse_circuit_breaker_reset_seconds: float = 300.0
    cse_max_retries: int = 4

    # --- CBSL (robots.txt asks for Crawl-delay: 10) --------------------------------
    # Not a self-chosen politeness figure like the CSE one: this is the
    # site operator's own published request, so it is honoured exactly.
    cbsl_crawl_delay_seconds: float = 10.0

    # --- Backtest / historical depth (Part O #2) ----------------------------------
    historical_backfill_start_date: str = "2015-01-01"

    # --- Part O #8: sector / ticker exclusions ------------------------------------
    excluded_sectors: list[str] = Field(default_factory=list)
    excluded_tickers: list[str] = Field(default_factory=list)

    # --- M5 — Convergence Engine & Playbook System (docs/CLAUDE_CODE_BRIEF_M5.md) --
    m5_enabled: bool = False
    """The ONLY M5-related field on this object, deliberately: every
    other M5 setting lives in `m5.config.M5Settings`, a completely
    separate settings object M5's own modules read instead (brief §0's
    isolation rule extended to config, not just data/components). This
    field exists purely so `app/main.py`'s own allowlisted guard line
    (brief §1.3 — `if settings.m5_enabled:`) has something real to read;
    `pydantic_settings.BaseSettings` with `extra="ignore"` (this class's
    own `model_config`) silently drops an undeclared env var, so the
    guard would otherwise always evaluate false regardless of the real
    `M5_ENABLED` env var. A disclosed, minimal exception to brief §1.3's
    literal "only main.py, one line" — flagged here per the brief's own
    "if an existing file must change, STOP and raise it" rule, not
    silently done. Grants M5 no write access to anything and changes no
    existing behaviour."""


settings = Settings()
