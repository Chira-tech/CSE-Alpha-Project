"""OI-4's own named, unfinished scope, closed for real: `docs/audits/
R1_OPEN_ISSUES.md`'s OI-4 section found the SAME note-reference-as-value
bug pattern OI-1 fixed (for 8 specific statement lines only) on a 9th
line (`interest_expense`) it never checked, and said plainly: "a full
re-run of OI-1's reverification sweep across every OTHER confirmed
statement line ... is real, separate, universe-wide work this session
did not do ... remains genuinely unknown at the scale of how many."

This script is that re-run — made possible by `check_magnitude_
plausibility` (`app.domain.financial_statement_parsing`), which didn't
exist when OI-1/OI-4 were written and replaces their crude "8 named
lines, absolute value < 100,000" heuristic with the real, self-scaling
signal: a value implausibly small relative to the LARGEST other value on
the SAME filing, whatever line it's on. Same structure as `scripts/
reverify_suspicious_fundamentals.py` otherwise (batched by source_url,
one download per filing, checkpointed/resumable, >=2s pacing) —
deliberately, so this stays recognisable as the same kind of operation,
not a divergent one-off.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.domain.financial_statement_parsing import check_magnitude_plausibility  # noqa: E402
from app.models.fundamentals import Fundamental  # noqa: E402


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def find_confirmed_magnitude_flagged(db: Session) -> list[Fundamental]:
    """Every CONFIRMED (REPORTED) row that check_magnitude_plausibility
    flags, computed the same way the real check runs in production: group
    by (ticker, period_end, period_type), build the full `values` dict
    from every stored line on that filing (confirmed or not — the check
    itself doesn't care), run the check, and keep whichever flagged line
    happens to be a REPORTED row."""
    all_rows = db.scalars(select(Fundamental)).all()
    groups: dict[tuple[str, dt.date, str], list[Fundamental]] = defaultdict(list)
    for r in all_rows:
        groups[(r.ticker, r.period_end, r.period_type)].append(r)

    flagged: list[Fundamental] = []
    for group_rows in groups.values():
        values: dict[str, Decimal] = {}
        by_line: dict[str, Fundamental] = {}
        for r in group_rows:
            if r.statement_line not in values:  # first occurrence wins, matches real usage
                values[r.statement_line] = r.value
                by_line[r.statement_line] = r
        for check in check_magnitude_plausibility(values):
            if check.passed:
                continue
            flagged_line = check.name.split(" implausibly small")[0]
            row = by_line.get(flagged_line)
            if row is not None and row.confirmed_by is not None and row.source_url is not None:
                flagged.append(row)
    return flagged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pacing-seconds", type=float, default=2.0)
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "docs" / "audits" / "R1_OI4_FULL_SCOPE_REVERIFICATION.md",
    )
    parser.add_argument("--limit-filings", type=int, default=None, help="cap for a dry run")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        rows = find_confirmed_magnitude_flagged(db)
        by_url: dict[str, list[Fundamental]] = defaultdict(list)
        for r in rows:
            by_url[r.source_url].append(r)

        urls = sorted(by_url)
        if args.limit_filings:
            urls = urls[: args.limit_filings]

        print(f"{len(rows)} candidate rows across {len(urls)} distinct filings.", file=sys.stderr)

        from app.ingestion.financial_pdf_extractor import (
            build_fundamental_drafts,
            download_pdf,
            extract_financial_statement_candidates,
        )

        checkpoint_path = args.out.with_suffix(".partial.jsonl")
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        done_urls: set[str] = set()
        results: list[dict] = []
        if checkpoint_path.exists():
            import json
            with checkpoint_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    done_urls.add(rec["_url"])
                    results.append(rec["_row"])
            print(f"Resuming: {len(done_urls)} filings already done in {checkpoint_path}", file=sys.stderr)

        checkpoint_f = checkpoint_path.open("a", encoding="utf-8")

        def _checkpoint(url: str, row: dict) -> None:
            import json
            checkpoint_f.write(json.dumps({"_url": url, "_row": row}) + "\n")
            checkpoint_f.flush()

        def _row(r: Fundamental, fresh: Decimal | None, outcome: str, detail: str) -> dict:
            return {
                "ticker": r.ticker, "line": r.statement_line, "period": str(r.period_end),
                "stored": f"{r.value:,}", "fresh": f"{fresh:,}" if fresh is not None else "—",
                "outcome": outcome, "detail": detail,
            }

        for i, url in enumerate(urls):
            if url in done_urls:
                continue
            if i > 0:
                time.sleep(args.pacing_seconds)
            print(f"[{i+1}/{len(urls)}] {url}", file=sys.stderr)
            filing_rows = by_url[url]
            try:
                pdf_bytes = download_pdf(url, user_agent=settings.cse_user_agent)
                candidates = extract_financial_statement_candidates(pdf_bytes)
            except Exception as exc:  # noqa: BLE001
                for r in filing_rows:
                    row = _row(r, None, "unverifiable", f"{type(exc).__name__}: {exc}")
                    results.append(row)
                    _checkpoint(url, row)
                continue

            for r in filing_rows:
                try:
                    drafts = build_fundamental_drafts(
                        ticker=r.ticker, period_end=r.period_end, period_type=r.period_type,
                        first_available_date=r.first_available_date, source_url=url,
                        candidates=candidates,
                    )
                except Exception as exc:  # noqa: BLE001
                    row = _row(r, None, "unverifiable", f"{type(exc).__name__}: {exc}")
                    results.append(row)
                    _checkpoint(url, row)
                    continue
                match = next((d for d in drafts if d.statement_line == r.statement_line), None)
                if match is None:
                    row = _row(
                        r, None, "unverifiable",
                        "current pipeline found no matching line on any primary-statement page",
                    )
                    results.append(row)
                    _checkpoint(url, row)
                    continue
                outcome = "confirmed_correct" if match.value == r.value else "stale_or_wrong"
                row = _row(r, match.value, outcome, "")
                results.append(row)
                _checkpoint(url, row)
    finally:
        db.close()
        try:
            checkpoint_f.close()
        except NameError:
            pass

    n_correct = sum(1 for r in results if r["outcome"] == "confirmed_correct")
    n_wrong = sum(1 for r in results if r["outcome"] == "stale_or_wrong")
    n_unverifiable = sum(1 for r in results if r["outcome"] == "unverifiable")

    lines = [
        "# OI-4 full-scope re-verification sweep",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}Z",
        "",
        "Closes OI-4's own named gap (docs/audits/R1_OPEN_ISSUES.md): OI-1's sweep only ever checked "
        "8 named statement lines with a crude `abs(value) < 100,000` filter. This sweep uses "
        "`check_magnitude_plausibility` instead — every statement line, self-scaled to each filing's "
        "own largest extracted value — so it measures the FULL scope for the first time, not a sample.",
        "",
        f"{len(results)} candidate rows across {len(urls)} distinct filings, re-verified against "
        "today's live source PDFs using today's unmodified extraction pipeline.",
        "",
        f"- **Confirmed still wrong (`stale_or_wrong`): {n_wrong}** — today's pipeline produces a "
        "DIFFERENT value than what's stored. These are the real, currently-actionable rows.",
        f"- Stored value matches a fresh re-extraction (`confirmed_correct`): {n_correct} — the "
        "stored figure IS what today's pipeline would produce (a genuine, tiny-but-real figure the "
        "magnitude check correctly left alone via `check_accounting_identities` never even needing "
        "to fire, or a value already fixed by a prior remediation pass).",
        f"- Unverifiable: {n_unverifiable} — network/parse failure or the line no longer matches on "
        "re-extraction; needs manual follow-up, not silently one or the other.",
        "",
        "## Rows confirmed still wrong (act on these)",
        "",
        _md_table(
            ["Ticker", "Line", "Period", "Stored", "Fresh (today's pipeline)"],
            [[r["ticker"], r["line"], r["period"], r["stored"], r["fresh"]]
             for r in results if r["outcome"] == "stale_or_wrong"],
        ),
        "",
        "## Unverifiable (needs manual follow-up)",
        "",
        _md_table(
            ["Ticker", "Line", "Period", "Stored", "Detail"],
            [[r["ticker"], r["line"], r["period"], r["stored"], r["detail"][:100]]
             for r in results if r["outcome"] == "unverifiable"],
        ),
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {args.out}", file=sys.stderr)
    print(f"correct={n_correct} wrong={n_wrong} unverifiable={n_unverifiable}", file=sys.stderr)


if __name__ == "__main__":
    main()
