"""OI-4 pass-2/3 left ~20 rows OVER-corrected: `_merge_all_split_pairs`
fused a spurious "<page-ref> <note-ref>" pair into the value (AHPL's real
"Other components of equity 96 25 23,093,391 ..." -> 2,523,093,391,000,
~110x the real figure and 59x the filing's own total equity), and the
small-side magnitude flag cleared it without complaint.

Two parser fixes landed since (app.domain.financial_statement_parsing):
a component-subtotal ceiling in `reconcile_magnitude_implausible_values`,
and a second-leading-reference drop in `split_label_and_values`. This
script re-runs the NOW-FIXED extractor against each affected filing and
writes back the corrected value, same conservative shape as
`remediate_oi4_full_scope.py`: dry-run by default, every touched row
kept AI_ASSISTED/unconfirmed (§8), a dated note prepended to
`source_snippet` with the original wrong value preserved. A row is only
corrected when the fresh reading is itself plausible (at or below the
subtotal it rolls into); anything still implausible is left flagged and
named, never forced.

Also corrects the 5 `income_tax_expense` rows OI-4's sweep marked
`unverifiable`: their real source line reads nil for the period
("Income tax expense 4 - -") and the stored value is the note reference
— the real figure is 0.
"""
from __future__ import annotations

import datetime as dt
import sys
import urllib.request
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.ingestion.financial_pdf_extractor import extract_financial_statement_candidates  # noqa: E402
from app.models.enums import ProvenanceTier  # noqa: E402
from app.models.fundamentals import Fundamental  # noqa: E402

REMEDIATION_TAG = "FULL-SCOPE REMEDIATION 2026-08-28"

# component line -> the subtotal(s) that structurally bound it, most
# specific first (mirrors financial_statement_parsing._COMPONENT_SUBTOTAL_
# CEILINGS, plus profit_before_tax which the parser guard doesn't cover)
CEILINGS: dict[str, tuple[str, ...]] = {
    "inventories": ("total_current_assets", "total_assets"),
    "trade_receivables": ("total_current_assets", "total_assets"),
    "trade_payables": ("total_current_liabilities", "total_liabilities", "total_assets"),
    "total_interest_bearing_debt": ("total_liabilities", "total_assets"),
    "revaluation_reserves": ("total_equity", "total_equity_and_liabilities"),
    "profit_before_tax": ("revenue", "total_assets"),
}
TOLERANCE = Decimal("1.10")

NIL_TAX_ROWS = [
    ("BFN.N0000", "income_tax_expense", dt.date(2020, 3, 31), "annual"),
    ("CALI.U0000", "income_tax_expense", dt.date(2026, 6, 30), "quarterly"),
    ("CALC.U0000", "income_tax_expense", dt.date(2026, 6, 30), "quarterly"),
    ("WLTH.N0000", "income_tax_expense", dt.date(2026, 6, 30), "quarterly"),
    ("CALU.U0000", "income_tax_expense", dt.date(2026, 3, 31), "quarterly"),
]


def _ceiling_for(db, row: Fundamental) -> Decimal | None:
    for sibling in CEILINGS.get(row.statement_line, ()):
        v = db.scalar(
            select(Fundamental.value)
            .where(
                Fundamental.ticker == row.ticker,
                Fundamental.period_end == row.period_end,
                Fundamental.period_type == row.period_type,
                Fundamental.statement_line == sibling,
            )
            .order_by(Fundamental.version)
            .limit(1)
        )
        if v:
            return abs(v)
    return None


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=120).read()


def _note(original_value: Decimal, corrected: Decimal, why: str) -> str:
    return (
        f"[OI-4 OVER-CORRECTION REFIX {dt.date.today().isoformat()}] {why} "
        f"Original stored value {original_value:,} corrected to {corrected:,} by "
        f"scripts/refix_oi4_overcorrections.py after the two-leading-reference / "
        f"subtotal-ceiling parser fixes. Reverted to AI_ASSISTED — a human must "
        f"confirm before this can enter a valuation (§8).\n\nPrevious snippet: "
    )


