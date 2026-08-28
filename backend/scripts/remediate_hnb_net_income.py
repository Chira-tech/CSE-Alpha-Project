"""One-off, fully manually-verified remediation for HNB.N0000's real
~15x net_income error (R1_VALIDATION.md's single most material
finding — root cause not found in that pass, closed this session).

WHY THIS NEEDS A TARGETED SCRIPT RATHER THAN AN AUTOMATED SWEEP: the
wrong row (id 6780, period_type='annual', period_end=2024-12-31,
value=3,179,557,000) is silently wrong in a way NEITHER automated check
in this system can detect — `check_magnitude_plausibility` correctly
does not flag it (3.18bn is not implausibly small relative to HNB's own
~2.08 trillion total_assets — this is a plausible-LOOKING wrong value,
not a note-reference-scale outlier), and `check_accounting_identities`'s
"pre-tax profit - tax = net income" is not computable for this period
at all (`income_tax_expense` was never confirmed for the annual period).
This is a real, structural limit of what the automated sweeps built
this session can catch — named here honestly, not swept under the rug.

Verified TWO independent ways, not assumed:
  1. Live re-extraction against the real source PDF (today's fixed
     pipeline — all four root-cause fixes from this session together)
     produces 41,341,793,000 for the Bank-level FY2024 figure.
  2. An INDEPENDENT, already-confirmed row already sitting in this same
     database (id 45754, period_type='quarterly', same period_end,
     confirmed 21 Aug 2026 by 'claude-agent' — an earlier session,
     unrelated to this one) carries the exact same value,
     41,341,793,000, from a DIFFERENT source PDF entirely. Two
     independent extractions, two different documents, the same number
     — real corroboration, not a single fragile reading.
"""
from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import ProvenanceTier  # noqa: E402
from app.models.fundamentals import Fundamental  # noqa: E402

TICKER = "HNB.N0000"
PERIOD_END = dt.date(2024, 12, 31)
PERIOD_TYPE = "annual"
STATEMENT_LINE = "net_income"
WRONG_VALUE = Decimal("3179557000")
CORRECT_VALUE = Decimal("41341793000")


def main() -> None:
    dry_run = "--apply" not in sys.argv
    db = SessionLocal()
    try:
        row = db.scalar(
            select(Fundamental).where(
                Fundamental.ticker == TICKER,
                Fundamental.period_end == PERIOD_END,
                Fundamental.period_type == PERIOD_TYPE,
                Fundamental.statement_line == STATEMENT_LINE,
                Fundamental.value == WRONG_VALUE,
            )
        )
        if row is None:
            print("NOT FOUND — already corrected by a prior run of this script, or the value changed.")
            return

        print(f"Found: id={row.id} value={row.value} confirmed_by={row.confirmed_by!r}")
        original_note = row.source_snippet or ""
        new_snippet = (
            f"[HNB NET_INCOME REMEDIATION {dt.date.today().isoformat()}] Original stored value "
            f"{WRONG_VALUE:,} was wrong — the real page (HNB's own primary income statement) was "
            f"being silently excluded by two stacked extraction bugs (a joint-venture 'Summarised "
            f"Statement' note not excluded, then the real page's own routine footer boilerplate "
            f"tripping the notes-page exclusion — both fixed this session, see ROADMAP.md). "
            f"Corrected to {CORRECT_VALUE:,}, verified two independent ways: (1) live re-extraction "
            f"against the real source PDF with today's fixed pipeline, (2) an independently-confirmed "
            f"row already in this database (id 45754, period_type=quarterly, same period_end, "
            f"confirmed 21 Aug 2026 from a different source PDF) carries the identical figure. "
            f"Reverted to AI_ASSISTED — a human must confirm this corrected value before it can enter "
            f"a valuation again (§8); this script never auto-confirms.\n\nOriginal snippet: {original_note}"
        )

        if dry_run:
            print(f"DRY RUN — would revert to AI_ASSISTED, value -> {CORRECT_VALUE:,}. Re-run with --apply to commit.")
            return

        row.value = CORRECT_VALUE
        row.provenance_tier = ProvenanceTier.AI_ASSISTED
        row.confirmed_by = None
        row.confirmed_at = None
        row.source_snippet = new_snippet
        db.commit()
        print(f"APPLIED — id={row.id} reverted to AI_ASSISTED, value -> {CORRECT_VALUE:,}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
