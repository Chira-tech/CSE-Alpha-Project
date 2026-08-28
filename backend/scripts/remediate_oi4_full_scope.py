"""OI-4 full-scope remediation — the same safe action `scripts/
remediate_oi1.py` already took, applied to the results of `scripts/
reverify_magnitude_flagged_fundamentals.py` instead of OI-1's own
narrower 8-line sweep: revert every confirmed-wrong row back to
AI_ASSISTED/unconfirmed, value CORRECTED to what today's real,
unmodified pipeline verified against the live source PDF — never
silently re-promoted to REPORTED. A human still has to look at each one
via the confirm queue (§8) before it can feed a valuation again.

Source of truth: docs/audits/R1_OI4_FULL_SCOPE_REVERIFICATION.md's "Rows
confirmed still wrong" table — parsed directly from that file so this
script can never drift from what was actually verified.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import ProvenanceTier  # noqa: E402
from app.models.fundamentals import Fundamental  # noqa: E402

REPORT_PATH = REPO_ROOT / "docs" / "audits" / "R1_OI4_FULL_SCOPE_REVERIFICATION.md"

_ROW_RE = re.compile(
    r"^\|\s*(?P<ticker>\S+)\s*\|\s*(?P<line>\S+)\s*\|\s*(?P<period>\d{4}-\d{2}-\d{2})\s*\|\s*"
    r"(?P<stored>-?[\d,]+(?:\.\d+)?)\s*\|\s*(?P<fresh>-?[\d,]+(?:\.\d+)?)\s*\|\s*$"
)


def parse_wrong_rows() -> list[tuple[str, str, dt.date, Decimal, Decimal]]:
    text = REPORT_PATH.read_text(encoding="utf-8")
    section = text.split("## Rows confirmed still wrong")[1].split("## Unverifiable")[0]
    out = []
    for line in section.splitlines():
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        out.append((
            m.group("ticker"), m.group("line"), dt.date.fromisoformat(m.group("period")),
            Decimal(m.group("stored").replace(",", "")), Decimal(m.group("fresh").replace(",", "")),
        ))
    return out


def main() -> None:
    dry_run = "--apply" not in sys.argv
    wrong_rows = parse_wrong_rows()
    print(f"Parsed {len(wrong_rows)} confirmed-wrong entries from {REPORT_PATH}", file=sys.stderr)

    db = SessionLocal()
    reverted = 0
    not_found = 0
    already_unconfirmed = 0
    try:
        for ticker, line, period_end, stored, fresh in wrong_rows:
            rows = db.scalars(
                select(Fundamental).where(
                    Fundamental.ticker == ticker,
                    Fundamental.statement_line == line,
                    Fundamental.period_end == period_end,
                    Fundamental.value == stored,
                )
            ).all()
            if not rows:
                not_found += 1
                print(f"  NOT FOUND (already changed?): {ticker} {line} {period_end} stored={stored}", file=sys.stderr)
                continue
            for row in rows:
                if row.confirmed_by is None and row.provenance_tier == ProvenanceTier.AI_ASSISTED:
                    already_unconfirmed += 1
                original_note = row.source_snippet or ""
                row.source_snippet = (
                    f"[OI-4 FULL-SCOPE REMEDIATION {dt.date.today().isoformat()}] Original stored value "
                    f"{stored} was wrong — the same note-reference-as-value bug pattern OI-1 fixed, now "
                    f"found on a line OI-1's own narrower 8-line sweep never checked. Corrected to "
                    f"{fresh}, re-verified against the live source PDF by scripts/reverify_magnitude_"
                    f"flagged_fundamentals.py. Reverted to AI_ASSISTED — a human must confirm this "
                    f"corrected value before it can enter a valuation (§8); this script never "
                    f"auto-confirms.\n\nOriginal snippet: {original_note}"
                )
                row.value = fresh
                row.provenance_tier = ProvenanceTier.AI_ASSISTED
                row.confirmed_by = None
                row.confirmed_at = None
                reverted += 1

        print(
            f"\n{reverted} rows would be reverted+corrected "
            f"({already_unconfirmed} were already unconfirmed AI_ASSISTED; {not_found} not found — "
            "likely already fixed by a prior run of this script).",
            file=sys.stderr,
        )

        if dry_run:
            print("DRY RUN — no changes written. Re-run with --apply to commit.", file=sys.stderr)
            db.rollback()
        else:
            db.commit()
            print("APPLIED — changes committed.", file=sys.stderr)
    finally:
        db.close()


if __name__ == "__main__":
    main()
