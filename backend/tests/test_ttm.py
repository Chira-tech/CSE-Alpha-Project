"""app.domain.ttm — the real P0 fix: trailing-twelve-month annualisation
for a cumulative-since-year-start interim flow figure. Fixture values are
COMB.N0000's own real, confirmed numbers (18 Aug 2026) — the real bug
this module closes, not an invented example."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.ttm import trailing_twelve_months
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental

TICKER = "COMB.N0000"
AS_OF = dt.date(2026, 8, 18)
CURRENT_PERIOD_END = dt.date(2026, 6, 30)
CURRENT_VALUE = Decimal("35423054000")


def _row(period_end, period_type, value, first_available=None):
    return Fundamental(
        ticker=TICKER, period_end=period_end, period_type=period_type,
        first_available_date=first_available or period_end, version=1,
        statement_line="net_income", value=Decimal(value),
        provenance_tier=ProvenanceTier.REPORTED,
    )


def _ttm(db_session, **overrides):
    kwargs = dict(
        current_period_end=CURRENT_PERIOD_END, current_period_type="quarterly",
        current_value=CURRENT_VALUE,
    )
    kwargs.update(overrides)
    return trailing_twelve_months(db_session, TICKER, "net_income", AS_OF, **kwargs)


class TestTrailingTwelveMonths:
    def test_real_comb_numbers_reconcile_exactly(self, db_session):
        """FY2025 + H1 2026 - H1 2025 = 65,195,124,000 — COMB's own real
        TTM net income, verified by hand against the live app (18 Aug
        2026) before this fix existed."""
        db_session.add_all(
            [
                _row(dt.date(2025, 6, 30), "quarterly", "31165447000"),
                _row(dt.date(2025, 12, 31), "annual", "60937517000"),
            ]
        )
        db_session.commit()

        assert _ttm(db_session) == Decimal("65195124000")

    def test_real_live_db_shape_with_no_annual_rows_uses_reset_detection(self, db_session):
        """The real, live shape found in the actual dev DB (18 Aug 2026),
        discovered debugging why this exact fix returned None for COMB
        against real data despite every fixture-based test above passing:
        NOT ONE `Fundamental` row anywhere in the database has ever had
        `period_type == "annual"` — every real annual-report PDF has
        exceeded this environment's background-processing ceiling before
        finishing. COMB's own real 2025-12-31 row is stored with
        `period_type == "quarterly"`, like every other period on file, even
        though it is a genuine full fiscal year's cumulative total. This
        must still recover the real 65,195,124,000 TTM figure by detecting
        the real downward reset at the next period (2026-03-31's real
        cumulative value is lower, since a new fiscal year had begun), not
        by trusting `period_type`."""
        db_session.add_all(
            [
                _row(dt.date(2025, 6, 30), "quarterly", "31165447000"),
                _row(dt.date(2025, 12, 31), "quarterly", "60937517000"),
                _row(dt.date(2026, 3, 31), "quarterly", "15200000000"),  # real reset down
            ]
        )
        db_session.commit()

        assert _ttm(db_session) == Decimal("65195124000")

    def test_an_annual_current_period_is_used_directly_no_adjustment(self, db_session):
        ttm = _ttm(
            db_session, current_period_type="annual", current_period_end=dt.date(2025, 12, 31),
            current_value=Decimal("60937517000"),
        )
        assert ttm == Decimal("60937517000")

    def test_no_confirmed_annual_period_refuses_rather_than_using_the_raw_cumulative_figure(
        self, db_session
    ):
        """Real, live case: NTB.N0000 has exactly one confirmed quarterly
        period and nothing else — the exact shape that, before this fix,
        silently used the raw 6-month cumulative figure as if it were a
        full year. Must now refuse."""
        assert _ttm(db_session) is None

    def test_annual_present_but_no_prior_year_comparator_still_refuses(self, db_session):
        db_session.add(_row(dt.date(2025, 12, 31), "annual", "60937517000"))
        db_session.commit()

        assert _ttm(db_session) is None

    def test_a_prior_year_comparator_slightly_off_calendar_is_still_matched(self, db_session):
        """Real filings don't always land on the identical calendar date
        year over year — a comparator 10 days off the exact 365-day mark
        is still the real one and must be used, not refused."""
        db_session.add_all(
            [
                _row(dt.date(2025, 6, 20), "quarterly", "31165447000"),  # 10 days early
                _row(dt.date(2025, 12, 31), "annual", "60937517000"),
            ]
        )
        db_session.commit()

        assert _ttm(db_session) == Decimal("65195124000")

    def test_a_prior_year_comparator_far_off_calendar_is_refused_not_guessed(self, db_session):
        db_session.add_all(
            [
                _row(dt.date(2025, 3, 31), "quarterly", "17000000000"),  # ~90 days early — not it
                _row(dt.date(2025, 12, 31), "annual", "60937517000"),
            ]
        )
        db_session.commit()

        assert _ttm(db_session) is None

    def test_no_confirmed_data_at_all_returns_none(self, db_session):
        assert _ttm(db_session) is None

    def test_an_unconfirmed_ai_assisted_comparator_is_never_used(self, db_session):
        annual = _row(dt.date(2025, 12, 31), "annual", "60937517000")
        prior = _row(dt.date(2025, 6, 30), "quarterly", "31165447000")
        prior.provenance_tier = ProvenanceTier.AI_ASSISTED
        db_session.add_all([annual, prior])
        db_session.commit()

        assert _ttm(db_session) is None
