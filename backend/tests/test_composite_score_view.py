"""§38 wiring — app.domain.composite_score_view now folds Macro & sector
fit and Timing & momentum into the real blend (Valuation/Growth remain
deliberately excluded — see that module's own docstring)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.composite_score_view import composite_score_for
from app.models.securities import Security

AS_OF = dt.date(2026, 8, 1)


class TestCompositeScoreFor:
    def test_a_fresh_ticker_has_macro_and_timing_honestly_excluded_not_crashed(self, db_session):
        db_session.add(Security(ticker="FRESH.N0000", name="Fresh PLC"))
        db_session.commit()

        view = composite_score_for(db_session, "FRESH.N0000", AS_OF)
        by_key = {p.key: p for p in view.pillars}
        assert by_key["macro_sector_fit"].included is False
        assert by_key["macro_sector_fit"].reason is not None
        assert by_key["timing_momentum"].included is False
        assert by_key["timing_momentum"].reason is not None
        # Valuation/Growth stay excluded regardless -- the real, unchanged
        # cost-based reason, not a per-ticker data gap.
        assert by_key["valuation"].included is False
        assert by_key["growth"].included is False

    def test_timing_battery_evidence_is_carried_on_the_view(self, db_session):
        db_session.add(Security(ticker="FRESH2.N0000", name="Fresh PLC 2"))
        db_session.commit()

        view = composite_score_for(db_session, "FRESH2.N0000", AS_OF)
        assert view.timing_battery is not None
        assert len(view.timing_battery.signals) == 6
        assert view.timing_battery.contrarian.no_adverse_disclosure_60d == "unknown"

    def test_unknown_ticker_returns_none(self, db_session):
        assert composite_score_for(db_session, "NOPE.N0000", AS_OF) is None
