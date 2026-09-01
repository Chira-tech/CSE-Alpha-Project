"""
Part II §5.2: "nightly cross-check against a second source... discrepancy
>0.5% quarantines the ticker."

Distinct from `app.jobs.reconciliation`, which checks our own stored
adjustment-factor series against an independent recomputation from our
own confirmed corporate actions — an INTERNAL consistency check, not a
second source at all (see PARAMETERS.md #5's long-standing correction of
that point). This job is the first genuine external check: TradingView,
a company with no relationship to cse.lk, against today's own captured
close.

Deliberately does not attempt to reconcile any date but today. TradingView
carries a live quote only, no historical series (see
`app.domain.second_source`), so there is nothing to compare a past date
against — pretending otherwise would silently compare stale figures.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from zoneinfo import ZoneInfo

from decimal import Decimal

from app.config import settings
from app.domain.second_source import SecondSourceShapeError, cross_check
from app.domain.tick_size import price_tolerance_fraction
from app.ingestion.tradingview_client import fetch_quotes
from app.models.data_quality import DataAlert
from app.models.prices import PriceDaily

logger = logging.getLogger("cse_alpha.jobs.second_source_reconciliation")

ALERT_TYPE = "second_source_mismatch"
MARKET_TZ = ZoneInfo("Asia/Colombo")


class StaleComparisonError(ValueError):
    """Raised rather than silently comparing a past close against a live
    quote.

    Found the hard way: an early manual run compared a 3-day-stale stored
    close (bootstrap had not run since 14 Aug) against TradingView's LIVE
    quote for 17 Aug, and 181 of 283 tickers came back "mismatched" —
    every one of them spurious, just three trading days of ordinary price
    movement misread as a data-quality failure. TradingView has no
    historical series to query (see `app.domain.second_source`), so
    `as_of` can only ever mean "today" or the comparison is meaningless
    by construction, not merely imprecise.
    """


def resolve_alerts_now_within_tolerance(
    db: Session, *, pct_floor: Decimal | None = None
) -> int:
    """`docs/CSE_Data_Health_Diagnosis_And_Protocol.md` §2 / E2 — an open
    `second_source_mismatch` whose recorded gap now sits inside the
    `max(pct_floor, 2 ticks)` band (because the tick term relaxes the
    tolerance at a low price) is auto-resolved, the same way
    `app.jobs.market_cap_reconciliation` retires an alert its check no
    longer raises. Uses the ticker's latest stored close for the tick
    band; skips an alert with no price or no recorded `mismatch_pct`.
    Returns the number resolved."""
    floor = pct_floor if pct_floor is not None else settings.second_source_mismatch_pct_floor
    resolved = 0
    for alert in db.scalars(
        select(DataAlert).where(
            DataAlert.resolved.is_(False), DataAlert.alert_type == ALERT_TYPE
        )
    ):
        if alert.mismatch_pct is None:
            continue
        close = db.scalar(
            select(PriceDaily.close)
            .where(PriceDaily.ticker == alert.ticker, PriceDaily.close.is_not(None))
            .order_by(PriceDaily.date.desc())
            .limit(1)
        )
        if close is None:
            continue
        if Decimal(str(alert.mismatch_pct)) <= price_tolerance_fraction(close, pct_floor=floor):
            alert.resolved = True
            alert.resolved_at = dt.datetime.now(dt.timezone.utc)
            alert.resolved_by = "system:second_source_tick_tolerance_e2"
            resolved += 1
    db.commit()
    if resolved:
        logger.info("E2: auto-resolved %d second-source alert(s) now within the tick tolerance", resolved)
    return resolved


def check_against_second_source(
    db: Session, tickers: list[str], *, as_of: dt.date
) -> dict[str, object]:
    """Compare `as_of`'s stored close for each ticker against TradingView's
    current quote. Raises a `DataAlert` (same table and quarantine
    mechanism as the internal reconciliation job) for anything outside
    the configured threshold — the same 0.5% Part II §5.2 specifies,
    already in use for the internal check, not a second invented number.

    Raises `StaleComparisonError` if `as_of` is not today in Colombo —
    see that class for why this is not merely a style preference.
    """
    # E2: retire any open alert whose gap now falls inside the tick-aware
    # tolerance before raising new ones.
    resolve_alerts_now_within_tolerance(db)

    today = dt.datetime.now(dt.timezone.utc).astimezone(MARKET_TZ).date()
    if as_of != today:
        raise StaleComparisonError(
            f"as_of={as_of} is not today ({today} Colombo) — TradingView has no "
            f"historical series to compare against, only a live quote, so comparing "
            f"a past close against it would be comparing against the wrong day"
        )

    closes = {
        ticker: close
        for ticker, close in db.execute(
            select(PriceDaily.ticker, PriceDaily.close).where(
                PriceDaily.ticker.in_(tickers), PriceDaily.date == as_of
            )
        ).all()
        if close is not None
    }
    if not closes:
        logger.info("second-source check: no stored closes for %s, nothing to compare", as_of)
        return {"checked": 0, "matched": 0, "mismatched": 0, "no_quote": 0, "unreadable": 0}

    quotes = fetch_quotes(list(closes))

    matched = mismatched = unreadable = 0
    now = dt.datetime.now(dt.timezone.utc)

    for ticker, our_close in closes.items():
        quote = quotes.get(ticker)
        if quote is None:
            continue
        try:
            result = cross_check(
                ticker,
                our_close,
                quote,
                pct_floor=settings.second_source_mismatch_pct_floor,
            )
        except SecondSourceShapeError:
            logger.exception("second-source quote for %s could not be trusted", ticker)
            unreadable += 1
            continue

        if result.within_tolerance:
            matched += 1
            continue

        mismatched += 1
        db.add(
            DataAlert(
                ticker=ticker,
                alert_type=ALERT_TYPE,
                detail=(
                    f"stored close {result.our_close} for {as_of} disagrees with TradingView's "
                    f"current quote {result.their_close} by {result.mismatch_pct:.4%}, exceeding "
                    f"the {result.tolerance_pct:.2%} tolerance (max of a {settings.second_source_mismatch_pct_floor:.1%} "
                    f"floor and two CSE ticks at this price). This is an EXTERNAL second-source "
                    f"check (Part II §5.2), independent of the internal adj_factor reconciliation. "
                    f"Ticker quarantined until resolved."
                ),
                mismatch_pct=float(result.mismatch_pct),
                raised_at=now,
            )
        )
        logger.warning(
            "second-source mismatch for %s: ours=%s theirs=%s (%.4f%%)",
            ticker, result.our_close, result.their_close, result.mismatch_pct * 100,
        )

    db.commit()

    summary = {
        "checked": len(closes),
        "matched": matched,
        "mismatched": mismatched,
        "no_quote": len(closes) - matched - mismatched - unreadable,
        "unreadable": unreadable,
    }
    logger.info("second-source reconciliation for %s: %s", as_of, summary)
    return summary