def main() -> None:
    apply = "--apply" in sys.argv
    db = SessionLocal()
    corrected = 0
    left = 0
    try:
        flagged = db.scalars(
            select(Fundamental).where(Fundamental.source_snippet.like(f"%{REMEDIATION_TAG}%"))
        ).all()
        over = []
        for r in flagged:
            ceil = _ceiling_for(db, r)
            if ceil is not None and abs(r.value) > ceil * TOLERANCE:
                over.append((r, ceil))

        by_url: dict[str, list] = {}
        for r, ceil in over:
            by_url.setdefault(r.source_url, []).append((r, ceil))

        print(f"{len(over)} over-corrected rows across {len(by_url)} filings\n")

        for url, rows in by_url.items():
            tickers = sorted({r.ticker for r, _ in rows})
            print(f"--- {url}  ({', '.join(tickers)}) ---")
            try:
                data = _download(url)
                candidates = extract_financial_statement_candidates(data)
            except Exception as e:  # noqa: BLE001
                print(f"  DOWNLOAD/EXTRACT FAILED: {e!r} — left untouched")
                left += len(rows)
                continue
            fresh: dict[str, Decimal] = {}
            for _page, line in candidates:
                if line.statement_line and line.statement_line not in fresh and line.primary_value is not None:
                    fresh[line.statement_line] = line.primary_value
            for r, ceil in rows:
                new = fresh.get(r.statement_line)
                if new is None:
                    print(f"  {r.ticker} {r.statement_line} {r.period_end}: no fresh line — LEFT (val {r.value:,})")
                    left += 1
                    continue
                if abs(new) > ceil * TOLERANCE:
                    print(f"  {r.ticker} {r.statement_line} {r.period_end}: fresh {new:,} still > ceiling {ceil:,} — LEFT")
                    left += 1
                    continue
                # ...and the fresh reading must not be implausibly SMALL
                # either — LPRT's re-extraction returns a bare 1,000 for a
                # revaluation reserve against ~1bn total equity (itself a
                # note-reference-as-value misread the two-leading-ref drop
                # doesn't reach on that filing's shape). Same 1e-6 floor
                # `financial_statement_parsing._MAGNITUDE_IMPLAUSIBILITY_
                # RATIO` uses; a real component is never a millionth of
                # its own subtotal.
                if abs(new) < ceil * Decimal("0.000001"):
                    print(f"  {r.ticker} {r.statement_line} {r.period_end}: fresh {new:,} implausibly small vs {ceil:,} — LEFT")
                    left += 1
                    continue
                print(f"  {r.ticker} {r.statement_line} {r.period_end}: {r.value:,} -> {new:,}")
                if apply:
                    r.source_snippet = _note(r.value, new, "spurious page/note token fused into the value.") + (r.source_snippet or "")
                    r.value = new
                    r.provenance_tier = ProvenanceTier.AI_ASSISTED
                    r.confirmed_by = None
                    r.confirmed_at = None
                corrected += 1

        print("\n--- nil income_tax_expense rows (source line reads '- -' for the period) ---")
        for ticker, line, period_end, period_type in NIL_TAX_ROWS:
            rows = db.scalars(
                select(Fundamental).where(
                    Fundamental.ticker == ticker,
                    Fundamental.statement_line == line,
                    Fundamental.period_end == period_end,
                    Fundamental.period_type == period_type,
                )
            ).all()
            for r in rows:
                if r.value == 0:
                    continue
                print(f"  {ticker} {line} {period_end}: {r.value} -> 0")
                if apply:
                    r.source_snippet = _note(Decimal(r.value), Decimal(0), "note reference stored as value; source line reads nil for this period.") + (r.source_snippet or "")
                    r.value = Decimal(0)
                    r.provenance_tier = ProvenanceTier.AI_ASSISTED
                    r.confirmed_by = None
                    r.confirmed_at = None
                corrected += 1

        print(f"\n{corrected} rows would be corrected, {left} left flagged.")
        if apply:
            db.commit()
            print("APPLIED — committed.")
        else:
            db.rollback()
            print("DRY RUN — re-run with --apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
