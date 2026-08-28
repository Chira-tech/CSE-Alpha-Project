"""OI-1 remediation, step 2 — the full re-verification sweep.

Downloads every DISTINCT source filing behind the "suspicious" (< 100,000
in magnitude, on a headline canonical line) `Fundamental` rows found by
`scripts/audit_data_integrity.py`'s synthetic sweep, reruns THIS project's
current, unmodified production extraction pipeline against each fresh,
and reports — per row — whether today's code reproduces the stored value
or produces something different.

Batched by `source_url` (not by row): 396 candidate rows collapse to ~253
distinct filings, so each PDF is downloaded and parsed exactly once
regardless of how many suspicious line items it contains, at >=2s pacing
between distinct filings (this project's own courtesy-access discipline).
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
from app.models.fundamentals import Fundamental  # noqa: E402

CORE_LINES = (
    "revenue", "net_income", "total_assets", "total_equity", "total_liabilities",
    "profit_before_tax", "total_comprehensive_income", "operating_profit",
)


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pacing-seconds", type=float, default=2.0)
    parser.add_argument(
        "--confirmed-only", action="store_true", default=True,
        help="only re-verify REPORTED+confirmed rows (the ones actually live in valuations). Default true.",
    )
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "docs" / "audits" / "R1_OI1_REVERIFICATION.md",
    )
    parser.add_argument("--limit-filings", type=int, default=None, help="cap for a dry run")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        stmt = select(Fundamental).where(
            Fundamental.statement_line.in_(CORE_LINES),
            Fundamental.value < 100_000,
            Fundamental.value > -100_000,
            Fundamental.source_url.is_not(None),
        )
        if args.confirmed_only:
            stmt = stmt.where(Fundamental.confirmed_by.is_not(None))
        rows = db.scalars(stmt).all()

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
        # Resume support: if a partial file from an earlier (interrupted) run
        # exists, skip URLs already recorded in it rather than re-downloading
        # and re-paying the >=2s-per-filing cost for work already done.
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

            # Group filing_rows by (period_end, period_type) since one filing
            # can carry multiple periods' worth of stored rows (comparatives).
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
        "# OI-1 full re-verification sweep",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}Z",
        "",
        f"{len(results)} candidate rows across {len(urls)} distinct filings, re-verified against "
        "today's live source PDFs using today's unmodified extraction pipeline.",
        "",
        f"- **Confirmed still wrong (`stale_or_wrong`): {n_wrong}** — today's pipeline produces a "
        "DIFFERENT value than what's stored. These are the real, currently-actionable rows.",
        f"- Stored value matches a fresh re-extraction (`confirmed_correct`): {n_correct} — the "
        "stored figure IS what today's pipeline would produce; not a bug, a false positive of the "
        "crude `< 100000` magnitude filter that found the candidate set.",
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
