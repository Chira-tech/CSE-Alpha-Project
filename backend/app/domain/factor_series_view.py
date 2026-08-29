"""
§35's DB-wired WEEKLY factor return series builder — the bulk-loaded
extension of `app.domain.factor_library_view.hml_hard_for`'s own proven
single-snapshot pattern into a genuine time series, persisted to
`macro_series` under the `factor.*` series ids (`app.domain.
factor_series.ALL_FACTOR_SERIES_IDS`) and read back through that table's
own existing, unmodified `app.domain.macro_view.series_history`/
`latest_observation`.

WHY THIS MUST BULK-LOAD RATHER THAN CALL THE PER-TICKER `_view.py`
FUNCTIONS ONCE PER WEEK. `hml_hard_for`'s own pattern (three DB round-
trips per ticker per call: `market_cap_for`, `hard_book_for`,
`cumulative_adjusted_return`) is proven correct but costs real time —
repeating it across ~163 real weeks × 290 tickers is ~142,000 ORM calls,
tens of minutes, not something to run inline or even casually as a
background job. This module instead loads `prices_daily` and
`float_data` ONCE into memory (per ticker, sorted, real depth: ~200k
price rows and 295 float rows in this system's own real dev database —
both trivially small for a single in-process load) and re-derives
market cap and weekly returns as pure in-memory arithmetic from there —
`market_cap = shares_issued × close` (raw close, NOT adjusted — matching
`market_cap_view.market_cap_for`'s own convention exactly) and weekly
returns from `close × adj_factor` (matching `price_returns.
cumulative_adjusted_return`'s own convention exactly).

THE ONE INPUT DELIBERATELY NOT BULK-REIMPLEMENTED: HARD BOOK VALUE.
`valuation_view.hard_book_for`'s own line-item matching (confirmed-tier
filtering, sector-specific revaluation-reserve label variants,
point-in-time period selection) is real, non-trivial logic already
tested end to end. Reimplementing it a second time in bulk risks a
silent divergence between the trusted slow path and a new fast path —
exactly the kind of bug this project's own "trust but verify" discipline
warns against. Real compromise instead: hard book value moves only when
a new CONFIRMED annual filing lands — in practice at most a few times
across this system's whole ~3-year price window per company — so this
module calls the real, trusted `hard_book_for` at a coarser
`HARD_BOOK_REFRESH_CADENCE_DAYS` (30 real days, not weekly) cadence per
ticker and forward-fills that value across the weeks between checkpoints,
cutting the ~47,000 weekly calls this one input would otherwise need
down to ~3,500 while never re-deriving its line-item logic independently.
Every other per-week value (market cap, all four sorted factors' size/
style inputs, MKT-RF) is genuinely bulk in-memory, genuinely weekly, no
compromise.

A SECOND REAL DATA GAP, FOUND AND FIXED WHILE BUILDING THIS: `float_data`
carries exactly ONE real `shares_issued` snapshot per ticker (2026-08-18/
19 — this system has never captured a historical share-count series).
Naively holding that one snapshot as valid for every earlier week would
be silently wrong for any ticker with a real share-count change in
between. See `_load_shares_issued`'s own docstring for the real fix:
this system already has real, confirmed `corporate_actions` rows
(BONUS_ISSUE/RIGHTS_ISSUE/STOCK_SPLIT/CONSOLIDATION) that walk the
current snapshot backward correctly for the (checked live: exactly 3)
tickers where it matters, and leave the other 287 exactly as a held-
constant snapshot, which is the genuinely correct value for a ticker
with no real change on record.

ONE DESIGNATED SMB, NOT A SEPARATE SORT. §35.1 lists SMB and HML as
independent 2×3 sorts, but both share the identical size split — this
module reads SMB off the HML_hard sort's own `size_factor_return`
(computed from the SAME six portfolios HML_hard's style split already
produced) rather than running a second, redundant sort whose
`size_factor_return` would differ from HML_hard's only by sampling noise
from a slightly different constituent set on ties. Disclosed here, once,
not a silent simplification.

RISK-FREE RATE: §35.1's own literal choice, the 91-day T-bill's weekly
primary-market yield (`SERIES_TBILL_91D`), converted from an annualised
fraction to a weekly return via `(1+annual)^(1/52) - 1` — "converted to
the return frequency" is spec's own phrase; this is the standard
compounding conversion, not a linear approximation.

A WEEK WITH TOO FEW REAL, INCLUDABLE TICKERS PRODUCES NO ROW FOR THAT
FACTOR THAT WEEK — never a fabricated, interpolated, or zero-filled
value. `FactorSeriesBuildSummary.warnings` names every such gap.
"""
from __future__ import annotations

