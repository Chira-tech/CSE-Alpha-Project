"""Phase 4 of `docs/CSE_Universe_Integrity_Rollout.md` — "Recompute and
diff".

Recompute the whole composite ranking now, diff it against an earlier
frozen snapshot, and write a per-name before/after report: every ticker
whose verdict or score changed, and every one that entered or left the
ranked set, each with the reason visible. This is the evidence the
integrity work changed the output the way it was meant to (several
Strong Buys evaporating, as AAF's and HDFC's did) and the check that it
did not quietly break something else.

    python -m scripts.universe_verdict_diff                 # vs newest earlier snapshot
    python -m scripts.universe_verdict_diff --against 2026-08-16
    python -m scripts.universe_verdict_diff --write-snapshot  # also freeze this run

Writes `docs/audits/UNIVERSE_VERDICT_DIFF.md`. Reuses the exact
serialisation the API and the stored snapshots use
(`app.domain.composite_ranking_snapshot_view.serialize_ranking`), so the
"after" side here is the same object the scoreboard would show.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.domain.composite_ranking_snapshot_view import (  # noqa: E402
    build_insights,
    load_payload,
    serialize_ranking,
    write_snapshot,
)
from app.domain.composite_ranking_view import composite_ranking_for  # noqa: E402
from app.models.composite_ranking_snapshot import CompositeRankingSnapshot  # noqa: E402

#: A score move at least this large is worth a line in the movers table —
#: matches `build_insights`' own `INSIGHT_MIN_SCORE_MOVE`.
MIN_SCORE_MOVE = Decimal(4)


def _rows(payload: dict, key: str) -> dict[str, dict]:
    return {r["ticker"]: r for r in payload.get(key, [])}


def _score(row: dict | None) -> Decimal | None:
    if row is None:
        return None
    raw = row.get("total_score")
    return Decimal(raw) if raw is not None else None


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def diff_payloads(before: dict, after: dict) -> dict:
    """Pure diff of two `serialize_ranking` payloads. Returns lists of
    table rows for each change class — no I/O, so it is unit-testable
    without a full universe recompute."""
    after_ranked, before_ranked = _rows(after, "ranked"), _rows(before, "ranked")
    after_excl = _rows(after, "excluded")
    all_tickers = sorted(
        set(after_ranked) | set(before_ranked) | set(after_excl) | set(_rows(before, "excluded"))
    )

    verdict_changed: list[list[str]] = []
    newly_excluded: list[list[str]] = []
    newly_included: list[list[str]] = []
    score_movers: list[tuple[Decimal, list[str]]] = []

    for t in all_tickers:
        a_rank, b_rank = after_ranked.get(t), before_ranked.get(t)
        was_ranked, is_ranked = b_rank is not None, a_rank is not None

        if was_ranked and not is_ranked:
            reason = (after_excl.get(t, {}).get("warnings") or ["left the ranked set"])[0]
            newly_excluded.append([t, b_rank.get("verdict", "—"), _trim(reason)])
            continue
        if is_ranked and not was_ranked:
            newly_included.append([t, a_rank.get("verdict", "—"), _dec(_score(a_rank))])
            continue
        if not (was_ranked and is_ranked):
            continue

        wv, nv = b_rank.get("verdict"), a_rank.get("verdict")
        if wv != nv:
            verdict_changed.append([t, f"{wv} → {nv}", _dec(_score(b_rank)), _dec(_score(a_rank))])

        bs, as_ = _score(b_rank), _score(a_rank)
        if bs is not None and as_ is not None and abs(as_ - bs) >= MIN_SCORE_MOVE:
            score_movers.append((abs(as_ - bs), [t, f"{bs:+.1f} → {as_:+.1f}", f"{as_ - bs:+.1f}"]))

    score_movers.sort(key=lambda x: x[0], reverse=True)
    return {
        "verdict_changed": verdict_changed,
        "newly_excluded": newly_excluded,
        "newly_included": newly_included,
        "score_movers": [row for _, row in score_movers],
    }


def _baseline(db: Session, against: dt.date | None, today: dt.date) -> CompositeRankingSnapshot | None:
    q = select(CompositeRankingSnapshot).order_by(
        CompositeRankingSnapshot.as_of.desc(), CompositeRankingSnapshot.computed_at.desc()
    )
    if against is not None:
        return db.scalar(q.where(CompositeRankingSnapshot.as_of <= against))
    # Newest snapshot whose run date is before today; fall back to the
    # newest of any date so a same-day re-run still produces a diff.
    earlier = db.scalar(q.where(CompositeRankingSnapshot.as_of < today))
    return earlier or db.scalar(q)


def run(db: Session, *, against: dt.date | None, write: bool, out_path: Path) -> None:
    today = dt.date.today()

    started = dt.datetime.now(dt.timezone.utc)
    after_view = composite_ranking_for(db, today)
    after = serialize_ranking(after_view)
    duration = Decimal(str(round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 2)))

    base = _baseline(db, against, today)
    if base is None:
        sys.exit("No prior snapshot to diff against. Run the scoreboard once first.")
    before = load_payload(base)

    d = diff_payloads(before, after)
    verdict_changed = d["verdict_changed"]
    newly_excluded = d["newly_excluded"]
    newly_included = d["newly_included"]
    score_movers = d["score_movers"]
    insights = build_insights(after, before)

    L: list[str] = [
        "# Universe verdict diff — Phase 4",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}Z"
        f" · DB: `{settings.database_url}`",
        "",
        f"**After:** recomputed now, `as_of` {after['as_of']} — "
        f"{len(after_ranked)} ranked, {len(after_excl)} excluded.  "
        f"**Before:** snapshot `as_of` {before['as_of']} "
        f"(run {base.computed_at:%Y-%m-%d %H:%M}Z) — {len(before_ranked)} ranked, "
        f"{len(before_excl)} excluded.",
        "",
        "Reproduce with `python -m scripts.universe_verdict_diff` from `backend/`. Nothing is "
        "written to the ranking by this script unless `--write-snapshot` is passed.",
        "",
        "## Summary",
        "",
        _md_table(
            ["Change", "Count"],
            [
                ["Verdict changed", str(len(verdict_changed))],
                ["Dropped out of the ranked set", str(len(newly_excluded))],
                ["Entered the ranked set", str(len(newly_included))],
                [f"Score moved ≥ {MIN_SCORE_MOVE}", str(len(score_movers))],
            ],
        ),
        "",
    ]

    if insights:
        L += ["## Narrative (same engine as the scoreboard's Top Insights)", ""]
        L += [f"- {s}" for s in insights]
        L += [""]

    L += [f"## Verdict changed — {len(verdict_changed)}", ""]
    L += [
        _md_table(["Ticker", "Verdict", "Score before", "Score after"], verdict_changed)
        if verdict_changed
        else "_None._",
        "",
    ]

    L += [f"## Dropped out of the ranked set — {len(newly_excluded)}", ""]
    L += [
        _md_table(["Ticker", "Was", "Why it dropped"], newly_excluded)
        if newly_excluded
        else "_None._",
        "",
    ]

    L += [f"## Entered the ranked set — {len(newly_included)}", ""]
    L += [
        _md_table(["Ticker", "Verdict", "Score"], newly_included) if newly_included else "_None._",
        "",
    ]

    L += [f"## Score movers (≥ {MIN_SCORE_MOVE}) — {len(score_movers)}", ""]
    L += [
        _md_table(["Ticker", "Score", "Δ"], score_movers) if score_movers else "_None._",
        "",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(L), encoding="utf-8")
    print(f"Wrote {out_path}", file=sys.stderr)
    print(
        f"verdict changed {len(verdict_changed)}, dropped {len(newly_excluded)}, "
        f"entered {len(newly_included)}, movers {len(score_movers)}",
        file=sys.stderr,
    )

    if write:
        snap = write_snapshot(db, after_view, computed_at=started, duration_seconds=duration)
        print(f"Froze this run as snapshot id={snap.id} (as_of {snap.as_of}).", file=sys.stderr)


def _dec(v: Decimal | None) -> str:
    return "—" if v is None else f"{v:+.1f}"


def _trim(s: str, n: int = 130) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--against", type=lambda s: dt.date.fromisoformat(s), default=None,
                        help="diff against the newest snapshot on or before this YYYY-MM-DD")
    parser.add_argument("--write-snapshot", action="store_true",
                        help="also freeze the recomputed run as a new snapshot")
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "docs" / "audits" / "UNIVERSE_VERDICT_DIFF.md")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        run(db, against=args.against, write=args.write_snapshot, out_path=args.out)
    finally:
        db.close()


if __name__ == "__main__":
    main()
