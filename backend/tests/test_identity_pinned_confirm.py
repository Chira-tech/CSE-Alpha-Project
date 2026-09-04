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
    all_validation_clean_pending_ids,
    identity_pinned_ids,
    validation_clean_ids,
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


# --- validation_clean_ids: the broad binary-model signal ------------------


def _clean_filing(db) -> list[Fundamental]:
    """A wholly-consistent balance sheet: foots in four independent
    directions, nine line items, every value plausible. Magnitudes are
    real-filing scale so an off-by-one-crore break clears the flat
    Rs 1,000 identity-rounding tolerance."""
    return [
        _row(db, line="total_assets", value="1000000000"),
        _row(db, line="total_equity", value="400000000"),
        _row(db, line="total_liabilities", value="600000000"),
        _row(db, line="total_equity_and_liabilities", value="1000000000"),
        _row(db, line="total_current_assets", value="300000000"),
        _row(db, line="total_non_current_assets", value="700000000"),
        _row(db, line="total_current_liabilities", value="250000000"),
        _row(db, line="total_non_current_liabilities", value="350000000"),
        _row(db, line="cash_and_cash_equivalents", value="120000000"),
    ]


def test_whole_clean_filing_is_admitted_line_by_line(db_session):
    _seed_security(db_session)
    rows = _clean_filing(db_session)
    clean = validation_clean_ids(db_session, rows)
    assert clean == {r.id for r in rows}


def test_one_broken_identity_disqualifies_the_whole_filing(db_session):
    _seed_security(db_session)
    rows = _clean_filing(db_session)
    # total_liabilities no longer foots with equity against assets
    bad = next(r for r in rows if r.statement_line == "total_liabilities")
    bad.value = Decimal("590000000")
    db_session.commit()
    assert validation_clean_ids(db_session, rows) == set()


def test_too_few_line_items_is_not_clean_just_unvalidated(db_session):
    _seed_security(db_session)
    rows = [
        _row(db_session, line="total_assets", value="1000"),
        _row(db_session, line="total_equity", value="400"),
        _row(db_session, line="total_liabilities", value="600"),
        _row(db_session, line="total_equity_and_liabilities", value="1000"),
    ]
    assert validation_clean_ids(db_session, rows) == set()


def test_a_single_computable_identity_is_not_enough(db_session):
    _seed_security(db_session)
    rows = [
        _row(db_session, line="total_assets", value="1000"),
        _row(db_session, line="total_equity_and_liabilities", value="1000"),
        _row(db_session, line="revenue", value="800"),
        _row(db_session, line="net_income", value="90"),
        _row(db_session, line="cash_and_cash_equivalents", value="120"),
        _row(db_session, line="property_plant_and_equipment", value="500"),
    ]
    # only "assets = equity and liabilities" computes — below the two-identity floor
    assert validation_clean_ids(db_session, rows) == set()


def test_already_reported_rows_are_not_re_promoted(db_session):
    _seed_security(db_session)
    rows = _clean_filing(db_session)
    rows[0].provenance_tier = ProvenanceTier.REPORTED
    rows[0].confirmed_by = "human"
    db_session.commit()
    clean = validation_clean_ids(db_session, rows)
    assert rows[0].id not in clean
    assert clean == {r.id for r in rows[1:]}


def test_all_validation_clean_pending_ids_sweeps_the_queue(db_session):
    _seed_security(db_session)
    rows = _clean_filing(db_session)
    assert all_validation_clean_pending_ids(db_session) == sorted(r.id for r in rows)