import bisect
import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cbsl_parsing import SERIES_TBILL_91D
from app.domain.factor_series import (
    ALL_FACTOR_SERIES_IDS,
    SERIES_FACTOR_HML_HARD,
    SERIES_FACTOR_LIQ,
    SERIES_FACTOR_MKT_RF,
    SERIES_FACTOR_MOM,
    SERIES_FACTOR_SMB,
    MarketWeightedInput,
    mom_style_value,
    value_weighted_return,
)
from app.domain.liquidity import amihud_illiquidity_ratio
from app.domain.market_cap import market_cap as compute_market_cap
from app.domain.portfolio_sort import SortConstituent, two_by_three_sort
from app.domain.valuation_view import hard_book_for
from app.models.corporate_actions import CorporateAction
from app.models.enums import CorporateActionType
from app.models.float_data import FloatData
from app.models.macro import MacroSeries
from app.models.prices import PriceDaily
from app.models.securities import Security

#: Types whose confirmed `ratio` changes real share count — the four this
#: module reconstructs history through. DIVIDEND_CASH is deliberately
#: absent (no share-count effect).
_SHARE_COUNT_ACTION_TYPES = frozenset(
    {
        CorporateActionType.BONUS_ISSUE,
        CorporateActionType.RIGHTS_ISSUE,
        CorporateActionType.STOCK_SPLIT,
        CorporateActionType.CONSOLIDATION,
    }
)

FORMATION_CADENCE_DAYS = 7
HARD_BOOK_REFRESH_CADENCE_DAYS = 30
AMIHUD_TRAILING_DAYS = 90
COMPUTED_SOURCE = "computed:factor_series_view"

#: Safely before this system's own real price history (2023-07-04) — see
#: `_load_shares_issued`'s own docstring for why the oldest reconstructed
#: shares-issued point is re-stamped to this date rather than left at its
#: own breakpoint.
_SENTINEL_EARLIEST_DATE = dt.date(2000, 1, 1)


@dataclass(frozen=True)
class FactorSeriesBuildSummary:
    formation_dates_attempted: int
    rows_written: dict[str, int]
    """Keyed by `series_id` — how many real weekly rows each factor
    actually got, which can differ per factor (a week can produce SMB/
    HML_hard but fail LIQ if too few tickers have enough Amihud history,
    for instance)."""
    warnings: tuple[str, ...]


def _load_price_history(db: Session) -> dict[str, list[tuple[dt.date, Decimal, Decimal, int | None]]]:
    """`dict[ticker] -> sorted [(date, close, adj_factor, volume), ...]`
    — one bulk query, the whole real point of this module."""
    rows = db.execute(
        select(PriceDaily.ticker, PriceDaily.date, PriceDaily.close, PriceDaily.adj_factor, PriceDaily.volume)
        .where(PriceDaily.close.is_not(None))
        .order_by(PriceDaily.ticker, PriceDaily.date)
    ).all()
    by_ticker: dict[str, list[tuple[dt.date, Decimal, Decimal, int | None]]] = {}
    for ticker, date, close, adj_factor, volume in rows:
        by_ticker.setdefault(ticker, []).append((date, close, adj_factor, volume))
    return by_ticker


