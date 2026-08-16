"""
Fetch -> parse -> store for CBSL Daily Economic Indicators.

Every observation lands in `macro_series` with its own obs_date and
first_available_date, both taken from the PDF itself (§6). The T-bill
figures in particular are dated a day or two before the edition that
carries them and were published a day after it — so all three dates
differ, and only `first_available_date` may ever be used to decide
whether a model could have seen the number.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.domain.cbsl_parsing import CbslParseError, parse_daily_indicators
from app.domain.macro_view import record_observation
from app.ingestion.cbsl_client import CbslClient, CbslNotPublished, CbslUnavailable

logger = logging.getLogger("cse_alpha.ingestion.cbsl_loader")


def ingest_edition(client: CbslClient, db: Session, edition_date: dt.date) -> int:
    """Returns the number of observations written for one edition."""
    pdf_bytes = client.fetch_edition(edition_date)
    indicators = parse_daily_indicators(pdf_bytes, edition_date)

    for observation in indicators.observations:
        record_observation(
            db,
            series_id=observation.series_id,
            obs_date=observation.obs_date,
            value=observation.value,
            first_available_date=observation.first_available_date,
            source=f"cbsl.gov.lk daily indicators {edition_date:%Y-%m-%d}",
        )
    return len(indicators.observations)


def ingest_range(
    client: CbslClient,
    db: Session,
    start: dt.date,
    end: dt.date,
    *,
    on_progress=None,
) -> dict[str, int]:
    """Walk a date range newest-first, skipping non-publication days.

    Newest-first so an interrupted backfill still leaves the most recent
    (and most useful) data in place. Weekdays only — CBSL doesn't publish
    at weekends, and requesting them would just burn 10 seconds apiece
    against a site that asked to be crawled slowly.
    """
    editions = 0
    observations = 0
    missing = 0
    failed = 0
    unavailable: list[dt.date] = []

    day = end
    while day >= start:
        if day.weekday() >= 5:  # Saturday/Sunday
            day -= dt.timedelta(days=1)
            continue
        try:
            written = ingest_edition(client, db, day)
            editions += 1
            observations += written
            if on_progress:
                on_progress(day, written, None)
        except CbslNotPublished:
            missing += 1
            if on_progress:
                on_progress(day, 0, "not published")
        except CbslUnavailable as exc:
            # Explicitly NOT counted as "not published" — we don't know.
            # Reported separately so the operator can re-run for these
            # dates rather than believing the series is complete.
            unavailable.append(day)
            if on_progress:
                on_progress(day, 0, "could not fetch (will retry on a later run)")
        except CbslParseError as exc:
            # A parse failure means the layout changed. Log loudly and
            # keep going: one bad edition must not abandon a backfill that
            # is costing 10 seconds per day by design.
            failed += 1
            logger.error("parse failed for %s: %s", day, exc)
            if on_progress:
                on_progress(day, 0, f"parse failed: {exc}")
        except Exception as exc:  # noqa: BLE001 — network/transient
            failed += 1
            logger.exception("fetch failed for %s", day)
            if on_progress:
                on_progress(day, 0, f"failed: {exc}")

        day -= dt.timedelta(days=1)

    return {
        "editions": editions,
        "observations": observations,
        "not_published": missing,
        "unavailable": unavailable,
        "failed": failed,
    }
