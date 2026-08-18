"""
Bridges stored `prices_daily`/`macro_series` rows to `app.domain.
event_study` — the I/O layer that module deliberately doesn't have.

THE ONE REAL EVENT TYPE THIS SYSTEM CAN BUILD TODAY: CBSL POLICY RATE
CHANGES. §30 step 5's own text names five candidate event categories
("CARs around CBSL/CCPI/IMF/budget/election dates") — this module wires
exactly one, `"cbsl_policy_rate_change"`, because it is the only one
with a real, already-ingested date source: a genuine rate CHANGE is any
date where `cbsl.policy_rate`'s own stored value differs from its
immediately preceding real observation (not every date the series has
an observation — most of those are the rate simply being unchanged,
which is not an event). CCPI release dates, IMF programme milestones,
budget dates, and election dates all need a NEW real structured date
source this system does not have (a scraped or human-maintained
calendar, analogous to §34's national-project register) — a disclosed,
named scope boundary, not a silent omission.

TRADING-DAY WINDOWS, NOT CALENDAR-DAY OFFSETS. The estimation and event
windows are both measured in real trading days — positions in the
sorted list of dates where BOTH the ticker and the real ASPI market
proxy actually have a return, the intersection of `app.domain.price_
returns.ticker_adjusted_returns` and the ASPI's own daily return series
computed from `app.domain.macro_view.series_history`. An event date that
doesn't fall on (or isn't nearest to) a real trading day, or whose full
estimation/event window isn't entirely available within this system's
real ~1-year price history depth, is skipped and named — never silently
padded or shortened.
"""
from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.event_study import (
    DEFAULT_ESTIMATION_LENGTH,
    DEFAULT_EVENT_WINDOW,
    AggregateEventStudyResult,
    SingleEventResult,
    aggregate_car_across_events,
    single_event_market_model_car,
)
from app.domain.macro import SERIES_ASPI, SERIES_POLICY_RATE
from app.domain.macro_view import series_history
from app.domain.price_returns import ticker_adjusted_returns

DEFAULT_LOOKBACK_DAYS = 400

SUPPORTED_EVENT_TYPES = ("cbsl_policy_rate_change",)


def policy_rate_change_dates(db: Session, as_of: dt.date, lookback_days: int) -> list[dt.date]:
    """Real dates where `cbsl.policy_rate` genuinely moved from its own
    immediately preceding real observation — not every date the series
    has a reading (most are "still unchanged," not an event)."""
    rows = series_history(db, SERIES_POLICY_RATE, as_of, limit=lookback_days)
    changes: list[dt.date] = []
    prev_value: Decimal | None = None
    for row in rows:
        if prev_value is not None and row.value != prev_value:
            changes.append(row.obs_date)
        prev_value = row.value
    return changes


def _aspi_returns(db: Session, as_of: dt.date, lookback_days: int) -> dict[dt.date, Decimal]:
    """Real ASPI daily returns, the market proxy — from stored levels
    via `app.domain.macro_view.series_history`, the same real ASPI
    series `app.domain.macro_engine_view`'s own log-return computation
    already draws on for the regime classifier (simple, not log, returns
    here — matching `app.domain.price_returns.ticker_adjusted_returns`'s
    own convention so both sides of the market model use the same return
    definition)."""
    rows = series_history(db, SERIES_ASPI, as_of, limit=lookback_days)
    returns: dict[dt.date, Decimal] = {}
    prev_value: Decimal | None = None
    for row in rows:
        if prev_value is not None and prev_value > 0:
            returns[row.obs_date] = (row.value - prev_value) / prev_value
        prev_value = row.value
    return returns


@dataclass(frozen=True)
class EventOutcome:
    event_date: dt.date
    result: SingleEventResult | None
    skip_reason: str | None
    """Populated only when `result` is `None` — why this real event
    couldn't be studied (insufficient trading days on one side of the
    window, event date not found near a real trading day, etc.)."""


@dataclass(frozen=True)
class EventStudyView:
    ticker: str
    event_type: str
    as_of: dt.date
    trading_day_count: int
    """Real dates where BOTH the ticker and the ASPI have a return —
    the universe event windows are drawn from."""

    events: tuple[EventOutcome, ...]
    aggregate: AggregateEventStudyResult | None
    warnings: tuple[str, ...]