def _load_shares_issued(db: Session) -> dict[str, list[tuple[dt.date, int]]]:
    """A REAL reconstructed history, not a single snapshot held constant.

    PER LISTED LINE, DELIBERATELY — NOT summed across an issuer's share
    classes the way `app.domain.market_cap_view.latest_shares_issued_all_
    classes` does for valuation. Raised in the 29 Aug 2026 audit and kept
    as-is on purpose, because the two cases are genuinely different:
    dividing a company-wide `total_equity` by one class's share count is
    an unambiguous numerator/denominator mismatch (it produced HNB.X0000's
    2,400 book value against a true ~487), whereas `own price x own
    shares` is internally consistent and is the ordinary security-level
    convention for a size sort. Which of the two a factor library SHOULD
    use for a dual-class issuer is a methodology choice with no single
    right answer, and changing it here would silently move SMB/HML/MOM/LIQ
    and everything downstream of them (Carhart certification, the timing
    battery, the §38 composite score) with no validation that the result
    is better. Its one real cost, stated rather than hidden: the 20
    `.X0000` non-voting lines are sorted on their own class's market cap,
    so a large bank's non-voting line sits in a smaller size bucket than
    the issuer as a whole would.

    `float_data` in this system's real dev database carries exactly one
    real `shares_issued` snapshot per ticker (captured 2026-08-18/19,
    `app.ingestion.security_enrichment`'s own current-state-only scrape
    — there is no historical share-count series anywhere in this
    system). Naively treating that single point as valid for every
    earlier formation week would be WRONG, not just approximate, for any
    ticker with a real share-count-changing event in between — and this
    system already has real, confirmed data to correct for exactly that:
    `corporate_actions` rows of type BONUS_ISSUE/RIGHTS_ISSUE/
    STOCK_SPLIT/CONSOLIDATION, each with a real confirmed `ratio` and
    `ex_date`. Checked live against the real dev DB: only 3 such
    confirmed actions exist across the whole 2023-07-04+ window (ACL.
    N0000 stock split, ACME.N0000 and AAF.N0000 rights issues) — small
    enough to walk backward through exactly, not a reason to skip this
    and accept the naive constant.

    Walks backward from the one known current snapshot through every
    confirmed share-count-changing action for that ticker, most recent
    first, computing what share count must have existed just BEFORE each
    one: `shares_before = shares_after / (1 + ratio)` for BONUS_ISSUE/
    RIGHTS_ISSUE/STOCK_SPLIT (ratio = new shares per share held — see
    `app.domain.corporate_actions.price_ratio_for_event`'s own identical
    convention), `shares_before = shares_after * ratio` for CONSOLIDATION
    (ratio = old shares per new share — the reverse direction, per
    `app.api.routes.corporate_actions._validate_confirmable`'s own
    documented convention for that type).

    For the 287/290 tickers with no such confirmed action at all, this
    produces the exact same single-point series `FloatData` already
    gives — the reconstruction changes nothing where there is nothing
    real to correct for."""
    latest_rows = db.execute(
        select(FloatData.ticker, FloatData.as_of, FloatData.shares_issued).order_by(FloatData.ticker, FloatData.as_of.desc())
    ).all()
    latest_by_ticker: dict[str, tuple[dt.date, int]] = {}
    for ticker, as_of, shares in latest_rows:
        latest_by_ticker.setdefault(ticker, (as_of, shares))  # first row per ticker, since ordered desc

    actions = db.execute(
        select(CorporateAction.ticker, CorporateAction.ex_date, CorporateAction.type, CorporateAction.ratio)
        .where(CorporateAction.confirmed_by.is_not(None), CorporateAction.type.in_(_SHARE_COUNT_ACTION_TYPES))
        .order_by(CorporateAction.ticker, CorporateAction.ex_date.desc())
    ).all()
    actions_by_ticker: dict[str, list[tuple[dt.date, CorporateActionType, Decimal | None]]] = {}
    for ticker, ex_date, action_type, ratio in actions:
        actions_by_ticker.setdefault(ticker, []).append((ex_date, action_type, ratio))

    by_ticker: dict[str, list[tuple[dt.date, int]]] = {}
    for ticker, (snapshot_date, snapshot_shares) in latest_by_ticker.items():
        points: list[tuple[dt.date, int]] = [(snapshot_date, snapshot_shares)]
        current_shares = Decimal(snapshot_shares)
        for ex_date, action_type, ratio in actions_by_ticker.get(ticker, []):
            if ratio is None or ex_date > snapshot_date:
                continue
            if action_type == CorporateActionType.CONSOLIDATION:
                shares_before = current_shares * ratio
            else:
                shares_before = current_shares / (1 + ratio)
            # The reconstructed count applies from just before this
            # action's ex_date, back to whatever the NEXT (earlier)
            # action pushes it further. Represented as a breakpoint at
            # `ex_date - 1 day` so `_most_recent_on_or_before(..., ex_date)`
            # still correctly returns the POST-action (current) count on
            # the ex_date itself, matching how every other point-in-time
            # lookup in this system treats an effective date as inclusive.
            points.append((ex_date - dt.timedelta(days=1), int(shares_before)))
            current_shares = shares_before
        points.sort(key=lambda p: p[0])
        # The OLDEST reconstructed point must cover every earlier date
        # too, not just from its own breakpoint onward — re-stamped to a
        # sentinel date safely before this system's own real price
        # history (2023-07-04) so `_most_recent_on_or_before` treats it
        # as "the best known count for any date this far back or later,
        # until the next real breakpoint" rather than leaving everything
        # before the oldest action's ex_date uncovered. For a ticker
        # with NO confirmed share-count action at all (287 of 290 real
        # tickers), this is the ONLY point, and the same re-stamping is
        # exactly what makes the one real current snapshot usable as a
        # backward-held-constant value for the whole window — the
        # correct behaviour, not an oversight, since "no confirmed
        # action" genuinely means "no known change."
        oldest_date, oldest_shares = points[0]
        points[0] = (_SENTINEL_EARLIEST_DATE, oldest_shares)
        by_ticker[ticker] = points
    return by_ticker


