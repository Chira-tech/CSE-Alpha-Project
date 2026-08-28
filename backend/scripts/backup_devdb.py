"""Periodic, safe-while-live snapshot of the dev SQLite database.

Uses sqlite3's own online backup API (`Connection.backup`) rather than a
raw file copy — this takes a page-consistent snapshot even while the
long-running `backfill-financials` process still has the file open and
is actively writing to it, so a backup can never catch a half-written
transaction. Run manually or on a schedule (see `register_task.ps1`
alongside this file); each run keeps only the most recent
`KEEP` snapshots so backups/ doesn't grow without bound over a
multi-hour backfill.

    python scripts/backup_devdb.py
"""
from __future__ import annotations

import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
SRC = BACKEND_DIR / "devdb.sqlite"
BACKUP_DIR = BACKEND_DIR / "backups"
KEEP = 10  # most recent snapshots to retain
ATTEMPTS = 5  # a live-writer backfill process can hold the source locked briefly


def _try_backup(dest: Path) -> None:
    # mode=ro plus a generous busy_timeout: `Connection.backup` already
    # retries internally on SQLITE_BUSY/SQLITE_LOCKED (its own `sleep`
    # param), but a source held by a long write transaction (a big PDF's
    # worth of fundamentals rows) can outlast that — busy_timeout backs
    # the retry with SQLite's own wait-and-retry at the C level too.
    src_con = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)
    src_con.execute("PRAGMA busy_timeout = 30000")
    dest_con = sqlite3.connect(dest)
    try:
        src_con.backup(dest_con, sleep=1.0)
    finally:
        dest_con.close()
        src_con.close()


def main() -> int:
    if not SRC.exists():
        print(f"No {SRC} found — nothing to back up.", file=sys.stderr)
        return 1

    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = BACKUP_DIR / f"devdb-{ts}.sqlite"

    for attempt in range(1, ATTEMPTS + 1):
        try:
            _try_backup(dest)
            break
        except sqlite3.Error as exc:
            # Never leave a partial/corrupt snapshot behind — a half-copied
            # file with the right name is worse than no file, since it
            # looks like a valid backup until someone tries to restore it.
            for stray in (dest, dest.with_name(dest.name + "-journal")):
                stray.unlink(missing_ok=True)
            if attempt == ATTEMPTS:
                print(f"Backup FAILED after {ATTEMPTS} attempts: {exc}", file=sys.stderr)
                return 1
            print(f"Backup attempt {attempt} failed ({exc}), retrying...", file=sys.stderr)
            time.sleep(5)

    # A snapshot that opens but is missing the expected table is exactly
    # as dangerous as one that failed outright — verify before trusting it.
    check_con = sqlite3.connect(dest)
    try:
        row_count = check_con.execute("select count(*) from fundamentals").fetchone()[0]
    except sqlite3.Error as exc:
        check_con.close()
        dest.unlink(missing_ok=True)
        print(f"Backup produced an unreadable snapshot ({exc}) — removed.", file=sys.stderr)
        return 1
    check_con.close()

    print(f"Backed up {SRC} -> {dest} ({row_count} fundamentals rows)")

    # Prune to the KEEP most recent snapshots.
    snapshots = sorted(BACKUP_DIR.glob("devdb-*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in snapshots[KEEP:]:
        stale.unlink()
        print(f"Pruned old snapshot {stale.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
