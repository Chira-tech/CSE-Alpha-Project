"""
Bridges stored `macro_series` rows to `app.domain.regime_classification`
— the I/O layer that module deliberately doesn't have, the same split
`app.domain.cost_of_equity_view`/`app.domain.valuation_view` already draw
for §17/§18-26.

WHICH REAL SERIES THIS ACTUALLY USES, AND WHY NOT MORE. §29 names roughly
14 series across seven blocks; this system has real ingested coverage of
five: the policy rate, the 364-day T-bill primary yield, CCPI y/y, the
USD/LKR TT buying rate (all via `app.domain.cbsl_parsing`), and the §29
hero spread itself (`app.domain.macro_view.current_spread`, which is
itself built from the market P/E and the T-bill yield). No gross-
reserves series is ingested anywhere in this system, so `reserves_trend_
signal` is never built here — not because the signal function doesn't
exist (it does, tested, in `regime_classification.py`), but because
there is no real data to feed it, and this module never fabricates a
reading. Real economy (GDP/PMI/exports), fiscal/sovereign, and global
blocks are entirely unwired, the same honestly-named gap ROADMAP.md
tracks for the rest of §29's variable set.

THE STATISTICAL READ'S DATA SOURCE. `app.domain.index_history_loader`
backfills roughly a year of real ASPI daily closes into `macro_series`
under `SERIES_ASPI` — the only series in this system's macro layer with
plausible year-long depth, and therefore the only one used for the
Markov-switching fit. Log returns, not simple returns, computed here
from consecutive closes (`ln(close_t / close_t-1)`) — the standard
convention for a returns series that will be fed to a model built around
an additive mean/variance decomposition, since log returns compound
additively across periods where simple returns don't.
"""
from __future__ import annotations

import datetime as dt
import math
import threading
import time
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.cbsl_parsing import (
    SERIES_CCPI_YOY,
    SERIES_POLICY_RATE,
    SERIES_TBILL_364D,
    SERIES_USD_LKR_BUY,
)
from app.domain.macro import SERIES_ASPI
from app.domain.macro_view import current_spread, series_history
from app.domain.regime_classification import (
    MacroSignal,
    MarkovRegimeRead,
    RegimeLabel,
    RegimeRead,
    classify_composite_regime,
    classify_regime,
    currency_trend_signal,
    fit_markov_regime_read,
    hero_spread_signal,
    inflation_vs_target_signal,
    policy_rate_direction_signal,
    tbill_yield_trend_signal,
)

#: How far back to look for a "trend" reading on a continuous daily
#: series (currency) — 30 calendar days, matching §32's own worked
#: example framing ("stabilised recently after policy action", a
#: recent-weeks characterisation, not a multi-month one).
CURRENCY_TREND_WINDOW_DAYS = 30


def _latest_two(db: Session, series_id: str, as_of: dt.date) -> tuple[object, object] | None:
    """The two most recent DISTINCT observations of a series, oldest
    first — what a "direction" signal (policy rate, T-bill yield) needs.
    `None` when fewer than two observations are visible as of `as_of`."""
    rows = series_history(db, series_id, as_of, limit=2)
    if len(rows) < 2:
        return None
    return rows[0], rows[1]


def _latest_and_window_ago(
    db: Session, series_id: str, as_of: dt.date, window_days: int
) -> tuple[object, object] | None:
    """The latest observation and the most recent observation at or
    before `window_days` calendar days earlier — what a "trend over the
    window" signal (currency) needs. `None` when there's no observation
    old enough to compare against, which is the honest state for a
    freshly-started series rather than comparing across too short a gap."""
    rows = series_history(db, series_id, as_of, limit=500)
    if len(rows) < 2:
        return None
    current = rows[-1]
    target_date = current.obs_date - dt.timedelta(days=window_days)
    candidates = [r for r in rows if r.obs_date <= target_date]
    if not candidates:
        return None
    return current, candidates[-1]


