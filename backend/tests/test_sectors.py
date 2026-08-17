"""
GICS classification from the exchange's own publication.

Codes, names and memberships below are real, captured from `sector_list`
and `listBySector` on 17 August 2026.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.domain.gics import is_industry_group, sector_for_industry_group
from app.ingestion.sector_loader import (
    SOURCE,
    SectorFetchError,
    apply_sector_map,
    fetch_sector_map,
)
from app.models.securities import Security

# The two entries in `sector_list` that are market indices, not industry
# groups. Both arrive with indexCode null.
NON_GROUPS = [
    {"id": 1, "name": "ALL SHARE PRICE INDEX", "symbol": "ASI", "indexCode": None},
    {"id": 40, "name": "S&P SL20", "symbol": "SPSL", "indexCode": None},
]
REAL_GROUPS = [
    {"id": 236, "name": "Banks", "symbol": "BNK", "indexCode": "4010"},
    {"id": 225, "name": "Capital Goods", "symbol": "CG", "indexCode": "2010"},
]


class FakeClient:
    """Stands in for CseClient; records what was asked for."""

    def __init__(self, groups, members=None, list_payload_override=None):
        self.groups = groups
        self.members = members or {}
        self.override = list_payload_override
        self.requested_sector_ids: list[int] = []

    def post_form(self, path, data):
        if path == "sector_list":
            return {"indicesList": self.groups}
        assert path == "listBySector"
        self.requested_sector_ids.append(data["sectorId"])
        if self.override is not None:
            return self.override
        return {
            "reqIndustryBySectors": [
                {"symbol": s} for s in self.members.get(data["sectorId"], [])
            ]
        }


class TestGicsHierarchy:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("4010", "Financials"),
            ("4020", "Financials"),
            ("4030", "Financials"),
            ("2010", "Industrials"),
            ("2530", "Consumer Discretionary"),
            ("3020", "Consumer Staples"),
            ("1510", "Materials"),
            ("6020", "Real Estate"),
            ("5510", "Utilities"),
        ],
    )
    def test_industry_group_rolls_up_to_its_sector(self, code, expected):
        """The exchange publishes only the industry group. The sector above
        follows from the code's first two digits by the definition of the
        scheme — it is not inferred from the company."""
        assert sector_for_industry_group(code) == expected

    @pytest.mark.parametrize("code", [None, "", "40", "40100", "abcd", "9910"])
    def test_unrecognised_codes_return_none_rather_than_guessing(self, code):
        assert sector_for_industry_group(code) is None
        assert not is_industry_group(code)


class TestIndexEntriesAreNotSectors:
    def test_the_aspi_is_not_treated_as_an_industry_group(self):
        """`sector_list` mixes the ASPI and S&P SL20 in with the 20 real
        groups. Taking the list at face value would file listed companies
        under "ALL SHARE PRICE INDEX"."""
        client = FakeClient(NON_GROUPS + REAL_GROUPS, members={236: ["COMB.N0000"], 225: []})
        mapping = fetch_sector_map(client)
        assert client.requested_sector_ids == [236, 225]  # never 1 or 40
        assert mapping == {"COMB.N0000": ("Banks", "4010")}

    def test_a_list_of_only_index_entries_raises(self):
        """Zero classifiable groups means the endpoint changed shape.
        Returning an empty map would look like "no company has a sector"
        and wipe the classification on the next apply."""
        with pytest.raises(SectorFetchError):
            fetch_sector_map(FakeClient(NON_GROUPS))

    def test_a_missing_indices_list_raises(self):
        class Broken(FakeClient):
            def post_form(self, path, data):
                return {"unexpected": []}

        with pytest.raises(SectorFetchError):
            fetch_sector_map(Broken([]))


class TestApplying:
    @pytest.fixture()
    def db(self, db_session):
        db_session.add_all(
            [
                Security(ticker="COMB.N0000", name="COMMERCIAL BANK", issuer_code="COMB"),
                Security(ticker="COMB.X0000", name="COMMERCIAL BANK", issuer_code="COMB"),
                Security(ticker="JKH.N0000", name="JOHN KEELLS HOLDINGS", issuer_code="JKH"),
                Security(ticker="AFS.N0000", name="ALPHA FIRE SERVICES", issuer_code="AFS"),
            ]
        )
        db_session.commit()
        return db_session

    MAP = {
        "COMB.N0000": ("Banks", "4010"),
        "COMB.X0000": ("Banks", "4010"),
        "JKH.N0000": ("Capital Goods", "2010"),
    }

    def test_both_lines_of_an_issuer_get_the_same_classification(self, db):
        apply_sector_map(db, self.MAP)
        rows = {s.ticker: s for s in db.scalars(select(Security)).all()}
        assert rows["COMB.N0000"].cse_sector == rows["COMB.X0000"].cse_sector == "Banks"
        assert rows["COMB.X0000"].gics_sector == "Financials"

    def test_the_derived_sector_and_the_code_are_both_stored(self, db):
        apply_sector_map(db, self.MAP)
        jkh = db.get(Security, "JKH.N0000")
        assert jkh.cse_sector == "Capital Goods"
        assert jkh.gics_industry_group_code == "2010"
        assert jkh.gics_sector == "Industrials"

    def test_uncovered_securities_are_left_null_not_bucketed(self, db):
        """26 traded lines are absent from the exchange's GICS publication.
        An "Other" bucket would let them rank in a sector percentile they
        were never classified into."""
        apply_sector_map(db, self.MAP)
        assert db.get(Security, "AFS.N0000").cse_sector is None

    def test_archetype_is_never_written_by_this_loader(self, db):
        """John Keells is Sri Lanka's largest diversified conglomerate —
        hotels, transport, consumer foods, financial services, property —
        and GICS files it under Capital Goods. That is exactly the
        misclassification Appendix P2 warns about, and precisely why the
        valuation router's archetype must stay hand-set."""
        apply_sector_map(db, self.MAP)
        assert db.get(Security, "JKH.N0000").archetype is None

    def test_summary_counts_classified_and_unclassified(self, db):
        summary = apply_sector_map(db, self.MAP)
        assert summary["securities"] == 4
        assert summary["classified"] == 3
        assert summary["unclassified"] == 1
        assert summary["updated"] == 3


