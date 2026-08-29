"""
A REAL, P0 bug, found live (18 Aug 2026) via a direct product-owner
review: COMB.N0000 — Sri Lanka's largest private bank, LKR 205.75,
trading normally — showed a triangulated fair value of LKR 93.06 and an
"Exit" verdict, i.e. this system was recommending selling a large,
liquid, well-run bank for less than half what it trades at. Confirmed
live against COMB's own real, confirmed figures: `return_on_equity` was
computed as `net_income ÷ total_equity` using the LATEST CONFIRMED
PERIOD's `net_income` directly — 35,423,054,000 for the period ending
2026-06-30 — giving ROE = 9.73%.

The real cause: this system's own verified CSE interim-statement
convention (confirmed live on multiple companies' real filings this
session — e.g. NTB.N0000's real "Six Months Ended 30 June" column
header) means a "quarterly" period's stored net_income is CUMULATIVE
SINCE THE FISCAL YEAR START, not a standalone quarter — COMB's own real
statement line reads "Profit for the period 35,423,054 31,165,447 ..."
where 35,423,054 is six months (Jan-June 2026), not three. Using it
directly as an annual figure understates ROE by roughly half. With
Ke ≈ 17% for a bank, a 9.73% "ROE" reads as value-DESTROYING relative
to cost of equity — residual income and justified P/B both correctly
produce a low fair value from that WRONG input. The real,
trailing-twelve-month-annualised ROE, computed below, is 17.92% —
comfortably above Ke, an entirely different, far more plausible verdict
for this real company.

TTM = last_full_fiscal_year_value
    + this_period's_cumulative_value
    - the_prior_year's_cumulative_value_for_the_SAME_relative_window

A SECOND REAL FINDING, discovered wiring this up: no `Fundamental` row
in this entire database has ever had `period_type == "annual"` — every
real annual-report PDF this session has attempted has exceeded this
environment's background-processing ceiling before finishing (a real,
separate, already-named constraint), so genuine annual filings simply
never became drafts. COMB's own real Dec-31 rows — which ARE genuine
full-fiscal-year cumulative totals, being each year's final (Q4)
cumulative report — are stored with `period_type == "quarterly"` like
everything else.

So "the last full fiscal year" can't be found by period_type alone here
(that branch is kept for if/when a real annual filing does land — see
below). Instead: CSE's cumulative-since-year-start convention means a
ticker's own real quarterly net_income sequence is monotonically
non-decreasing WITHIN a fiscal year and RESETS DOWN at the start of the
next one (verified against COMB's own full real history: 6 real
fiscal-year boundaries, 2019 through 2025, every one a real downward
reset from one period to the next). The period immediately before such
a reset is, by construction, that fiscal year's real full-year total —
found here without needing `period_type` or the (currently unpopulated)
`Security.fiscal_year_end` field at all.

KNOWN, DISCLOSED LIMITATION, found live in COMB's own real history: one
real period (2024-12-31) is itself lower than the period before it
(2024-09-30) for a reason not investigated here — a genuine data
anomaly on that one filing, not a fiscal-year boundary. The reset
heuristic would misidentify 2024-09-30 as a "fiscal year end" if asked
about a period near that date. It is NOT wrong for the real case this
fix was built to close (the closest real reset before any period in
2026 is the correct 2025-12-31), but a caller reasoning about historical
periods in 2024 should know this heuristic is not infallible — a genuine
`period_type == "annual"` row, once real annual filings are ingested,
will replace the need for it entirely.

NEVER FALLS BACK to the raw, un-annualised cumulative figure when a TTM
component (a real fiscal-year-end value, or a real prior-year comparator
at the same relative point in the fiscal year) is missing — that silent
fallback is exactly the bug this module exists to close. `None`, named,
is the only alternative to a real, correctly-annualised value. This is a
real, disclosed trade-off: most of this system's real held tickers today
have only 1-2 confirmed quarterly periods and no fiscal-year-end/prior-
year comparator, so their ROE-driven anchors (justified P/B, residual
income) go from "confidently wrong" to "honestly uncomputable" until
deeper history is confirmed for them too — the same "withheld beats
wrong" law (§1) this system already applies everywhere else, now closing
the one place it wasn't yet applied to period length itself.

`trailing_twelve_months` deliberately takes the CALLER's already-
resolved current period (end date, type, value) as parameters rather
than re-deriving "the latest period" itself from the raw history — a
real bug, found live while wiring this in: a caller that filters to
`period_type="annual"` has already decided which period is "latest" in
ITS OWN context, and this function independently re-scanning the full,
unfiltered history for its own idea of "latest" could silently disagree
with that (and did, in a real test case).
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.domain.point_in_time import fundamentals_as_of
from app.domain.provenance import can_enter_valuation

_LAST_FISCAL_YEAR_MAX_AGE_DAYS = 457
"""How far back the "last full fiscal year" may sit from the current
period and still be the one this TTM is built around. Fifteen months: a
current period can legitimately be up to four quarters past its own last
year-end, plus a margin for a late filing or a non-calendar fiscal year.
Anything older is a different year entirely and must not be used as the
base — see the COMB.N0000 case in `trailing_twelve_months` for what
happens when it is."""

_PRIOR_YEAR_TOLERANCE_DAYS = 20
"""How far a real prior-year comparator's `period_end` may drift from
exactly 365 days before the current period and still be trusted as "the
same relative point in the fiscal year" — real filings don't always
land on the identical calendar date year over year (leap years, the
exchange's own filing-date variance), but a real comparator is never
more than a few weeks off; anything further is refused rather than
silently paired with the wrong period."""


def _last_fiscal_year_end_value(
    confirmed_quarterlies: list, before: dt.date
) -> Decimal | None:
    """The real cumulative value at the most recent fiscal-year boundary
    strictly before `before` — see this module's own docstring for why
    this is inferred from a real downward reset in the data rather than
    from `period_type` (no row in this database has ever had
    `period_type == "annual"`)."""
    ordered = sorted(
        (r for r in confirmed_quarterlies if r.period_end < before), key=lambda r: r.period_end
    )
    for i in range(len(ordered) - 1, 0, -1):
        if ordered[i].value < ordered[i - 1].value:  # a real downward reset
            return ordered[i - 1].value
    return None


def trailing_twelve_months(
    db: Session,
    ticker: str,
    statement_line: str,
    as_of: dt.date,
    *,
    current_period_end: dt.date,
    current_period_type: str,
    current_value: Decimal,
) -> Decimal | None:
    """The real, correctly-annualised trailing-twelve-month value for a
    flow-type statement line (net income, revenue, ...), built AROUND
    the caller's own already-resolved current period — see this
    module's own docstring for the full real finding, the exact
    formula, and why the current period is a parameter rather than
    re-derived here. `None` (never the raw un-annualised figure) when
    `current_period_type` is "quarterly" and either a real fiscal-year-
    end value or a real prior-year comparator at the same relative
    point in the year is missing.
    """
    if current_period_type == "annual":
        return current_value  # already a real full year — no adjustment needed

    rows = fundamentals_as_of(db, ticker, as_of, statement_line=statement_line)
    confirmed = [r for r in rows if can_enter_valuation(r.provenance_tier)]

    # The annual row must be the fiscal year IMMEDIATELY preceding this
    # period, not merely the newest one that happens to be visible.
    #
    # A REAL BUG THIS CLOSES (29 Aug 2026), on this module's own reference
    # company. `fundamentals_as_of` resolves §6 restatement versioning per
    # period_end, so where a period has BOTH an annual row and a quarterly
    # row (a Q4 cumulative filing and the annual report for the same
    # year-end), only one survives — and which one survives depends on
    # their version numbers. For COMB.N0000 that left just two annual rows
    # visible, 2022-12-31 and 2021-12-31, with the real 2025-12-31 and
    # 2024-12-31 annuals shadowed by their quarterly twins. `max(annuals)`
    # therefore picked a THREE-YEAR-OLD fiscal year as the base for a
    # 2026-06-30 TTM, giving 28,657,079,000 against the correct
    # 65,195,124,000 — ROE 7.88% instead of the 17.92% this module's own
    # docstring records as right, putting a real, liquid, well-run bank
    # back in the "Exit" zone: precisely the P0 bug this module was built
    # to fix, re-entering through a different door.
    #
    # Falling through to the quarterly reset heuristic when no RECENT
    # annual row is visible is not a workaround — that heuristic is this
    # module's original mechanism, verified against COMB's own six real
    # fiscal-year boundaries, and it finds 2025-12-31 correctly.
    annuals = [
        r for r in confirmed
        if r.period_type == "annual"
        and r.period_end < current_period_end
        and (current_period_end - r.period_end).days <= _LAST_FISCAL_YEAR_MAX_AGE_DAYS
    ]
    if annuals:
        last_fiscal_year_value = max(annuals, key=lambda r: r.period_end).value
    else:
        quarterlies_before = [r for r in confirmed if r.period_type == "quarterly"]
        last_fiscal_year_value = _last_fiscal_year_end_value(quarterlies_before, current_period_end)
        if last_fiscal_year_value is None:
            return None

    target_prior_date = current_period_end - dt.timedelta(days=365)
    quarterlies = [
        r for r in confirmed
        if r.period_type == "quarterly" and r.period_end != current_period_end
    ]
    candidates = [
        r for r in quarterlies
        if abs((r.period_end - target_prior_date).days) <= _PRIOR_YEAR_TOLERANCE_DAYS
    ]
    if not candidates:
        return None
    prior_year_period = min(candidates, key=lambda r: abs((r.period_end - target_prior_date).days))

    return last_fiscal_year_value - prior_year_period.value + current_value


class AnnualisedFlow(NamedTuple):
    """A twelve-month flow figure plus HOW it was obtained, so the caller
    can disclose the basis rather than presenting every ROE as if it came
    from the same kind of measurement."""

    value: Decimal
    basis: str  # "ttm" | "latest_annual"
    period_end: dt.date | None  # the annual period used, when basis is latest_annual


def annualised_flow(
    db: Session,
    ticker: str,
    statement_line: str,
    as_of: dt.date,
    *,
    current_period_end: dt.date,
    current_period_type: str,
    current_value: Decimal,
) -> AnnualisedFlow | None:
    """`trailing_twelve_months`, and when that cannot be built, the most
    recent confirmed ANNUAL row for the same line.

    WHY THE FALLBACK EXISTS (measured, 29 Aug 2026). `trailing_twelve_
    months` needs a real prior-year comparator at the same relative point
    in the fiscal year, and returns None without one — correctly, since
    the raw cumulative figure would understate ROE by roughly half (the
    COMB.N0000 P0 bug this module was built for). But that module was
    written when, as its own docstring records, "no `Fundamental` row in
    this entire database has ever had `period_type == 'annual'`". The
    financial-report archive backfill has since created thousands of real
    annual rows, and most tickers now have a DEEP annual history against a
    SPARSE quarterly one — AAF.N0000, for instance, has two quarterly
    periods and eleven annual ones, so no prior-year quarterly comparator
    exists and TTM can never be built for it.

    Measured across the universe: 200 of 283 tickers lost `net_income`
    this way, which removes ROE, which removes justified P/B and residual
    income, which leaves triangulation with no anchors at all — the single
    largest reason this system valued only 25 of 290 companies.

    An annual row needs no annualisation: it IS twelve months of the same
    flow, as reported. Nothing is estimated or scaled here. The cost is
    recency — the annual period can be older than the current balance
    sheet — so the basis is returned for the caller to disclose, and TTM
    from quarterlies is still always preferred when it is available.
    """
    ttm = trailing_twelve_months(
        db, ticker, statement_line, as_of,
        current_period_end=current_period_end,
        current_period_type=current_period_type,
        current_value=current_value,
    )
    if ttm is not None:
        return AnnualisedFlow(ttm, "ttm", None)

    rows = fundamentals_as_of(db, ticker, as_of, statement_line=statement_line)
    annuals = [
        r for r in rows
        if r.period_type == "annual" and can_enter_valuation(r.provenance_tier)
    ]
    if not annuals:
        return None
    latest = max(annuals, key=lambda r: r.period_end)
    return AnnualisedFlow(Decimal(latest.value), "latest_annual", latest.period_end)
