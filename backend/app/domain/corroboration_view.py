"""
R1 T2.5 — "is this AI-assisted figure independently corroborated?", the
one check the confirm queue treats as safe to act on without a human
looking at each individual value.

Lifted verbatim out of `app.api.routes.fundamentals` (where it was
route-private as `_corroborated_ids`) so BOTH the route's
`confirm-batch-corroborated` endpoint AND the scheduled
`auto_confirm_corroborated_fundamentals` job (`app.jobs.runner`) run the
identical logic and cannot drift. The route re-imports `corroborated_ids`
from here; its behaviour is unchanged.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.fundamental_validation import (
    _IDENTITY_LINES,
    _NCI_RELATIVE_TOLERANCE,
    _NCI_TOLERANT_IDENTITIES,
    validate_filing,
)
from app.domain.financial_statement_parsing import (
    _IDENTITY_ROUNDING_TOLERANCE,
    _identity_diffs,
    _magnitude_implausible_keys,
)
from app.domain.provenance import can_enter_valuation
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental


def _identity_tolerance(name: str, balance_sheet_size: Decimal) -> Decimal:
    """The gap an accounting identity may carry and still be considered
    to foot: the flat Rs 1,000 publication-rounding tolerance, widened to
    the non-controlling-interest band for the two balance-sheet
    composition identities where the extracted `total_equity` is
    legitimately owners'-equity-only (mirrors
    `fundamental_validation.validate_filing`)."""
    tol = _IDENTITY_ROUNDING_TOLERANCE
    if name in _NCI_TOLERANT_IDENTITIES and balance_sheet_size > 0:
        tol = max(tol, balance_sheet_size * _NCI_RELATIVE_TOLERANCE)
    return tol


def corroborated_ids(db: Session, rows: list[Fundamental]) -> set[int]:
    """One bulk query for every REPORTED row matching ANY of these rows'
    (ticker, period_end, statement_line) keys — not N queries per row,
    same discipline every other bulk lookup in this codebase already
    applies — then an in-Python exact-value-and-different-`source_url`
    check, since SQLAlchemy has no clean portable "tuple IN (values)"
    across both SQLite (dev) and Postgres (prod).

    DELIBERATELY NOT keyed on `period_type` too, found live (23 Aug
    2026, ABAN.N0000's real total_assets for 2019-03-31): the same
    point-in-time balance-sheet figure is genuinely reported once as
    `period_type="annual"` (that year's own annual report) and again as
    `period_type="quarterly"` (a later interim report's own comparative
    prior-year-end column) — the first version of this function required
    both to match, which meant it never fired for exactly the shape of
    corroboration that's most common in this data. Safe to drop: a real
    flow figure (`revenue`, `net_income`, ...) genuinely measures a
    different span in each period_type and would essentially never
    coincidentally match to the exact rupee AND land at a different
    `source_url` AND land on the same `period_end` — the value+source
    check below already carries the real safety property, not the
    period_type match.
    """
    if not rows:
        return set()
    keys = {(r.ticker, r.period_end, r.statement_line) for r in rows}
    tickers = {k[0] for k in keys}
    candidates = db.scalars(
        select(Fundamental).where(
            Fundamental.ticker.in_(tickers),
            Fundamental.provenance_tier == ProvenanceTier.REPORTED,
        )
    ).all()
    reported_by_key: dict[tuple, list[Fundamental]] = {}
    for c in candidates:
        reported_by_key.setdefault((c.ticker, c.period_end, c.statement_line), []).append(c)

    corroborated: set[int] = set()
    for r in rows:
        key = (r.ticker, r.period_end, r.statement_line)
        for c in reported_by_key.get(key, ()):
            if c.value == r.value and c.source_url != r.source_url:
                corroborated.add(r.id)
                break
    return corroborated


def identity_pinned_ids(db: Session, rows: list[Fundamental]) -> set[int]:
    """AI-assisted rows whose value is ARITHMETICALLY PINNED by an
    accounting identity that already balances against at least one
    confirmed line on the same filing.

    This is a second, independent "safe to confirm without a human"
    signal alongside `corroborated_ids` (an independently-sourced
    REPORTED row carrying the same figure). It is strictly stronger than
    a name-match: a corrupted value cannot make
    `owners_equity + NCI = total_equity` (or `assets = equity +
    liabilities`, etc.) foot to the rupee against a figure a human
    already confirmed. Found necessary 4 Sep 2026: LOLC's re-extracted
    "equity attributable to owners" and "non-controlling interest" both
    foot exactly to its confirmed `total_equity` and match
    stockanalysis.com, yet the multi-signal cross-check would not promote
    them.

    An AI-assisted row is pinned when, for some identity it participates
    in: every other line of that identity is present, at least one of
    them is already confirmed, the identity balances within tolerance
    (the NCI band for the two balance-sheet composition identities, the
    flat Rs 1,000 rounding tolerance otherwise), and the row itself
    carries no magnitude-plausibility flag.

    Filing-level integrity gate: NOTHING on a filing is promoted if ANY
    accounting identity computable on that filing is broken beyond
    tolerance. A filing whose `assets = current + non-current` is off by
    a hundred billion, or whose `assets = equity + liabilities` is off by
    a dropped leading digit (RHL.X0000's corrupted `total_equity`, found
    4 Sep 2026), is an unreliable extraction as a whole — a single
    identity that happens to foot on it is not enough to auto-confirm a
    value a human has not seen.
    """
    if not rows:
        return set()

    by_filing: dict[tuple, list[Fundamental]] = defaultdict(list)
    wanted_ids = {r.id for r in rows}
    tickers = {r.ticker for r in rows}
    # Load every row (any tier) for the affected filings, once.
    for r in db.scalars(select(Fundamental).where(Fundamental.ticker.in_(tickers))):
        by_filing[(r.ticker, r.period_end, r.period_type)].append(r)

    pinned: set[int] = set()
    for filing_rows in by_filing.values():
        best: dict[str, Fundamental] = {}
        for r in filing_rows:
            cur = best.get(r.statement_line)
            if cur is None or r.version > cur.version:
                best[r.statement_line] = r
        values = {ln: r.value for ln, r in best.items()}
        confirmed_lines = {
            ln for ln, r in best.items() if can_enter_valuation(r.provenance_tier)
        }
        flagged = _magnitude_implausible_keys(values)
        balance_sheet_size = max(
            (abs(values[k]) for k in ("total_assets", "total_equity_and_liabilities") if k in values),
            default=Decimal(0),
        )

        diffs = _identity_diffs(values)
        tol = {name: _identity_tolerance(name, balance_sheet_size) for name in diffs}

        # Filing-level integrity gate — one broken footing disqualifies
        # every value on the filing.
        if any(diff > tol[name] for name, diff in diffs.items()):
            continue

        for name, diff in diffs.items():
            lines = _IDENTITY_LINES.get(name, ())
            present = [ln for ln in lines if ln in values]
            if not any(ln in confirmed_lines for ln in present):
                continue
            if diff > tol[name]:
                continue
            for ln in present:
                row = best[ln]
                if (
                    row.id in wanted_ids
                    and not can_enter_valuation(row.provenance_tier)
                    and ln not in flagged
                ):
                    pinned.add(row.id)
    return pinned


def all_identity_pinned_pending_ids(db: Session) -> list[int]:
    """Every pending AI-assisted row `identity_pinned_ids` would promote,
    across the whole queue — mirrors `all_corroborated_pending_ids`."""
    pending = list(
        db.scalars(
            select(Fundamental).where(
                Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED,
                Fundamental.confirmed_by.is_(None),
            )
        ).all()
    )
    return sorted(identity_pinned_ids(db, pending))


#: A "validation-clean" filing must carry at least this many distinct
#: line items and have at least this many accounting identities actually
#: computable on it. One identity holding could be a coincidence or a
#: derived line reproducing its own inputs; two independent ones holding
#: (e.g. assets = equity + liabilities AND assets = current + non-current)
#: means the extraction is internally consistent in two directions. A
#: filing with only three or four scattered lines has nothing to check
#: against and is not "clean", just unvalidated.
_MIN_LINES_FOR_CLEAN = 5
_MIN_IDENTITIES_FOR_CLEAN = 2


def validation_clean_ids(db: Session, rows: list[Fundamental]) -> set[int]:
    """AI-assisted rows on a filing whose WHOLE extraction passes the
    data-integrity gate — every line clears `validate_filing` (identity +
    magnitude), at least two accounting identities are computable and all
    hold within tolerance, and the filing carries at least five line
    items.

    This is the product owner's binary model taken to its conclusion
    (3 Sep 2026: "just pass to the system; once that doesn't go through
    it should be in the queue"). Where `identity_pinned_ids` needs a
    human-confirmed line to anchor an identity, this rule does not — a
    balance sheet that foots in two independent directions and trips no
    magnitude flag is trusted as a whole, the same statistical argument
    the accounting-identity gate rests on everywhere else: independent
    extraction errors do not coincidentally foot to the rupee. Every
    unconfirmed line on such a filing is admitted, not only the ones a
    balancing identity names, because the evidence is about the filing,
    not the single line.

    The year-on-year trend check is deliberately NOT applied here: a
    promoted row becomes REPORTED, the nightly `revalidate_all` then runs
    the full battery (trend included) over it, and
    `fundamentals_as_of(exclude_validation_failed=True)` drops it from
    valuation if the trend check later flags it — a post-promotion
    backstop rather than a gate.
    """
    if not rows:
        return set()

    by_filing: dict[tuple, list[Fundamental]] = defaultdict(list)
    wanted_ids = {r.id for r in rows}
    tickers = {r.ticker for r in rows}
    for r in db.scalars(select(Fundamental).where(Fundamental.ticker.in_(tickers))):
        by_filing[(r.ticker, r.period_end, r.period_type)].append(r)

    clean: set[int] = set()
    for filing_rows in by_filing.values():
        best: dict[str, Fundamental] = {}
        for r in filing_rows:
            cur = best.get(r.statement_line)
            if cur is None or r.version > cur.version:
                best[r.statement_line] = r
        values = {ln: r.value for ln, r in best.items()}

        if len(values) < _MIN_LINES_FOR_CLEAN:
            continue
        if len(_identity_diffs(values)) < _MIN_IDENTITIES_FOR_CLEAN:
            continue
        if not all(v.passed for v in validate_filing(values).values()):
            continue

        for ln, row in best.items():
            if row.id in wanted_ids and not can_enter_valuation(row.provenance_tier):
                clean.add(row.id)
    return clean


def all_validation_clean_pending_ids(db: Session) -> list[int]:
    """Every pending AI-assisted row `validation_clean_ids` would promote,
    across the whole queue — mirrors `all_corroborated_pending_ids`."""
    pending = list(
        db.scalars(
            select(Fundamental).where(
                Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED,
                Fundamental.confirmed_by.is_(None),
            )
        ).all()
    )
    return sorted(validation_clean_ids(db, pending))


def _pending_ai_assisted(db: Session, *, limit: int, offset: int) -> list[Fundamental]:
    return list(
        db.scalars(
            select(Fundamental)
            .where(
                Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED,
                Fundamental.confirmed_by.is_(None),
            )
            .order_by(Fundamental.id)
            .limit(limit)
            .offset(offset)
        ).all()
    )


def all_corroborated_pending_ids(db: Session, *, batch_size: int = 500) -> list[int]:
    """Every pending AI-assisted fundamental the server can independently
    verify as corroborated right now, across the whole queue — paged so a
    queue past 11,000 rows (a real backfill state, see
    `app.api.routes.fundamentals.FundamentalsPage`) is never loaded whole.
    Used by the nightly auto-confirm job and by Data health's
    "N corroborated, cleared automatically" count."""
    found: list[int] = []
    offset = 0
    while True:
        batch = _pending_ai_assisted(db, limit=batch_size, offset=offset)
        if not batch:
            break
        hits = corroborated_ids(db, batch)
        found.extend(r.id for r in batch if r.id in hits)
        offset += len(batch)
        if len(batch) < batch_size:
            break
    return found
