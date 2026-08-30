"""Data health endpoint — UI spec screen 9, Master Spec §8/§50."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from freezegun import freeze_time

from app.models.corporate_actions import CorporateAction
from app.models.corporate_actions import CorporateActionType as ActionType
from app.models.data_quality import DataAlert
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

NOW = dt.datetime.now(dt.timezone.utc)


def test_empty_database_reports_zeros_not_errors(client):
    health = client.get("/data-health").json()
    assert health["securities_count"] == 0
    assert health["price_rows"] == 0
    assert health["latest_price_date"] is None
    assert health["price_feed_age_days"] is None  # null, not 0 — we don't know
    assert health["quarantined"] == []


@freeze_time("2026-08-16")
def test_counts_and_feed_age(db_session, client):
    db_session.add_all(
        [
            Security(ticker="JKH.N0000", name="John Keells"),
            Security(ticker="AAF.N0000", name="Asia Asset"),
        ]
    )
    db_session.add(
        PriceDaily(ticker="JKH.N0000", date=dt.date(2026, 8, 14), close=Decimal("20"), fetched_at=NOW)
    )
    db_session.commit()

    health = client.get("/data-health").json()
    assert health["securities_count"] == 2
    assert health["price_rows"] == 1
    assert health["latest_price_date"] == "2026-08-14"
    assert health["price_feed_age_days"] == 2
    assert health["securities_with_no_price"] == 1  # AAF has none


def test_confirm_queue_counts_split_pending_confirmed_rejected(db_session, client):
    db_session.add(Security(ticker="JKH.N0000", name="John Keells"))
    db_session.add_all(
        [
            CorporateAction(ticker="JKH.N0000", ex_date=dt.date(2026, 1, 1), type=ActionType.DIVIDEND_CASH),
            CorporateAction(
                ticker="JKH.N0000",
                ex_date=dt.date(2026, 2, 1),
                type=ActionType.DIVIDEND_CASH,
                confirmed_by="analyst",
                confirmed_at=NOW,
            ),
            CorporateAction(
                ticker="JKH.N0000",
                ex_date=dt.date(2026, 3, 1),
                type=ActionType.DIVIDEND_CASH,
                rejected_by="analyst",
                rejected_at=NOW,
            ),
        ]
    )
    db_session.commit()

    health = client.get("/data-health").json()
    assert health["corporate_actions_total"] == 3
    assert health["corporate_actions_pending"] == 1
    assert health["corporate_actions_confirmed"] == 1
    assert health["corporate_actions_rejected"] == 1


def test_fundamentals_pending_counts_only_unconfirmed_ai_assisted(db_session, client):
    db_session.add(Security(ticker="JFP.N0000", name="JF Packaging"))
    common = dict(
        ticker="JFP.N0000",
        period_end=dt.date(2026, 3, 31),
        period_type="annual",
        first_available_date=dt.date(2026, 8, 14),
        version=1,
        value=Decimal("1"),
    )
    db_session.add_all(
        [
            Fundamental(**common, statement_line="a", provenance_tier=ProvenanceTier.AI_ASSISTED),
            Fundamental(
                **common,
                statement_line="b",
                provenance_tier=ProvenanceTier.REPORTED,
                confirmed_by="analyst",
                confirmed_at=NOW,
            ),
            # Reported-from-the-start rows were never drafts and must not
            # inflate the pending count.
            Fundamental(**common, statement_line="c", provenance_tier=ProvenanceTier.REPORTED),
        ]
    )
    db_session.commit()

    health = client.get("/data-health").json()
    assert health["fundamentals_total"] == 3
    assert health["fundamentals_pending_confirmation"] == 1
    assert health["fundamentals_confirmed"] == 1


def test_confirm_burn_down_counts_last_7_days_only(db_session, client):
    """The redesign doc's §3.6 burn-down signal: how much is being
    cleared, next to how much is left."""
    db_session.add(Security(ticker="JKH.N0000", name="John Keells"))
    recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
    db_session.add_all(
        [
            Fundamental(
                ticker="JKH.N0000", period_end=dt.date(2025, 12, 31), period_type="annual",
                first_available_date=dt.date(2026, 3, 1), version=1, statement_line="revenue",
                value=Decimal("1"), provenance_tier=ProvenanceTier.REPORTED,
                confirmed_by="a", confirmed_at=recent,
            ),
            Fundamental(
                ticker="JKH.N0000", period_end=dt.date(2024, 12, 31), period_type="annual",
                first_available_date=dt.date(2025, 3, 1), version=1, statement_line="revenue",
                value=Decimal("1"), provenance_tier=ProvenanceTier.REPORTED,
                confirmed_by="a", confirmed_at=old,
            ),
            CorporateAction(
                ticker="JKH.N0000", ex_date=dt.date(2026, 2, 1), type=ActionType.DIVIDEND_CASH,
                confirmed_by="a", confirmed_at=recent,
            ),
        ]
    )
    db_session.commit()

    health = client.get("/data-health").json()
    assert health["fundamentals_confirmed_last_7d"] == 1
    assert health["corporate_actions_confirmed_last_7d"] == 1


def test_quarantined_lists_only_unresolved_alerts(db_session, client):
    db_session.add_all(
        [
            DataAlert(
                ticker="AAF.N0000",
                alert_type="reconciliation_mismatch",
                detail="mismatch 1.2%",
                raised_at=NOW,
                resolved=False,
            ),
            DataAlert(
                ticker="JKH.N0000",
                alert_type="reconciliation_mismatch",
                detail="already sorted out",
                raised_at=NOW,
                resolved=True,
            ),
        ]
    )
    db_session.commit()

    health = client.get("/data-health").json()
    assert [q["ticker"] for q in health["quarantined"]] == ["AAF.N0000"]
