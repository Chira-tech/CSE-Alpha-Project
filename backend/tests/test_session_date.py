"""
`infer_session_date` — deriving the trading date from the feed rather
than assuming it is today.

This exists because of a real bug caught in the running app: bootstrapping
on a Sunday filed Friday's prices under Sunday's date. `tradeSummary`
always returns the last COMPLETED session, so any ingestion that runs on a
non-trading day (weekend, public holiday, before the open, or a retried
job) would fabricate an observation on a date the market never traded —
exactly what Master Spec §6's point-in-time discipline exists to prevent.
"""
from __future__ import annotations

import datetime as dt

from app.ingestion.price_loader import infer_session_date
from app.ingestion.schemas import TradeSummaryRow

# 2026-08-14 17:56 Asia/Colombo — a real timestamp from the live feed.
FRIDAY_MS = 1786691785346
# ~24h earlier
THURSDAY_MS = FRIDAY_MS - 86_400_000


def _row(symbol: str, last_traded_time: int | None) -> TradeSummaryRow:
    return TradeSummaryRow.model_validate({"symbol": symbol, "lastTradedTime": last_traded_time})


def test_derives_the_session_date_from_feed_timestamps():
    rows = [_row("A", FRIDAY_MS), _row("B", FRIDAY_MS), _row("C", FRIDAY_MS)]
    assert infer_session_date(rows) == dt.date(2026, 8, 14)


def test_uses_the_modal_date_not_the_maximum():
    """A single stale or mis-stamped row must not drag the whole session's
    date with it — which `max()` would have done."""
    rows = [_row("A", THURSDAY_MS), _row("B", THURSDAY_MS), _row("C", FRIDAY_MS)]
    assert infer_session_date(rows) == dt.date(2026, 8, 13)


def test_ignores_rows_with_no_timestamp():
    rows = [_row("A", None), _row("B", FRIDAY_MS), _row("C", None)]
    assert infer_session_date(rows) == dt.date(2026, 8, 14)


def test_returns_none_when_nothing_carries_a_timestamp():
    """Callers must then decide explicitly rather than silently
    defaulting to today — which is the bug this whole module prevents."""
    assert infer_session_date([_row("A", None)]) is None
    assert infer_session_date([]) is None


def test_timestamps_are_interpreted_in_colombo_time():
    """A late-evening Colombo trade is still that day's session; reading
    the timestamp in UTC would roll some sessions back a day."""
    # 2026-08-14 23:30 Asia/Colombo == 18:00 UTC same day
    late_colombo = int(
        dt.datetime(2026, 8, 14, 23, 30, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))).timestamp()
        * 1000
    )
    assert infer_session_date([_row("A", late_colombo)]) == dt.date(2026, 8, 14)
