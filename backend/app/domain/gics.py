"""
GICS hierarchy for CSE-listed companies.

The exchange classifies its listings into 20 GICS **industry groups** and
publishes the membership itself (`sector_list` + `listBySector`). It does
not publish the level above, the 11 GICS **sectors** — but that level is
not a judgement call: the industry group's four-digit code contains it.
`4010` (Banks) sits under `40` (Financials) by the definition of the
scheme, so deriving it is arithmetic on a published standard, not a guess
about a company.

This matters for §12's sector-relative percentiles. Sri Lanka has three
listed telecoms and one automobile company; ranking a company against two
peers produces a percentile that is technically computable and
practically meaningless. Having both levels lets a percentile fall back
to the wider group when the narrow one is too thin, and lets the UI say
which was used.

WHAT THIS IS NOT. GICS is not the archetype the valuation router (§16)
needs. Appendix P2 is explicit that GICS misclassifies CSE conglomerates
— a diversified holding company with a hotel, a plantation and a finance
arm lands in whichever industry group its largest segment falls, and no
single DDM or FCFE anchor fits it. Archetype stays a hand-maintained
field; nothing here writes to it.
"""
from __future__ import annotations

# The 11 GICS sectors, keyed by the two-digit prefix every industry group
# code carries. Fixed by the standard, not by anything CSE-specific.
_SECTOR_BY_PREFIX = {
    "10": "Energy",
    "15": "Materials",
    "20": "Industrials",
    "25": "Consumer Discretionary",
    "30": "Consumer Staples",
    "35": "Health Care",
    "40": "Financials",
    "45": "Information Technology",
    "50": "Communication Services",
    "55": "Utilities",
    "60": "Real Estate",
}


def sector_for_industry_group(code: str | None) -> str | None:
    """Map a four-digit GICS industry-group code to its GICS sector.

    Returns None for anything unrecognised rather than guessing. The CSE's
    own sector list includes two entries that are not industry groups at
    all — the All Share Price Index and S&P SL20, which are market indices
    — and they arrive with no code; they must not be classified.
    """
    if not code:
        return None
    code = code.strip()
    if len(code) != 4 or not code.isdigit():
        return None
    return _SECTOR_BY_PREFIX.get(code[:2])


def is_industry_group(code: str | None) -> bool:
    """Whether a `sector_list` entry is a real industry group.

    `sector_list` mixes the 20 industry groups with the ASPI and S&P SL20.
    Those two have `indexCode: null`, so treating the list as uniformly
    sectoral would file every listed company under "All Share Price
    Index".
    """
    return sector_for_industry_group(code) is not None
