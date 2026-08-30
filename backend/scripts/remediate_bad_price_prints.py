"""
One-off remediation for individual corrupt price rows surfaced by the
universe-integrity triage (`scripts.audit_universe_integrity`, the
"decimal / units artefact" bucket).

WHY A TARGETED SCRIPT, NOT AN AUTOMATED SWEEP. The universe-integrity job
already QUARANTINES a ticker with an unexplained one-day jump — that is
the right automated response (surface it, exclude it, let a human look).
It cannot decide WHICH side of the jump is wrong or what the right value
is; that needs a human eye on the surrounding series. This script carries
only rows where that judgment has been made and written down below.

--- LMF.N0000, 2024-09-08 ---
The whole row is a self-consistent x10 error from the feed: OHLC all read
234.00, turnover 887,328 on volume 3,792 (887,328 / 3,792 = 234.0 — the
feed's own turnover agrees with the wrong price). Every surrounding
session, both before and after, trades in a tight 24.50-25.90 band
(2024-09-02 .. 2024-09-13), and 2024-09-09 is back at 24.60. This is not
a real move and not a one-field typo — it is a bad feed record. There is
no trustworthy close to substitute, so the price fields are set to NULL
(the same "missing is missing, never a fabricated number" rule the rest
of this system follows); volume/turnover are left as-is since they are
not price signals and a NULL close already removes this day from every
return, ratio and liquidity-percentile calculation that filters on
`close IS NOT NULL`.

NOT INCLUDED, deliberately: ABL.N0000's 2024-07-15 step (2.20 -> 22.40,
then a sustained ~21-22). There the pre-step price is the suspect one and
it is not a single row — ABL shows a 10-day gap before it, suggesting a
suspension and a whole stale/wrong run rather than one bad print. That
needs a real look at ABL's listing history against the exchange, not a
mechanical NULL, so it stays flagged (quarantined by the discontinuity
check) rather than "fixed" here.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.prices import PriceDaily  # noqa: E402

# (ticker, date, expected-wrong close) — the expected close is asserted
# before any write, so a re-run against changed data is a no-op rather
# than a blind overwrite.
BAD_ROWS: list[tuple[str, dt.date, str]] = [
    ("LMF.N0000", dt.date(2024, 9, 8), "234.0000"),
]


def main() -> None:
    dry_run = "--apply" not in sys.argv
    db = SessionLocal()
    try:
        changed = 0
        for ticker, date, expected_close in BAD_ROWS:
            row = db.scalar(
                select(PriceDaily).where(PriceDaily.ticker == ticker, PriceDaily.date == date)
            )
            if row is None:
                print(f"  {ticker} {date}: no row — skipping")
                continue
            if row.close is None:
                print(f"  {ticker} {date}: close already NULL — nothing to do")
                continue
            if str(row.close) != expected_close and f"{float(row.close):.4f}" != expected_close:
                print(
                    f"  {ticker} {date}: close is {row.close}, not the expected {expected_close} — "
                    "data has changed since this script was written; NOT touching it"
                )
                continue
            print(
                f"  {ticker} {date}: close {row.close}, open {row.open}, high {row.high}, "
                f"low {row.low} -> NULL  (volume {row.volume} / turnover {row.turnover} kept)"
            )
            if not dry_run:
                row.close = None
                row.open = None
                row.high = None
                row.low = None
                row.vwap = None
                changed += 1

        if dry_run:
            print("\nDRY RUN — re-run with --apply to write. Nothing was changed.")
        else:
            db.commit()
            print(f"\nApplied: {changed} row(s) NULLed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
