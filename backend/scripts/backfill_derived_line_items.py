"""ONE-TIME backfill of DERIVED line items over already-confirmed data.

THE GAP. `app.domain.financial_statement_parsing.derive_additional_line_
items` computes three canonical concepts that only ever exist as an
arithmetic combination of other lines — `depreciation_and_amortisation`,
`change_in_net_working_capital`, and `net_working_capital`. It is real,
tested and correct, but it only ever ran at INGESTION time, against that
one filing's freshly-extracted values. Every row ingested before it
existed never got the derivation, and nothing has ever revisited them.

Measured 29 Aug 2026, and this is the whole reason the §18 FCFF DCF
values nobody:

    depreciation_expense                     132 tickers, 1,919 rows
    depreciation_and_amortisation (derived)   10 tickers,    43 rows
    operating_profit_before_working_capital_changes  149 tickers
    cash_generated_from_operations                   159 tickers
    net_working_capital (derived)             13 tickers,    13 rows

224 tickers have confirmed `revenue`; requiring D&A as well collapses
that to 4, and requiring `net_working_capital` collapses it to 0. The
inputs are sitting in the database — the arithmetic was simply never run
over them.

PROVENANCE. Ingestion writes its derived drafts as AI_ASSISTED, correctly,
because at that moment the INPUTS are unconfirmed extractions too. Here
the inputs are all `can_enter_valuation` figures, so the output is
`ProvenanceTier.DERIVED` — which is precisely what §8's tier list exists
for, and which `can_enter_valuation` admits. Nothing is promoted to
Reported and no human confirmation is bypassed: a value computed from
confirmed inputs is exactly as trustworthy as those inputs, and is
labelled as computed rather than reported.

POINT-IN-TIME. A derived row's `first_available_date` is the LATEST of
its inputs' — the figure could not have been known before every component
was public (§6).

    python scripts/backfill_derived_line_items.py            # dry run
    python scripts/backfill_derived_line_items.py --apply
    python scripts/backfill_derived_line_items.py --revert --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.domain.financial_statement_parsing import (  # noqa: E402
    DERIVED_DIFFERENCES,
    DERIVED_SUMS,
    NET_WORKING_CAPITAL_ASSET_COMPONENTS,
    NET_WORKING_CAPITAL_LIABILITY_COMPONENTS,
    derive_additional_line_items,
)
from app.domain.provenance import can_enter_valuation  # noqa: E402
from app.models.enums import ProvenanceTier  # noqa: E402
from app.models.fundamentals import Fundamental  # noqa: E402

TAG = "[DERIVED-BACKFILL"
REPORT = REPO_ROOT / "docs" / "audits" / f"DERIVED_BACKFILL_{dt.date.today().isoformat()}.md"


def derive_da_from_depreciation_only(values: dict[str, Decimal]) -> Decimal | None:
    """`depreciation_and_amortisation` for a company that reports
    depreciation but no separate amortisation line.

    `DERIVED_SUMS` deliberately requires BOTH components and produces
    nothing from one — the right call at ingestion, where a missing
    amortisation line may simply not have been parsed off the page yet.
    Applied to CONFIRMED data it is too strict: only 21 tickers have a
    confirmed `amortisation_expense` against 132 with depreciation, so the
    strict rule leaves the DCF with 4 usable tickets universe-wide.

    Treating D&A as depreciation alone when no amortisation line exists is
    a real reading (most industrials and plantations genuinely carry no
    material amortisation), and it errs in the SAFE direction: D&A is
    added back to EBIT in §18.1's FCFF, so understating it understates
    free cash flow and therefore fair value — the same
    directionally-conservative discipline `app.domain.wacc` already
    applies to a missing cost of debt. Every row produced this way says so
    in its own `source_snippet`.
    """
    if "depreciation_and_amortisation" in values or "amortisation_expense" in values:
        return None
    return values.get("depreciation_expense")


def _components_note(line: str, values: dict[str, Decimal]) -> str:
    if line == "net_working_capital":
        assets = sorted(k for k in NET_WORKING_CAPITAL_ASSET_COMPONENTS if k in values)
        liabilities = sorted(k for k in NET_WORKING_CAPITAL_LIABILITY_COMPONENTS if k in values)
        return (
            "assets (" + "; ".join(f"{k} = {values[k]:,}" for k in assets) + ") minus liabilities ("
            + "; ".join(f"{k} = {values[k]:,}" for k in liabilities) + ")"
        )
    if line in DERIVED_SUMS:
        return "sum of " + "; ".join(f"{k} = {values[k]:,}" for k in DERIVED_SUMS[line] if k in values)
    if line in DERIVED_DIFFERENCES:
        a, b = DERIVED_DIFFERENCES[line]
        return f"{a} = {values[a]:,} minus {b} = {values[b]:,}"
    return "derived"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.revert:
            rows = db.scalars(
                select(Fundamental).where(
                    Fundamental.provenance_tier == ProvenanceTier.DERIVED,
                    Fundamental.source_snippet.like(f"%{TAG}%"),
                )
            ).all()
            print(f"{len(rows)} rows were written by this backfill.")
            if args.apply:
                for r in rows:
                    db.delete(r)
                db.commit()
                print("REVERTED (rows deleted).")
            else:
                db.rollback()
                print("DRY RUN — re-run with --revert --apply.", file=sys.stderr)
            return

        all_rows = db.scalars(select(Fundamental)).all()
        groups: dict[tuple, list[Fundamental]] = defaultdict(list)
        for r in all_rows:
            groups[(r.ticker, r.period_end, r.period_type)].append(r)

        to_write: list[tuple] = []  # (key, line, value, note, first_available)
        for key, rows in groups.items():
            usable = [r for r in rows if can_enter_valuation(r.provenance_tier)]
            if not usable:
                continue
            # lowest version wins, matching every other reader in this codebase
            best: dict[str, Fundamental] = {}
            for r in usable:
                cur = best.get(r.statement_line)
                if cur is None or r.version < cur.version:
                    best[r.statement_line] = r
            values = {line: Decimal(r.value) for line, r in best.items()}
            present = set(values)

            derived = derive_additional_line_items(values)
            da_fallback = derive_da_from_depreciation_only(values)
            if da_fallback is not None and "depreciation_and_amortisation" not in derived:
                derived["depreciation_and_amortisation"] = da_fallback

            for line, value in derived.items():
                if line in present:
                    continue
                if line == "depreciation_and_amortisation" and da_fallback is not None:
                    note = (
                        f"depreciation_expense = {values['depreciation_expense']:,} used alone — this "
                        "filing reports no separate amortisation line. Understates D&A if one exists "
                        "unextracted, which understates FCFF and therefore fair value (the safe "
                        "direction)."
                    )
                else:
                    note = _components_note(line, values)
                first_available = max(
                    (best[k].first_available_date for k in values if k in best),
                    default=key[1],
                )
                to_write.append((key, line, value, note, first_available))

        by_line: dict[str, int] = defaultdict(int)
        tickers: dict[str, set] = defaultdict(set)
        for (ticker, _pe, _pt), line, *_ in to_write:
            by_line[line] += 1
            tickers[line].add(ticker)

        print(f"{len(to_write)} derived rows to write across {len({k[0] for k, *_ in to_write})} tickers")
        for line, n in sorted(by_line.items(), key=lambda kv: -kv[1]):
            print(f"   {line:<36} {n:>6} rows   {len(tickers[line]):>4} tickers")

        lines = [
            f"# Derived line-item backfill — {dt.date.today().isoformat()}",
            "",
            "`derive_additional_line_items` only ever ran at ingestion time, so every row "
            "stored before it existed never got the derivation. The inputs were already in "
            "the database; the arithmetic had simply never been run over them.",
            "",
            "Written as `ProvenanceTier.DERIVED` — computed from inputs that already pass "
            "`can_enter_valuation`, labelled as computed rather than reported, and never "
            "promoted to Reported. Each row's `first_available_date` is the LATEST of its "
            "inputs' (§6: it could not have been known before every component was public).",
            "",
            "| line | rows | tickers |",
            "|---|---|---|",
        ]
        for line, n in sorted(by_line.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {line} | {n} | {len(tickers[line])} |")
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nWrote {REPORT}")

        if not args.apply:
            db.rollback()
            print("DRY RUN — nothing written. Re-run with --apply.", file=sys.stderr)
            return

        today = dt.date.today().isoformat()
        for (ticker, period_end, period_type), line, value, note, first_available in to_write:
            db.add(Fundamental(
                ticker=ticker,
                period_end=period_end,
                period_type=period_type,
                first_available_date=first_available,
                version=1,
                statement_line=line,
                value=value,
                currency="LKR",
                provenance_tier=ProvenanceTier.DERIVED,
                restated_flag=False,
                source_url=None,
                source_page=None,
                source_snippet=(
                    f"{TAG} {today}] Computed, not reported: {note}. Every input is a figure "
                    f"that already passes §8's can_enter_valuation, so this carries the DERIVED "
                    f"tier. Revert: scripts/backfill_derived_line_items.py --revert --apply."
                ),
                confirmed_by=None,
                confirmed_at=None,
            ))
        db.commit()
        print(f"APPLIED — {len(to_write)} derived rows written.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
