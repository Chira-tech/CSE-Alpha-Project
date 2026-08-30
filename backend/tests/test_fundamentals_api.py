"""The fundamentals confirm-queue API (Master Spec §8: AI-assisted values
"cannot enter a valuation until human-confirmed and promoted to
Reported")."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.securities import Security

TICKER = "JFP.N0000"


def _seed_security(db, ticker=TICKER):
    db.add(Security(ticker=ticker, name="JF Packaging PLC"))
    db.commit()


def _seed_ai_assisted(db, **overrides) -> Fundamental:
    defaults = dict(
        ticker=TICKER,
        period_end=dt.date(2026, 3, 31),
        period_type="annual",
        first_available_date=dt.date(2026, 8, 14),
        version=1,
        statement_line="total_assets",
        value=Decimal("3807110"),
        currency="LKR",
        provenance_tier=ProvenanceTier.AI_ASSISTED,
        restated_flag=False,
        source_snippet="Total Assets 3,807,110 3,722,727 3,559,834 3,453,018",
        confirmed_by=None,
        confirmed_at=None,
    )
    defaults.update(overrides)
    row = Fundamental(**defaults)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- GET /fundamentals/summary (queue composition, redesign doc §3) ------


def test_queue_summary_buckets_by_type_and_flags_old_filings(client, db_session):
    _seed_security(db_session)
    _seed_ai_assisted(db_session, statement_line="total_assets", period_type="annual")
    _seed_ai_assisted(db_session, statement_line="net_income", period_type="annual")
    _seed_ai_assisted(
        db_session, statement_line="revenue", period_type="quarterly",
        first_available_date=dt.date(2019, 5, 1),  # filed years ago, still pending
    )
    # A confirmed row must not show up in any pending bucket.
    _seed_ai_assisted(
        db_session, statement_line="equity", provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="someone", confirmed_at=dt.datetime.now(dt.timezone.utc),
    )

    body = client.get("/fundamentals/summary").json()

    assert body["pending_total"] == 3
    assert {b["key"]: b["count"] for b in body["by_period_type"]} == {"annual": 2, "quarterly": 1}
    assert {b["key"] for b in body["by_statement_line"]} == {"total_assets", "net_income", "revenue"}
    assert body["by_ticker"][0] == {"key": TICKER, "count": 3}
    assert body["oldest_pending_first_available"] == "2019-05-01"
    assert body["pending_filed_over_a_year_ago"] == 1
    assert body["corroborated_pending"] == 0


def test_queue_summary_counts_corroborated_pending(client, db_session):
    _seed_security(db_session)
    pending = _seed_ai_assisted(db_session, statement_line="net_income", value=Decimal("500"),
                                source_url="https://cse/ai.pdf")
    _seed_ai_assisted(
        db_session, statement_line="net_income", value=Decimal("500"), version=2,
        provenance_tier=ProvenanceTier.REPORTED, source_url="https://cse/audited.pdf",
        confirmed_by="a human", confirmed_at=dt.datetime.now(dt.timezone.utc),
    )

    body = client.get("/fundamentals/summary").json()
    assert body["corroborated_pending"] == 1


# --- (ticker, period_end, period_type, statement_line, version) uniqueness ---
# Migration 0019: the database-level backstop behind every ingestion path's
# own application-level idempotency check (`_already_ingested`,
# `_already_ingested_by_source`) — closes a real, narrow concurrent-run race
# (two ingestion processes hitting the exact same filing at the exact same
# moment could both pass their own check before either commits).


def test_duplicate_ticker_period_type_line_version_is_rejected_at_the_db_level(db_session):
    """The real invariant this migration backs: every legitimate code path
    already avoids producing this on its own (see migration 0019's own
    docstring), so this test exercises the database-level backstop
    directly — a second row with the SAME 5-tuple, not routed through any
    application code that would normally prevent it, must still be
    refused by the schema itself."""
    _seed_security(db_session)
    _seed_ai_assisted(db_session, statement_line="net_income", version=1)
    with pytest.raises(IntegrityError):
        _seed_ai_assisted(db_session, statement_line="net_income", version=1)


def test_same_period_different_version_is_allowed(db_session):
    """The constraint's own point: a GENUINE second filing for the same
    period (a restatement, or an independently-sourced corroborating
    reprint) always gets a different `version` from `_next_version`, and
    must remain completely unaffected by this constraint."""
    _seed_security(db_session)
    row1 = _seed_ai_assisted(db_session, statement_line="net_income", version=1)
    row2 = _seed_ai_assisted(db_session, statement_line="net_income", version=2)
    assert row1.id != row2.id


def test_list_defaults_to_pending_ai_assisted_only(db_session, client):
    _seed_security(db_session)
    _seed_ai_assisted(db_session)
    _seed_ai_assisted(
        db_session,
        statement_line="net_income",
        value=Decimal("189908"),
        provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="analyst",
        confirmed_at=dt.datetime.now(dt.timezone.utc),
    )

    response = client.get("/fundamentals")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    rows = body["items"]
    assert len(rows) == 1
    assert rows[0]["statement_line"] == "total_assets"
    assert rows[0]["provenance_tier"] == "A"


def test_confirm_promotes_to_reported(db_session, client):
    _seed_security(db_session)
    row = _seed_ai_assisted(db_session)

    response = client.post(f"/fundamentals/{row.id}/confirm", json={"actor": "analyst"})
    assert response.status_code == 200
    body = response.json()
    assert body["provenance_tier"] == "R"
    assert body["confirmed_by"] == "analyst"
    assert body["value"] == "3807110.0000"
    # version and first_available_date must be untouched by confirmation
    assert body["version"] == 1
    assert body["first_available_date"] == "2026-08-14"


def test_confirm_with_correction_updates_value_without_bumping_version(db_session, client):
    _seed_security(db_session)
    row = _seed_ai_assisted(db_session, value=Decimal("999999"))  # extractor picked the wrong column

    response = client.post(
        f"/fundamentals/{row.id}/confirm",
        json={"actor": "analyst", "correction": {"value": "3807110"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["value"]) == Decimal("3807110")
    assert body["version"] == 1  # a correction to OUR extraction is not a restatement


def test_cannot_confirm_twice(db_session, client):
    _seed_security(db_session)
    row = _seed_ai_assisted(db_session)
    client.post(f"/fundamentals/{row.id}/confirm", json={"actor": "analyst"})

    response = client.post(f"/fundamentals/{row.id}/confirm", json={"actor": "someone-else"})
    assert response.status_code == 409


def test_cannot_confirm_a_row_that_is_already_reported(db_session, client):
    """Only the AI-assisted -> Reported promotion goes through this
    endpoint; a genuinely Reported row was never a draft in the first
    place and has nothing to be "confirmed" into."""
    _seed_security(db_session)
    row = _seed_ai_assisted(db_session, provenance_tier=ProvenanceTier.REPORTED)

    response = client.post(f"/fundamentals/{row.id}/confirm", json={"actor": "analyst"})
    assert response.status_code == 409
    assert "AI-assisted" in response.json()["detail"]


def test_get_unknown_id_404s(client):
    response = client.get("/fundamentals/999999")
    assert response.status_code == 404


def test_list_pending_only_false_returns_everything(db_session, client):
    _seed_security(db_session)
    _seed_ai_assisted(db_session)
    _seed_ai_assisted(
        db_session,
        statement_line="net_income",
        provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="analyst",
        confirmed_at=dt.datetime.now(dt.timezone.utc),
    )

    response = client.get("/fundamentals", params={"pending_only": False})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_is_paged_with_a_default_limit_of_20(db_session, client):
    _seed_security(db_session)
    for i in range(25):
        _seed_ai_assisted(db_session, statement_line=f"line_{i:02d}")

    response = client.get("/fundamentals")
    body = response.json()
    assert body["total"] == 25
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["items"]) == 20


def test_list_second_page_via_offset(db_session, client):
    _seed_security(db_session)
    for i in range(25):
        _seed_ai_assisted(db_session, statement_line=f"line_{i:02d}")

    response = client.get("/fundamentals", params={"limit": 20, "offset": 20})
    body = response.json()
    assert body["total"] == 25
    assert body["offset"] == 20
    assert len(body["items"]) == 5  # the remainder, not a short page error


def test_confirm_batch_promotes_every_valid_id(db_session, client):
    _seed_security(db_session)
    rows = [_seed_ai_assisted(db_session, statement_line=f"line_{i}") for i in range(3)]

    response = client.post(
        "/fundamentals/confirm-batch",
        json={"actor": "analyst", "ids": [r.id for r in rows]},
    )
    assert response.status_code == 200
    body = response.json()
    assert sorted(body["confirmed"]) == sorted(r.id for r in rows)
    assert body["failed"] == []

    for r in rows:
        db_session.refresh(r)
        assert r.provenance_tier == ProvenanceTier.REPORTED
        assert r.confirmed_by == "analyst"


def test_confirm_batch_reports_bad_ids_without_failing_the_good_ones(db_session, client):
    _seed_security(db_session)
    good = _seed_ai_assisted(db_session, statement_line="total_assets")
    already_confirmed = _seed_ai_assisted(
        db_session,
        statement_line="net_income",
        confirmed_by="someone-else",
        confirmed_at=dt.datetime.now(dt.timezone.utc),
        provenance_tier=ProvenanceTier.REPORTED,
    )

    response = client.post(
        "/fundamentals/confirm-batch",
        json={"actor": "analyst", "ids": [good.id, already_confirmed.id, 999999]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["confirmed"] == [good.id]
    failed_ids = {f["id"] for f in body["failed"]}
    assert failed_ids == {already_confirmed.id, 999999}


# --- R1 T2.5: corroboration-gated bulk confirm ----------------------------
# Built directly in response to OI-1 (docs/audits/R1_OPEN_ISSUES.md): a
# careless bulk-confirm pass with no corroboration check promoted 396
# wrong figures to REPORTED tier. This is the safe replacement.


def test_corroborated_flag_true_when_an_independent_reported_row_matches(db_session, client):
    _seed_security(db_session)
    pending = _seed_ai_assisted(
        db_session, statement_line="net_income", value=Decimal("22889584"),
        source_url="https://cdn.cse.lk/original.pdf",
    )
    # A DIFFERENT filing (e.g. next year's comparative column) already
    # REPORTED the exact same figure — genuine independent corroboration.
    # A real ingestion of a second, distinct source_url for this same
    # period always gets version=2 from `_next_version` — matched here so
    # this fixture reflects what real data actually looks like, not just
    # what the corroboration query itself checks (it doesn't key on
    # version at all — see `_corroborated_ids`'s own docstring — but the
    # unique constraint on (ticker, period_end, period_type,
    # statement_line, version) does, migration 0019).
    _seed_ai_assisted(
        db_session, statement_line="net_income", value=Decimal("22889584"),
        source_url="https://cdn.cse.lk/later_filing.pdf", version=2,
        provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="analyst", confirmed_at=dt.datetime.now(dt.timezone.utc),
    )

    body = client.get("/fundamentals").json()
    row = next(r for r in body["items"] if r["id"] == pending.id)
    assert row["corroborated"] is True


def test_corroborated_flag_false_with_no_independent_match(db_session, client):
    _seed_security(db_session)
    pending = _seed_ai_assisted(db_session, statement_line="net_income", value=Decimal("9"))

    body = client.get("/fundamentals").json()
    row = next(r for r in body["items"] if r["id"] == pending.id)
    assert row["corroborated"] is False


def test_corroborated_flag_false_when_only_match_is_the_same_source_url(db_session, client):
    """Same source_url twice is not independent corroboration — it's the
    same document counted twice. `version=2` on the second row only to
    satisfy the (ticker, period_end, period_type, statement_line,
    version) uniqueness constraint (migration 0019) so this fixture can
    exist at all — same source_url, different version isn't a real shape
    ordinary ingestion produces (it would have skipped re-ingesting an
    identical PDF outright), this is deliberately a synthetic case
    probing the API's own defensive same-source_url check specifically."""
    _seed_security(db_session)
    pending = _seed_ai_assisted(
        db_session, statement_line="net_income", value=Decimal("9"),
        source_url="https://cdn.cse.lk/same.pdf",
    )
    _seed_ai_assisted(
        db_session, statement_line="net_income", value=Decimal("9"),
        source_url="https://cdn.cse.lk/same.pdf", version=2,
        provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="analyst", confirmed_at=dt.datetime.now(dt.timezone.utc),
    )

    body = client.get("/fundamentals").json()
    row = next(r for r in body["items"] if r["id"] == pending.id)
    assert row["corroborated"] is False


