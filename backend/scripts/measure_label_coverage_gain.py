"""One-time: how much did the measured label additions actually gain?

Companion to `measure_unmatched_labels.py`. That script found the real
unmatched wordings; this one re-parses the SAME cached filings and counts
how many now yield `operating_profit` and `capital_expenditure`, so the
gain is measured on real filings rather than inferred from label counts.

Reads only the local PDF cache — no network, no DB writes.

    .venv/Scripts/python.exe scripts/measure_label_coverage_gain.py
"""

from __future__ import annotations

import collections
import hashlib
import io
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pdfplumber  # noqa: E402

from app.domain.financial_statement_parsing import (  # noqa: E402
    detect_expected_value_columns,
    extract_candidate_lines,
    repair_character_doubling,
)
from app.ingestion.financial_pdf_extractor import _is_primary_statement_page  # noqa: E402

CACHE = pathlib.Path(__file__).parent / ".pdf_cache"
DB = pathlib.Path(__file__).parents[1] / "devdb.sqlite"
TRACKED = ("operating_profit", "capital_expenditure", "profit_before_tax",
           "operating_profit_before_working_capital_changes",
           "cash_generated_from_operations")
MAX_PAGES = 40


def keys_in(pdf_bytes: bytes) -> set[str]:
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
                if line.statement_line:
                    found.add(line.statement_line)
    return found


def main() -> int:
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c = db.cursor()

    # Attribute each cached file back to its ticker by URL, rather than
    # re-running the selection query. That query orders by
    # (period_type, period_end) with no tiebreaker, so on ties SQLite may
    # return a different filing between runs and the cache key would not
    # line up -- measured: reconstructing the mapping that way matched 1
    # of 130 cached files.
    url_to_ticker: dict[str, str] = {}
    for ticker, url in c.execute(
            "select distinct ticker, source_url from fundamentals where source_url is not null"):
        url_to_ticker.setdefault(hashlib.sha256(url.encode()).hexdigest()[:24], ticker)

    cached = sorted(CACHE.glob("*.pdf"))
    print(f"re-parsing {len(cached)} cached filings\n")
    hits: dict[str, set[str]] = collections.defaultdict(set)
    ok = 0
    for i, path in enumerate(cached, 1):
        ticker = url_to_ticker.get(path.stem, path.stem)
        try:
            keys = keys_in(path.read_bytes())
        except Exception as exc:  # noqa: BLE001 - diagnostic script
            print(f"[{i}/{len(cached)}] {ticker}: parse failed {type(exc).__name__}")
            continue
        ok += 1
        for k in keys & set(TRACKED):
            hits[k].add(ticker)

    print(f"{ok} filings parsed\n")
    print(f"{'canonical key':<50}{'filings yielding it':>20}")
    for k in TRACKED:
        print(f"  {k:<48}{len(hits[k]):>18}")
    both = hits["operating_profit"] & hits["capital_expenditure"]
    print(f"\n  BOTH operating_profit AND capital_expenditure: {len(both)} of {ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
