"""
Bridges stored `Fundamental` rows to the pure ratio engine.

Kept separate from app.domain.ratios so that module stays free of ORM
types and remains directly testable against hand-computed figures.

The point-in-time rule applies here as everywhere: line items are
selected through `first_available_date <= as_of`, never `period_end`
(§6). A ratio computed from a restatement the market hadn't seen yet is
the exact look-ahead bias Part N #1 calls the most common source of alpha
that does not exist.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.point_in_time import fundamentals_as_of
from app.domain.provenance import can_enter_valuation
from app.domain.ratios import LineItem, RatioResult, compute_all
from app.domain.trend_detection import RatioSeriesPoint, RatioTrend, analyse_ratio_trend
from app.domain.ttm import trailing_twelve_months
from app.models.fundamentals import Fundamental


#: Flow-type statement lines that some §12 ratio (`app.domain.ratios`)
#: divides by a STOCK (balance-sheet, point-in-time) quantity rather than
#: another flow from the same period: `net_income` (return_on_equity,
#: return_on_assets) and `gross_profit` (gross_profitability — Novy-
#: Marx's gross-profit-to-assets). Left as a single quarter's raw
#: cumulative figure, either reads as roughly a quarter of its true
#: annualised value — the exact COMB "sell a healthy bank" bug
#: `app.domain.ttm` was built to close.
#:
#: Deliberately does NOT include `revenue`/`operating_profit`/`cost_of_
#: sales`: every ratio those feed (gross_margin, operating_margin, net_
#: margin) divides one flow by ANOTHER flow from the identical period, so
#: a same-period ratio is already correct un-annualised — and this is
#: EXACTLY why the annualised view is never allowed to silently replace
#: the raw one (see `ratios_for`'s own docstring for the real regression
#: an earlier version of this fix introduced by doing that): pairing an
#: annualised `net_income`/`gross_profit` against a raw-period `revenue`
#: would overstate net_margin/gross_margin by roughly the same factor
#: annualisation corrects for on the other side.
_FLOW_LINES_NEEDING_ANNUALISATION: tuple[str, ...] = ("net_income", "gross_profit")

#: Which §12 ratios need the ANNUALISED view of their flow inputs (flow ÷
#: stock — a balance-sheet quantity doesn't shrink to a quarter's worth)
#: versus the RAW, as-filed view every other ratio correctly wants (flow
#: ÷ flow from the identical period). `ratios_for`/`all_sector_
#: percentiles` compute the full ratio set against BOTH views and pick
#: each ratio's result from whichever one its own formula actually needs
#: — never a single shared view for every ratio, which is where an
#: earlier version of this fix went wrong.
_RATIOS_NEEDING_ANNUALISED_FLOW_INPUTS: frozenset[str] = frozenset(
    {"return_on_equity", "return_on_assets", "gross_profitability"}
)


def _raw_latest_period_items(
    rows: list[Fundamental],
) -> tuple[dt.date | None, dict[str, LineItem], dict[str, str]]:
    """The latest period's line items exactly as filed — no annualisation
    applied. Returns (period_end, items, period_type_by_line), the last
    of which `ttm_adjusted_copy` needs to know which of `items` came
    from a quarterly vs annual filing. Shared by every caller below so
    "what counts as the latest period, and what to do about a repeated
    statement_line" is decided in exactly one place."""
    if not rows:
        return None, {}, {}
    latest_period = max(r.period_end for r in rows)
    items: dict[str, LineItem] = {}
    period_type_by_line: dict[str, str] = {}
    for row in rows:
        if row.period_end != latest_period:
            continue
        # fundamentals_as_of already resolves restatement versions; if the
        # same line still appears twice, prefer the higher version.
        if row.statement_line not in items:
            items[row.statement_line] = LineItem(value=row.value, provenance=row.provenance_tier)
            period_type_by_line[row.statement_line] = row.period_type
    return latest_period, items, period_type_by_line


