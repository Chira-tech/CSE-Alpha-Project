"""
First-run bootstrap: populate `securities` and today's `prices_daily` from
the live CSE API so a fresh database has something real in it.

This is NOT a historical backfill (Part O #2 — still unsolved, see
ROADMAP.md). `tradeSummary` returns one row per listed company for the
most recent session only, so bootstrapping gives you the full universe of
~283 names plus a single day of prices. Every subsequent day's prices come
from the scheduled EOD snapshot job (§52).

Deliberately does NOT invent an `archetype` (§15) or `cse_sector` for each
company: the model router depends on archetype being right, GICS
misclassifies several CSE conglomerates (Appendix P2 says the mapping
"must be corrected by hand"), and a wrong archetype silently routes a bank
through an industrial DCF — the exact failure Part N #7 warns about.
Archetype is left NULL until it's assigned deliberately.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.cse_client import CseClient
from app.ingestion.price_loader import fetch_eod_prices, infer_session_date, upsert_eod_prices
from app.ingestion.schemas import TradeSummaryRow
from app.domain.instrument_type import classify, issuer_code
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.ingestion.bootstrap")


def bootstrap_securities(db: Session, rows: list[TradeSummaryRow]) -> tuple[int, int]:
    """Insert any securities present in tradeSummary that we don't already
    have. Returns (inserted, already_known). Never overwrites an existing
    row — a human may have set `archetype`/`cse_sector` by hand and a
    re-run must not clobber that.

    Takes already-fetched rows rather than fetching its own: securities and
    prices come from the same single response, and §5's "never parallel
    hammering / conservative pacing" spirit means not making two identical
    requests when one will do.
    """
    existing = {t for (t,) in db.execute(select(Security.ticker)).all()}

    inserted = 0
    for row in rows:
        if row.symbol in existing:
            continue
        db.add(
            Security(
                ticker=row.symbol,
                name=row.name or row.symbol,
                instrument_type=classify(row.symbol).value,
                issuer_code=issuer_code(row.symbol),
            )
        )
        inserted += 1

    if inserted:
        db.commit()
    return inserted, len(existing)


def run_bootstrap(db: Session, as_of: dt.date | None = None) -> dict[str, object]:
    """One tradeSummary fetch feeds both the securities universe and the
    day's prices.

    When `as_of` isn't given the session date is derived from the feed's
    own timestamps (see `infer_session_date`) rather than defaulting to
    today — the CSE feed always returns the last COMPLETED session, so
    bootstrapping on a weekend, a holiday, or before the open would
    otherwise file stale prices under a date the market never traded.
    """
    with CseClient() as client:
        rows = fetch_eod_prices(client)

    session_date = as_of or infer_session_date(rows)
    if session_date is None:
        raise ValueError(
            "could not determine the trading session date from the feed (no row carried a "
            "lastTradedTime) — pass an explicit --as-of rather than guessing"
        )

    inserted, already = bootstrap_securities(db, rows)
    prices = upsert_eod_prices(db, session_date, rows)

    logger.info(
        "bootstrap: %d new securities (%d already known), %d price rows for session %s",
        inserted,
        already,
        prices,
        session_date,
    )
    return {
        "securities_inserted": inserted,
        "securities_already_known": already,
        "price_rows": prices,
        "session_date": session_date,
    }
