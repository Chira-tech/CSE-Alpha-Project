"""§34 national project register wired to real stored data —
app.domain.national_projects_view."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.national_projects_view import (
    confirmed_base_case_impacts_for,
    confirmed_base_case_revenue_growth_adjustment_for,
)
from app.models.enums import (
    NationalProjectImpactMetric,
    NationalProjectStatus,
    NationalProjectTransmissionChannel,
    ProvenanceTier,
)
from app.models.national_projects import NationalProject, NationalProjectTickerImpact
from app.models.securities import Security

TICKER = "SWAD.N0000"
AS_OF = dt.date(2026, 8, 18)


def _seed_security(db, ticker=TICKER):
    db.add(Security(ticker=ticker, name="Swadeshi Industrial Works PLC"))
    db.commit()


def _seed_project(
    db,
    *,
    status=NationalProjectStatus.FINANCING_CLOSED,
    confirmed=True,
    confirmed_at=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc),
    rejected=False,
    impact_metric=NationalProjectImpactMetric.REVENUE,
    quantified_impact_pct=Decimal("0.015"),
    provenance_tag=ProvenanceTier.ESTIMATED,
    ticker=TICKER,
) -> NationalProject:
    project = NationalProject(
        name="Test project", status=status,
        confirmed_by="analyst" if confirmed else None,
        confirmed_at=confirmed_at if confirmed else None,
        rejected_by="analyst" if rejected else None,
        rejected_at=dt.datetime.now(dt.timezone.utc) if rejected else None,
    )
    db.add(project)
    db.flush()
    db.add(
        NationalProjectTickerImpact(
            project_id=project.id, ticker=ticker,
            transmission_channel=NationalProjectTransmissionChannel.MATERIALS_SUPPLIER,
            impact_metric=impact_metric, quantified_impact_pct=quantified_impact_pct,
            impact_description="Test fixture.", provenance_tag=provenance_tag,
        )
    )
    db.commit()
    return project


class TestConfirmedBaseCaseImpactsFor:
    def test_confirmed_financing_closed_project_is_included(self, db_session):
        _seed_security(db_session)
        _seed_project(db_session)
        impacts = confirmed_base_case_impacts_for(db_session, TICKER, AS_OF)
        assert len(impacts) == 1

    def test_unconfirmed_project_is_excluded(self, db_session):
        _seed_security(db_session)
        _seed_project(db_session, confirmed=False)
        assert confirmed_base_case_impacts_for(db_session, TICKER, AS_OF) == []

    def test_rejected_project_is_excluded(self, db_session):
        _seed_security(db_session)
        _seed_project(db_session, confirmed=True, rejected=True)
        assert confirmed_base_case_impacts_for(db_session, TICKER, AS_OF) == []

    def test_announced_stage_confirmed_project_is_excluded_from_base_case(self, db_session):
        _seed_security(db_session)
        _seed_project(db_session, status=NationalProjectStatus.ANNOUNCED)
        assert confirmed_base_case_impacts_for(db_session, TICKER, AS_OF) == []

    def test_confirmed_after_as_of_is_excluded(self, db_session):
        """Point-in-time: a project confirmed AFTER the valuation date
        must not backdate its influence — the same look-ahead-bias guard
        §6 applies everywhere else in this system."""
        _seed_security(db_session)
        _seed_project(db_session, confirmed_at=dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc))
        assert confirmed_base_case_impacts_for(db_session, TICKER, AS_OF) == []

    def test_different_ticker_is_excluded(self, db_session):
        _seed_security(db_session)
        _seed_security(db_session, ticker="OTHER.N0000")
        _seed_project(db_session, ticker="OTHER.N0000")
        assert confirmed_base_case_impacts_for(db_session, TICKER, AS_OF) == []


class TestConfirmedBaseCaseRevenueGrowthAdjustmentFor:
    def test_none_when_no_eligible_projects(self, db_session):
        _seed_security(db_session)
        adjustment, contributing = confirmed_base_case_revenue_growth_adjustment_for(
            db_session, TICKER, AS_OF
        )
        assert adjustment is None
        assert contributing == []

    def test_sums_multiple_confirmed_revenue_impacts(self, db_session):
        _seed_security(db_session)
        _seed_project(db_session, quantified_impact_pct=Decimal("0.015"))
        # A second, independent confirmed project also affecting this ticker.
        project2 = NationalProject(
            name="Second project", status=NationalProjectStatus.OPERATIONAL,
            confirmed_by="analyst", confirmed_at=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc),
        )
        db_session.add(project2)
        db_session.flush()
        db_session.add(
            NationalProjectTickerImpact(
                project_id=project2.id, ticker=TICKER,
                transmission_channel=NationalProjectTransmissionChannel.BENEFICIARY_OF_DEMAND,
                impact_metric=NationalProjectImpactMetric.REVENUE,
                quantified_impact_pct=Decimal("0.008"),
                impact_description="Test fixture.", provenance_tag=ProvenanceTier.FORECAST,
            )
        )
        db_session.commit()

        adjustment, contributing = confirmed_base_case_revenue_growth_adjustment_for(
            db_session, TICKER, AS_OF
        )
        assert adjustment == Decimal("0.023")
        assert len(contributing) == 2

    def test_margin_metric_impacts_are_excluded(self, db_session):
        _seed_security(db_session)
        _seed_project(db_session, impact_metric=NationalProjectImpactMetric.MARGIN)
        adjustment, contributing = confirmed_base_case_revenue_growth_adjustment_for(
            db_session, TICKER, AS_OF
        )
        assert adjustment is None
        assert contributing == []