def ttm_adjusted_copy(
    db: Session,
    ticker: str,
    as_of: dt.date,
    latest_period: dt.date,
    raw_items: dict[str, LineItem],
    period_type_by_line: dict[str, str],
) -> dict[str, LineItem]:
    """The real P0 TTM fix (`app.domain.ttm`), applied to every line in
    `_FLOW_LINES_NEEDING_ANNUALISATION` present for the latest period —
    returns a NEW dict; `raw_items` is never mutated, since callers
    computing a same-period (flow ÷ flow) ratio need the untouched
    original alongside this annualised view, not instead of it.

    Only applied when the line is itself already confirmed
    (`can_enter_valuation`): an AI-assisted figure is carried through
    as-is — `trailing_twelve_months` only ever reasons over CONFIRMED
    periods, so mixing an unconfirmed current period with confirmed
    history could silently pair mismatched dates. `None` back from
    `trailing_twelve_months` (not enough confirmed annual/quarterly
    history to annualise) means the item is DROPPED from this copy,
    never silently left at its un-annualised quarterly value — "refuse
    rather than guess," same as everywhere else in this pipeline.
    """
    items = dict(raw_items)
    for line in _FLOW_LINES_NEEDING_ANNUALISATION:
        if line not in items or not can_enter_valuation(items[line].provenance):
            continue
        line_period_type = period_type_by_line.get(line)
        if line_period_type is None:
            continue
        ttm_value = trailing_twelve_months(
            db, ticker, line, as_of,
            current_period_end=latest_period, current_period_type=line_period_type,
            current_value=items[line].value,
        )
        if ttm_value is not None:
            items[line] = LineItem(value=ttm_value, provenance=items[line].provenance)
        else:
            del items[line]
    return items


def compute_all_correctly_scoped(
    raw_items: dict[str, LineItem], ttm_items: dict[str, LineItem]
) -> list[RatioResult]:
    """Every §12 ratio, each read from whichever of the two views its OWN
    formula needs (see `_RATIOS_NEEDING_ANNUALISED_FLOW_INPUTS`'s own
    docstring) — never one shared view applied to every ratio, which
    silently overstated `gross_margin`/`net_margin` (annualised numerator
    ÷ raw-period denominator) the one time this fix tried that."""
    raw_results = {r.key: r for r in compute_all(raw_items)}
    ttm_results = {r.key: r for r in compute_all(ttm_items)}
    return [
        ttm_results[key] if key in _RATIOS_NEEDING_ANNUALISED_FLOW_INPUTS else raw_results[key]
        for key in raw_results
    ]


def latest_period_line_items(
    db: Session, ticker: str, as_of: dt.date, period_type: str | None = None
) -> tuple[dt.date | None, dict[str, LineItem]]:
    """Line items for the most recent period visible on `as_of`, with
    `net_income`/`gross_profit` annualised (TTM) when confirmed and
    computable — see `ttm_adjusted_copy`'s own docstring. Returns
    (period_end, items). Mixing periods would produce ratios whose
    numerator and denominator come from different dates — so this picks a
    single period and works only within it, even if that means fewer
    computable ratios.

    NOTE for callers computing more than one ratio from this dict: if any
    of them is a flow-over-flow margin ratio (`gross_margin`, `net_
    margin`), do NOT feed it this annualised dict directly — use
    `ratios_for` instead, which computes each ratio from the view it
    actually needs. This function stays a single-view convenience for
    callers (like the screener's ROE column) that only ever want ONE
    flow-over-stock ratio and never a margin ratio from the same dict.
    """
    rows: list[Fundamental] = fundamentals_as_of(db, ticker, as_of)
    if period_type is not None:
        rows = [r for r in rows if r.period_type == period_type]
    latest_period, raw_items, period_type_by_line = _raw_latest_period_items(rows)
    if latest_period is None:
        return None, {}
    ttm_items = ttm_adjusted_copy(db, ticker, as_of, latest_period, raw_items, period_type_by_line)
    return latest_period, ttm_items