def test_confirm_batch_corroborated_promotes_only_genuinely_corroborated_rows(db_session, client):
    _seed_security(db_session)
    corroborated_row = _seed_ai_assisted(
        db_session, statement_line="revenue", value=Decimal("261589819"),
        source_url="https://cdn.cse.lk/a.pdf",
    )
    _seed_ai_assisted(
        db_session, statement_line="revenue", value=Decimal("261589819"),
        source_url="https://cdn.cse.lk/b.pdf", version=2,
        provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="analyst", confirmed_at=dt.datetime.now(dt.timezone.utc),
    )
    uncorroborated_row = _seed_ai_assisted(db_session, statement_line="net_income", value=Decimal("9"))

    response = client.post(
        "/fundamentals/confirm-batch-corroborated",
        json={"actor": "analyst", "ids": [corroborated_row.id, uncorroborated_row.id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["confirmed"] == [corroborated_row.id]
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == uncorroborated_row.id
    assert "not corroborated" in body["failed"][0]["reason"]

    db_session.refresh(corroborated_row)
    assert corroborated_row.provenance_tier == ProvenanceTier.REPORTED
    assert corroborated_row.confirmed_by == "analyst (corroborated bulk confirm)"
    # The distinct marker makes this action searchable/auditable separately
    # from a genuine per-row human review, per this endpoint's own docstring.

    db_session.refresh(uncorroborated_row)
    assert uncorroborated_row.provenance_tier == ProvenanceTier.AI_ASSISTED
    assert uncorroborated_row.confirmed_by is None


def test_confirm_batch_corroborated_rejects_a_client_claiming_false_corroboration(db_session, client):
    """The corroboration check is re-verified server-side on every id in
    THIS endpoint — a client cannot bypass it by simply calling
    confirm-batch-corroborated on an uncorroborated row."""
    _seed_security(db_session)
    row = _seed_ai_assisted(db_session, statement_line="net_income", value=Decimal("9"))

    response = client.post(
        "/fundamentals/confirm-batch-corroborated",
        json={"actor": "sneaky", "ids": [row.id]},
    )
    body = response.json()
    assert body["confirmed"] == []
    assert body["failed"][0]["id"] == row.id

    db_session.refresh(row)
    assert row.provenance_tier == ProvenanceTier.AI_ASSISTED


def test_corroborated_flag_true_across_different_period_types_for_the_same_balance_sheet_date(
    db_session, client,
):
    """Regression for a real bug found live (23 Aug 2026, ABAN.N0000's
    real total_assets for 2019-03-31): the first version of this feature
    required `period_type` to match too, which meant it never fired for
    the most common real corroboration shape — the same point-in-time
    balance-sheet figure reported once as that year's own annual filing
    (period_type='annual') and again as a later interim report's
    comparative prior-year-end column (period_type='quarterly')."""
    _seed_security(db_session)
    pending = _seed_ai_assisted(
        db_session, statement_line="total_assets", value=Decimal("2794523371"),
        period_type="annual", source_url="https://cdn.cse.lk/annual_2019.pdf",
    )
    _seed_ai_assisted(
        db_session, statement_line="total_assets", value=Decimal("2794523371"),
        period_type="quarterly", source_url="https://cdn.cse.lk/interim_2021.pdf",
        provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="analyst", confirmed_at=dt.datetime.now(dt.timezone.utc),
    )

    body = client.get("/fundamentals").json()
    row = next(r for r in body["items"] if r["id"] == pending.id)
    assert row["corroborated"] is True
