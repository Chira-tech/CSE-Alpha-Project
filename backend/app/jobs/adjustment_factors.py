"""Builds and STORES the §7 total-return adjustment-factor series.

THE GAP THIS CLOSES, found in the 29 Aug 2026 audit. Master Spec §7
requires "a total-return adjustment factor series per ticker, applied
cumulatively backwards across the entire price history", and this project
had every piece of it except one: `app.domain.corporate_actions.
build_adjustment_factor_series` computes the series correctly and is unit
tested; `app.jobs.reconciliation` recomputes it nightly to CHECK the
stored one; `app.domain.price_returns`, `factor_series_view` and
`sector_sensitivity_view` all multiply `close * adj_factor` and say in
their own docstrings that this is "never raw close, which would be
contaminated by unadjusted dividends/bonus issues/splits".

Nothing ever wrote it. `app.ingestion.price_loader` sets `adj_factor` to
1.0 on insert and no code path has ever changed it, so all 200,817 stored
price rows carried exactly 1.0 against 311 confirmed corporate actions —
meaning every consumer above was silently using the raw close while
believing it was adjusted, and the reconciliation check was comparing a
recomputed series against a constant.

The damage was real and measurable: CDB.N0000's 1:9 split shows as
436.50 -> 42.50, a **-90% one-day return**, and APLA.N0000's as
1,646 -> 167. Those feed the Dimson beta regression (and therefore Ke,
and therefore every fair value), §37's momentum battery, the §35.1 factor
series, §33's sector sensitivity, and the price-change columns on
Companies/Opportunities.

Idempotent and safe to re-run: it recomputes each ticker's whole series
from its confirmed actions and writes only the rows whose factor actually
changes.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.corporate_actions import build_adjustment_factor_series, price_ratio_for_event
from app.jobs.reconciliation import _load_confirmed_events
from app.models.prices import PriceDaily
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.jobs.adjustment_factors")


def usable_events(
    events: list, earliest_price_date: dt.date
) -> tuple[list, list[str]]:
    """Split confirmed events into those a price ratio can actually be
    computed for and those it can't, with a reason for each exclusion.

    Two genuinely different exclusions, and conflating them would hide a
    real problem behind a harmless one:

    - An event at or before the earliest stored price affects NO stored
      date (the factor only ever applies to dates strictly before an
      event's ex_date), so dropping it changes nothing at all. Most of
      this system's confirmed dividends are here — the corporate-action
      history reaches back years further than the ~1-year price history.
    - An event INSIDE the price window whose ratio can't be computed (a
      cash dividend with no stored close on the day before its ex_date,
      a rights issue missing its subscription price) is a real, reported
      under-adjustment: that ticker's factors will be too small. Named
      per event rather than silently skipped, because the resulting
      series is genuinely incomplete and a reader must be able to tell.
    """
    usable: list = []
    skipped: list[str] = []
    for event in events:
        if event.ex_date <= earliest_price_date:
            continue  # affects no stored row; not a gap worth reporting
        try:
            price_ratio_for_event(event)
        except (ValueError, ArithmeticError, TypeError) as exc:
            skipped.append(f"{event.ex_date} {event.kind.value}: {exc}")
            continue
        usable.append(event)
    return usable, skipped


def rebuild_adjustment_factors_for_ticker(db: Session, ticker: str) -> tuple[int, list[str]]:
    """Recompute and store this ticker's whole adj_factor series. Returns
    `(price_rows_changed, skipped_event_reasons)`."""
    rows = list(
        db.scalars(
            select(PriceDaily).where(PriceDaily.ticker == ticker).order_by(PriceDaily.date)
        )
    )
    if not rows:
        return 0, []

    dates = [r.date for r in rows]
    events, skipped = usable_events(_load_confirmed_events(db, ticker), dates[0])
    # With no confirmed price-affecting action the correct series is all
    # 1.0 — which is also what a never-built series looks like, so this
    # still writes nothing and cannot "undo" a real factor by accident.
    factors = build_adjustment_factor_series(dates, events)

    changed = 0
    for row in rows:
        new = factors.get(row.date, Decimal(1))
        if row.adj_factor is None or Decimal(row.adj_factor) != new:
            row.adj_factor = new
            changed += 1
    return changed, skipped


def rebuild_all_adjustment_factors(db: Session, *, on_progress=None) -> dict[str, int]:
    """Every ticker. Pure recomputation from already-stored, already-
    confirmed data — no network, so this is cheap enough to run whenever a
    corporate action is confirmed."""
    tickers = [t for (t,) in db.execute(select(Security.ticker).order_by(Security.ticker))]
    total_changed = 0
    tickers_touched = 0
    all_skipped: dict[str, list[str]] = {}
    for i, ticker in enumerate(tickers, 1):
        changed, skipped = rebuild_adjustment_factors_for_ticker(db, ticker)
        if changed:
            tickers_touched += 1
            total_changed += changed
        if skipped:
            all_skipped[ticker] = skipped
        if on_progress is not None:
            on_progress(i, len(tickers), ticker)
    db.commit()
    if all_skipped:
        logger.warning(
            "adjustment factors: %d ticker(s) have events inside the price window whose "
            "ratio could not be computed — their factors are UNDER-adjusted: %s",
            len(all_skipped), all_skipped,
        )
    logger.info(
        "adjustment factors: %d price rows updated across %d ticker(s)",
        total_changed, tickers_touched,
    )
    return {
        "tickers_scanned": len(tickers),
        "tickers_changed": tickers_touched,
        "price_rows_changed": total_changed,
        "tickers_with_unusable_events": all_skipped,
    }
