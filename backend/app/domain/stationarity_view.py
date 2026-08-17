"""
Bridges stored `macro_series` rows to `app.domain.stationarity` — the
I/O layer that module deliberately doesn't have.

TESTED ON LEVELS, NOT RETURNS/CHANGES. §30 step 2's actual question
("is this series I(0) or I(1)?") is about the LEVEL series — a T-bill
yield of 10.01%, not its day-to-day change — because that integration
order is what determines whether Johansen cointegration, ARDL bounds
testing, or a plain VAR in differences is the right next step. A returns
series (already differenced once) is almost always stationary by
construction, which would make every macro series in this system look
"already I(0)" and defeat the entire point of testing.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.macro_view import series_history
from app.domain.stationarity import MIN_OBSERVATIONS, StationarityAssessment, assess_stationarity

#: Same horizon `app.domain.macro_engine_view`/`app.domain.sector_
#: sensitivity_view` already use for "how far back to look" — comfortably
#: covers the real backfills this system's ingestion jobs produce.
DEFAULT_LOOKBACK_LIMIT = 400


@dataclass(frozen=True)
class SeriesStationarityView:
    series_id: str
    as_of: dt.date
    observation_count: int
    assessment: StationarityAssessment | None
    warnings: tuple[str, ...]


def stationarity_for_series(
    db: Session, series_id: str, as_of: dt.date | None = None, *, limit: int = DEFAULT_LOOKBACK_LIMIT
) -> SeriesStationarityView:
    """§30 step 1, live, on one real `macro_series` series' level values.
    Never fabricates a result: `assessment` is `None` when fewer real
    observations exist than `app.domain.stationarity.MIN_OBSERVATIONS`
    needs, the same "None, named" discipline every other live-wired view
    in this system uses."""
    stamp = as_of or dt.date.today()
    rows = series_history(db, series_id, stamp, limit=limit)
    warnings: list[str] = []

    assessment = None
    if len(rows) < MIN_OBSERVATIONS:
        warnings.append(
            f"Only {len(rows)} real observations of {series_id!r} available as of {stamp} — "
            f"below the {MIN_OBSERVATIONS} minimum every §30 step 1 test needs to run at all."
        )
    else:
        assessment = assess_stationarity([r.value for r in rows])

    return SeriesStationarityView(
        series_id=series_id, as_of=stamp, observation_count=len(rows),
        assessment=assessment, warnings=tuple(warnings),
    )
