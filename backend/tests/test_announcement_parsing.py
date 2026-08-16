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
    before_after_to_new_per_held,
    classify_announcement_category,
    parse_before_after_ratio_text,
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


# --- share-split "before:after" convention, real captures ------------------
# Lanka Tiles (TILE.N0000): existing 53,050,410 -> resulting 265,252,050
# (x5); First Capital Holdings (CFVF.N0000): existing 101,250,000 ->
# resulting 405,000,000 (x4) — see app/ingestion/README_ENDPOINTS.md.


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1:5", (Decimal(1), Decimal(5))),
        ("1 : 4", (Decimal(1), Decimal(4))),
        ("Sub-division of 01 Ordinary Share into 05 Ordinary Shares", (Decimal(1), Decimal(5))),
    ],
)
def test_parses_real_captured_share_split_text(text, expected):
    assert parse_before_after_ratio_text(text) == expected


def test_before_after_ratio_is_a_different_convention_from_rights_new_held():
    """The two conventions must never be interchangeable: "1:5" means
    something completely different depending on which parser reads it."""
    split_result = parse_before_after_ratio_text("1:5")
    rights_result = parse_share_ratio_text("in the proportion of 1:5")
    assert split_result == rights_result == (Decimal(1), Decimal(5))
    # But the DOMAIN MEANING differs: a split's (1,5) is before:after
    # (4 new shares per held), while a rights (1,5) is new:held (1 new
    # share per 5 held) — same numbers, opposite conclusions.
    assert before_after_to_new_per_held(*split_result) == Decimal(4)
    new, held = rights_result
    assert new / held == Decimal("0.2")


@pytest.mark.parametrize(
    "text",
    [None, "", "no ratio mentioned here", "Sub-division of shares, details to follow"],
)
def test_before_after_returns_none_for_unparseable_text(text):
    assert parse_before_after_ratio_text(text) is None


def test_before_after_rejects_after_not_greater_than_before():
    # A "split" that doesn't increase share count isn't a split.
    assert parse_before_after_ratio_text("5:5") is None
    assert parse_before_after_ratio_text("5:1") is None


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (Decimal(1), Decimal(5), Decimal(4)),
        (Decimal(1), Decimal(4), Decimal(3)),
        (Decimal(2), Decimal(6), Decimal(2)),  # 2->6 is also a 1:3-per-share ratio
    ],
)
def test_before_after_to_new_per_held(before, after, expected):
    assert before_after_to_new_per_held(before, after) == expected


def test_before_after_to_new_per_held_rejects_non_positive_before():
    with pytest.raises(ValueError):
        before_after_to_new_per_held(Decimal(0), Decimal(5))