class TestManualCorrections:
    @pytest.fixture()
    def db(self, db_session):
        db_session.add(
            Security(
                ticker="JKH.N0000",
                name="JOHN KEELLS HOLDINGS",
                cse_sector="Diversified Holdings",
                sector_source="manual",
            )
        )
        db_session.commit()
        return db_session

    def test_a_hand_set_classification_survives_a_refresh(self, db):
        """Appendix P2 treats the classification as hand-correctable. A
        weekly refresh that silently reverted corrections would make
        correcting anything pointless."""
        summary = apply_sector_map(db, {"JKH.N0000": ("Capital Goods", "2010")})
        assert db.get(Security, "JKH.N0000").cse_sector == "Diversified Holdings"
        assert summary["skipped_manual"] == 1
        assert summary["updated"] == 0

    def test_but_it_can_be_overridden_explicitly(self, db):
        apply_sector_map(db, {"JKH.N0000": ("Capital Goods", "2010")}, overwrite_manual=True)
        assert db.get(Security, "JKH.N0000").cse_sector == "Capital Goods"

    def test_a_loader_written_value_is_refreshed_freely(self, db_session):
        db_session.add(
            Security(ticker="X.N0000", name="X", cse_sector="Banks", sector_source=SOURCE)
        )
        db_session.commit()
        apply_sector_map(db_session, {"X.N0000": ("Insurance", "4030")})
        assert db_session.get(Security, "X.N0000").cse_sector == "Insurance"

    def test_rerunning_is_idempotent(self, db_session):
        db_session.add(Security(ticker="X.N0000", name="X"))
        db_session.commit()
        mapping = {"X.N0000": ("Banks", "4010")}
        assert apply_sector_map(db_session, mapping)["updated"] == 1
        second = apply_sector_map(db_session, mapping)
        assert second["updated"] == 0
        assert second["unchanged"] == 1
