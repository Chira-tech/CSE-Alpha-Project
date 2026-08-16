"""
app.ingestion.corporate_actions_loader, mocked with real payloads captured
from the live CSE API on 16 Aug 2026 (Asia Asset Finance PLC / AAF.N0000 —
see app/ingestion/README_ENDPOINTS.md for the full trace). Using real
captures rather than invented fixtures is deliberate: this is exactly the
kind of integration where an imagined response shape looks plausible and
is subtly wrong.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import httpx
import respx

from app.ingestion.corporate_actions_loader import ingest_corporate_actions_for_ticker
from app.ingestion.cse_client import CseClient
from app.models.corporate_actions import CorporateAction
from app.models.corporate_actions import CorporateActionType as DbActionType
from app.models.securities import Security

TICKER = "AAF.N0000"
BASE = "https://example.test/api"

ANNOUNCEMENT_LIST = {
    "reqCompanyAnnouncement": [
        {
            "id": 31879,
            "createdDate": 1784132908000,
            "dateOfAnnouncement": "15 Jul 2026",
            "announcementId": 38054,
            "announcementCategory": "CASH DIVIDEND",
            "company": "ASIA ASSET FINANCE PLC",
        },
        {
            "id": 31741,
            "createdDate": 1783056608000,
            "dateOfAnnouncement": "03 Jul 2026",
            "announcementId": 37897,
            "announcementCategory": "RIGHTS ISSUE (DATES)",
            "company": "ASIA ASSET FINANCE PLC",
        },
        {
            "id": 32023,
            "createdDate": 1785469530000,
            "dateOfAnnouncement": "30 Jul 2026",
            "announcementId": 38246,
            "announcementCategory": "EXTRAORDINARY GENERAL MEETING",
            "company": "ASIA ASSET FINANCE PLC",
        },
    ]
}

CASH_DIVIDEND_DETAIL = {
    "reqBaseAnnouncement": {
        "id": 38054,
        "dType": "CashDividendWithDates",
        "dateOfAnnouncement": "15 Jul 2026",
        "remarks": (
            "Asia Asset Finance PLC – Dividend to the Convertible Irredeemable Five (05) Year "
            "Preference Shares of the Face Value of Rs.10/- Share at a Fixed - Non Cumulative "
            "Dividend of Cents .70 for the Financial Year 2026"
        ),
        "symbol": "AAF",
        "companyName": "ASIA ASSET FINANCE PLC",
        "financialYear": "2025/2026",
        "votingDivPerShare": 0,
        "nonVotingDivPerShare": 0,
        "xd": "24 Jul 2026",
        "payment": "13 Aug 2026",
        "recordDate": 1785090600000,
    }
}

RIGHTS_DATES_DETAIL = {
    "reqBaseAnnouncement": {
        "id": 37897,
        "remarks": "RIGHTS ISSUE DATES TO BE DISCLOSED",
        "title": "RIGHTS ISSUE (DATES)",
        "dateOfAnnouncement": "03 Jul 2026",
        "recordDate": 1785695400000,
        "allotment": 1786300200000,
        "xr": 1785436200000,
        "tradingCommencement": 1786645800000,
        "symbol": "AAF",
        "companyName": "ASIA ASSET FINANCE PLC",
        "votingProportion": (
            "04 (Four) new Ordinary Voting Shares will be provisionally allotted to every "
            "11 (Eleven) Ordinary Voting Shares"
        ),
        "egm": 1785349800000,
    }
}


def _client() -> CseClient:
    return CseClient(base_url=BASE, min_seconds_between_calls=0.0)


@respx.mock
def test_ingest_creates_dividend_and_rights_drafts_skips_non_action_rows(db_session):
    db_session.add(Security(ticker=TICKER, name="Asia Asset Finance PLC"))
    db_session.commit()

    respx.post(f"{BASE}/getAnnouncementByCompany").mock(
        return_value=httpx.Response(200, json=ANNOUNCEMENT_LIST)
    )
    respx.post(f"{BASE}/getAnnouncementById", data={"announcementId": "38054"}).mock(
        return_value=httpx.Response(200, json=CASH_DIVIDEND_DETAIL)
    )
    # Verified real behaviour: getAnnouncementById 204s for a "general
    # announcement" family id; loader must fall back.
    respx.post(f"{BASE}/getAnnouncementById", data={"announcementId": "37897"}).mock(
        return_value=httpx.Response(204)
    )
    respx.post(f"{BASE}/getGeneralAnnouncementById", data={"announcementId": "37897"}).mock(
        return_value=httpx.Response(200, json=RIGHTS_DATES_DETAIL)
    )
    # EGM row (38246) is not a corporate-action category, so no detail
    # call should ever be made for it — deliberately unmocked; respx will
    # raise if it's hit.

    client = _client()
    inserted = ingest_corporate_actions_for_ticker(client, db_session, TICKER)
    client.close()

    assert inserted == 2

    rows = {row.type: row for row in db_session.query(CorporateAction).all()}

    dividend = rows[DbActionType.DIVIDEND_CASH]
    assert dividend.confirmed_by is None
    assert dividend.confirmed_at is None
    assert dividend.ex_date == dt.date(2026, 7, 24)
    assert dividend.cash_amount is None  # 0 in the API is treated as "not really provided"
    assert "not machine-readable" in dividend.notes

    rights = rows[DbActionType.RIGHTS_ISSUE]
    assert rights.confirmed_by is None
    assert rights.ex_date == dt.date(2026, 7, 31)
    # Stored through a Numeric(18,8) column, so compare with a small
    # tolerance rather than exact full-precision Decimal division.
    assert abs(rights.ratio - (Decimal(4) / Decimal(11))) < Decimal("0.00000001")
    assert rights.subscription_price is None  # only on the initial disclosure, not the dates record
    assert rights.cum_rights_price is None  # always resolved from our own price series, never the announcement
    assert "subscription price" in rights.notes


SPLIT_TICKER = "CFVF.N0000"

SPLIT_ANNOUNCEMENT_LIST = {
    "reqCompanyAnnouncement": [
        {
            "id": 11833,
            "createdDate": 1644898391000,
            "dateOfAnnouncement": "15 Feb 2022",
            "announcementId": 13681,
            "announcementCategory": "SUB-DIVISION OF SHARES",
            "company": "FIRST CAPITAL HOLDINGS PLC",
        },
        {
            "id": 12157,
            "createdDate": 1647238919000,
            "dateOfAnnouncement": "11 Mar 2022",
            "announcementId": 14032,
            "announcementCategory": "SUB-DIVISION OF SHARES (DATES)",
            "company": "FIRST CAPITAL HOLDINGS PLC",
        },
    ]
}

SPLIT_INITIAL_DETAIL = {
    "reqBaseAnnouncement": {
        "id": 13681,
        "dType": "ShareSplits",
        "dateOfAnnouncement": "15 Feb 2022",
        "remarks": None,
        "symbol": "CFVF",
        "companyName": "FIRST CAPITAL HOLDINGS PLC",
        "votingExistingNumOfShares": 101250000,
        "votingResultingNumOfShares": "405000000",  # verified: API returns this as a string
        "votingProportion": "1 : 4",
        "tradingSuspended": None,
        "tradingCommencement": None,
    }
}

SPLIT_DATES_DETAIL = {
    "reqBaseAnnouncement": {
        "id": 14032,
        "title": "SUB-DIVISION OF SHARES (DATES)",
        "remarks": None,
        "dateOfAnnouncement": "11 Mar 2022",
        "symbol": "CFVF",
        "companyName": "FIRST CAPITAL HOLDINGS PLC",
        "recordDate": None,
        "allotment": None,
        "xr": None,  # verified: null for splits, unlike rights issues
        "tradingCommencement": 1650565800000,
        "tradingSuspended": 1649615400000,
        "votingProportion": None,  # verified: null on the dates record for splits (unlike rights)
    }
}


@respx.mock
def test_ingest_pairs_initial_and_dates_announcements_for_a_share_split(db_session):
    """Real captured data for First Capital Holdings PLC's April 2022
    sub-division: ratio lives on the initial disclosure (both as exact
    share counts and as "1 : 4" text), the ex-date lives on the *separate*
    "(DATES)" announcement as `tradingCommencement` — not `xr`, which is
    null for splits (verified also on Lanka Tiles TILE.N0000)."""
    db_session.add(Security(ticker=SPLIT_TICKER, name="First Capital Holdings PLC"))
    db_session.commit()

    respx.post(f"{BASE}/getAnnouncementByCompany").mock(
        return_value=httpx.Response(200, json=SPLIT_ANNOUNCEMENT_LIST)
    )
    respx.post(f"{BASE}/getAnnouncementById", data={"announcementId": "13681"}).mock(
        return_value=httpx.Response(200, json=SPLIT_INITIAL_DETAIL)
    )
    respx.post(f"{BASE}/getAnnouncementById", data={"announcementId": "14032"}).mock(
        return_value=httpx.Response(204)
    )
    respx.post(f"{BASE}/getGeneralAnnouncementById", data={"announcementId": "14032"}).mock(
        return_value=httpx.Response(200, json=SPLIT_DATES_DETAIL)
    )

    client = _client()
    inserted = ingest_corporate_actions_for_ticker(client, db_session, SPLIT_TICKER)
    client.close()

    assert inserted == 1
    split = db_session.query(CorporateAction).filter_by(ticker=SPLIT_TICKER).one()
    assert split.type is DbActionType.STOCK_SPLIT
    assert split.confirmed_by is None
    assert split.ex_date == dt.date(2022, 4, 22)  # from tradingCommencement, not xr
    # (405,000,000 - 101,250,000) / 101,250,000 = 3 additional shares per held share
    assert split.ratio == Decimal("3.00000000")
    assert "exact share counts" in split.notes
    assert "MISSING" not in split.notes


@respx.mock
def test_ingest_is_idempotent_on_rerun(db_session):
    db_session.add(Security(ticker=TICKER, name="Asia Asset Finance PLC"))
    db_session.commit()

    respx.post(f"{BASE}/getAnnouncementByCompany").mock(
        return_value=httpx.Response(200, json=ANNOUNCEMENT_LIST)
    )
    respx.post(f"{BASE}/getAnnouncementById", data={"announcementId": "38054"}).mock(
        return_value=httpx.Response(200, json=CASH_DIVIDEND_DETAIL)
    )
    respx.post(f"{BASE}/getAnnouncementById", data={"announcementId": "37897"}).mock(
        return_value=httpx.Response(204)
    )
    respx.post(f"{BASE}/getGeneralAnnouncementById", data={"announcementId": "37897"}).mock(
        return_value=httpx.Response(200, json=RIGHTS_DATES_DETAIL)
    )

    client = _client()
    first_run = ingest_corporate_actions_for_ticker(client, db_session, TICKER)
    second_run = ingest_corporate_actions_for_ticker(client, db_session, TICKER)
    client.close()

    assert first_run == 2
    assert second_run == 0  # already-drafted rows must not duplicate
    assert len(list(db_session.query(CorporateAction).all())) == 2


@respx.mock
def test_confirmed_row_is_never_touched_by_a_rerun(db_session):
    """A human-confirmed row for the same (ticker, ex_date, type) must
    block a new draft from being created — re-ingesting must never
    reintroduce a duplicate or contest an already-reviewed row."""
    db_session.add(Security(ticker=TICKER, name="Asia Asset Finance PLC"))
    db_session.add(
        CorporateAction(
            ticker=TICKER,
            ex_date=dt.date(2026, 7, 24),
            type=DbActionType.DIVIDEND_CASH,
            cash_amount=Decimal("0.70"),
            confirmed_by="analyst",
            confirmed_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db_session.commit()

    respx.post(f"{BASE}/getAnnouncementByCompany").mock(
        return_value=httpx.Response(200, json=ANNOUNCEMENT_LIST)
    )
    respx.post(f"{BASE}/getAnnouncementById", data={"announcementId": "38054"}).mock(
        return_value=httpx.Response(200, json=CASH_DIVIDEND_DETAIL)
    )
    respx.post(f"{BASE}/getAnnouncementById", data={"announcementId": "37897"}).mock(
        return_value=httpx.Response(204)
    )
    respx.post(f"{BASE}/getGeneralAnnouncementById", data={"announcementId": "37897"}).mock(
        return_value=httpx.Response(200, json=RIGHTS_DATES_DETAIL)
    )

    client = _client()
    inserted = ingest_corporate_actions_for_ticker(client, db_session, TICKER)
    client.close()

    assert inserted == 1  # only the rights draft; dividend already exists (confirmed)
    dividend = (
        db_session.query(CorporateAction)
        .filter_by(ticker=TICKER, type=DbActionType.DIVIDEND_CASH)
        .one()
    )
    assert dividend.confirmed_by == "analyst"  # untouched
    assert dividend.cash_amount == Decimal("0.70")  # untouched