def _most_recent_on_or_before(dated: list[tuple], as_of: dt.date) -> tuple | None:
    """Generic "most recent tuple on or before `as_of`" over a list
    sorted ascending by its first (date) element — the one point-in-time
    lookup rule every input in this module shares."""
    dates = [d[0] for d in dated]
    idx = bisect.bisect_right(dates, as_of) - 1
    return dated[idx] if idx >= 0 else None


def _weekly_return(closes: list[tuple[dt.date, Decimal, Decimal, int | None]], start: dt.date, end: dt.date) -> Decimal | None:
    start_row = _most_recent_on_or_before(closes, start)
    end_row = _most_recent_on_or_before(closes, end)
    if start_row is None or end_row is None:
        return None
    start_adj = start_row[1] * start_row[2]
    end_adj = end_row[1] * end_row[2]
    if start_adj <= 0:
        return None
    return (end_adj / start_adj) - 1


def _market_cap(
    closes: list[tuple[dt.date, Decimal, Decimal, int | None]],
    shares: list[tuple[dt.date, int]],
    as_of: dt.date,
) -> Decimal | None:
    close_row = _most_recent_on_or_before(closes, as_of)
    shares_row = _most_recent_on_or_before(shares, as_of)
    if close_row is None or shares_row is None:
        return None
    return compute_market_cap(shares_row[1], close_row[1])  # raw close, matching market_cap_view's own convention


def _amihud_style_value(
    closes: list[tuple[dt.date, Decimal, Decimal, int | None]], as_of: dt.date
) -> Decimal | None:
    """Trailing `AMIHUD_TRAILING_DAYS` of real daily returns/turnover
    ending on or before `as_of`, turnover as `close × volume` (§ app.
    domain.liquidity's own documented convention — `PriceDaily.turnover`
    is unpopulated for almost all backfilled rows)."""
    window_start = as_of - dt.timedelta(days=AMIHUD_TRAILING_DAYS)
    window = [r for r in closes if window_start <= r[0] <= as_of]
    if len(window) < 2:
        return None
    returns: list[Decimal] = []
    turnovers: list[Decimal] = []
    prev_adj: Decimal | None = None
    for date, close, adj_factor, volume in window:
        adj = close * adj_factor
        if prev_adj is not None and prev_adj > 0:
            returns.append(abs((adj - prev_adj) / prev_adj))
            turnovers.append(close * Decimal(volume or 0))
        prev_adj = adj
    return amihud_illiquidity_ratio(returns, turnovers)


