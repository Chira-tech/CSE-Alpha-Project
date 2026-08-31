"""Backfill `securities.trading_status` — `docs/CSE_Universe_Integrity_
Rollout.md` golden case 6.

Re-runnable and idempotent, same shape as `scripts.audit_universe_
integrity`:

    python -m scripts.backfill_trading_status            # from backend/
    python -m scripts.backfill_trading_status --dry-run  # report only

Rules, in order:

  1. `delisting_date` is set                -> 'delisted'
  2. has price history, newest close is    -> 'suspended'
     more than STALE_DAYS calendar days old
  3. everything else                        -> 'active'

Rule 2 is a judgement, not an exchange fact: the CSE does not publish a
clean suspension flag (see `app.models.registry.IssuerRegistry`'s own
docstring — its non-trading set mixes suspensions, debt-only issuers and
names that merely did not trade that day). A line that has genuinely
traded before and then goes silent for over three months is, for this
engine's purposes, not a name it can hold a live opinion on — so it is
quarantined rather than ranked on a three-month-old price. A real
suspension feed, when one exists, should set this column directly and
this heuristic becomes the fallback.

STALE_DAYS is deliberately far longer than `security_status_view`'s
10-day PROVISIONAL staleness window: 10 days old is an illiquid name
still trading (golden case 7, still valued); 90+ days is a name that has
effectively stopped (golden case 6, quarantined).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.prices import PriceDaily  # noqa: E402
from app.models.securities import Security  # noqa: E402

STALE_DAYS = 90


def _classify(delisting_date: dt.date | None, last_close: dt.date | None, today: dt.date) -> str:
    if delisting_date is not None:
        return "delisted"
    if last_close is not None and (today - last_close).days > STALE_DAYS:
        return "suspended"
    return "active"


def run(db: Session, *, today: dt.date, apply: bool) -> dict[str, int]:
    last_close_by_ticker = {
        t: d
        for t, d in db.execute(
            select(PriceDaily.ticker, func.max(PriceDaily.date))
            .where(PriceDaily.close.is_not(None))
            .group_by(PriceDaily.ticker)
        )
    }

    changes: dict[str, tuple[str, str]] = {}
    counts = {"active": 0, "suspended": 0, "delisted": 0}
    for security in db.scalars(select(Security)):
        want = _classify(security.delisting_date, last_close_by_ticker.get(security.ticker), today)
        counts[want] += 1
        if security.trading_status != want:
            changes[security.ticker] = (security.trading_status, want)
            if apply:
                security.trading_status = want

    if apply:
        db.commit()

    verb = "set" if apply else "would set"
    print(f"{verb}: " + ", ".join(f"{k}={v}" for k, v in counts.items()), file=sys.stderr)
    for ticker, (was, now) in sorted(changes.items()):
        print(f"  {ticker:14s} {was} -> {now}", file=sys.stderr)
    if not changes:
        print("  (no changes)", file=sys.stderr)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        run(db, today=dt.date.today(), apply=not args.dry_run)
    finally:
        db.close()


if __name__ == "__main__":
    main()
