"""
§15 sector frameworks + §16 model router.

Every archetype in Appendix P2's 15-item list is exercised at least once
so a gap in the routing table shows up as a failing test, not a runtime
KeyError on whichever company happens to hit it first in production.
"""
from __future__ import annotations

from app.domain.archetype import ARCHETYPES
from app.domain.valuation_router import route_valuation


class TestTheCaseTheSpecBuildsTheWholeSectionAround:
    def test_a_bank_never_gets_a_firm_side_model(self):
        """§15's own words: "a bank's debt is its raw material, not its
        financing; free cash flow to the firm is not a meaningful
        concept for it." This is the specific error the router exists to
        make impossible."""
        decision = route_valuation("bank")
        suppressed_models = {s.model for s in decision.suppressed}
        assert "FCFF DCF" in suppressed_models
        assert "EV/EBIT" in suppressed_models
        assert "EV/EBITDA" in suppressed_models
        for model in decision.primary_models:
            assert model not in suppressed_models

    def test_every_suppression_carries_a_stated_reason(self):
        """§16: "If a model was suppressed, the user sees which one and
        why" — a suppression with an empty reason would fail that
        requirement even if the model name were correct."""
        decision = route_valuation("bank")
        assert decision.suppressed
        for s in decision.suppressed:
            assert s.reason.strip()

    def test_a_bank_routes_to_its_published_primary_models(self):
        decision = route_valuation("bank")
        assert decision.primary_models == (
            "Justified P/TBV from ROE", "Residual income", "Multi-stage DDM",
        )
        assert "EV/EBIT" in decision.meaningless_metrics


class TestFinancialFirmClassification:
    def test_non_bank_finance_and_insurance_are_also_financial_firms(self):
        for archetype in ("non_bank_finance", "insurance"):
            decision = route_valuation(archetype)
            assert decision.is_financial_firm
            assert any(s.model == "FCFF DCF" for s in decision.suppressed)

    def test_an_operating_business_is_not_a_financial_firm(self):
        decision = route_valuation("manufacturing")
        assert not decision.is_financial_firm
        assert decision.suppressed == ()


class TestHoldingCompanyRouting:
    def test_a_diversified_holding_routes_to_sum_of_the_parts(self):
        decision = route_valuation("diversified_holding")
        assert decision.is_holding_company
        assert "Sum-of-the-parts" in decision.primary_models
        assert "Consolidated margins" in decision.meaningless_metrics

    def test_only_diversified_holding_is_flagged_a_holding_company(self):
        decision = route_valuation("manufacturing")
        assert not decision.is_holding_company


class TestCyclicalNormalisation:
    def test_plantations_require_earnings_normalisation(self):
        """§15's own example: "Normalised mid-cycle earnings" for
        plantations, and P/E in a commodity trough is explicitly named
        meaningless."""
        decision = route_valuation("plantation")
        assert decision.requires_earnings_normalisation
        assert "P/E in a commodity trough" in decision.meaningless_metrics

    def test_power_and_energy_also_requires_normalisation(self):
        decision = route_valuation("power_energy")
        assert decision.requires_earnings_normalisation

    def test_consumer_does_not_require_normalisation(self):
        decision = route_valuation("consumer")
        assert not decision.requires_earnings_normalisation


class TestUnansweredRoutingQuestions:
    def test_cash_flow_predictability_is_reported_as_unanswerable_not_assumed(self):
        """This system does not extract CFO/FCF at all. Silently treating
        net income as a stand-in for "cash flows positive and
        predictable" would be exactly the kind of unstated substitution
        this project has avoided everywhere else."""
        decision = route_valuation("manufacturing")
        questions = {q.question for q in decision.unanswered_questions}
        assert "Are cash flows positive and reasonably predictable?" in questions

    def test_distress_routing_is_unanswerable_without_an_altman_z(self):
        decision = route_valuation("manufacturing")
        missing = {q.missing_input for q in decision.unanswered_questions}
        assert any("Altman Z" in m for m in missing)

    def test_unanswered_questions_are_reported_even_with_no_archetype(self):
        """What CAN'T be answered doesn't depend on what CAN — both facts
        are true regardless of whether archetype routing succeeded."""
        decision = route_valuation(None)
        assert len(decision.unanswered_questions) == 3


class TestMissingOrUnrecognisedArchetype:
    def test_no_archetype_blocks_routing_rather_than_defaulting(self):
        """The exact failure mode this module exists to prevent: silently
        falling back to a generic profile the moment archetype
        confirmation lags would eventually apply an industrial DCF to an
        unconfirmed bank."""
        decision = route_valuation(None)
        assert decision.primary_models == ()
        assert not decision.in_published_table
        assert "no archetype" in decision.note.lower()

    def test_an_unrecognised_archetype_string_is_refused_not_guessed(self):
        decision = route_valuation("not_a_real_archetype")
        assert decision.primary_models == ()
        assert "Unrecognised archetype" in decision.note


class TestEveryPublishedArchetypeIsCovered:
    def test_every_appendix_p2_archetype_routes_to_something(self):
        """15 archetypes are named in Appendix P2. A KeyError on any one
        of them in production would mean a real company's page crashes —
        this is the test that catches a gap before that happens."""
        for archetype in ARCHETYPES:
            decision = route_valuation(archetype)
            assert decision.archetype == archetype
            assert decision.note != "" or decision.primary_models != ()

    def test_the_twelve_published_table_rows_are_marked_as_such(self):
        published = {
            "bank", "non_bank_finance", "insurance", "diversified_holding",
            "manufacturing", "consumer", "plantation", "hotel", "telecom",
            "construction_materials", "power_energy", "property",
        }
        for archetype in published:
            assert route_valuation(archetype).in_published_table, archetype

    def test_healthcare_logistics_and_other_are_marked_as_not_in_the_table(self):
        """§15's table has 12 rows; Appendix P2 lists 15 archetypes.
        These three are real archetypes with no published row, and
        pretending otherwise would misrepresent what the spec says."""
        for archetype in ("healthcare", "logistics", "other"):
            decision = route_valuation(archetype)
            assert not decision.in_published_table
            assert decision.note.strip()