def weekly_risk_free_rate(db: Session, as_of: dt.date) -> Decimal | None:
    """§35.1's own literal choice: the 91-day T-bill's weekly primary-
    market yield, compounded down to a weekly return."""
    row = db.scalar(
        select(MacroSeries)
        .where(MacroSeries.series_id == SERIES_TBILL_91D, MacroSeries.first_available_date <= as_of)
        .order_by(MacroSeries.obs_date.desc())
        .limit(1)
    )
    if row is None:
        return None
    annual = float(row.value)
    weekly = (1.0 + annual) ** (1.0 / 52.0) - 1.0
    return Decimal(str(round(weekly, 10)))


def _hard_book_style_values(
    db: Session, tickers: list[str], formation_dates: list[dt.date]
) -> dict[str, list[tuple[dt.date, Decimal | None]]]:
    """One real `hard_book_for` call per ticker per
    `HARD_BOOK_REFRESH_CADENCE_DAYS`-spaced checkpoint spanning the whole
    build window — forward-filled across the weeks between checkpoints.
    See module docstring for why this one input alone isn't bulk-
    reimplemented."""
    if not formation_dates:
        return {}
    start, end = formation_dates[0], formation_dates[-1]
    checkpoints: list[dt.date] = []
    d = start
    while d <= end:
        checkpoints.append(d)
        d += dt.timedelta(days=HARD_BOOK_REFRESH_CADENCE_DAYS)
    if checkpoints[-1] != end:
        checkpoints.append(end)

    result: dict[str, list[tuple[dt.date, Decimal | None]]] = {}
    for ticker in tickers:
        points: list[tuple[dt.date, Decimal | None]] = []
        for cp in checkpoints:
            view = hard_book_for(db, ticker, cp)
            value = view.result.hard_book_value if view.result is not None else None
            points.append((cp, value))
        result[ticker] = points
    return result


