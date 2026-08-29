"""ONE-TIME release of the fundamentals confirm queue from a cut-off date.

Product-owner decision (29 Aug 2026): the confirm queue should be cleared
for everything from 2021 onward so the valuation engine and the web app
can be exercised against real coverage. Pre-2021 rows stay queued —
measured separately, they unlock no additional valuation (median confirmed
depth is already 39 periods per ticker) and only add trend depth.

THIS IS DELIBERATELY NOT A CHECKED PROMOTION. `auto-confirm-fundamentals`
already promoted everything that passed a correctness check, and
`external_crosscheck.py` already confirmed or corrected everything a third
party could adjudicate. What remains is, by construction, the set that
FAILED a check — most of it on filings that do not satisfy an accounting
identity. Releasing it is a considered trade of data quality for coverage,
taken with the risk stated, and it is recorded on every row so it can be
told apart from a genuinely verified confirmation and undone wholesale.

    python scripts/release_queue_from.py                 # dry run
    python scripts/release_queue_from.py --apply
    python scripts/release_queue_from.py --revert --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import ProvenanceTier  # noqa: E402
from app.models.fundamentals import Fundamental  # noqa: E402

TAG = "auto:released-from-queue-v1"
_NOTE_RE = re.compile(r"^\[QUEUE-RELEASE [^\]]*\].*?\n\n", re.S)
_FAILURE_MARKER = "EXTRACTION FAILED ARITHMETIC CHECK"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="2021-01-01", help="release rows with period_end >= this")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()
    since = dt.date.fromisoformat(args.since)

    db = SessionLocal()
    try:
        if args.revert:
            rows = db.scalars(select(Fundamental).where(Fundamental.confirmed_by == TAG)).all()
            print(f"{len(rows)} rows were released by this pass.")
            if args.apply:
                for row in rows:
                    row.provenance_tier = ProvenanceTier.AI_ASSISTED
                    row.confirmed_by = None
                    row.confirmed_at = None
                    row.source_snippet = _NOTE_RE.sub("", row.source_snippet or "", count=1)
                db.commit()
                print("REVERTED.")
            else:
                db.rollback()
                print("DRY RUN — re-run with --revert --apply.", file=sys.stderr)
            return

        rows = db.scalars(
            select(Fundamental).where(
                Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED,
                Fundamental.period_end >= since,
            )
        ).all()

        unbalanced = sum(1 for r in rows if _FAILURE_MARKER in (r.source_snippet or ""))
        by_line = Counter(r.statement_line for r in rows)
        by_year = Counter(r.period_end.year for r in rows)
        tickers = {r.ticker for r in rows}

        print(f"Releasing {len(rows)} queued rows with period_end >= {since}")
        print(f"  distinct tickers                      : {len(tickers)}")
        print(f"  on filings failing an accounting check: {unbalanced}  <-- accepted risk")
        print(f"  by year: {dict(sorted(by_year.items()))}")
        print(f"  top lines: {dict(by_line.most_common(8))}")

        report = REPO_ROOT / "docs" / "audits" / f"QUEUE_RELEASE_{dt.date.today().isoformat()}.md"
        lines = [
            f"# Fundamentals queue release — {dt.date.today().isoformat()}",
            "",
            f"Released **{len(rows)} rows** with `period_end >= {since}` across "
            f"**{len(tickers)} tickers**, tagged `{TAG}`.",
            "",
            "## What this is, honestly",
            "",
            "This is NOT a verified confirmation. Everything that passed a correctness "
            "check was already promoted by `auto-confirm-fundamentals`, and everything a "
            "third party could adjudicate was already handled by `external_crosscheck.py`. "
            "What remains is the set that failed a check — "
            f"**{unbalanced} of these {len(rows)} rows sit on a filing that does not "
            "satisfy an accounting identity**. Releasing them trades data quality for "
            "coverage so the engine and the web app can be exercised. Every row carries a "
            "dated note saying so, and `--revert --apply` undoes the whole pass.",
            "",
            "Pre-2021 rows were deliberately left queued: measured separately, they unlock "
            "no additional valuation (median confirmed depth is already 39 periods per "
            "ticker) and add only trend depth.",
            "",
            "## By year",
            "",
            "| year | rows |",
            "|---|---|",
        ]
        for y, n in sorted(by_year.items()):
            lines.append(f"| {y} | {n} |")
        lines += ["", "## By statement line", "", "| line | rows |", "|---|---|"]
        for line, n in by_line.most_common():
            lines.append(f"| {line} | {n} |")
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nWrote {report}")

        if not args.apply:
            db.rollback()
            print("DRY RUN — nothing written. Re-run with --apply.", file=sys.stderr)
            return

        today = dt.date.today().isoformat()
        stamp = dt.datetime.now(dt.timezone.utc)
        for row in rows:
            failed = _FAILURE_MARKER in (row.source_snippet or "")
            row.provenance_tier = ProvenanceTier.REPORTED
            row.confirmed_by = TAG
            row.confirmed_at = stamp
            row.source_snippet = (
                f"[QUEUE-RELEASE {today}] Released to the system by a product-owner "
                f"decision to clear the confirm queue from {since} onward, NOT by passing a "
                f"correctness check — this row had already failed one"
                + (" (its filing does not satisfy an accounting identity)" if failed else "")
                + f". Treat with less confidence than a row confirmed on evidence. Revert: "
                f"scripts/release_queue_from.py --revert --apply.\n\n"
                + (row.source_snippet or "")
            )
        db.commit()
        print(f"APPLIED — {len(rows)} rows released to REPORTED.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