def regime_signals_for(db: Session, as_of: dt.date) -> tuple[list[MacroSignal], list[str]]:
    """Every composite-read signal this system can currently build from
    real `macro_series` data, plus a list naming which ones it couldn't
    (and why) — mirrors `app.domain.valuation_view._confirmable_line_
    items`'s `(items, excluded)` shape, just for macro signals instead of
    company fundamentals."""
    signals: list[MacroSignal] = []
    missing: list[str] = []

    spread = current_spread(db, as_of)
    if spread is not None:
        signals.append(hero_spread_signal(spread.spread))
    else:
        missing.append("§29 hero spread (needs both a market P/E and a T-bill observation).")

    policy_pair = _latest_two(db, SERIES_POLICY_RATE, as_of)
    if policy_pair is not None:
        previous, current = policy_pair
        signals.append(policy_rate_direction_signal(current.value, previous.value))
    else:
        missing.append("Policy rate direction (needs 2+ cbsl.policy_rate observations).")

    tbill_pair = _latest_two(db, SERIES_TBILL_364D, as_of)
    if tbill_pair is not None:
        previous, current = tbill_pair
        signals.append(tbill_yield_trend_signal(current.value, previous.value))
    else:
        missing.append("364-day T-bill yield trend (needs 2+ cbsl.tbill_364d observations).")

    ccpi_row = series_history(db, SERIES_CCPI_YOY, as_of, limit=1)
    if ccpi_row:
        signals.append(inflation_vs_target_signal(ccpi_row[-1].value))
    else:
        missing.append("CCPI vs target (needs a cbsl.ccpi_yoy observation).")

    usd_lkr_pair = _latest_and_window_ago(db, SERIES_USD_LKR_BUY, as_of, CURRENCY_TREND_WINDOW_DAYS)
    if usd_lkr_pair is not None:
        current, previous = usd_lkr_pair
        if previous.value != 0:
            pct_change = (current.value - previous.value) / previous.value
            signals.append(currency_trend_signal(pct_change))
        else:
            missing.append("LKR/USD trend (previous observation was zero).")
    else:
        missing.append(
            f"LKR/USD trend (needs a cbsl.usd_lkr_tt_buying observation at least "
            f"{CURRENCY_TREND_WINDOW_DAYS} days before another one)."
        )

    missing.append(
        "Reserves trend, real-economy (GDP/PMI/exports), fiscal/sovereign and global "
        "blocks — no series ingested for any of these yet (§29's remaining variable set)."
    )

    return signals, missing


def _aspi_log_returns(db: Session, as_of: dt.date, limit: int = 400) -> list[tuple[dt.date, Decimal]]:
    """Log returns from consecutive real ASPI closes — see module
    docstring for why log returns specifically. `limit` caps how far back
    to look; 400 comfortably covers the ~1 year `index_history_loader`
    backfills, with headroom rather than cutting it exactly at the
    boundary.

    Each return is paired with `curr`'s own `obs_date` — a bad row can be
    skipped below, so a caller that wants to re-align a per-return result
    (`MarkovRegimeRead.history`) back onto real calendar dates needs the
    dates carried alongside the values, not re-derived by zipping against
    `rows` afterward, which would silently misalign the moment any row is
    skipped."""
    rows = series_history(db, SERIES_ASPI, as_of, limit=limit)
    if len(rows) < 2:
        return []
    returns: list[tuple[dt.date, Decimal]] = []
    for prev, curr in zip(rows, rows[1:]):
        if prev.value <= 0 or curr.value <= 0:
            continue  # a non-positive index level is a data error, not a real return
        returns.append((curr.obs_date, Decimal(str(math.log(float(curr.value) / float(prev.value))))))
    return returns


@dataclass(frozen=True)
class RegimeView:
    as_of: dt.date
    result: RegimeRead | None
    signals: tuple[MacroSignal, ...]
    statistical: MarkovRegimeRead | None
    missing_signals: tuple[str, ...]
    warnings: tuple[str, ...]

    regime_history: tuple[tuple[dt.date, RegimeLabel], ...] = ()
    """`statistical.history` re-aligned onto real calendar dates — one
    (date, label) pair per real ASPI trading day the Markov fit ran over.
    Empty when `statistical` is None. Statistical-read-only, same caveat
    as `MarkovRegimeRead.history` — not the 50/50 blend `result.label`
    is."""


