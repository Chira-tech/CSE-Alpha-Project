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


settings = Settings()
