"""One-time diagnostic: which REAL label wordings are we failing to match?

`operating_profit` is missing for 211 of 294 tickers and
`capital_expenditure` for 199 — between them the biggest blocker on §18's
DCF (see docs/SYSTEM_AUDIT.md L3). This module's own standing rule is to
add a canonical label only after seeing it on a real filing, never by
guessing, so this script MEASURES the real wordings instead.

For a sample of tickers that are missing one of these lines, it
re-downloads a filing we already have on file (`fundamentals.source_url`,
so no CSE index call is needed), runs the real page-selection and
line-splitting code, and collects every label that parsed as a line item
but matched NO canonical key. Those are ranked by how many DISTINCT
tickers print them — a wording used by 40 companies is worth adding; one
used by a single company is probably that company's own phrasing.

Throwaway, per this project's "one-time cleanups are scripts, not
subsystems" rule: no DB writes, no new tables, no migration. PDFs are
cached under `scripts/.pdf_cache/` (gitignored) so re-runs cost nothing.

    .venv/Scripts/python.exe scripts/measure_unmatched_labels.py --limit 60
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import pathlib
import re
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pdfplumber  # noqa: E402

from app.domain.financial_statement_parsing import (  # noqa: E402
    detect_expected_value_columns,
    extract_candidate_lines,
    normalize_label,
    repair_character_doubling,
)
from app.ingestion.financial_pdf_extractor import (  # noqa: E402
    _is_primary_statement_page,
    download_pdf,
)

CACHE = pathlib.Path(__file__).parent / ".pdf_cache"
DB = pathlib.Path(__file__).parents[1] / "devdb.sqlite"
USER_AGENT = "cse-alpha-engine/0.1 (personal research use)"
PACE_SECONDS = 2.0

#: Labels worth reporting even at low frequency, because they sit on the
#: two lines we are hunting. Substring test on the normalised label.
INTEREST = (
    "operat", "purchas", "acquisi", "propert", "plant", "equipment",
    "capital expend", "capex", "addition", "invest in", "results from",
)


def cached_pdf(url: str) -> bytes | None:
    CACHE.mkdir(exist_ok=True)
    key = CACHE / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".pdf")
    if key.exists():
        return key.read_bytes()
    try:
        data = download_pdf(url, user_agent=USER_AGENT)
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        print(f"    ! download failed: {type(exc).__name__}", flush=True)
        return None
    key.write_bytes(data)
    time.sleep(PACE_SECONDS)
    return data


#: Stop after this many pages. An interim is 5-15 pages, so anything
#: past this is an annual report that slipped through the quarterly
#: preference (some tickers have no quarterly filing on file) and would
#: cost minutes for labels the interims already give us.
MAX_PAGES = 40


def unmatched_labels(pdf_bytes: bytes) -> set[str]:
    """Every label on a primary-statement page that parsed as a line item
    but matched no canonical key."""
    found: set[str] = set()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages[:MAX_PAGES]:
            text = page.extract_text() or ""
            if not text:
                continue
            text = repair_character_doubling(text)
            if not _is_primary_statement_page(text):
                continue
            cols = detect_expected_value_columns(text) or 2
            for line in extract_candidate_lines(text, cols):
                if line.statement_line is not None:
                    continue
                label = normalize_label(line.raw_label)
                # Drop pure noise: too short, or mostly digits/punctuation.
                if len(label) < 6 or not re.search(r"[a-z]{4}", label):
                    continue
                if len(label) > 90:
                    continue
                found.add(label)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60, help="tickers to sample")
    ap.add_argument("--top", type=int, default=45, help="labels to print")
    ap.add_argument("--all-archetypes", action="store_true",
                    help="include banks/insurers (off by default — see FINANCIAL below)")
    args = ap.parse_args()

    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c = db.cursor()

    have_op = {r[0] for r in c.execute(
        "select distinct ticker from fundamentals "
        "where statement_line='operating_profit' and confirmed_at is not null")}
    have_cx = {r[0] for r in c.execute(
        "select distinct ticker from fundamentals "
        "where statement_line='capital_expenditure' and confirmed_at is not null")}

    # Banks, finance companies and insurers do not report an "operating
    # profit" or a meaningful capital-expenditure line, and they are not
    # supposed to: `valuation_router` already lists "Free cash flow" among
    # their `meaningless_metrics`, so an FCFF DCF is correctly never
    # routed to them. Sampling their filings would rank their own wording
    # (interest income, impairment charges) above the industrial lines
    # actually being hunted. Excluded by default, measured not assumed —
    # 59 of 294 tickers.
    financial = {r[0] for r in c.execute(
        "select ticker from securities "
        "where archetype in ('bank','non_bank_finance','insurance')")}
    universe = [r[0] for r in c.execute("select ticker from securities order by ticker")]
    missing = [t for t in universe if t not in have_op or t not in have_cx]
    if not args.all_archetypes:
        missing = [t for t in missing if t not in financial]

    # Prefer QUARTERLY filings. A CSE interim is 5-15 pages and carries
    # BOTH the income statement and the cash-flow statement, so it has
    # everything this measurement needs. Annual reports carry the same
    # statements but run to 200-400 pages, and pdfplumber takes minutes
    # per file — measured here, not assumed: the first run of this script
    # preferred annuals and managed 3 filings in 4 minutes.
    targets: list[tuple[str, str]] = []
    for ticker in missing:
        row = c.execute(
            "select source_url from fundamentals where ticker=? and source_url is not null "
            "order by (period_type='quarterly') desc, period_end desc, source_url limit 1", (ticker,)).fetchone()
        if row:
            targets.append((ticker, row[0]))
    targets = targets[: args.limit]

    print(f"{len(missing)} tickers missing operating_profit and/or capital_expenditure")
    print(f"sampling {len(targets)} of them that have a filing on file\n")

    by_label: dict[str, set[str]] = collections.defaultdict(set)
    ok = 0
    for i, (ticker, url) in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {ticker}", flush=True)
        data = cached_pdf(url)
        if not data:
            continue
        try:
            labels = unmatched_labels(data)
        except Exception as exc:  # noqa: BLE001 - diagnostic script
            print(f"    ! parse failed: {type(exc).__name__}", flush=True)
            continue
        ok += 1
        for label in labels:
            by_label[label].add(ticker)

    print(f"\n{ok} filings parsed; {len(by_label)} distinct unmatched labels\n")

    # Persist the raw label -> tickers map so the ranking can be re-cut
    # (different filters, different thresholds) without re-downloading or
    # re-parsing anything.
    raw = pathlib.Path(__file__).parent / ".unmatched_labels.json"
    raw.write_text(json.dumps({k: sorted(v) for k, v in by_label.items()}, indent=1), encoding="utf-8")
    print(f"raw label->tickers map written to {raw.name}\n")

    ranked = sorted(by_label.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    print("=" * 78)
    print(f"TOP {args.top} UNMATCHED LABELS (by distinct tickers printing them)")
    print("=" * 78)
    for label, tickers in ranked[: args.top]:
        print(f"{len(tickers):>4}  {label}")

    print()
    print("=" * 78)
    print("UNMATCHED LABELS ON THE TWO LINES WE ARE HUNTING")
    print("=" * 78)
    for label, tickers in ranked:
        if len(tickers) >= 2 and any(k in label for k in INTEREST):
            print(f"{len(tickers):>4}  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
