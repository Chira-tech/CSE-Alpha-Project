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

from app.ingestion.corporate_actions_loader import (
    _pair_rows,
    ingest_corporate_actions_for_ticker,
    recently_scanned_tickers,
)
from app.ingestion.cse_client import CseClient
from app.ingestion.schemas import CompanyAnnouncementRow
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
def test_a_scan_is_recorded_even_when_it_finds_nothing_new(db_session):
    """Real bug, found live (18 Aug 2026): a full-universe sweep always
    restarted from ticker #1 because nothing recorded that a ticker had
    been scanned at all — see `CorporateActionScanLog`'s own docstring.
    A scan that finds zero NEW drafts (everything already drafted, or
    genuinely nothing to find) must still count as a real, completed
    scan of that ticker, exactly like a scan that found ten."""
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

    before = dt.datetime.now(dt.timezone.utc)
    client = _client()
    ingest_corporate_actions_for_ticker(client, db_session, TICKER)  # first run: 2 real drafts
    second_run = ingest_corporate_actions_for_ticker(client, db_session, TICKER)  # 0 new
    client.close()

    assert second_run == 0
    # A scan that found nothing new is STILL a real, recorded scan —
    # this is exactly the case the original bug lost.
    assert TICKER in recently_scanned_tickers(db_session, before)


def test_recently_scanned_tickers_respects_the_real_cutoff(db_session):
    from app.models.corporate_action_scan_log import CorporateActionScanLog

    now = dt.datetime.now(dt.timezone.utc)
    db_session.add(CorporateActionScanLog(ticker="OLD.N0000", last_scanned_at=now - dt.timedelta(hours=48)))
    db_session.add(CorporateActionScanLog(ticker="RECENT.N0000", last_scanned_at=now - dt.timedelta(hours=1)))
    db_session.commit()

    cutoff = now - dt.timedelta(hours=20)
    scanned = recently_scanned_tickers(db_session, cutoff)
    assert scanned == {"RECENT.N0000"}


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


class TestPairRowsWithConcurrentEvents:
    """§ROADMAP: "the rights-issue/split announcement-pairing heuristic
    (`_pair_rows`) is untested against a company with two concurrent
    events of the same type." No real example of that has ever been
    captured live (every real payload in this file is a single event per
    type), so — unlike every other fixture above — the rows here are
    SYNTHETIC, built directly as `CompanyAnnouncementRow` objects rather
    than real captured JSON. That is a deliberate departure from this
    file's own "real captures, not invented fixtures" discipline, stated
    here rather than left for a reader to notice, because there is
    nothing real to capture yet for this specific scenario.

    `_pair_rows`' own docstring already names its assumption exactly:
    "the Nth initial disclosure corresponds to the Nth dates follow-up in
    chronological order." These tests check that assumption two ways —
    where it holds, and where it doesn't — rather than only exercising
    the case that was already implicitly trusted.
    """

    @staticmethod
    def _row(announcement_id: int, date: str, category: str, created: int) -> CompanyAnnouncementRow:
        return CompanyAnnouncementRow(
            id=announcement_id,
            createdDate=created,
            dateOfAnnouncement=date,
            announcementId=announcement_id,
            announcementCategory=category,
            company="SYNTHETIC TEST PLC",
        )

    def test_two_sequential_non_overlapping_events_pair_correctly(self):
        """Event A fully resolves (initial + dates) before event B's
        initial is even filed — the ordinary case, and the one every real
        capture to date happens to be. The heuristic's core assumption
        holds here by construction."""
        rows = [
            self._row(1, "01 Jan 2026", "RIGHTS ISSUE", 1),
            self._row(2, "10 Jan 2026", "RIGHTS ISSUE (DATES)", 2),
            self._row(3, "01 Feb 2026", "RIGHTS ISSUE", 3),
            self._row(4, "10 Feb 2026", "RIGHTS ISSUE (DATES)", 4),
        ]
        pairs = _pair_rows(rows)
        assert len(pairs) == 2
        assert pairs[0] == (rows[0], rows[1])  # event A: initial 1 Jan + dates 10 Jan
        assert pairs[1] == (rows[2], rows[3])  # event B: initial 1 Feb + dates 10 Feb

    def test_two_interleaved_events_are_mispaired_a_known_limitation(self):
        """Event A's initial files first (1 Jan), then event B's initial
        files (15 Jan) BEFORE event A's own dates follow-up appears —
        e.g. B is processed faster than A. Chronologically:
        initials = [A@1Jan, B@15Jan], dates = [B@20Jan, A@1Feb].

        Index-wise pairing gives (A-initial, B-dates) and
        (B-initial, A-dates) — WRONG, a real cross-event mispairing.
        This is not a hypothetical: it is exactly the ordering that
        breaks the stated assumption, and this test exists to make that
        failure visible and tracked rather than silently possible.
        Fixing it needs a real correlating field between an initial
        announcement and its own "(DATES)" follow-up (e.g. a shared
        parent-announcement id) — not guessed at here without a live
        example to verify against, per this project's own discipline.
        """
        event_a_initial = self._row(10, "01 Jan 2026", "RIGHTS ISSUE", 10)
        event_b_initial = self._row(11, "15 Jan 2026", "RIGHTS ISSUE", 11)
        event_b_dates = self._row(12, "20 Jan 2026", "RIGHTS ISSUE (DATES)", 12)
        event_a_dates = self._row(13, "01 Feb 2026", "RIGHTS ISSUE (DATES)", 13)

        pairs = _pair_rows([event_a_initial, event_b_initial, event_b_dates, event_a_dates])

        assert len(pairs) == 2
        # Documents the mispairing — NOT the correct outcome. A future fix
        # that resolves this should update this assertion to the correct
        # pairing (event_a_initial, event_a_dates) and
        # (event_b_initial, event_b_dates), verified against a real
        # captured example first.
        assert pairs[0] == (event_a_initial, event_b_dates)
        assert pairs[1] == (event_b_initial, event_a_dates)

    def test_unmatched_dates_row_pairs_with_none(self):
        """An initial disclosure with no dates follow-up yet (still
        pending) must not be dropped or falsely paired — `build_*_draft`
        already handles a `None` half of the pair by naming the missing
        field (see the "MISSING" note assertions elsewhere in this
        file); this just confirms `_pair_rows` produces that shape."""
        initial_only = self._row(20, "01 Mar 2026", "RIGHTS ISSUE", 20)
        pairs = _pair_rows([initial_only])
        assert pairs == [(initial_only, None)]
