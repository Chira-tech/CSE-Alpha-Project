"""
§16 archetype proposals from the GICS classification.

Company names and GICS groups below are real, taken from the exchange's
own classification as read into `securities.cse_sector` on 17 Aug 2026.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.domain.archetype import ARCHETYPES, propose_archetype
from app.ingestion.archetype_loader import SOURCE, apply_archetype_proposals
from app.models.securities import Security


class TestStraightforwardGroups:
    @pytest.mark.parametrize(
        ("name", "sector", "expected"),
        [
            ("COMMERCIAL BANK OF CEYLON PLC", "Banks", "bank"),
            ("ASIA ASSET FINANCE PLC", "Diversified Financials", "non_bank_finance"),
            ("CEYLINCO INSURANCE PLC", "Insurance", "insurance"),
            ("NESTLE LANKA PLC", "Food, Beverage & Tobacco", "consumer"),
            ("DIALOG AXIATA PLC", "Telecommunication Services", "telecom"),
            ("CEYLON ELECTRICITY BOARD PLC", "Utilities", "power_energy"),
            ("OVERSEAS REALTY (CEYLON) PLC", "Real Estate Management&Development", "property"),
            ("FREIGHT LINKS EXPRESS (CEYLON) PLC", "Transportation", "logistics"),
            ("ASIA SIYAKA COMMODITIES PLC", "Health Care Equipment & Services", "healthcare"),
        ],
    )
    def test_unambiguous_gics_groups_map_directly(self, name, sector, expected):
        result = propose_archetype(name, sector)
        assert result.archetype == expected

    def test_a_transportation_company_that_happens_to_be_named_holdings_still_gets_flagged(self):
        """The real Transportation-group constituent Expolanka Holdings PLC
        is exactly the case the conglomerate guard is meant to catch even
        inside an otherwise-safe GICS group: it operates well beyond
        logistics, and the name says so before the segment data would."""
        result = propose_archetype("EXPOLANKA HOLDINGS PLC", "Transportation")
        assert result.archetype is None

    def test_every_mapped_archetype_is_a_real_archetype(self):
        """Guards against a typo in the lookup table producing a value
        nothing downstream recognises."""
        from app.domain.archetype import _ARCHETYPE_BY_INDUSTRY_GROUP

        for archetype in _ARCHETYPE_BY_INDUSTRY_GROUP.values():
            assert archetype in ARCHETYPES


class TestHotelKeywordGate:
    def test_a_hotel_named_company_in_consumer_services_gets_hotel(self):
        result = propose_archetype("ASIAN HOTELS AND PROPERTIES PLC", "Consumer Services")
        assert result.archetype == "hotel"

    def test_a_resort_named_company_gets_hotel(self):
        result = propose_archetype("BERUWALA RESORTS PLC", "Consumer Services")
        assert result.archetype == "hotel"

    def test_consumer_services_without_a_hotel_keyword_is_not_guessed(self):
        """Real membership of this GICS group is hotel-dominated on the
        CSE but not exclusively so. Nothing safe to assume without the
        name confirming it."""
        result = propose_archetype("SOME OTHER SERVICES PLC", "Consumer Services")
        assert result.archetype is None
        assert "hotel-dominated" in result.reason


class TestConglomerateGuard:
    def test_john_keells_is_never_auto_proposed(self):
        """This is the exact case Appendix P2 warns about — GICS files it
        under Capital Goods, and no single archetype fits a company with
        hotels, transport, consumer foods, financial services and
        property. The whole point of this module is refusing to guess
        here, not picking the least-wrong label."""
        result = propose_archetype("JOHN KEELLS HOLDINGS PLC", "Capital Goods")
        assert result.archetype is None
        assert "diversified group" in result.reason

    def test_a_holdings_name_is_flagged_even_in_an_otherwise_safe_group(self):
        result = propose_archetype("HAYLEYS HOLDINGS PLC", "Materials")
        assert result.archetype is None

    def test_group_named_company_is_also_flagged(self):
        result = propose_archetype("VALLIBEL ONE GROUP PLC", "Diversified Financials")
        assert result.archetype is None


class TestNameOverrides:
    def test_a_plantation_company_overrides_its_gics_group(self):
        """No GICS group maps to "plantation" — the override is the only
        route to that archetype, so it has to fire even inside a group
        that would otherwise map elsewhere."""
        result = propose_archetype("KOTAGALA PLANTATIONS PLC", "Materials")
        assert result.archetype == "plantation"

    def test_a_tea_company_is_recognised_without_the_word_plantation(self):
        result = propose_archetype("KELANI VALLEY TEA PLC", "Food, Beverage & Tobacco")
        assert result.archetype == "plantation"

    def test_a_cement_company_overrides_to_construction_materials(self):
        result = propose_archetype("TOKYO CEMENT COMPANY (LANKA) PLC", "Materials")
        assert result.archetype == "construction_materials"

    def test_overrides_take_priority_over_the_conglomerate_guard(self):
        """A clear single-business signal in the name is worth trusting
        even alongside a word like HOLDINGS — a plantation holding
        company is still, functionally, a plantation company."""
        result = propose_archetype("KEGALLE PLANTATIONS HOLDINGS PLC", "Materials")
        assert result.archetype == "plantation"


class TestUnmappedGroups:
    def test_a_group_with_no_mapping_entry_is_left_for_review(self):
        result = propose_archetype("SOMETHING PLC", "Some New GICS Group")
        assert result.archetype is None
        assert "no archetype mapping" in result.reason

    def test_no_sector_at_all_is_left_for_review(self):
        """26 traded lines have no GICS classification at all (§12 gap).
        Nothing to derive an archetype from."""
        result = propose_archetype("UNCLASSIFIED CO PLC", None)
        assert result.archetype is None
        assert "no GICS classification" in result.reason


class TestLoaderIntegration:
    @pytest.fixture()
    def db(self, db_session):
        db_session.add_all(
            [
                Security(ticker="COMB.N0000", name="COMMERCIAL BANK OF CEYLON PLC",
                          cse_sector="Banks", issuer_code="COMB"),
                Security(ticker="JKH.N0000", name="JOHN KEELLS HOLDINGS PLC",
                          cse_sector="Capital Goods", issuer_code="JKH"),
                Security(ticker="X.N0000", name="X PLC", cse_sector=None, issuer_code="X"),
            ]
        )
        db_session.commit()
        return db_session

    def test_proposals_are_written_with_their_source(self, db):
        summary = apply_archetype_proposals(db)
        comb = db.get(Security, "COMB.N0000")
        assert comb.archetype == "bank"
        assert comb.archetype_source == SOURCE
        assert summary["proposed"] == 1  # only COMB — JKH and X both need review

    def test_conglomerates_and_unclassified_lines_land_in_needs_review(self, db):
        summary = apply_archetype_proposals(db)
        tickers_needing_review = {t for t, _ in summary["needs_review"]}
        assert tickers_needing_review == {"JKH.N0000", "X.N0000"}
        assert db.get(Security, "JKH.N0000").archetype is None

    def test_a_hand_set_archetype_survives_a_rerun(self, db):
        jkh = db.get(Security, "JKH.N0000")
        jkh.archetype = "diversified_holding"
        jkh.archetype_source = "manual"
        db.commit()

        summary = apply_archetype_proposals(db)
        assert db.get(Security, "JKH.N0000").archetype == "diversified_holding"
        assert summary["skipped_manual"] == 1

    def test_rerunning_is_idempotent(self, db):
        apply_archetype_proposals(db)
        second = apply_archetype_proposals(db)
        assert second["proposed"] == 0
        assert second["unchanged"] == 1
