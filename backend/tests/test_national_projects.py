"""§34 national project register — app.domain.national_projects."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.national_projects import (
    TickerImpact,
    may_influence_base_case,
    may_influence_bull_case,
    net_revenue_growth_adjustment,
    status_rank,
    validate_impact_provenance_tag,
)
from app.models.enums import NationalProjectImpactMetric, NationalProjectStatus, ProvenanceTier


class TestStatusRank:
    def test_ladder_is_strictly_increasing(self):
        assert status_rank(NationalProjectStatus.ANNOUNCED) < status_rank(NationalProjectStatus.MOU)
        assert status_rank(NationalProjectStatus.MOU) < status_rank(NationalProjectStatus.FINANCING_CLOSED)
        assert status_rank(NationalProjectStatus.FINANCING_CLOSED) < status_rank(
            NationalProjectStatus.UNDER_CONSTRUCTION
        )
        assert status_rank(NationalProjectStatus.UNDER_CONSTRUCTION) < status_rank(
            NationalProjectStatus.OPERATIONAL
        )


class TestMayInfluenceBaseCase:
    def test_announced_confirmed_does_not_qualify(self):
        assert not may_influence_base_case(NationalProjectStatus.ANNOUNCED, is_confirmed=True)

    def test_mou_confirmed_does_not_qualify(self):
        assert not may_influence_base_case(NationalProjectStatus.MOU, is_confirmed=True)

    def test_financing_closed_confirmed_qualifies(self):
        assert may_influence_base_case(NationalProjectStatus.FINANCING_CLOSED, is_confirmed=True)

    def test_operational_confirmed_qualifies(self):
        assert may_influence_base_case(NationalProjectStatus.OPERATIONAL, is_confirmed=True)

    def test_financing_closed_unconfirmed_does_not_qualify(self):
        """§34's blanket rule: confirmation is required regardless of
        status — an unconfirmed financing-closed project still cannot
        affect any valuation."""
        assert not may_influence_base_case(NationalProjectStatus.FINANCING_CLOSED, is_confirmed=False)


class TestMayInfluenceBullCase:
    def test_announced_confirmed_qualifies(self):
        """§34: earlier stages influence only the bull case — but they
        DO influence it, once confirmed."""
        assert may_influence_bull_case(NationalProjectStatus.ANNOUNCED, is_confirmed=True)

    def test_announced_unconfirmed_does_not_qualify(self):
        assert not may_influence_bull_case(NationalProjectStatus.ANNOUNCED, is_confirmed=False)

    def test_operational_confirmed_qualifies(self):
        """The bull case is the superset — base-case-eligible statuses
        remain bull-case-eligible too."""
        assert may_influence_bull_case(NationalProjectStatus.OPERATIONAL, is_confirmed=True)


class TestValidateImpactProvenanceTag:
    def test_estimated_is_valid(self):
        validate_impact_provenance_tag(ProvenanceTier.ESTIMATED)  # does not raise

    def test_forecast_is_valid(self):
        validate_impact_provenance_tag(ProvenanceTier.FORECAST)  # does not raise

    @pytest.mark.parametrize(
        "tag",
        [
            ProvenanceTier.REPORTED,
            ProvenanceTier.DERIVED,
            ProvenanceTier.NORMALISED,
            ProvenanceTier.AI_ASSISTED,
            ProvenanceTier.UNAVAILABLE,
        ],
    )
    def test_every_other_tier_is_rejected(self, tag):
        with pytest.raises(ValueError, match="ESTIMATED.*FORECAST|E.*or.*F"):
            validate_impact_provenance_tag(tag)


class TestNetRevenueGrowthAdjustment:
    def test_none_when_no_revenue_impacts(self):
        impacts = [
            TickerImpact(NationalProjectImpactMetric.MARGIN, Decimal("0.02")),
        ]
        assert net_revenue_growth_adjustment(impacts) is None

    def test_none_when_revenue_impact_has_no_quantified_value_yet(self):
        impacts = [TickerImpact(NationalProjectImpactMetric.REVENUE, None)]
        assert net_revenue_growth_adjustment(impacts) is None

    def test_sums_multiple_confirmed_revenue_impacts(self):
        impacts = [
            TickerImpact(NationalProjectImpactMetric.REVENUE, Decimal("0.015")),
            TickerImpact(NationalProjectImpactMetric.REVENUE, Decimal("0.008")),
            TickerImpact(NationalProjectImpactMetric.MARGIN, Decimal("0.05")),  # excluded
        ]
        assert net_revenue_growth_adjustment(impacts) == Decimal("0.023")

    def test_empty_list_gives_none(self):
        assert net_revenue_growth_adjustment([]) is None
