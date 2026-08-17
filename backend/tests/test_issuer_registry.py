"""
The issuer registry (§7 survivorship).

Fixture rows are real `cntSecurity` entries captured live on 17 Aug 2026,
including four of the eleven the exchange flags as deleted. DFCC Vardhana
Bank is the clearest check: it merged into DFCC Bank and stopped existing,
which is exactly the kind of company a survivors-only universe silently
drops.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app.ingestion.issuer_registry_loader import (
    RegistryShapeError,
    fetch_registry,
    upsert_registry,
)
from app.models.registry import IssuerRegistry
from app.models.securities import Security

TODAY = dt.date(2026, 8, 17)

REAL_ROWS = [
    {"securityId": 208, "name": "COMMERCIAL BANK OF CEYLON PLC", "symbol": "COMB", "boardId": 0, "deleted": 0},
    {"securityId": 1104, "name": "DFCC VARDHANA BANK PLC", "symbol": "DVBD", "boardId": 0, "deleted": 1},
    {"securityId": 370, "name": "COMMERCIAL LEASING COMPANY PLC", "symbol": "COML", "boardId": 0, "deleted": 1},
    {"securityId": 667, "name": "CEYLON OXYGEN LIMITED", "symbol": "COXY", "boardId": 4, "deleted": 1},
    {"securityId": 3, "name": "BANK OF CEYLON", "symbol": "BOC", "boardId": 0, "deleted": 0},
]


@pytest.fixture()
def db_with_traded_lines(db_session):
    """COMB trades (two lines, one issuer); BOC exists on the exchange but
    only as a debenture, so no equity line of it is in `securities`."""
    db_session.add_all(
        [
            Security(ticker="COMB.N0000", name="COMMERCIAL BANK OF CEYLON PLC", issuer_code="COMB"),
            Security(ticker="COMB.X0000", name="COMMERCIAL BANK OF CEYLON PLC", issuer_code="COMB"),
        ]
    )
    db_session.commit()
    return db_session


class TestSurvivorship:
    def test_delisted_issuers_are_recorded_not_dropped(self, db_with_traded_lines):
        """The whole point of §7: a company that no longer trades must
        still be in the database, or every backtest sees only survivors."""
        upsert_registry(db_with_traded_lines, REAL_ROWS, observed_on=TODAY)
        dvbd = db_with_traded_lines.get(IssuerRegistry, "DVBD")
        assert dvbd is not None
        assert dvbd.delisted is True
        assert dvbd.name == "DFCC VARDHANA BANK PLC"

    def test_the_registry_holds_more_issuers_than_trade(self, db_with_traded_lines):
        upsert_registry(db_with_traded_lines, REAL_ROWS, observed_on=TODAY)
        total = db_with_traded_lines.scalars(select(IssuerRegistry)).all()
        trading = [r for r in total if r.currently_trading]
        assert len(total) == 5
        assert {r.issuer_code for r in trading} == {"COMB"}

    def test_not_flagged_does_not_mean_trading(self, db_with_traded_lines):
        """Bank of Ceylon is not deleted and not trading as equity — it
        lists only debentures. Collapsing these into one status would
        either resurrect it or bury it."""
        upsert_registry(db_with_traded_lines, REAL_ROWS, observed_on=TODAY)
        boc = db_with_traded_lines.get(IssuerRegistry, "BOC")
        assert boc.delisted is False
        assert boc.currently_trading is False

    def test_summary_counts_the_three_states_separately(self, db_with_traded_lines):
        summary = upsert_registry(db_with_traded_lines, REAL_ROWS, observed_on=TODAY)
        assert summary["registry_issuers"] == 5
        assert summary["delisted"] == 3
        assert summary["trading"] == 1


class TestIssuerJoin:
    def test_both_lines_of_one_issuer_count_as_one_trading_issuer(self, db_with_traded_lines):
        """COMB.N0000 and COMB.X0000 are one company. The registry must
        not report Commercial Bank twice."""
        upsert_registry(db_with_traded_lines, REAL_ROWS, observed_on=TODAY)
        assert db_with_traded_lines.get(IssuerRegistry, "COMB").currently_trading is True
        assert upsert_registry(db_with_traded_lines, REAL_ROWS, observed_on=TODAY)["trading"] == 1

    def test_a_suffixed_symbol_is_normalised_to_its_issuer(self, db_with_traded_lines):
        """The registry publishes bare codes today. If it ever starts
        publishing lines, the join key must not silently change."""
        upsert_registry(
            db_with_traded_lines,
            [{"securityId": 1, "name": "X PLC", "symbol": "XYZ.N0000", "boardId": 0, "deleted": 0}],
            observed_on=TODAY,
        )
        assert db_with_traded_lines.get(IssuerRegistry, "XYZ") is not None


class TestRefresh:
    def test_first_seen_is_never_moved_forward(self, db_with_traded_lines):
        """It is the only lower bound on a delisting date this exchange
        gives us, so a later run must not overwrite it."""
        upsert_registry(db_with_traded_lines, REAL_ROWS, observed_on=dt.date(2026, 1, 5))
        upsert_registry(db_with_traded_lines, REAL_ROWS, observed_on=TODAY)
        row = db_with_traded_lines.get(IssuerRegistry, "COMB")
        assert row.first_seen == dt.date(2026, 1, 5)
        assert row.last_seen == TODAY

    def test_a_newly_delisted_issuer_is_reported(self, db_with_traded_lines):
        alive = [dict(r, deleted=0) for r in REAL_ROWS]
        upsert_registry(db_with_traded_lines, alive, observed_on=dt.date(2026, 1, 5))
        summary = upsert_registry(db_with_traded_lines, REAL_ROWS, observed_on=TODAY)
        assert summary["newly_delisted"] == 3

    def test_rerunning_does_not_duplicate(self, db_with_traded_lines):
        upsert_registry(db_with_traded_lines, REAL_ROWS, observed_on=TODAY)
        summary = upsert_registry(db_with_traded_lines, REAL_ROWS, observed_on=TODAY)
        assert summary["inserted"] == 0
        assert summary["updated"] == 5


class TestShapeGuards:
    class _Client:
        def __init__(self, payload):
            self.payload = payload

        def get_json(self, path):
            assert path == "cntSecurity"
            return self.payload

    @pytest.mark.parametrize("payload", [{}, {"content": []}, [], None, {"content": "nope"}])
    def test_an_unusable_payload_raises_rather_than_wiping_the_registry(self, payload):
        """Returning an empty list here would look like "the exchange
        knows of no issuers", and a caller that trusted it could mark the
        entire universe as gone."""
        with pytest.raises(RegistryShapeError):
            fetch_registry(self._Client(payload))

    def test_rows_without_a_symbol_are_skipped_not_stored(self, db_with_traded_lines):
        summary = upsert_registry(
            db_with_traded_lines,
            REAL_ROWS + [{"securityId": 9, "name": "NO SYMBOL", "symbol": "", "deleted": 0}],
            observed_on=TODAY,
        )
        assert summary["inserted"] == 5
