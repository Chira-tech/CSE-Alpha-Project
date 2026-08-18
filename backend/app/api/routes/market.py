"""
Live market overview — ASPI and the S&P/CSE sector indices.

IMPORTANT, and reflected in the response shape: this is a **live
passthrough** to the CSE API, not a query against our own point-in-time
store. Nothing here is persisted, so nothing here is subject to the §6
first_available_date discipline — which is fine for "what is the market
doing right now", and would NOT be fine as an input to any model. Every
response carries `fetched_at` and a `source` note so a caller can never
mistake it for stored, versioned data.

Two behaviours worth knowing about:

1. PARTIAL RESPONSES, NOT ALL-OR-NOTHING. Each upstream call is made
   independently and a failure degrades that section only — the response
   carries an `unavailable` list naming what couldn't be fetched and why.
   UI spec §15.1 requires a Partial state that "renders what exists,
   marks what does not"; returning 502 for the whole screen because one
   of three endpoints hiccuped is exactly the all-or-nothing failure that
   rule exists to prevent.

2. SHORT-LIVED CACHE. Master Spec §5 requires >=2s pacing between calls,
   so three sequential fetches cost ~4.5s wall-clock. Without a cache
   every page load (and every React StrictMode double-render in dev) pays
   that again and hammers an unofficial endpoint we're meant to treat
   gently. 60s matches the spirit of §52's 5-minute price cadence while
   keeping the screen feeling live.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.macro import SERIES_ASPI, SERIES_MARKET_PER
from app.domain.macro_view import (
    current_spread,
    latest_observation,
    risk_free_observation,
    series_history,
    spread_history,
)
from app.domain.ardl_cointegration_view import ardl_bounds_test_for
from app.domain.causality_analysis_view import impulse_response_fevd_for, toda_yamamoto_for
from app.domain.estimator_selection_view import select_and_fit_estimator
from app.domain.johansen_vecm_view import johansen_vecm_for
from app.domain.sector_sensitivity_view import sector_sensitivity_matrix_for
from app.domain.stationarity_view import stationarity_for_series
from app.domain.var_differences_view import var_in_differences_for
from app.ingestion.cse_client import CseClient, ShapeChangedError
from app.ingestion.schemas import AspiData, SectorIndexRow

logger = logging.getLogger("cse_alpha.api.market")

router = APIRouter(prefix="/market", tags=["market"])

_CACHE_TTL_SECONDS = 60.0


class IndexSnapshot(BaseModel):
    value: float | None
    change: float | None
    percentage: float | None
    low: float | None = None
    high: float | None = None


class SectorSnapshot(BaseModel):
    name: str
    symbol: str | None
    index_value: float | None
    change: float | None
    percentage: float | None
    turnover_today: float | None


class UnavailableSection(BaseModel):
    section: str
    reason: str


class MarketOverview(BaseModel):
    status: str | None
    aspi: IndexSnapshot | None
    sectors: list[SectorSnapshot]
    unavailable: list[UnavailableSection]
    fetched_at: dt.datetime
    cached: bool = False
    source: str = "cse.lk (live passthrough — not stored, not point-in-time)"


_cache: tuple[float, MarketOverview] | None = None
_cache_lock = threading.Lock()


def _describe(exc: Exception) -> str:
    """A reason string a human can act on, not a stack trace (§15.1)."""
    if isinstance(exc, ShapeChangedError):
        return (
            "the CSE API returned a response shape this system doesn't recognise — "
            "the upstream feed has likely changed and the loader needs updating"
        )
    return f"the CSE API could not be reached ({type(exc).__name__})"


def _build_overview() -> MarketOverview:
    status: str | None = None
    aspi: IndexSnapshot | None = None
    sectors: list[SectorSnapshot] = []
    unavailable: list[UnavailableSection] = []

    with CseClient() as client:
        try:
            payload = client.post_json("marketStatus")
            if isinstance(payload, dict):
                status = str(payload.get("status", "unknown"))
        except Exception as exc:  # noqa: BLE001 — unofficial upstream, many failure modes
            logger.warning("marketStatus unavailable: %s", exc)
            unavailable.append(UnavailableSection(section="Market status", reason=_describe(exc)))

        try:
            payload = client.post_json("aspiData", model=AspiData)
            if isinstance(payload, AspiData):
                aspi = IndexSnapshot(
                    value=payload.value,
                    change=payload.change,
                    percentage=payload.percentage,
                    low=payload.lowValue,
                    high=payload.highValue,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("aspiData unavailable: %s", exc)
            unavailable.append(UnavailableSection(section="All Share Price Index", reason=_describe(exc)))

        try:
            payload = client.post_json("allSectors")
            if isinstance(payload, list):
                for raw in payload:
                    try:
                        row = SectorIndexRow.model_validate(raw)
                    except Exception:  # noqa: BLE001 — skip one bad row, keep the rest
                        continue
                    sectors.append(
                        SectorSnapshot(
                            name=row.name,
                            symbol=row.symbol,
                            index_value=row.indexValue,
                            change=row.change,
                            percentage=row.percentage,
                            turnover_today=row.sectorTurnoverToday,
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("allSectors unavailable: %s", exc)
            unavailable.append(UnavailableSection(section="Sector indices", reason=_describe(exc)))

    return MarketOverview(
        status=status,
        aspi=aspi,
        sectors=sorted(sectors, key=lambda s: s.name),
        unavailable=unavailable,
        fetched_at=dt.datetime.now(dt.timezone.utc),
    )


class SpreadPoint(BaseModel):
    obs_date: dt.date
    earnings_yield: Decimal
    tbill_yield: Decimal
    spread: Decimal


class SpreadOut(BaseModel):
    """§29's hero variable. `available` is False when either input is
    missing, with `missing` naming which — never a zero or a stale
    figure, because the cost of equity and the regime read are both
    built on this."""

    available: bool
    missing: list[str]
    obs_date: dt.date | None = None
    market_per: Decimal | None = None
    earnings_yield: Decimal | None = None
    tbill_yield: Decimal | None = None
    tbill_obs_date: dt.date | None = None
    tbill_source: str | None = None
    spread: Decimal | None = None
    history: list[SpreadPoint] = []


@router.get("/spread", response_model=SpreadOut)
def equity_tbill_spread(db: Session = Depends(get_db)) -> SpreadOut:
    current = current_spread(db)
    if current is None:
        missing: list[str] = []
        if latest_observation(db, SERIES_MARKET_PER) is None:
            missing.append("market P/E (run `python -m app.cli capture-market`)")
        if risk_free_observation(db) is None:
            missing.append(
                "364-day T-bill yield (run `python -m app.cli cbsl --days 10`)"
            )
        return SpreadOut(available=False, missing=missing)

    return SpreadOut(
        available=True,
        missing=[],
        obs_date=current.obs_date,
        market_per=current.market_per,
        earnings_yield=current.earnings_yield,
        tbill_yield=current.tbill_yield,
        tbill_obs_date=current.tbill_obs_date,
        tbill_source=current.tbill_source,
        spread=current.spread,
        history=[
            SpreadPoint(
                obs_date=p.obs_date,
                earnings_yield=p.earnings_yield,
                tbill_yield=p.tbill_yield,
                spread=p.spread,
            )
            for p in spread_history(db)
        ],
    )


class IndexPoint(BaseModel):
    obs_date: dt.date
    value: Decimal
    source: str


class IndexHistoryOut(BaseModel):
    """ASPI closing levels. `recovered` counts the rows whose close was
    reconstructed from the feed's percentage change rather than read
    directly — see `app.domain.index_history` for why that distinction
    is load-bearing rather than cosmetic."""

    series_id: str
    points: list[IndexPoint]
    recovered: int


@router.get("/index-history", response_model=IndexHistoryOut)
def index_history(db: Session = Depends(get_db)) -> IndexHistoryOut:
    rows = series_history(db, SERIES_ASPI, limit=400)
    return IndexHistoryOut(
        series_id=SERIES_ASPI,
        points=[
            IndexPoint(obs_date=r.obs_date, value=r.value, source=r.source) for r in rows
        ],
        recovered=sum(1 for r in rows if r.source.endswith("(pc)")),
    )


class SensitivityEstimateOut(BaseModel):
    shock_name: str
    coefficient: Decimal
    p_value: Decimal
    r_squared: Decimal
    observation_count: int
    significant: bool
    direction_label: str


class SectorSensitivityRowOut(BaseModel):
    sector: str
    constituent_count: int
    estimates: list[SensitivityEstimateOut]


class SectorSensitivityOut(BaseModel):
    """§33's sector sensitivity matrix — a real, estimated regression of
    each sector's daily return on real macro shock series, never a
    hard-coded relationship (§33's own explicit warning). See
    `app.domain.sector_sensitivity`'s own module docstring for exactly
    which shocks are real and why §33's own illustrative Oil/Tourism/
    Fiscal columns aren't among them."""

    as_of: dt.date
    rows: list[SectorSensitivityRowOut]
    thin_sectors: list[list[object]]
    """`[sector, constituent_count]` pairs for a sector with a real
    `cse_sector` assignment but too few real tickers to estimate from —
    named, not silently dropped."""

    shocks_used: list[str]
    warnings: list[str]


@router.get("/sector-sensitivity", response_model=SectorSensitivityOut)
def sector_sensitivity(db: Session = Depends(get_db)) -> SectorSensitivityOut:
    view = sector_sensitivity_matrix_for(db)
    return SectorSensitivityOut(
        as_of=view.as_of,
        rows=[
            SectorSensitivityRowOut(
                sector=row.sector,
                constituent_count=row.constituent_count,
                estimates=[
                    SensitivityEstimateOut(
                        shock_name=e.shock_name,
                        coefficient=e.coefficient,
                        p_value=e.p_value,
                        r_squared=e.r_squared,
                        observation_count=e.observation_count,
                        significant=e.significant,
                        direction_label=e.direction_label,
                    )
                    for e in row.estimates
                ],
            )
            for row in view.rows
        ],
        thin_sectors=[[sector, count] for sector, count in view.thin_sectors],
        shocks_used=list(view.shocks_used),
        warnings=list(view.warnings),
    )


class UnitRootTestOut(BaseModel):
    test_name: str
    statistic: Decimal
    p_value: Decimal
    lags_used: int
    critical_values: dict[str, Decimal]
    null_hypothesis: str
    stationarity_conclusion: str
    break_index: int | None = None
    """Only populated for Zivot-Andrews — the 0-indexed position in the
    series identified as the most likely structural break."""


class StationarityOut(BaseModel):
    """§30 step 1, live, on one real `macro_series` series' LEVEL values
    (not returns — see `app.domain.stationarity_view`'s own docstring
    for why that distinction matters). Real series ids this system
    actually has coverage of: `cbsl.policy_rate`, `cbsl.tbill_364d`,
    `cbsl.ccpi_yoy`, `cbsl.usd_lkr_tt_buying` (all via `app.domain.
    cbsl_parsing`), `cse.aspi` (via `app.domain.index_history_loader`)."""

    series_id: str
    as_of: dt.date
    observation_count: int
    adf: UnitRootTestOut | None
    phillips_perron: UnitRootTestOut | None
    kpss: UnitRootTestOut | None
    zivot_andrews: UnitRootTestOut | None
    consensus: str | None
    note: str | None
    warnings: list[str]


@router.get("/stationarity", response_model=StationarityOut)
def stationarity(series_id: str, db: Session = Depends(get_db)) -> StationarityOut:
    view = stationarity_for_series(db, series_id)

    def _out(result) -> UnitRootTestOut | None:
        if result is None:
            return None
        return UnitRootTestOut(
            test_name=result.test_name, statistic=result.statistic, p_value=result.p_value,
            lags_used=result.lags_used, critical_values=result.critical_values,
            null_hypothesis=result.null_hypothesis,
            stationarity_conclusion=result.stationarity_conclusion,
            break_index=getattr(result, "break_index", None),
        )

    assessment = view.assessment
    return StationarityOut(
        series_id=view.series_id, as_of=view.as_of, observation_count=view.observation_count,
        adf=_out(assessment.adf) if assessment else None,
        phillips_perron=_out(assessment.phillips_perron) if assessment else None,
        kpss=_out(assessment.kpss) if assessment else None,
        zivot_andrews=_out(assessment.zivot_andrews) if assessment else None,
        consensus=assessment.consensus if assessment else None,
        note=assessment.note if assessment else None,
        warnings=list(view.warnings),
    )


class BoundsTestCriticalValueOut(BaseModel):
    lower: Decimal
    upper: Decimal


class BoundsTestResultOut(BaseModel):
    dependent_name: str
    independent_names: list[str]
    statistic: Decimal
    critical_values: dict[str, BoundsTestCriticalValueOut]
    conclusion: str
    ect_coefficient: Decimal | None
    half_life_periods: Decimal | None
    observation_count: int
    note: str


class CointegrationOut(BaseModel):
    """§30 step 2's ARDL-bounds-testing default estimator, live, on real
    `macro_series` LEVEL data — see `app.domain.ardl_cointegration_view`
    for exactly how two series published on different real-world
    cadences (e.g. ASPI daily, the T-bill yield on auction days) get
    aligned before the fit runs. `result` is `None` — never a fabricated
    or forced conclusion — whenever too few real aligned observations
    exist or the underlying fit genuinely fails; `warnings` names why."""

    dependent_series_id: str
    independent_series_ids: list[str]
    as_of: dt.date
    aligned_observation_count: int
    result: BoundsTestResultOut | None
    warnings: list[str]


def _bounds_test_result_out(r) -> BoundsTestResultOut:
    return BoundsTestResultOut(
        dependent_name=r.dependent_name,
        independent_names=list(r.independent_names),
        statistic=r.statistic,
        critical_values={
            pct: BoundsTestCriticalValueOut(lower=band["lower"], upper=band["upper"])
            for pct, band in r.critical_values.items()
        },
        conclusion=r.conclusion,
        ect_coefficient=r.ect_coefficient,
        half_life_periods=r.half_life_periods,
        observation_count=r.observation_count,
        note=r.note,
    )


@router.get("/cointegration", response_model=CointegrationOut)
def cointegration(
    dependent_series_id: str,
    independent_series_id: str,
    db: Session = Depends(get_db),
) -> CointegrationOut:
    """Single independent series for now — a query-string list is the
    natural extension once a caller actually needs a multi-variate bounds
    test; §30 step 2's own worked description is a two-series relationship
    (market level vs. one macro level), so this starts there rather than
    building unused generality ahead of a real need."""
    view = ardl_bounds_test_for(db, dependent_series_id, [independent_series_id])
    result_out = _bounds_test_result_out(view.result) if view.result is not None else None
    return CointegrationOut(
        dependent_series_id=view.dependent_series_id,
        independent_series_ids=list(view.independent_series_ids),
        as_of=view.as_of,
        aligned_observation_count=view.aligned_observation_count,
        result=result_out,
        warnings=list(view.warnings),
    )


class JohansenTestOut(BaseModel):
    dependent_name: str
    independent_name: str
    trace_statistics: list[Decimal]
    trace_critical_values: list[dict[str, Decimal]]
    selected_rank: int
    conclusion: str
    observation_count: int
    note: str


class VecmFitOut(BaseModel):
    johansen: JohansenTestOut
    alpha_dependent: Decimal | None
    alpha_independent: Decimal | None
    beta: Decimal | None
    half_life_periods: Decimal | None
    note: str


class JohansenVecmOut(BaseModel):
    """§30 step 2's "all I(1)" branch, live, on real `macro_series` LEVEL
    data — same real cross-cadence alignment as `GET /market/
    cointegration`, see `app.domain.johansen_vecm_view`'s own docstring.
    `result` is `None` only when too few real aligned observations exist
    or the rank test itself fails; once real data clears that bar,
    `result` is always present even for a non-cointegrated outcome (see
    `app.domain.johansen_vecm.fit_vecm`)."""

    dependent_series_id: str
    independent_series_id: str
    as_of: dt.date
    aligned_observation_count: int
    result: VecmFitOut | None
    warnings: list[str]


def _vecm_fit_out(r) -> VecmFitOut:
    return VecmFitOut(
        johansen=JohansenTestOut(
            dependent_name=r.johansen.dependent_name,
            independent_name=r.johansen.independent_name,
            trace_statistics=list(r.johansen.trace_statistics),
            trace_critical_values=[dict(band) for band in r.johansen.trace_critical_values],
            selected_rank=r.johansen.selected_rank,
            conclusion=r.johansen.conclusion,
            observation_count=r.johansen.observation_count,
            note=r.johansen.note,
        ),
        alpha_dependent=r.alpha_dependent,
        alpha_independent=r.alpha_independent,
        beta=r.beta,
        half_life_periods=r.half_life_periods,
        note=r.note,
    )


@router.get("/johansen-vecm", response_model=JohansenVecmOut)
def johansen_vecm(
    dependent_series_id: str,
    independent_series_id: str,
    db: Session = Depends(get_db),
) -> JohansenVecmOut:
    view = johansen_vecm_for(db, dependent_series_id, independent_series_id)
    result_out = _vecm_fit_out(view.result) if view.result is not None else None
    return JohansenVecmOut(
        dependent_series_id=view.dependent_series_id,
        independent_series_id=view.independent_series_id,
        as_of=view.as_of,
        aligned_observation_count=view.aligned_observation_count,
        result=result_out,
        warnings=list(view.warnings),
    )


class VarDifferencesResultOut(BaseModel):
    dependent_name: str
    independent_name: str
    lags: int
    is_stable: bool
    dependent_on_independent_lag1_coefficient: Decimal
    dependent_on_independent_lag1_p_value: Decimal
    significant: bool
    observation_count: int
    note: str


class VarDifferencesOut(BaseModel):
    """§30 step 2's "no cointegration" branch, live, on real
    `macro_series` LEVEL data (differenced internally — see `app.domain.
    var_differences`'s own docstring). `result` is `None` only when too
    few real aligned observations exist or the underlying fit fails."""

    dependent_series_id: str
    independent_series_id: str
    as_of: dt.date
    aligned_observation_count: int
    result: VarDifferencesResultOut | None
    warnings: list[str]


def _var_differences_result_out(r) -> VarDifferencesResultOut:
    return VarDifferencesResultOut(
        dependent_name=r.dependent_name,
        independent_name=r.independent_name,
        lags=r.lags,
        is_stable=r.is_stable,
        dependent_on_independent_lag1_coefficient=r.dependent_on_independent_lag1_coefficient,
        dependent_on_independent_lag1_p_value=r.dependent_on_independent_lag1_p_value,
        significant=r.significant,
        observation_count=r.observation_count,
        note=r.note,
    )


@router.get("/var-differences", response_model=VarDifferencesOut)
def var_differences(
    dependent_series_id: str,
    independent_series_id: str,
    db: Session = Depends(get_db),
) -> VarDifferencesOut:
    view = var_in_differences_for(db, dependent_series_id, independent_series_id)
    result_out = _var_differences_result_out(view.result) if view.result is not None else None
    return VarDifferencesOut(
        dependent_series_id=view.dependent_series_id,
        independent_series_id=view.independent_series_id,
        as_of=view.as_of,
        aligned_observation_count=view.aligned_observation_count,
        result=result_out,
        warnings=list(view.warnings),
    )


class EstimatorSelectionOut(BaseModel):
    """§30 step 2 assembled end to end: real stationarity assessments for
    both series pick which of the three named estimators to attempt
    (`app.domain.estimator_selection.select_estimator`'s own routing
    rule), the attempt actually runs against real `macro_series` data,
    and a real "not cointegrated" verdict falls back to a VAR in first
    differences — see `app.domain.estimator_selection_view`'s own
    docstring. At most one of `johansen_vecm`/`ardl_bounds_test`/
    `var_differences` is populated unless a fallback occurred, in which
    case both the initial attempt and the fallback are present so a
    caller can see exactly what happened, not just the final answer."""

    dependent_series_id: str
    independent_series_id: str
    as_of: dt.date
    dependent_consensus: str | None
    independent_consensus: str | None
    initial_choice: str
    estimator_used: str
    reason: str
    johansen_vecm: VecmFitOut | None = None
    ardl_bounds_test: BoundsTestResultOut | None = None
    var_differences: VarDifferencesResultOut | None = None


@router.get("/estimator-selection", response_model=EstimatorSelectionOut)
def estimator_selection(
    dependent_series_id: str,
    independent_series_id: str,
    db: Session = Depends(get_db),
) -> EstimatorSelectionOut:
    result = select_and_fit_estimator(db, dependent_series_id, independent_series_id)
    johansen_out = None
    if result.johansen_vecm is not None and result.johansen_vecm.result is not None:
        johansen_out = _vecm_fit_out(result.johansen_vecm.result)
    ardl_out = None
    if result.ardl_bounds_test is not None and result.ardl_bounds_test.result is not None:
        ardl_out = _bounds_test_result_out(result.ardl_bounds_test.result)
    var_out = None
    if result.var_differences is not None and result.var_differences.result is not None:
        var_out = _var_differences_result_out(result.var_differences.result)
    return EstimatorSelectionOut(
        dependent_series_id=result.dependent_series_id,
        independent_series_id=result.independent_series_id,
        as_of=result.as_of,
        dependent_consensus=result.dependent_consensus,
        independent_consensus=result.independent_consensus,
        initial_choice=result.initial_choice,
        estimator_used=result.estimator_used,
        reason=result.reason,
        johansen_vecm=johansen_out,
        ardl_bounds_test=ardl_out,
        var_differences=var_out,
    )


class ImpulseResponseFevdResultOut(BaseModel):
    dependent_name: str
    independent_name: str
    estimator: str
    periods: int
    irf_dependent_to_independent_shock: list[Decimal]
    irf_independent_to_dependent_shock: list[Decimal]
    fevd_dependent_explained_by_independent: list[Decimal]
    fevd_independent_explained_by_dependent: list[Decimal]
    observation_count: int
    note: str


class ImpulseResponseFevdOut(BaseModel):
    """§30 step 3's impulse response / FEVD, live, computed from
    whichever real estimator §30 step 2's own selection landed on for
    this pair — see `app.domain.causality_analysis_view`'s own
    docstring. `result` is `None` when step 2's selection didn't reach a
    VAR-shaped fit (ARDL, or insufficient data) or too little real
    aligned data exists; `estimator_used` names which branch was
    actually used, or is `None` alongside `result`."""

    dependent_series_id: str
    independent_series_id: str
    as_of: dt.date
    aligned_observation_count: int
    estimator_used: str | None
    result: ImpulseResponseFevdResultOut | None
    warnings: list[str]


@router.get("/impulse-response-fevd", response_model=ImpulseResponseFevdOut)
def impulse_response_fevd(
    dependent_series_id: str,
    independent_series_id: str,
    periods: int = 10,
    db: Session = Depends(get_db),
) -> ImpulseResponseFevdOut:
    view = impulse_response_fevd_for(db, dependent_series_id, independent_series_id, periods=periods)
    result_out = None
    if view.result is not None:
        r = view.result
        result_out = ImpulseResponseFevdResultOut(
            dependent_name=r.dependent_name,
            independent_name=r.independent_name,
            estimator=r.estimator,
            periods=r.periods,
            irf_dependent_to_independent_shock=list(r.irf_dependent_to_independent_shock),
            irf_independent_to_dependent_shock=list(r.irf_independent_to_dependent_shock),
            fevd_dependent_explained_by_independent=list(r.fevd_dependent_explained_by_independent),
            fevd_independent_explained_by_dependent=list(r.fevd_independent_explained_by_dependent),
            observation_count=r.observation_count,
            note=r.note,
        )
    return ImpulseResponseFevdOut(
        dependent_series_id=view.dependent_series_id,
        independent_series_id=view.independent_series_id,
        as_of=view.as_of,
        aligned_observation_count=view.aligned_observation_count,
        estimator_used=view.estimator_used,
        result=result_out,
        warnings=list(view.warnings),
    )


class GrangerCausalityResultOut(BaseModel):
    causing_name: str
    caused_name: str
    wald_statistic: Decimal
    degrees_of_freedom: int
    p_value: Decimal
    significant: bool


class TodaYamamotoResultOut(BaseModel):
    dependent_name: str
    independent_name: str
    lags: int
    integration_order_augmentation: int
    total_fitted_lags: int
    independent_causes_dependent: GrangerCausalityResultOut
    dependent_causes_independent: GrangerCausalityResultOut
    observation_count: int
    note: str


class TodaYamamotoOut(BaseModel):
    """§30 step 3's Toda-Yamamoto causality test, live — valid
    regardless of the pair's cointegration status (see `app.domain.
    causality_analysis`'s own docstring), so this runs independently of
    whatever §30 step 2 selected. `result` is `None` when either
    series' own real stationarity consensus is unknown or ambiguous
    (refusing to guess the augmentation) or too little real aligned
    data exists."""

    dependent_series_id: str
    independent_series_id: str
    as_of: dt.date
    aligned_observation_count: int
    dependent_consensus: str | None
    independent_consensus: str | None
    result: TodaYamamotoResultOut | None
    warnings: list[str]


@router.get("/toda-yamamoto", response_model=TodaYamamotoOut)
def toda_yamamoto(
    dependent_series_id: str,
    independent_series_id: str,
    db: Session = Depends(get_db),
) -> TodaYamamotoOut:
    view = toda_yamamoto_for(db, dependent_series_id, independent_series_id)
    result_out = None
    if view.result is not None:
        r = view.result

        def _causality_out(c) -> GrangerCausalityResultOut:
            return GrangerCausalityResultOut(
                causing_name=c.causing_name, caused_name=c.caused_name,
                wald_statistic=c.wald_statistic, degrees_of_freedom=c.degrees_of_freedom,
                p_value=c.p_value, significant=c.significant,
            )

        result_out = TodaYamamotoResultOut(
            dependent_name=r.dependent_name,
            independent_name=r.independent_name,
            lags=r.lags,
            integration_order_augmentation=r.integration_order_augmentation,
            total_fitted_lags=r.total_fitted_lags,
            independent_causes_dependent=_causality_out(r.independent_causes_dependent),
            dependent_causes_independent=_causality_out(r.dependent_causes_independent),
            observation_count=r.observation_count,
            note=r.note,
        )
    return TodaYamamotoOut(
        dependent_series_id=view.dependent_series_id,
        independent_series_id=view.independent_series_id,
        as_of=view.as_of,
        aligned_observation_count=view.aligned_observation_count,
        dependent_consensus=view.dependent_consensus,
        independent_consensus=view.independent_consensus,
        result=result_out,
        warnings=list(view.warnings),
    )


@router.get("", response_model=MarketOverview)
def market_overview(refresh: bool = False) -> MarketOverview:
    """`refresh=true` bypasses the cache — for an explicit user-initiated
    refresh. Never auto-refresh on a timer: UI spec §17 forbids
    "auto-refresh that moves content under the cursor"."""
    global _cache

    now = dt.datetime.now(dt.timezone.utc).timestamp()
    with _cache_lock:
        if not refresh and _cache is not None:
            cached_at, cached_value = _cache
            if now - cached_at < _CACHE_TTL_SECONDS:
                return cached_value.model_copy(update={"cached": True})

    overview = _build_overview()

    # Only cache a response that actually got something — otherwise a
    # transient outage would be pinned for the full TTL.
    if overview.aspi is not None or overview.sectors:
        with _cache_lock:
            _cache = (now, overview)

    return overview
