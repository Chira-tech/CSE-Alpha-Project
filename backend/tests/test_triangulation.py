"""§24 triangulation — hand-worked blends, and category derivation
cross-checked against the real `app.domain.valuation_router` routing
decisions rather than a second hand-coded archetype list."""
from __future__ import annotations

from decimal import Decimal

from app.domain.triangulation import (
    ValuationAnchor,
    triangulate,
    triangulation_category_for_archetype,
)
from app.domain.valuation_router import route_valuation


class TestCategoryDerivation:
    def test_bank_is_bank_finance(self):
        assert triangulation_category_for_archetype(route_valuation("bank")) == "bank_finance"

    def test_non_bank_finance_is_bank_finance(self):
        assert triangulation_category_for_archetype(route_valuation("non_bank_finance")) == "bank_finance"

    def test_insurance_is_insurance_not_bank_finance(self):
        assert triangulation_category_for_archetype(route_valuation("insurance")) == "insurance"

    def test_diversified_holding_is_conglomerate_holding(self):
        assert (
            triangulation_category_for_archetype(route_valuation("diversified_holding"))
            == "conglomerate_holding"
        )

    def test_property_is_property_not_operating(self):
        assert triangulation_category_for_archetype(route_valuation("property")) == "property"

    def test_plantation_is_cyclical(self):
        assert triangulation_category_for_archetype(route_valuation("plantation")) == "cyclical"

    def test_hotel_is_cyclical(self):
        assert triangulation_category_for_archetype(route_valuation("hotel")) == "cyclical"

    def test_manufacturing_is_operating(self):
        assert triangulation_category_for_archetype(route_valuation("manufacturing")) == "operating"

    def test_none_archetype_falls_through_to_operating(self):
        # An unconfirmed archetype no longer blocks the blend — whatever
        # anchors computed are worth an "operating" DCF+relative+book
        # blend, graded down elsewhere on the low anchor count.
        assert triangulation_category_for_archetype(route_valuation(None)) == "operating"

    def test_unrecognised_archetype_falls_through_to_operating(self):
        assert (
            triangulation_category_for_archetype(route_valuation("not_a_real_archetype"))
            == "operating"
        )

    def test_archetype_not_in_the_published_table_falls_through_to_operating(self):
        # healthcare / logistics / "other" route to real models but were
        # not in §15's 12-row table, so they used to get no blend at all.
        for a in ("other", "healthcare", "logistics"):
            assert triangulation_category_for_archetype(route_valuation(a)) == "operating"


class TestTriangulate:
    def test_hand_worked_full_blend(self):
        routing = route_valuation("bank")  # 0.40 / 0.35 / 0.25
        anchors = (
            ValuationAnchor("Residual income", "intrinsic", Decimal(100)),
            ValuationAnchor("Multi-stage DDM", "intrinsic", Decimal(110)),
            ValuationAnchor("Justified P/TBV NAV", "asset_sotp", Decimal(95)),
            ValuationAnchor("Justified P/B", "relative", Decimal(120)),
        )
        result = triangulate(routing, anchors)

        assert result.triangulation_category == "bank_finance"
        assert result.category_averages["intrinsic"] == Decimal(105)
        assert result.missing_categories == ()
        # 0.40*105 + 0.35*95 + 0.25*120 = 42 + 33.25 + 30 = 105.25
        assert abs(result.blended_fair_value_per_share - Decimal("105.25")) < Decimal("0.0001")

        # dispersion: values [100,110,95,120], mean 106.25, range 25
        expected_dispersion = Decimal(25) / Decimal("106.25")
        assert abs(result.dispersion_pct - expected_dispersion) < Decimal("0.0001")
        assert result.warnings == ()

    def test_missing_category_renormalises_weights(self):
        routing = route_valuation("manufacturing")  # 0.45 / 0.15 / 0.40
        anchors = (
            ValuationAnchor("FCFF DCF", "intrinsic", Decimal(200)),
            ValuationAnchor("Justified EV/EBIT", "relative", Decimal(180)),
        )
        result = triangulate(routing, anchors)

        assert result.missing_categories == ("asset_sotp",)
        # (200*0.45 + 180*0.40) / (0.45+0.40) = 162/0.85
        expected = (Decimal(200) * Decimal("0.45") + Decimal(180) * Decimal("0.40")) / Decimal("0.85")
        assert abs(result.blended_fair_value_per_share - expected) < Decimal("0.0001")
        assert any("renormalised" in w for w in result.warnings)

    def test_no_anchors_gives_none_blend_and_warning(self):
        routing = route_valuation("bank")
        result = triangulate(routing, ())
        assert result.blended_fair_value_per_share is None
        assert any("No anchors supplied" in w for w in result.warnings)

    def test_single_anchor_blends_but_dispersion_needs_two(self):
        routing = route_valuation("property")
        result = triangulate(routing, (ValuationAnchor("NAV", "asset_sotp", Decimal(50)),))
        assert result.dispersion_pct is None
        assert any("at least 2" in w for w in result.warnings)

    def test_unconfirmed_archetype_still_blends_whatever_computed(self):
        # No archetype -> the generic "operating" blend of whatever
        # anchors are supplied, rather than withholding a fair value the
        # inputs can actually support.
        routing = route_valuation(None)
        result = triangulate(routing, (ValuationAnchor("FCFF DCF", "intrinsic", Decimal(100)),))
        assert result.blended_fair_value_per_share == Decimal(100)
        assert result.triangulation_category == "operating"
