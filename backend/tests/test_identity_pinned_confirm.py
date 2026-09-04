"""`app.domain.corroboration_view.identity_pinned_ids` — the second
"safe to confirm without a human" signal alongside independent
corroboration.

A re-extracted AI-assisted value is promotable when it is arithmetically
pinned by an accounting identity that already balances against a
human-confirmed line on the same filing. Found necessary 4 Sep 2026:
LOLC's re-extracted "equity attributable to owners" and "non-controlling
interest" both foot to its confirmed `total_equity` yet the multi-signal
cross-check would not promote them.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.corroboration_view import (
    all_identity_pinned_pending_ids,
    identity_pinned_ids,
)
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.securities import Security

TICKER = "LOLC.N0000"
PERIOD_END = dt.date(2026, 3, 31)


def _seed_security(db, ticker=TICKER):
    db.add(Security(ticker=ticker, name="LOLC Holdings PLC"))
    db.commit()


def _row(db, *, line, value, tier=ProvenanceTier.AI_ASSISTED, version=1, **over) -> Fundamental:
    defaults = dict(
        ticker=TICKER,
        period_end=PERIOD_END,
        period_type="annual",
        first_available_date=dt.date(2026, 8, 14),
        version=version,
        statement_line=line,
        value=Decimal(value),
        currency="LKR",
        provenance_tier=tier,
        restated_flag=False,
        source_snippet="",
        confirmed_by="human" if tier == ProvenanceTier.REPORTED else None,
        confirmed_at=None,
    )
    defaults.update(over)
    r = Fundamental(**defaults)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_owners_equity_and_nci_pinned_by_confirmed_total_equity(db_session):
    """owners' equity + NCI foot exactly to a confirmed total_equity —
    both AI-assisted lines are pinned."""
    _seed_security(db_session)
    total_equity = _row(
        db_session, line="total_equity", value="654267819000",
        tier=ProvenanceTier.REPORTED,
    )
    owners = _row(db_session, line="equity_attributable_to_owners", value="390834232000")
    nci = _row(db_session, line="non_controlling_interest", value="263433587000")

    pinned = identity_pinned_ids(db_session, [owners, nci, total_equity])
    assert pinned == {owners.id, nci.id}
    # already-confirmed rows are never "promoted"
    assert total_equity.id not in pinned


def test_not_pinned_when_identity_does_not_foot(db_session):
    _seed_security(db_session)
    _row(db_session, line="total_equity", value="654267819000", tier=ProvenanceTier.REPORTED)
    owners = _row(db_session, line="equity_attributable_to_owners", value="111111111111")
    nci = _row(db_session, line="non_controlling_interest", value="263433587000")

    assert identity_pinned_ids(db_session, [owners, nci]) == set()


def test_not_pinned_when_no_line_of_the_identity_is_confirmed(db_session):
    """Every participating line is AI-assisted — nothing anchors the
    identity, so a shared corrupt read could still foot. Not promotable."""
    _seed_security(db_session)
    total_equity = _row(db_session, line="total_equity", value="654267819000")
    owners = _row(db_session, line="equity_attributable_to_owners", value="390834232000")
    nci = _row(db_session, line="non_controlling_interest", value="263433587000")

    assert identity_pinned_ids(db_session, [owners, nci, total_equity]) == set()


def test_filing_with_a_broken_footing_promotes_nothing(db_session):
    """RHL.X0000, 4 Sep 2026: a dropped leading digit made `total_equity`
    Rs 20bn short, so `assets = equity + liabilities` is broken — even
    though `owners equity + NCI = total equity` foots against that
    corrupted total, nothing on the filing is auto-confirmed."""
    _seed_security(db_session)
    _row(db_session, line="total_assets", value="29916337000", tier=ProvenanceTier.REPORTED)
    _row(db_session, line="total_liabilities", value="7996732000", tier=ProvenanceTier.REPORTED)
    # dropped digit: real is ~21_919_605_000
    _row(db_session, line="total_equity", value="1919605000", tier=ProvenanceTier.REPORTED)
    owners = _row(db_session, line="equity_attributable_to_owners", value="785451000")
    nci = _row(db_session, line="non_controlling_interest", value="1134154000")

    assert identity_pinned_ids(db_session, [owners, nci]) == set()


def test_all_identity_pinned_pending_ids_sweeps_the_queue(db_session):
    _seed_security(db_session)
    _row(db_session, line="total_equity", value="654267819000", tier=ProvenanceTier.REPORTED)
    owners = _row(db_session, line="equity_attributable_to_owners", value="390834232000")
    nci = _row(db_session, line="non_controlling_interest", value="263433587000")

    assert all_identity_pinned_pending_ids(db_session) == sorted([owners.id, nci.id])