# --- Disclosed-TTL cache -------------------------------------------------
# `regime_for` runs a real Markov-switching MLE fit on the ASPI return
# series (`fit_markov_regime_read`) — measured at ~3.8s cold. It is a
# MARKET-WIDE read: one value for the whole market on a given date,
# identical for every ticker, and called by `GET /market`, `/valuation/
# {ticker}`, `/composite-score/{ticker}`, `/opportunities` and `/market/
# sector-sensitivity`. The regime does not change intraday, so this is
# the same module-level `{key: (ts, RegimeView)}` + lock + short TTL
# pattern `app.domain.opportunity_ranking_view` established, with a longer
# 15-minute window since a Markov regime genuinely moves on a scale of
# weeks. `RegimeView` is a frozen dataclass, safe to share. `clear_cache`
# is the test escape hatch.
_REGIME_TTL_SECONDS = 15 * 60
_regime_lock = threading.Lock()
_regime_cache: dict[tuple[dt.date, int], tuple[float, "RegimeView"]] = {}


def clear_cache() -> None:
    with _regime_lock:
        _regime_cache.clear()


def regime_for(db: Session, as_of: dt.date | None = None, *, k_regimes: int = 2) -> RegimeView:
    """§29-33's regime read, live — `app.domain.regime_classification.
    classify_regime` fed by whatever real composite signals and real
    ASPI return history actually exist as of `as_of`. Never fabricates a
    read: `result` is `None` when neither a composite signal nor a long
    enough return series exists, the same "None, named" discipline every
    other live-wired view in this system uses.

    Cached at module level with a disclosed 15-minute TTL — see the
    comment above the cache for why (a ~3.8s Markov fit, market-wide,
    called by five endpoints).
    """
    stamp = as_of or dt.date.today()

    key = (stamp, k_regimes)
    with _regime_lock:
        hit = _regime_cache.get(key)
        if hit is not None and (time.monotonic() - hit[0]) < _REGIME_TTL_SECONDS:
            return hit[1]

    view = _regime_for_uncached(db, stamp, k_regimes)

    with _regime_lock:
        _regime_cache[key] = (time.monotonic(), view)
        stale = [
            k for k, v in _regime_cache.items()
            if k != key and (time.monotonic() - v[0]) >= _REGIME_TTL_SECONDS
        ]
        for k in stale:
            del _regime_cache[k]
    return view


def _regime_for_uncached(db: Session, stamp: dt.date, k_regimes: int) -> RegimeView:
    signals, missing = regime_signals_for(db, stamp)
    composite = classify_composite_regime(signals)

    dated_returns = _aspi_log_returns(db, stamp)
    returns = [v for _, v in dated_returns]
    statistical = fit_markov_regime_read(returns, k_regimes=k_regimes)

    warnings: list[str] = []
    if statistical is None:
        warnings.append(
            f"No statistical Markov-switching read: {len(returns)} real ASPI log-return "
            "observations available, below the minimum needed for a stable fit (or the fit "
            "did not converge)."
        )
    if composite is None:
        warnings.append("No composite rule-based read: zero real macro signals available.")

    result = classify_regime(composite, statistical)
    if result is None:
        warnings.append("No regime read at all — see the two reasons above.")

    # `fit_markov_regime_read` returns one history entry per input
    # `returns` value, same order — so it re-zips cleanly onto the dates
    # `_aspi_log_returns` kept alongside those same values.
    regime_history: tuple[tuple[dt.date, RegimeLabel], ...] = ()
    if statistical is not None:
        regime_history = tuple(
            (date, label)
            for (date, _), label in zip(dated_returns, statistical.history)
        )

    return RegimeView(
        as_of=stamp,
        result=result,
        signals=tuple(signals),
        statistical=statistical,
        missing_signals=tuple(missing),
        warnings=tuple(warnings),
        regime_history=regime_history,
    )