def bulk_latest_line_items(
    db: Session, as_of: dt.date, statement_lines: tuple[str, ...]
) -> dict[str, tuple[dt.date, dict[str, LineItem]]]:
    """The same point-in-time-and-restatement-version rule
    `fundamentals_as_of` applies per ticker, but for EVERY ticker in one
    query rather than one call per ticker — the single-query discipline
    `app.api.routes.securities.list_securities` already applies to
    prices ("done as a subquery rather than N+1 per-ticker lookups"),
    now extended to fundamentals so a screener column can exist without
    284 round trips. Only fetches the named `statement_lines`, not every
    line on file, since a screener typically wants one or two ratios'
    worth of inputs, not a full statement.

    Returns `{ticker: (latest_period_end, {statement_line: LineItem})}` —
    tickers with nothing point-in-time-visible are simply absent, not
    present with an empty dict, so a caller's `.get(ticker)` naturally
    distinguishes "no data" from "data with a gap."

    REAL BUG, FOUND LIVE (20 Aug 2026): this function used to hand back
    `net_income` exactly as stored for the latest period — for a company
    whose latest CONFIRMED period is a single quarter (the common case),
    that is one quarter's profit, not a year's. Every caller of this
    function feeds it straight into a ratio whose formula assumes an
    annual figure (`return_on_equity`, `return_on_assets`) —
    `app.api.routes.securities.list_securities`'s own screener ROE
    column and every sector percentile in `app.domain.sector_percentiles_
    view` among them. This is EXACTLY the COMB "sell a healthy bank" bug
    the P0 fix (`app.domain.ttm`) closed for `latest_period_line_items`
    and the valuation engine's own `app.domain.valuation_view._
    confirmable_line_items` — just never ported to this THIRD call site.
    Confirmed live: NTB.N0000's real confirmed 30 June 2026 quarter shows
    net_income = 17,166,738,000, which this function used to hand back
    as-is — a real bank's ROA computed from ONE quarter's profit reading
    roughly a quarter of its true annualised figure, silently understating
    every screener/percentile rank that depends on it. `gross_profit`
    carries the identical risk for `gross_profitability` (gross profit ÷
    total assets — the same flow-over-stock shape as ROE/ROA); both are
    handled by the shared `ttm_adjusted_copy` below — see that
    function's own docstring for the full guard.

    This function itself only ever hands back the ANNUALISED view — safe
    for a caller (like the screener's own ROE-only fetch) that computes
    exactly one flow-over-stock ratio from it, but NOT safe to feed to
    `compute_all`/every §12 ratio the way `app.domain.sector_percentiles_
    view.all_sector_percentiles` needs to: a margin ratio computed from
    this same annualised dict would pair an annualised numerator against
    a raw-period `revenue`, the exact mismatch `ratios_for`'s own
    docstring found live once this fix first shipped. Callers computing
    more than the one flow-over-stock ratio must fetch the raw view
    (`_raw_latest_period_items`-style, per ticker) separately and merge
    via `compute_all_correctly_scoped`, the same way `ratios_for` and
    `all_sector_percentiles` do.

    A REAL, KNOWN cost, not a correctness issue: this reintroduces one
    extra query per (ticker, flow line) needing annualisation
    (`trailing_twelve_months`'s own per-ticker `fundamentals_as_of` call)
    — the exact N+1 pattern this function's own docstring says it exists
    to avoid. Traded deliberately for correctness: a fast, wrong
    percentile rank is worse than a somewhat slower, real one. A
    genuinely bulk TTM computation (one query for every ticker's
    historical flow lines, annualised in Python without a per-ticker
    round trip) would remove this cost — a real, separate piece of work,
    not attempted here.
    """
    raw = bulk_raw_latest_line_items(db, as_of, statement_lines)
    return {
        ticker: (
            latest_period,
            ttm_adjusted_copy(db, ticker, as_of, latest_period, raw_items, period_type_by_line),
        )
        for ticker, (latest_period, raw_items, period_type_by_line) in raw.items()
    }


def bulk_raw_latest_line_items(
    db: Session, as_of: dt.date, statement_lines: tuple[str, ...]
) -> dict[str, tuple[dt.date, dict[str, LineItem], dict[str, str]]]:
    """The same universe-wide fetch `bulk_latest_line_items` runs, but
    returning the RAW (un-annualised) view plus each line's period_type —
    what `all_sector_percentiles` needs to compute both the raw and TTM
    views itself and merge per-ratio via `compute_all_correctly_scoped`,
    rather than being handed one dict that silently means two different
    things depending on which ratio reads it (see `ratios_for`'s own
    docstring for the real regression that shape caused).
    """
    rows = db.scalars(
        select(Fundamental).where(
            Fundamental.statement_line.in_(statement_lines),
            Fundamental.first_available_date <= as_of,
        )
    ).all()

    # ticker -> period_end -> statement_line -> highest-version row visible by as_of
    by_ticker: dict[str, dict[dt.date, dict[str, Fundamental]]] = {}
    for row in rows:
        by_period = by_ticker.setdefault(row.ticker, {})
        by_line = by_period.setdefault(row.period_end, {})
        existing = by_line.get(row.statement_line)
        if existing is None or row.version > existing.version:
            by_line[row.statement_line] = row

    result: dict[str, tuple[dt.date, dict[str, LineItem], dict[str, str]]] = {}
    for ticker, by_period in by_ticker.items():
        latest_period = max(by_period)
        latest_rows = by_period[latest_period]
        raw_items = {
            line: LineItem(value=f.value, provenance=f.provenance_tier)
            for line, f in latest_rows.items()
        }
        period_type_by_line = {line: f.period_type for line, f in latest_rows.items()}
        result[ticker] = (latest_period, raw_items, period_type_by_line)
    return result


