"""One-off runner: builds §35's weekly factor return series against the
real dev DB and prints a summary. (The real job-queue path is
app.jobs.runner._run_rebuild_factor_series; this script is for running
it directly during development, same pattern as the other scripts/ in
this directory.)
"""
import sys
import time

sys.path.insert(0, r"C:\Users\USER\Documents\Claude Code Projects\CSE-Alpha-Project\backend")

from app.db.session import SessionLocal
from app.domain.factor_series_view import rebuild_factor_series


def on_progress(done: int, total: int, message: str) -> bool:
    if done % 10 == 0 or done == total:
        print(f"  {done}/{total}: {message}", flush=True)
    return True


def main() -> None:
    db = SessionLocal()
    t0 = time.time()
    try:
        summary = rebuild_factor_series(db, on_progress=on_progress)
    finally:
        db.close()
    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"formation_dates_attempted: {summary.formation_dates_attempted}")
    print(f"rows_written: {summary.rows_written}")
    print(f"warnings ({len(summary.warnings)}), first 15:")
    for w in summary.warnings[:15]:
        print(f"  {w}")


if __name__ == "__main__":
    main()
