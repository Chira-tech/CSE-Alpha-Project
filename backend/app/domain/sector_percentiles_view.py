"""
DB-wired glue for `app.domain.sector_percentiles` (pure) — turns stored
`Security`/`Fundamental` rows into the universe-wide inputs that module
needs. Kept separate for the same reason `app.domain.fundamentals_view`
is kept separate from `app.domain.ratios`: the pure module stays free of
ORM types and directly testable against hand-built dicts.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.fundamentals_view import (
    bulk_raw_latest_line_items,
    compute_all_correctly_scoped,
    ttm_adjusted_copy,
)
from app.domain.ratios import DEFINITIONS
from app.domain.sector_percentiles import SectorPercentileResult, sector_percentiles_for_ratio
from app.models.securities import Security

#: The union of every §12 ratio's required line items — one bulk fetch
#: covers every ratio, not one fetch per ratio (same discipline
#: `app.api.routes.securities.list_securities` already applies for ROE
#: alone, extended here to the full ratio set).
_ALL_REQUIRED_LINE_ITEMS = tuple(sorted({field for d in DEFINITIONS for field in d.required}))

# --- Disclosed-TTL cache -------------------------------------------------
# `all_sector_percentiles` re-reads every ticker's confirmed line items,
# TTM-adjusts each, computes every §12 ratio and then sector-ranks all of
# them — ~1.4s, measured. It is universe-wide (a percentile needs every
# peer's value) and changes only when a fundamental is CONFIRMED, which is
# a deliberate batch action, never intraday. `GET /securities` (list),
# `GET /securities/{ticker}` (via `sector_percentiles_for`) and the §38
# composite score all hit it. Same module-level `{as_of: (ts, result)}`
# + lock + TTL pattern as `app.domain.opportunity_ranking_view`; 5-minute
# window. `clear_cache` is the test escape hatch (`conftest.py`).
_TTL_SECONDS = 5 * 60
_lock = threading.Lock()
_cache: dict[dt.date, tuple[float, dict[str, dict[str, "SectorPercentileResult"]]]] = {}


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def all_sector_percentiles(
    db: Session, as_of: dt.date | None = None
) -> dict[str, dict[str, SectorPercentileResult]]:
    """Every ticker's sector-relative percentile for every §12 ratio it
    has a computable value for, in one universe-wide pass.

    Percentiles are inherently a universe-wide concept — ranking one
    company needs every other company's value in its group — so there is
    no cheaper single-ticker version of this; `sector_percentiles_for`
    below just takes a slice of this same full computation, the same
    "one bulk query, not N per-ticker lookups" discipline `bulk_latest_
    line_items` itself already applies, extended one level further.

    Returns `{ticker: {ratio_key: SectorPercentileResult}}`. A ticker
    with no computable value for a given ratio simply has no entry for
    that ratio_key — the same "absent means no data" convention `bulk_
    raw_latest_line_items` itself uses, not a placeholder empty result.

    Each ratio is computed from whichever view (raw or TTM-annualised) its
    own formula needs, via `compute_all_correctly_scoped` — never one
    shared, already-annualised dict fed to every ratio indiscriminately,
    which is what an earlier version of this fix did and which silently
    overstated `gross_margin`/`net_margin` by pairing an annualised
    `net_income`/`gross_profit` against `revenue`'s still-raw, single-
    quarter value (see `app.domain.fundamentals_view.ratios_for`'s own
    docstring for the live regression this caused and how it was found).

    Cached at module level with a disclosed 5-minute TTL — see the comment
    above the cache.
    """
    stamp = as_of or dt.date.today()

    with _lock:
        hit = _cache.get(stamp)
        if hit is not None and (time.monotonic() - hit[0]) < _TTL_SECONDS:
            return hit[1]

    result = _all_sector_percentiles_uncached(db, stamp)

    with _lock:
        _cache[stamp] = (time.monotonic(), result)
        stale = [d for d, v in _cache.items() if d != stamp and (time.monotonic() - v[0]) >= _TTL_SECONDS]
        for d in stale:
            del _cache[d]
    return result


def _all_sector_percentiles_uncached(
    db: Session, stamp: dt.date
) -> dict[str, dict[str, SectorPercentileResult]]:
    sector_rows = db.execute(
        select(Security.ticker, Security.cse_sector, Security.gics_sector)
    ).all()
    narrow_sector_by_ticker = {ticker: cse for ticker, cse, _gics in sector_rows}
    wide_sector_by_ticker = {ticker: gics for ticker, _cse, gics in sector_rows}

    raw_by_ticker = bulk_raw_latest_line_items(db, stamp, _ALL_REQUIRED_LINE_ITEMS)
    ratio_results_by_ticker: dict[str, dict[str, Decimal]] = {}
    for ticker, (latest_period, raw_items, period_type_by_line) in raw_by_ticker.items():
        ttm_items = ttm_adjusted_copy(db, ticker, stamp, latest_period, raw_items, period_type_by_line)
        ratio_results_by_ticker[ticker] = {
            r.key: r.value
            for r in compute_all_correctly_scoped(raw_items, ttm_items)
            if r.value is not None
        }

    results: dict[str, dict[str, SectorPercentileResult]] = {ticker: {} for ticker, _, _ in sector_rows}
    for definition in DEFINITIONS:
        values_by_ticker: dict[str, Decimal] = {
            ticker: ticker_results[definition.key]
            for ticker, ticker_results in ratio_results_by_ticker.items()
            if definition.key in ticker_results
        }

        if not values_by_ticker:
            continue

        per_ticker = sector_percentiles_for_ratio(
            definition.key, values_by_ticker, narrow_sector_by_ticker, wide_sector_by_ticker
        )
        for ticker, result in per_ticker.items():
            results.setdefault(ticker, {})[definition.key] = result

    return results


def sector_percentiles_for(
    db: Session, ticker: str, as_of: dt.date | None = None
) -> dict[str, SectorPercentileResult]:
    """One ticker's slice of `all_sector_percentiles` — the shape `GET
    /securities/{ticker}` needs. Still runs the full universe-wide
    computation underneath; there is no cheaper single-ticker version of
    a percentile (see that function's own docstring)."""
    return all_sector_percentiles(db, as_of).get(ticker, {})