def ratios_for(
    db: Session, ticker: str, as_of: dt.date | None = None, period_type: str | None = None
) -> tuple[dt.date | None, list[RatioResult]]:
    """Every §12 ratio for `ticker`'s most recent visible period, each
    computed from whichever view (raw or TTM-annualised) its own formula
    needs — see `compute_all_correctly_scoped`'s own docstring.

    REAL REGRESSION, FOUND LIVE (20 Aug 2026), IN THIS FIX'S OWN EARLIER
    VERSION: the first attempt at annualising `net_income`/`gross_profit`
    for return_on_equity/return_on_assets/gross_profitability mutated ONE
    shared `items` dict and fed that same dict to `compute_all` for EVERY
    ratio — correctly fixing the three flow-over-stock ratios, but
    silently BREAKING `gross_margin`/`net_margin` in the process: both
    divide a flow by ANOTHER flow from the identical period (`revenue`),
    so pairing the now-annualised numerator against `revenue`'s still-
    raw, single-quarter value overstated both margins by roughly the
    factor annualisation had just corrected for on the other side.
    Confirmed live: ACME.N0000's `gross_margin` read as 47166.0000 (a
    plain ratio, not a percentage) under that version of this fix. Fixed
    by computing the full ratio set against BOTH views and picking each
    ratio's own correct one, rather than ever exposing one dict that
    silently means two different things depending on which ratio reads
    it.
    """
    stamp = as_of or dt.date.today()
    rows = fundamentals_as_of(db, ticker, stamp)
    if period_type is not None:
        rows = [r for r in rows if r.period_type == period_type]
    latest_period, raw_items, period_type_by_line = _raw_latest_period_items(rows)
    if latest_period is None:
        return None, compute_all({})
    ttm_items = ttm_adjusted_copy(db, ticker, stamp, latest_period, raw_items, period_type_by_line)
    return latest_period, compute_all_correctly_scoped(raw_items, ttm_items)


def historical_ratios_for(
    db: Session, ticker: str, as_of: dt.date | None = None, period_type: str | None = None
) -> dict[dt.date, list[RatioResult]]:
    """Every point-in-time-visible period's ratios, keyed by period_end —
    the input `analyse_ratio_trend` (§13) needs, and the reason it lives
    next to `ratios_for` rather than in the trend module itself: this is
    the only place that owns turning stored `Fundamental` rows into
    ratios, and duplicating that logic elsewhere would risk the two
    falling out of sync.
    """
    stamp = as_of or dt.date.today()
    rows = fundamentals_as_of(db, ticker, stamp)
    if period_type is not None:
        rows = [r for r in rows if r.period_type == period_type]

    by_period: dict[dt.date, dict[str, LineItem]] = {}
    for row in rows:
        items = by_period.setdefault(row.period_end, {})
        existing = items.get(row.statement_line)
        if existing is None:
            items[row.statement_line] = LineItem(value=row.value, provenance=row.provenance_tier)

    return {period: compute_all(items) for period, items in sorted(by_period.items())}


def ratio_series_by_key(
    db: Session, ticker: str, as_of: dt.date | None = None, period_type: str | None = None
) -> dict[str, list[RatioSeriesPoint]]:
    """Every ratio's own `(period_end, value)` history, sorted oldest
    first — the raw series `ratio_trends_for` reduces down to a single
    direction/significance verdict, and that a company-file ratio card
    (R1 T4.3.1) needs in full to draw its own path (§12/§13: "ROE
    increased from 11% -> 14% -> 16% -> 18%" beats "ROE = 18%"), not just
    the reduced verdict. Shared with `ratio_trends_for` below so the two
    can never disagree about which periods or values went into a ratio."""
    by_period = historical_ratios_for(db, ticker, as_of, period_type)

    series_by_key: dict[str, list[RatioSeriesPoint]] = {}
    for period_end, results in by_period.items():
        for result in results:
            if result.value is None:
                continue
            series_by_key.setdefault(result.key, []).append(
                RatioSeriesPoint(period_end=period_end, value=result.value)
            )
    for series in series_by_key.values():
        series.sort(key=lambda p: p.period_end)
    return series_by_key


def ratio_trends_for(
    db: Session, ticker: str, as_of: dt.date | None = None, period_type: str | None = None
) -> dict[str, RatioTrend]:
    """§13's trend metadata for every ratio with at least one computed
    value across the visible history. A ratio present in only one period
    still appears here — `analyse_ratio_trend` reports
    `insufficient_history` for it explicitly rather than the ratio simply
    not showing up, which would look like an omission rather than a fact
    about the data."""
    series_by_key = ratio_series_by_key(db, ticker, as_of, period_type)
    return {key: analyse_ratio_trend(key, series) for key, series in series_by_key.items()}
