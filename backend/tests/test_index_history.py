"""
ASPI close recovery from cse.lk `chartData`.

Fixture values are real points captured live from the endpoint in August
2026. The expected closes for 2026-08-05, 2026-08-04 and 2026-07-28 are
the figures the Central Bank published in its Daily Economic Indicators
PDF for those dates — an independent institution, not a restatement of
the CSE feed. They are what make these tests evidence rather than a
re-implementation of the code under test.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.domain.index_history import (
    MARKET_TZ,
    SOURCE_DIRECT,
    SOURCE_RECOVERED,
    ChartPoint,
    IndexHistoryError,
    parse_points,
    reconstruct_closes,
)


def point(date: str, time: str, value: str, pct: str) -> ChartPoint:
    stamped = dt.datetime.fromisoformat(f"{date}T{time}").replace(tzinfo=MARKET_TZ)
    return ChartPoint(stamped_at=stamped, value=Decimal(value), pct_change=Decimal(pct))


def millis(date: str, time: str) -> int:
    stamped = dt.datetime.fromisoformat(f"{date}T{time}").replace(tzinfo=MARKET_TZ)
    return int(stamped.timestamp() * 1000)


# A real contiguous run captured from the live endpoint, 27 Jul - 06 Aug
# 2026. It happens to contain both stamping regimes: 30 Jul, 03 Aug and
# 06 Aug are post-close (14:57), the rest are pre-open (08:16).
REAL_RUN = [
    point("2026-07-27", "08:16", "21191.57", "0.0889351118466481"),
    point("2026-07-28", "08:16", "21249.84", "0.29555552828544757"),
    point("2026-07-30", "14:57", "21148.71", "-0.3788660303714611"),
    point("2026-07-31", "08:16", "21142.1", "-0.0312548614076225"),
    point("2026-08-03", "14:57", "21121.78", "-0.035164589684138686"),
    point("2026-08-04", "08:16", "21101.87", "-0.09426288882849836"),
    point("2026-08-05", "08:16", "21215.84", "0.6344724998671858"),
    point("2026-08-06", "14:57", "21269.67", "0.48533231539372246"),
]


class TestTheCoreClaim:
    def test_pre_open_levels_are_replaced_by_the_recovered_close(self):
        """CBSL published 21,166.94 for 2026-08-05. The feed's own `v` for
        that date says 21,215.84 — wrong by 48.90 index points."""
        closes = {c.obs_date: c for c in reconstruct_closes(REAL_RUN)[0]}
        assert closes[dt.date(2026, 8, 5)].value == Decimal("21166.94")
        assert closes[dt.date(2026, 8, 5)].value != Decimal("21215.84")

    def test_recovered_closes_match_the_central_bank(self):
        """The three dates whose CBSL edition was fetched and read."""
        closes = {c.obs_date: c.value for c in reconstruct_closes(REAL_RUN)[0]}
        assert closes[dt.date(2026, 8, 4)] == Decimal("21082.08")
        assert closes[dt.date(2026, 7, 28)] == Decimal("21229.14")

    def test_recovered_values_are_labelled_as_recovered(self):
        """`source` has to distinguish the two readings, or a later reader
        cannot tell which rows rest on the pc identity."""
        closes = {c.obs_date: c.source for c in reconstruct_closes(REAL_RUN)[0]}
        assert closes[dt.date(2026, 8, 5)] == SOURCE_RECOVERED
        assert closes[dt.date(2026, 8, 3)] == SOURCE_DIRECT


class TestPostCloseHandling:
    def test_post_close_level_is_used_directly(self):
        closes = {c.obs_date: c for c in reconstruct_closes(REAL_RUN)[0]}
        assert closes[dt.date(2026, 8, 3)].value == Decimal("21121.78")

    def test_the_two_readings_agree_exactly_on_post_close_days(self):
        """On a post-close day the raw level and the level recovered from
        the next day's pc are independent routes to the same number, and
        on real data they agree to the last decimal. That is the evidence
        the pc identity is exact rather than approximate — and it is why
        a disagreement is worth warning about."""
        _, warnings = reconstruct_closes(REAL_RUN)
        assert not [w for w in warnings if "disagrees" in w]

    def test_a_post_close_level_that_contradicts_pc_warns_but_still_loads(self):
        """Both readings are meant to agree exactly. When they don't, the
        day is still recorded — one odd session must not silently drop
        data — but it is reported."""
        run = [
            point("2026-07-29", "14:48", "21229.14", "0.0"),
            point("2026-07-30", "14:48", "21000.00", "0.0"),  # implies 21000, not 21229.14
        ]
        closes, warnings = reconstruct_closes(run)
        assert any("disagrees" in w for w in warnings)
        assert len(closes) == 2

    def test_newest_point_is_dropped_when_the_session_has_not_closed(self):
        """Pulled at 08:16, today's close does not exist yet. Storing the
        pre-open level as a close is exactly the bug this module exists to
        prevent."""
        closes, warnings = reconstruct_closes(REAL_RUN)
        assert dt.date(2026, 8, 6) in {c.obs_date for c in closes}  # this one IS post-close
        pre_open_last = REAL_RUN[:-1] + [
            point("2026-08-06", "08:16", "21269.67", "0.48533231539372246")
        ]
        closes, warnings = reconstruct_closes(pre_open_last)
        assert dt.date(2026, 8, 6) not in {c.obs_date for c in closes}
        assert any("not yet knowable" in w for w in warnings)


class TestPointInTime:
    def test_a_close_is_available_the_day_it_is_struck(self):
        """True for this series and not a default to copy: CBSL series
        publish days after their observation date (§6)."""
        close = reconstruct_closes(REAL_RUN)[0][0]
        assert close.first_available_date == close.obs_date


class TestFeedShapeGuards:
    def test_duplicate_session_dates_raise(self):
        payload = [
            {"d": millis("2026-08-04", "08:16"), "v": 21101.87, "pc": 0.2},
            {"d": millis("2026-08-04", "14:48"), "v": 21105.00, "pc": 0.2},
        ]
        with pytest.raises(IndexHistoryError, match="duplicate session dates"):
            parse_points(payload)

    def test_points_are_sorted_even_if_the_feed_is_not(self):
        payload = [
            {"d": millis("2026-08-05", "08:16"), "v": 21215.84, "pc": 0.4},
            {"d": millis("2026-08-04", "08:16"), "v": 21101.87, "pc": 0.2},
        ]
        assert [p.session_date for p in parse_points(payload)] == [
            dt.date(2026, 8, 4),
            dt.date(2026, 8, 5),
        ]

    @pytest.mark.parametrize(
        "payload", [{"not": "a list"}, [{"d": 1, "v": None, "pc": 0}], [{"v": 1, "pc": 0}]]
    )
    def test_unreadable_payloads_raise_rather_than_return_nothing(self, payload):
        """An empty list back from a parser is indistinguishable from a
        quiet day; a raise is not."""
        with pytest.raises(IndexHistoryError):
            parse_points(payload)

    def test_non_positive_index_level_raises(self):
        with pytest.raises(IndexHistoryError, match="non-positive"):
            parse_points([{"d": millis("2026-08-04", "08:16"), "v": 0, "pc": 0.2}])

    def test_utc_conversion_does_not_shift_the_session_date(self):
        """Colombo is +05:30. A point stamped 08:16 local is 02:46 UTC —
        same date — but the conversion has to be explicit, because a naive
        reading of a late-evening stamp would file it under the wrong day."""
        payload = [{"d": millis("2026-08-04", "08:16"), "v": 21101.87, "pc": 0.2}]
        assert parse_points(payload)[0].session_date == dt.date(2026, 8, 4)


class TestImplausibleMoves:
    def test_a_decimal_shift_is_rejected_not_stored(self):
        run = [
            point("2026-07-29", "08:16", "21229.14", "0.0"),
            point("2026-07-30", "14:48", "2122.91", "0.0"),  # implies a 90% fall
        ]
        closes, warnings = reconstruct_closes(run)
        assert any("implausible" in w for w in warnings)
        assert dt.date(2026, 7, 29) not in {c.obs_date for c in closes}

    def test_a_minus_100_percent_change_does_not_divide_by_zero(self):
        run = [
            point("2026-07-29", "08:16", "21229.14", "0.0"),
            point("2026-07-30", "14:48", "21000.00", "-100"),
        ]
        closes, warnings = reconstruct_closes(run)
        assert any("non-positive prior close" in w for w in warnings)

    def test_a_genuine_large_move_is_kept(self):
        """The ASPI has had double-digit days. The guard must reject unit
        errors without rejecting real history."""
        run = [
            point("2026-07-29", "08:16", "20000.00", "0.0"),
            point("2026-07-30", "14:48", "21800.00", "9.0"),
        ]
        closes, _ = reconstruct_closes(run)
        assert {c.obs_date for c in closes} == {dt.date(2026, 7, 29), dt.date(2026, 7, 30)}


def test_empty_feed_yields_nothing_without_raising():
    assert reconstruct_closes([]) == ([], [])
