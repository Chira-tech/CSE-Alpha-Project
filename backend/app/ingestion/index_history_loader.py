"""
Backfill ~1 year of ASPI closes from `chartData` into `macro_series`.

Unlike everything else in `ingestion/`, this one genuinely back-fills:
`chartData` is the only endpoint on the public CSE API that returns a
historical series at all (see README_ENDPOINTS.md). It covers the index
only — per-company price history remains unavailable, so this does not
unblock the factor library.

The arithmetic that turns the feed's fields into official closes, and the
evidence for why the obvious reading is wrong, lives in
`app.domain.index_history`.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.index_history import (
    IndexClose,
    parse_points,
    reconstruct_closes,
)
from app.domain.macro import SERIES_ASPI
from app.ingestion.cse_client import CseClient
from app.models.macro import MacroSeries

logger = logging.getLogger("cse_alpha.ingestion.index_history")

# period=5 is the deepest the endpoint offers: ~240 daily points. Verified
# live against periods 1/3/4/5; chartId 2-6 all return [].
ASPI_CHART_ID = 1
PERIOD_ONE_YEAR = 5


def fetch_aspi_history(client: CseClient, *, period: int = PERIOD_ONE_YEAR) -> list[IndexClose]:
    payload = client.post_form(
        "chartData", data={"chartId": ASPI_CHART_ID, "period": period}
    )
    points = parse_points(payload)
    closes, warnings = reconstruct_closes(points)
    for warning in warnings:
        logger.warning("chartData integrity: %s", warning)
    logger.info(
        "chartData: %d points -> %d closes (%d recovered from pc, %d taken directly)",
        len(points),
        len(closes),
        sum(1 for c in closes if c.source.endswith("(pc)")),
        sum(1 for c in closes if not c.source.endswith("(pc)")),
    )
    return closes


def upsert_index_history(db: Session, closes: list[IndexClose]) -> int:
    """Returns the number of observations written.

    Existing rows are never overwritten, matching `market_internals`: a
    struck close does not change, and the row already there was written by
    the live daily capture, which observed the session directly rather
    than recovering it a year later.
    """
    if not closes:
        return 0

    existing: set = set(
        db.scalars(
            select(MacroSeries.obs_date).where(MacroSeries.series_id == SERIES_ASPI)
        ).all()
    )

    written = 0
    for close in closes:
        if close.obs_date in existing:
            continue
        db.add(
            MacroSeries(
                series_id=SERIES_ASPI,
                obs_date=close.obs_date,
                first_available_date=close.first_available_date,
                value=close.value,
                source=close.source,
            )
        )
        written += 1

    if written:
        db.commit()
    return written


def ingest_index_history(client: CseClient, db: Session) -> int:
    return upsert_index_history(db, fetch_aspi_history(client))
