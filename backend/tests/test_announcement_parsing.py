"""
These fixtures are real strings captured from the live CSE API during
Phase 1 verification (getAnnouncementByCompany / getAnnouncementById for
AAF.N0000, symbol "Asia Asset Finance PLC", June 2026 rights issue) — see
app/ingestion/README_ENDPOINTS.md for the full trace. Using real text
rather than invented examples is deliberate: it's exactly the kind of
phrasing that breaks a regex written from imagination.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.announcement_parsing import (
    classify_announcement_category,
    parse_share_ratio_text,
)

REAL_AAF_RIGHTS_TEXT = (
    "04 (Four) new Ordinary Voting Shares will be provisionally allotted "
    "to every 11 (Eleven) Ordinary Voting Shares"
)


def test_parses_real_captured_rights_issue_text():
    result = parse_share_ratio_text(REAL_AAF_RIGHTS_TEXT)
    assert result == (Decimal(4), Decimal(11))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 (One) new share for every 4 (Four) held", (Decimal(1), Decimal(4))),
        ("in the proportion of 1:5", (Decimal(1), Decimal(5))),
        ("A rights issue in the proportion of 2 : 7 shares", (Decimal(2), Decimal(7))),
    ],
)
def test_parses_common_phrasings(text, expected):
    assert parse_share_ratio_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "The Board has approved a rights issue, details to follow",
        "AGM to be held on 30 June 2026 at the corporate office",
    ],
)
def test_returns_none_for_unparseable_or_missing_text(text):
    assert parse_share_ratio_text(text) is None


def test_zero_or_negative_quantities_are_rejected():
    assert parse_share_ratio_text("0 (Zero) new shares for every 5 held") is None


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("CASH DIVIDEND", "dividend_cash"),
        ("CASH DIVIDEND (DATES TO BE NOTIFIED)", "dividend_cash"),
        ("RIGHTS ISSUE", "rights_issue"),
        ("RIGHTS ISSUE (DATES)", "rights_issue"),
        ("RIGHTS ISSUE / CHANGE OF DATE OF ACCEPTANCE AND PAYMENT", "rights_issue"),
        ("SUBDIVISION, PRIVATE PLACEMENT AND REDUCTION OF STATED CAPITAL", "stock_split"),
        ("BONUS ISSUE", "bonus_issue"),
        ("TRADING SUSPENDED", "suspension"),
        # consolidation must win over the rights-issue keyword when both appear
        ("CONSOLIDATION OF SHARES AND RIGHTS ISSUE", "consolidation"),
    ],
)
def test_classify_known_categories(category, expected):
    assert classify_announcement_category(category) == expected


@pytest.mark.parametrize(
    "category",
    [
        None,
        "",
        "ANNUAL GENERAL MEETING",
        "DEALINGS BY DIRECTORS",
        "CORPORATE DISCLOSURE",
        "CHANGE OF AUDITORS",
        "APPOINTMENT OF DIRECTORS",
    ],
)
def test_classify_returns_none_for_non_corporate_action_categories(category):
    assert classify_announcement_category(category) is None
