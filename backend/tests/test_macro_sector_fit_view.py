"""§38's Macro & sector fit, DB-wired — app.domain.macro_sector_fit_view."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.macro_sector_fit_view import macro_sector_fit_for
from app.domain.sector_sensitivity import SectorSensitivityRow, SensitivityEstimate
from app.domain.sector_sensitivity_view import SectorSensitivityView
from app.models.prices import PriceDaily
from app.models.securities import Security

AS_OF = dt.date(2026, 8, 17)


def _seed_ticker(db, ticker: str, sector: str | None) -> None:
    db.add(Security(ticker=ticker, name=ticker, cse_sector=sector))
    db.commit()


class TestMacroSectorFitFor:
    def test_ticker_with_no_sector_gets_no_sensitivity_or_momentum_component(self, db_session):
        _seed_ticker(db_session, "NOSECT.N0000", None)
        empty_view = SectorSensitivityView(as_of=AS_OF, rows=(), thin_sectors=(), shocks_used=(), warnings=())

        result = macro_sector_fit_for(
            db_session, "NOSECT.N0000", AS_OF, sector_sensitivity_view=empty_view, regime_label="risk_off",
        )
        assert result.sensitivity_component is None
        assert result.sector_momentum_component is None
        assert result.project_register_component is None
        assert result.score is None

    def test_supplied_sensitivity_view_and_regime_are_used_without_recomputing(self, db_session):
        """The load-bearing shared-cache behaviour: when a caller
        supplies a real `SectorSensitivityView`/`regime_label`, this
        function must use them directly rather than triggering its own
        (expensive) fresh computation — verified here by supplying a
        row this ticker's real DB state alone could never produce."""
        _seed_ticker(db_session, "T1.N0000", "Banks")
        row = SectorSensitivityRow(
            sector="Banks", constituent_count=10,
            estimates=(
                SensitivityEstimate(
                    shock_name="policy_rate", coefficient=Decimal("0.4"), p_value=Decimal("0.01"),
                    r_squared=Decimal("0.3"), observation_count=40, significant=True, direction_label="positive",
                ),
            ),
        )
        view = SectorSensitivityView(as_of=AS_OF, rows=(row,), thin_sectors=(), shocks_used=("policy_rate",), warnings=())

        result = macro_sector_fit_for(db_session, "T1.N0000", AS_OF, sector_sensitivity_view=view, regime_label="risk_off")
        # Risk-Off favors a positive-direction significant shock -> 1/1 favorable -> 100.
        assert result.sensitivity_component == Decimal(100)
        assert result.favorable_significant_shock_count == 1
        assert result.total_significant_shock_count == 1

    def test_sector_momentum_uses_real_seeded_prices(self, db_session):
        now = dt.datetime.now(dt.timezone.utc)
        _seed_ticker(db_session, "A.N0000", "Hotels")
        _seed_ticker(db_session, "B.N0000", "Hotels")
        d1, d2 = dt.date(2026, 7, 1), dt.date(2026, 8, 17)
        for ticker, prices in (("A.N0000", (Decimal(100), Decimal(120))), ("B.N0000", (Decimal(50), Decimal(60)))):
            db_session.add(PriceDaily(ticker=ticker, date=d1, close=prices[0], adj_factor=Decimal(1), fetched_at=now))
            db_session.add(PriceDaily(ticker=ticker, date=d2, close=prices[1], adj_factor=Decimal(1), fetched_at=now))
        db_session.commit()

        empty_view = SectorSensitivityView(as_of=AS_OF, rows=(), thin_sectors=(), shocks_used=(), warnings=())
        result = macro_sector_fit_for(
            db_session, "A.N0000", AS_OF, sector_sensitivity_view=empty_view, regime_label="risk_off",
        )
        # Both A and B rose 20% over the window -> real positive sector
        # momentum -> squashed score above the 50 midpoint.
        assert result.sector_momentum_component is not None
        assert result.sector_momentum_component > Decimal(50)
