"""§12's sector-relative percentiles wired to real stored `Security`/
`Fundamental` rows — app.domain.sector_percentiles_view."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.sector_percentiles_view import all_sector_percentiles, sector_percentiles_for
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.securities import Security

PERIOD = dt.date(2026, 3, 31)
AVAILABLE = dt.date(2026, 8, 14)
AS_OF = dt.date(2026, 8, 19)


def _seed_security(db, ticker: str, cse_sector: str | None, gics_sector: str | None = None):
    db.add(Security(ticker=ticker, name=f"{ticker} PLC", cse_sector=cse_sector, gics_sector=gics_sector))
    db.commit()


def _seed_roe_inputs(db, ticker: str, net_income: str, total_equity: str):
    db.add_all(
        [
            Fundamental(
                ticker=ticker,
                period_end=PERIOD,
                period_type="annual",
                first_available_date=AVAILABLE,
                version=1,
                statement_line="net_income",
                value=Decimal(net_income),
                provenance_tier=ProvenanceTier.REPORTED,
            ),
            Fundamental(
                ticker=ticker,
                period_end=PERIOD,
                period_type="annual",
                first_available_date=AVAILABLE,
                version=1,
                statement_line="total_equity",
                value=Decimal(total_equity),
                provenance_tier=ProvenanceTier.REPORTED,
            ),
        ]
    )
    db.commit()


class TestSectorPercentilesFor:
    def test_real_db_round_trip_five_banks(self, db_session):
        # ROE = net_income / total_equity: 5%, 10%, 15%, 20%, 25% ascending.
        banks = [
            ("A.N0000", "50", "1000"),
            ("B.N0000", "100", "1000"),
            ("C.N0000", "150", "1000"),
            ("D.N0000", "200", "1000"),
            ("E.N0000", "250", "1000"),
        ]
        for ticker, ni, eq in banks:
            _seed_security(db_session, ticker, cse_sector="Banks", gics_sector="Financials")
            _seed_roe_inputs(db_session, ticker, ni, eq)

        result = sector_percentiles_for(db_session, "E.N0000", AS_OF)
        assert result["return_on_equity"].percentile == Decimal(100)
        assert result["return_on_equity"].group_label == "Banks"
        assert result["return_on_equity"].group_size == 5
        assert result["return_on_equity"].used_wider_sector is False

        lowest = sector_percentiles_for(db_session, "A.N0000", AS_OF)
        assert lowest["return_on_equity"].percentile == Decimal(0)

    def test_point_in_time_gating_matches_bulk_latest_line_items(self, db_session):
        """A period not yet visible as of the query date must not be
        ranked as if it were on file — same point-in-time rule every
        other view in this module family already enforces."""
        _seed_security(db_session, "A.N0000", cse_sector="Banks", gics_sector="Financials")
        _seed_security(db_session, "B.N0000", cse_sector="Banks", gics_sector="Financials")
        _seed_security(db_session, "C.N0000", cse_sector="Banks", gics_sector="Financials")
        _seed_roe_inputs(db_session, "A.N0000", "50", "1000")
        _seed_roe_inputs(db_session, "B.N0000", "100", "1000")
        _seed_roe_inputs(db_session, "C.N0000", "150", "1000")

        before_available = AVAILABLE - dt.timedelta(days=1)
        result = all_sector_percentiles(db_session, before_available)
        assert result.get("A.N0000", {}).get("return_on_equity") is None

    def test_ticker_with_no_fundamentals_has_no_entries(self, db_session):
        _seed_security(db_session, "A.N0000", cse_sector="Banks", gics_sector="Financials")
        _seed_security(db_session, "B.N0000", cse_sector="Banks", gics_sector="Financials")
        _seed_security(db_session, "C.N0000", cse_sector="Banks", gics_sector="Financials")
        _seed_security(db_session, "NODATA.N0000", cse_sector="Banks", gics_sector="Financials")
        _seed_roe_inputs(db_session, "A.N0000", "50", "1000")
        _seed_roe_inputs(db_session, "B.N0000", "100", "1000")
        _seed_roe_inputs(db_session, "C.N0000", "150", "1000")

        result = sector_percentiles_for(db_session, "NODATA.N0000", AS_OF)
        assert result == {}