def event_study_for(
    db: Session,
    ticker: str,
    as_of: dt.date | None = None,
    *,
    event_type: str = "cbsl_policy_rate_change",
    estimation_length: int = DEFAULT_ESTIMATION_LENGTH,
    event_window: tuple[int, int] = DEFAULT_EVENT_WINDOW,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> EventStudyView:
    """§30 step 5, live, on real CBSL policy rate change dates and real
    `prices_daily`/ASPI return series. Every real candidate event is
    reported individually (`events`) — a real event that can't be
    studied (not enough real trading-day history on one side of its
    window) is named with `skip_reason`, never silently dropped from the
    count. `aggregate` is `None` below two real, studyable events —
    matching `app.domain.event_study.aggregate_car_across_events`'s own
    "a cross-sectional test needs more than one observation" rule."""
    stamp = as_of or dt.date.today()
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise ValueError(
            f"unsupported event_type {event_type!r} — only {SUPPORTED_EVENT_TYPES} have a real "
            "date source this system can draw on today (see module docstring)"
        )

    asset_returns = ticker_adjusted_returns(db, ticker, stamp, lookback_days)
    market_returns = _aspi_returns(db, stamp, lookback_days)
    trading_dates = sorted(set(asset_returns) & set(market_returns))

    warnings: list[str] = []
    if not trading_dates:
        warnings.append(f"No real overlapping trading-day returns for {ticker!r} and the ASPI at all.")
        return EventStudyView(
            ticker=ticker, event_type=event_type, as_of=stamp, trading_day_count=0,
            events=(), aggregate=None, warnings=tuple(warnings),
        )

    candidate_events = policy_rate_change_dates(db, stamp, lookback_days)
    if not candidate_events:
        warnings.append("No real CBSL policy rate change events found in the available window.")

    pre_window, post_window = event_window
    outcomes: list[EventOutcome] = []
    for event_date in candidate_events:
        # `idx` anchors the event to a real trading day: an exact match
        # when the event date itself was one, otherwise `bisect_left`
        # gives the next real trading day ON OR AFTER it — a standard
        # event-study convention for an announcement that lands on a
        # non-trading date.
        idx = bisect.bisect_left(trading_dates, event_date)
        if idx == len(trading_dates):
            outcomes.append(EventOutcome(
                event_date=event_date, result=None,
                skip_reason="No real trading day on or after this event date within the available window.",
            ))
            continue

        event_start = idx + pre_window
        event_end = idx + post_window
        estimation_end = event_start
        estimation_start = estimation_end - estimation_length

        if estimation_start < 0:
            outcomes.append(EventOutcome(
                event_date=event_date, result=None,
                skip_reason=(
                    f"Needs {estimation_length} real trading days before the event window, only "
                    f"{estimation_end} available in this system's own real price history."
                ),
            ))
            continue
        if event_end >= len(trading_dates):
            outcomes.append(EventOutcome(
                event_date=event_date, result=None,
                skip_reason="The event window extends beyond the most recent real trading day available.",
            ))
            continue

        est_dates = trading_dates[estimation_start:estimation_end]
        event_dates = trading_dates[event_start:event_end + 1]

        result = single_event_market_model_car(
            [asset_returns[d] for d in est_dates],
            [market_returns[d] for d in est_dates],
            [asset_returns[d] for d in event_dates],
            [market_returns[d] for d in event_dates],
        )
        if result is None:
            outcomes.append(EventOutcome(
                event_date=event_date, result=None,
                skip_reason="The market-model fit itself could not produce a result for this real event.",
            ))
        else:
            outcomes.append(EventOutcome(event_date=event_date, result=result, skip_reason=None))

    studyable = [o.result for o in outcomes if o.result is not None]
    aggregate = aggregate_car_across_events(studyable) if studyable else None

    return EventStudyView(
        ticker=ticker, event_type=event_type, as_of=stamp,
        trading_day_count=len(trading_dates),
        events=tuple(outcomes), aggregate=aggregate, warnings=tuple(warnings),
    )
