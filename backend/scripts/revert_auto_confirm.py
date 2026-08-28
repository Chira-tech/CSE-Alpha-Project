"""Undo the entire `auto-confirm-fundamentals` pass in one command.

Every row promoted by `app.domain.fundamental_cross_check` carries
`confirmed_by = "auto:cross-check-v1 [...]"` and an `[AUTO-CONFIRM ...]`
note at the head of its `source_snippet`. This reverts each such row to
`AI_ASSISTED` / unconfirmed and strips the note, leaving the original
extracted snippet intact. Dry-run by default.

    python scripts/revert_auto_confirm.py            # dry run
    python scripts/revert_auto_confirm.py --apply
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import ProvenanceTier  # noqa: E402
from app.models.fundamentals import Fundamental  # noqa: E402

_NOTE_RE = re.compile(r"^\[AUTO-CONFIRM [^\]]*\][^\n]*\n\n", re.S)


def main() -> None:
    apply = "--apply" in sys.argv
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(Fundamental).where(Fundamental.confirmed_by.like("auto:cross-check-v1%"))
        ).all()
        print(f"{len(rows)} rows were auto-confirmed by cross-check-v1.")
        by_line: dict[str, int] = {}
        for r in rows:
            by_line[r.statement_line] = by_line.get(r.statement_line, 0) + 1
            if apply:
                r.provenance_tier = ProvenanceTier.AI_ASSISTED
                r.confirmed_by = None
                r.confirmed_at = None
                r.source_snippet = _NOTE_RE.sub("", r.source_snippet or "", count=1)
        for line, n in sorted(by_line.items(), key=lambda kv: -kv[1]):
            print(f"  {line:<32} {n}")
        if apply:
            db.commit()
            print("APPLIED — all reverted to AI_ASSISTED.")
        else:
            db.rollback()
            print("DRY RUN — re-run with --apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
