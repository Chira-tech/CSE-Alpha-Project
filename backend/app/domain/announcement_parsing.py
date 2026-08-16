"""
Pure text-parsing helpers for CSE announcement free text. Verified against
real CSE API responses captured during Phase 1 (see
app/ingestion/README_ENDPOINTS.md for the full trace).

CSE rights/bonus announcements state the ratio as prose, not a machine
field — e.g. Asia Asset Finance PLC's June 2026 rights issue:

    "04 (Four) new Ordinary Voting Shares will be provisionally allotted
    to every 11 (Eleven) Ordinary Voting Shares"

`parse_share_ratio_text` extracts (new, held) from patterns like that.
This is deliberately best-effort: Master Spec §5 requires corporate
actions to go through "mandatory human confirm" regardless, so a
parse failure here just means the draft CorporateAction row is created
with `ratio=None` and the original text preserved in `notes` for a human
to fill in — it never blocks ingestion and never silently guesses.
"""
from __future__ import annotations

import re
from decimal import Decimal

# "<new> (word) new ... every <held> (word)" — covers "to every" / "for every"
_PROPORTION_WORDS = re.compile(
    r"(?P<new>\d+)\s*\([^)]*\)?[^0-9]{0,60}?\bnew\b[^0-9]{0,80}?\bevery\s+(?P<held>\d+)",
    re.IGNORECASE | re.DOTALL,
)

# "in the proportion of <new>:<held>" or "<new>:<held>" ratio shorthand
_PROPORTION_COLON = re.compile(
    r"proportion\s+of\s+(?P<new>\d+)\s*:\s*(?P<held>\d+)",
    re.IGNORECASE,
)


def parse_share_ratio_text(text: str | None) -> tuple[Decimal, Decimal] | None:
    """Returns (new_shares, held_shares) — e.g. (4, 11) for a "4 new for
    every 11 held" rights/bonus issue — or None if the text doesn't match
    a recognised pattern. Never raises; an unparseable string is exactly
    the expected case for a human to resolve, not an error.
    """
    if not text:
        return None

    match = _PROPORTION_WORDS.search(text)
    if match:
        new = Decimal(match.group("new"))
        held = Decimal(match.group("held"))
        if new > 0 and held > 0:
            return new, held

    match = _PROPORTION_COLON.search(text)
    if match:
        new = Decimal(match.group("new"))
        held = Decimal(match.group("held"))
        if new > 0 and held > 0:
            return new, held

    return None


# Master Spec §7 action types we act on, mapped from the free-text
# `announcementCategory` string CSE returns from getAnnouncementByCompany.
# Verified categories seen live: "CASH DIVIDEND", "CASH DIVIDEND (DATES TO
# BE NOTIFIED)", "RIGHTS ISSUE", "RIGHTS ISSUE (DATES)", "RIGHTS ISSUE
# DATES", "CONSOLIDATION OF SHARES AND RIGHTS ISSUE", "SUBDIVISION,
# PRIVATE PLACEMENT AND REDUCTION OF STATED CAPITAL". No live example of a
# pure bonus issue or a plain stock split was captured in this session —
# the keyword table below is deliberately broad (substring match) so new
# category wordings are more likely to be caught than missed; anything
# that matches becomes a draft row for human review rather than being
# silently dropped.
_CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("CASH DIVIDEND", "dividend_cash"),
    ("SCRIP DIVIDEND", "bonus_issue"),
    ("BONUS ISSUE", "bonus_issue"),
    ("CONSOLIDATION", "consolidation"),
    ("SUBDIVISION", "stock_split"),
    ("SUB-DIVISION", "stock_split"),
    ("SUB DIVISION", "stock_split"),
    ("STOCK SPLIT", "stock_split"),
    ("SPLIT OF SHARES", "stock_split"),
    ("RIGHTS ISSUE", "rights_issue"),
    ("TRADING SUSPENDED", "suspension"),
)


def classify_announcement_category(category: str | None) -> str | None:
    """Maps a CSE `announcementCategory` string to one of our
    CorporateActionType values (returned as the plain string value, not
    the enum, to keep this module free of an ORM/model import). Returns
    None for categories irrelevant to corporate-action adjustment (AGM
    notices, director dealings, general disclosures, etc.) — those are
    simply not corporate actions in the §7 sense and must not become
    draft rows.

    Order matters: more specific keywords are checked first so e.g.
    "CONSOLIDATION OF SHARES AND RIGHTS ISSUE" classifies as
    'consolidation' rather than 'rights_issue' — both are present in that
    single event, and a human resolving the draft needs to see both
    documents, but the consolidation is the dominant price-ratio effect on
    its own ex-date.
    """
    if not category:
        return None
    upper = category.upper()
    for keyword, action_type in _CATEGORY_KEYWORDS:
        if keyword in upper:
            return action_type
    return None