def rebuild_factor_series(
    db: Session,
    *,
    as_of: dt.date | None = None,
    on_progress: Callable[[int, int, str], bool] | None = None,
) -> FactorSeriesBuildSummary:
    """Builds and persists §35's five weekly factor return series over
    this system's real full `prices_daily` depth, up to `as_of` (default:
    today). Idempotent by `(series_id, obs_date)` — a re-run overwrites
    that week's row with a freshly-recomputed one rather than duplicating
    it, the same "safe to run again" discipline `app.ingestion.
    price_loader.upsert_eod_prices` already establishes for daily prices.

    `on_progress(done, total, message)` — matches `app.jobs.runner`'s own
    `_set_progress` shape; return `False` to request early stop (checked
    between formation weeks, never mid-week)."""
    stamp = as_of or dt.date.today()
    tickers = list(db.scalars(select(Security.ticker)).all())

    price_history = _load_price_history(db)
    shares_issued = _load_shares_issued(db)

    all_dates = [d for series in price_history.values() for d, *_ in series]
    if not all_dates:
        return FactorSeriesBuildSummary(formation_dates_attempted=0, rows_written={}, warnings=("no real price history at all",))
    earliest, latest = min(all_dates), min(max(all_dates), stamp)

    formation_dates: list[dt.date] = []
    d = earliest + dt.timedelta(weeks=1)  # first week needs a real prior formation point to return FROM
    while d <= latest:
        formation_dates.append(d)
        d += dt.timedelta(days=FORMATION_CADENCE_DAYS)

    hard_book_by_ticker = _hard_book_style_values(db, tickers, formation_dates)

    rows_written: dict[str, int] = {sid: 0 for sid in ALL_FACTOR_SERIES_IDS}
    warnings: list[str] = []
    existing = {
        (row.series_id, row.obs_date)
        for row in db.scalars(select(MacroSeries).where(MacroSeries.series_id.in_(ALL_FACTOR_SERIES_IDS)))
    }

    def _write(series_id: str, obs_date: dt.date, value: Decimal) -> None:
        key = (series_id, obs_date)
        if key in existing:
            row = db.scalar(
                select(MacroSeries).where(MacroSeries.series_id == series_id, MacroSeries.obs_date == obs_date)
            )
            row.value = value
        else:
            db.add(
                MacroSeries(
                    series_id=series_id, obs_date=obs_date, first_available_date=obs_date,
                    value=value, source=COMPUTED_SOURCE,
                )
            )
            existing.add(key)
        rows_written[series_id] += 1

    for i, t in enumerate(formation_dates):
        t_prev = t - dt.timedelta(days=FORMATION_CADENCE_DAYS)

        hml_hard_constituents: list[SortConstituent] = []
        mom_constituents: list[SortConstituent] = []
        liq_constituents: list[SortConstituent] = []
        mkt_inputs: list[MarketWeightedInput] = []

        for ticker in tickers:
            closes = price_history.get(ticker)
            if not closes:
                continue
            cap = _market_cap(closes, shares_issued.get(ticker, []), t)
            period_return = _weekly_return(closes, t_prev, t)
            if cap is None or cap <= 0 or period_return is None:
                continue

            mkt_inputs.append(MarketWeightedInput(ticker=ticker, market_cap=cap, period_return=period_return))

            adj_closes = [(dte, cl * af) for dte, cl, af, _vol in closes]
            mom_style = mom_style_value(adj_closes, t)
            if mom_style is not None:
                mom_constituents.append(
                    SortConstituent(key=ticker, size_value=cap, style_value=mom_style, period_return=period_return)
                )

            liq_style = _amihud_style_value(closes, t)
            if liq_style is not None:
                liq_constituents.append(
                    SortConstituent(key=ticker, size_value=cap, style_value=liq_style, period_return=period_return)
                )

            hard_book_points = hard_book_by_ticker.get(ticker, [])
            hb = _most_recent_on_or_before(hard_book_points, t)
            if hb is not None and hb[1] is not None and hb[1] > 0:
                hml_hard_constituents.append(
                    SortConstituent(key=ticker, size_value=cap, style_value=hb[1] / cap, period_return=period_return)
                )

        rf = weekly_risk_free_rate(db, t)
        mkt = value_weighted_return(mkt_inputs)
        if mkt is not None and rf is not None:
            _write(SERIES_FACTOR_MKT_RF, t, mkt - rf)
        else:
            warnings.append(f"{t}: MKT-RF not computable ({len(mkt_inputs)} eligible tickers, rf={rf})")

        hml_result = two_by_three_sort(hml_hard_constituents)
        if hml_result is not None:
            _write(SERIES_FACTOR_HML_HARD, t, hml_result.style_factor_return)
            _write(SERIES_FACTOR_SMB, t, hml_result.size_factor_return)
        else:
            warnings.append(f"{t}: HML_hard/SMB not computable ({len(hml_hard_constituents)} eligible tickers)")

        mom_result = two_by_three_sort(mom_constituents)
        if mom_result is not None:
            _write(SERIES_FACTOR_MOM, t, mom_result.style_factor_return)
        else:
            warnings.append(f"{t}: MOM not computable ({len(mom_constituents)} eligible tickers)")

        liq_result = two_by_three_sort(liq_constituents)
        if liq_result is not None:
            _write(SERIES_FACTOR_LIQ, t, liq_result.style_factor_return)
        else:
            warnings.append(f"{t}: LIQ not computable ({len(liq_constituents)} eligible tickers)")

        if on_progress is not None:
            keep_going = on_progress(i + 1, len(formation_dates), f"formation week {t.isoformat()}")
            if keep_going is False:
                warnings.append(f"stopped early after {t} on caller request")
                break

    db.commit()
    return FactorSeriesBuildSummary(
        formation_dates_attempted=len(formation_dates), rows_written=rows_written, warnings=tuple(warnings),
    )
