"""ONE-TIME external cross-check of the fundamentals confirm queue.

Every signal this system had until now — the accounting-identity web,
re-extraction, cross-source agreement, annual/quarterly reconciliation,
dual-listing agreement (`app.domain.fundamental_cross_check`) — ultimately
reads OUR OWN extraction of the CSE's own PDF. When that parse is wrong
they can all agree and still be wrong; that is exactly how OI-1/OI-4
happened. This script brings in a genuinely INDEPENDENT opinion: a third
party's published figures for the same company and period.

Not a product feature and deliberately not built as one — no table, no
migration, no wiring into the live cross-check engine. It runs once to
clean up existing data, in the same shape as `remediate_oi1.py`,
`remediate_oi4_full_scope.py` and `refix_oi4_overcorrections.py`: dry-run
by default, a resumable cache for the paced network phase, a dated note
that preserves the original value, and a single-command revert.

    python scripts/external_crosscheck.py --fetch      # phase 1, ~1h, resumable
    python scripts/external_crosscheck.py             # phase 2, report only
    python scripts/external_crosscheck.py --apply     # phase 3, writes

Source: stockanalysis.com. Its pages embed a SvelteKit data payload with
full-rupee arrays (not rounded to millions) and an explicit `datekey`
array of period-end dates, annual and quarterly. Its robots.txt allows
/quote/ (only /e/ and /p/ are disallowed) and sets no Crawl-delay, so this
self-imposes one, the same courtesy `app.ingestion.cbsl_client` extends to
CBSL's published delay.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import ProvenanceTier  # noqa: E402
from app.models.fundamentals import Fundamental  # noqa: E402
from app.models.securities import Security  # noqa: E402

SOURCE = "stockanalysis.com"
CACHE_PATH = REPO_ROOT / "docs" / "audits" / "external_fundamentals_cache.jsonl"
REPORT_PATH = REPO_ROOT / "docs" / "audits" / f"EXTERNAL_CROSSCHECK_{dt.date.today().isoformat()}.md"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

#: HARD mappings — the publisher's field means the same thing as our
#: canonical line beyond reasonable argument, so a disagreement here is
#: real evidence one of us is wrong. Only these may confirm or veto.
HARD_MAP: dict[str, str] = {
    "assets": "total_assets",
    "liabilities": "total_liabilities",
    "equity": "total_equity",
    "liabilitiesequity": "total_equity_and_liabilities",
    "assetsc": "total_current_assets",
    "currentLiabilities": "total_current_liabilities",
    "inventory": "inventories",
    "revenue": "revenue",
    "gp": "gross_profit",
    "opinc": "operating_profit",
    "netinccmn": "net_income",
    "ncfo": "cash_flow_from_operations",
    "ncfi": "net_cash_from_investing_activities",
    "ncff": "net_cash_from_financing_activities",
}

#: SOFT mappings — plausibly the same line, but the definitions genuinely
#: differ often enough that a mismatch proves nothing. Verified live on
#: RICH.N0000 2025-03-31: their `receivables` is 24,440,580,000 (total
#: receivables) against our `trade_receivables` of 11,069,351,000 (the
#: filing's own "Trade and other receivables" line) — both are correct
#: readings of different things. Reported for a human, never acted on.
SOFT_MAP: dict[str, str] = {
    "receivables": "trade_receivables",
    "accountsPayable": "trade_payables",
    "debt": "total_interest_bearing_debt",
    "capex": "capital_expenditure",
    "totalDepAmorCF": "depreciation_and_amortisation",
}

PAGES = {
    "": "income-statement",
    "balance-sheet/": "balance-sheet",
    "cash-flow-statement/": "cash-flow",
}

#: Agreement/conflict thresholds. The publisher's arrays carry JS float
#: artifacts (a real observed value: 67316914000.00001) and their own
#: rounding, so exact equality is the wrong test in both directions.
AGREE_REL = Decimal("0.001")  # <=0.1% apart -> the same figure

#: Only a gap THIS large is treated as proof someone is wrong. Deliberately
#: far above the noise floor, because a moderate gap is usually a real
#: definitional difference rather than an error — verified live on
#: RICH.N0000's quarterly revenue (ours 17,396,506,000 vs theirs
#: 18,469,540,000, ~6%) and net_income (~37%), which are a
#: three-months-ended vs cumulative / group-vs-parent column choice, not a
#: misread. Acting on those would mass-unconfirm correct data. The real
#: errors this exists to catch are order-of-magnitude: RICH's 2021-09-30
#: filing lost a leading digit on EVERY line (total_assets 5,555,380,000
#: against a true 75,555,380,000 — and both readings balance, so no
#: accounting identity could ever have caught it).
MATERIAL_REL = Decimal("0.20")
#: Below this, a percentage comparison is meaningless (3 vs 8 is 166% apart
#: but both are noise) — a conflict must also be materially large in
#: absolute rupees.
SMALL_ABS = Decimal("1000000")


def _rel_diff(a: Decimal, b: Decimal) -> Decimal:
    scale = max(abs(a), abs(b))
    if scale == 0:
        return Decimal(0)
    return abs(a - b) / scale


# --------------------------------------------------------------------------
# Phase 1 — fetch
# --------------------------------------------------------------------------

def _extract_array(text: str, field: str) -> list | None:
    m = re.search(r'(?:^|[,{"\\])' + re.escape(field) + r'\\?"?\s*:\s*(\[[^\]]*\])', text)
    if not m:
        return None
    raw = m.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def parse_payload(text: str) -> dict[tuple[str, str], Decimal]:
    """{(period_end_iso, source_field): value} from one page's payload."""
    dates = _extract_array(text, "datekey")
    if not dates:
        return {}
    out: dict[tuple[str, str], Decimal] = {}
    for field in list(HARD_MAP) + list(SOFT_MAP):
        arr = _extract_array(text, field)
        if not arr or len(arr) != len(dates):
            continue
        for date_str, value in zip(dates, arr):
            # "TTM" is a trailing-twelve-month roll-up, not a reported
            # period — it matches no filing and must never be compared.
            if date_str == "TTM" or value is None:
                continue
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date_str)):
                continue
            try:
                out[(str(date_str), field)] = Decimal(str(round(float(value))))
            except (ValueError, ArithmeticError):
                continue
    return out


def fetch_ticker(client: httpx.Client, ticker: str, pacing: float) -> list[dict]:
    rows: list[dict] = []
    for suffix, page_name in PAGES.items():
        for period_type, query in (("annual", ""), ("quarterly", "?p=quarterly")):
            url = f"https://stockanalysis.com/quote/cose/{ticker}/financials/{suffix}{query}"
            try:
                r = client.get(url, timeout=30, follow_redirects=True)
            except Exception as exc:  # noqa: BLE001 — one bad page must not stop the sweep
                print(f"    {page_name}/{period_type}: {type(exc).__name__}", file=sys.stderr)
                time.sleep(pacing)
                continue
            if r.status_code == 200:
                for (date_str, field), value in parse_payload(r.text).items():
                    rows.append({
                        "ticker": ticker, "period_end": date_str, "period_type": period_type,
                        "source_field": field, "value": str(value), "source_url": url,
                    })
            time.sleep(pacing)
    return rows


def phase_fetch(only_ticker: str | None, pacing: float) -> None:
    db = SessionLocal()
    try:
        tickers = [t for (t,) in db.execute(select(Security.ticker).order_by(Security.ticker))]
    finally:
        db.close()
    if only_ticker:
        tickers = [t for t in tickers if t == only_ticker]

    done: set[str] = set()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CACHE_PATH.exists():
        for line in CACHE_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["_ticker"])
                except (json.JSONDecodeError, KeyError):
                    continue
        print(f"Resuming: {len(done)} tickers already cached.", file=sys.stderr)

    todo = [t for t in tickers if t not in done]
    print(f"{len(todo)} tickers to fetch ({len(PAGES)*2} pages each).", file=sys.stderr)
    with httpx.Client(headers={"User-Agent": UA}) as client, CACHE_PATH.open("a", encoding="utf-8") as fh:
        for i, ticker in enumerate(todo, 1):
            rows = fetch_ticker(client, ticker, pacing)
            fh.write(json.dumps({"_ticker": ticker, "_rows": rows}) + "\n")
            fh.flush()
            print(f"  [{i}/{len(todo)}] {ticker}: {len(rows)} figures", file=sys.stderr)


def load_cache() -> dict[tuple[str, str, str, str], tuple[Decimal, str, str]]:
    """{(ticker, period_end, period_type, canonical_line): (value, field, url)}"""
    out: dict[tuple[str, str, str, str], tuple[Decimal, str, str]] = {}
    if not CACHE_PATH.exists():
        return out
    for line in CACHE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        for r in rec.get("_rows", []):
            canonical = HARD_MAP.get(r["source_field"]) or SOFT_MAP.get(r["source_field"])
            if canonical is None:
                continue
            key = (r["ticker"], r["period_end"], r["period_type"], canonical)
            # An income-statement page and a balance-sheet page can both
            # carry the same canonical line; first write wins, which is the
            # statement it actually belongs to given PAGES' ordering.
            out.setdefault(key, (Decimal(r["value"]), r["source_field"], r["source_url"]))
    return out


# --------------------------------------------------------------------------
# Phase 2/3 — compare, report, apply
# --------------------------------------------------------------------------

def classify(ours: Decimal, theirs: Decimal) -> str:
    """agree | conflict | minor. Only `agree` and `conflict` are ever acted
    on; `minor` is the deliberately-wide middle band that gets reported to
    a human and otherwise left completely alone (see MATERIAL_REL)."""
    rel = _rel_diff(ours, theirs)
    if rel <= AGREE_REL:
        return "agree"
    if rel >= MATERIAL_REL and abs(ours - theirs) >= SMALL_ABS:
        return "conflict"
    return "minor"


def signature(ours: Decimal, theirs: Decimal) -> str | None:
    """A MECHANICAL extraction-bug fingerprint, or None.

    A conflict alone never proves our figure wrong — measured across the
    universe, most disagreements are a real definitional difference (a
    quarterly filing's three-months-ended column against a cumulative one,
    or a group figure against a parent one). But when the two numbers share
    their entire digit string and differ only by a power of ten or a
    missing prefix, no definitional difference can explain it: a
    cumulative-vs-discrete total would not reproduce nine identical
    trailing digits by coincidence. That is a misread, and the external
    figure is the value we failed to read.

    Real cases behind each branch:
      scale_x1000          MASK.N0000 revenue 1,777,781 vs 1,777,781,000
                           (the filing's "Rs.'000" scale never applied)
      lost_leading_digits  LWL.N0000 revenue 978,398,000 vs 10,978,398,000
                           (pdfplumber split the leading digits off)
      scale_ours_x1000     AINS.N0000 total_assets 4,766,219,069,000 vs
                           4,766,219,069 (scale applied twice)
    """
    o, t = abs(int(ours)), abs(int(theirs))
    if o == 0 or t == 0:
        return None
    for mult in (1000, 100, 10):
        if t == o * mult:
            return f"scale_x{mult}"
        if o == t * mult:
            return f"scale_ours_x{mult}"
    so, st = str(o), str(t)
    # Require a real digit run in common, so a short number sharing a
    # couple of trailing digits with a longer one is never treated as proof.
    if len(st) > len(so) and st.endswith(so) and len(so) >= 4:
        return "lost_leading_digits"
    if len(so) > len(st) and so.endswith(st) and len(st) >= 4:
        return "extra_leading_digits"
    return None


def prefix_delta(stored: Decimal, derived: Decimal) -> bool:
    """True when `derived - stored` is exactly a leading-digit prefix that
    was dropped — i.e. a small integer times a power of ten larger than the
    stored number itself (70,000,000,000 in front of 6,512,434,000).

    This is the same misread class `signature()` recognises, asked in the
    one place that function cannot reach: a line whose correct value came
    from the accounting identity rather than from the external source.
    Allows a hair of relative slack because the derived figure inherits the
    external source's own rounding on the other two terms.
    """
    diff = derived - stored
    if diff <= 0 or stored <= 0:
        return False
    magnitude = Decimal(10) ** (len(str(int(abs(stored)))))
    while magnitude <= diff * 100:
        for lead in range(1, 100):
            candidate = Decimal(lead) * magnitude
            if candidate >= magnitude and abs(diff - candidate) <= max(candidate * Decimal("0.0001"), Decimal(1000)):
                return True
        magnitude *= 10
    return False


def enforce_filing_coherence(
    to_correct: list[tuple], stored_by_filing: dict[tuple, dict[str, Decimal]]
) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Corrections must leave a filing INTERNALLY CONSISTENT, not just move
    individual rows closer to an external figure.

    REAL CASE THIS EXISTS FOR (CBNK.N0000 2025-09-30, found live): every
    line on that balance sheet had lost the same leading digit, so the
    filing still satisfied `assets = equity + liabilities` under the wrong
    reading. The external source covers `assets` and `equity` but not
    `liabilities`, so correcting only what it covers would have left
    88,479,398,000 = 11,966,964,000 + 6,512,434,000 — a filing that
    balanced before and is broken after, which is worse data than either
    consistent state.

    So: for any filing whose balance-sheet identity holds before the
    corrections and would break after, derive the remaining member from the
    identity and accept it only if it carries the same dropped-prefix
    signature (`prefix_delta`). If it cannot be repaired coherently, EVERY
    correction for that filing is dropped rather than applied piecemeal.

    Returns (accepted, derived_extra, dropped).
    """
    by_filing: dict[tuple, list[tuple]] = defaultdict(list)
    for item in to_correct:
        row = item[0]
        by_filing[(row.ticker, row.period_end, row.period_type)].append(item)

    accepted: list[tuple] = []
    derived_extra: list[tuple] = []
    dropped: list[tuple] = []
    triple = ("total_assets", "total_equity", "total_liabilities")

    for filing, items in by_filing.items():
        stored = stored_by_filing.get(filing, {})
        if not set(triple) <= set(stored):
            accepted.extend(items)  # no identity to keep coherent
            continue
        before = abs(stored["total_assets"] - (stored["total_equity"] + stored["total_liabilities"]))
        after_vals = dict(stored)
        for row, theirs, _f, _s in items:
            after_vals[row.statement_line] = theirs
        after = abs(after_vals["total_assets"] - (after_vals["total_equity"] + after_vals["total_liabilities"]))

        if after <= before:
            accepted.extend(items)
            continue

        # Broken by a partial correction — try to repair the odd one out.
        corrected_lines = {row.statement_line for row, _t, _f, _s in items}
        missing = [ln for ln in triple if ln not in corrected_lines]
        repaired = False
        if len(missing) == 1:
            line = missing[0]
            if line == "total_liabilities":
                derived = after_vals["total_assets"] - after_vals["total_equity"]
            elif line == "total_equity":
                derived = after_vals["total_assets"] - after_vals["total_liabilities"]
            else:
                derived = after_vals["total_equity"] + after_vals["total_liabilities"]
            if prefix_delta(stored[line], derived):
                derived_extra.append((filing, line, stored[line], derived))
                repaired = True
        if repaired:
            accepted.extend(items)
        else:
            dropped.extend(items)
    return accepted, derived_extra, dropped


_ORIGINAL_VALUE_RE = re.compile(r"\[EXTERNAL-CORRECT [^\]]*\] stored value ([\d,\.\-]+) was a mechanical")
_NOTE_RE = re.compile(r"^\[EXTERNAL-(?:CONFIRM|CORRECT) [^\]]*\].*?\n\n", re.S)


def phase_revert(*, apply: bool) -> None:
    """Undo the whole pass: un-confirm every row this script touched and put
    back the original value on the ones it corrected (recovered from the
    note it wrote, which is why the note records the original figure)."""
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(Fundamental).where(Fundamental.confirmed_by.like("auto:external-v1%"))
        ).all()
        restored = 0
        for row in rows:
            note = row.source_snippet or ""
            m = _ORIGINAL_VALUE_RE.search(note)
            if apply:
                if m:
                    row.value = Decimal(m.group(1).replace(",", ""))
                    restored += 1
                row.provenance_tier = ProvenanceTier.AI_ASSISTED
                row.confirmed_by = None
                row.confirmed_at = None
                row.source_snippet = _NOTE_RE.sub("", note, count=1)
        print(f"{len(rows)} rows were written by this pass ({restored} values restored).")
        if apply:
            db.commit()
            print("REVERTED.")
        else:
            db.rollback()
            print("DRY RUN — re-run with --revert --apply.", file=sys.stderr)
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true", help="phase 1: populate the external cache")
    ap.add_argument("--apply", action="store_true", help="phase 3: write confirmations/corrections")
    ap.add_argument("--revert", action="store_true", help="undo this pass entirely")
    ap.add_argument("--ticker", type=str, default=None)
    ap.add_argument("--pacing-seconds", type=float, default=1.5)
    args = ap.parse_args()

    if args.fetch:
        phase_fetch(args.ticker, args.pacing_seconds)
        return

    if args.revert:
        phase_revert(apply=args.apply)
        return

    external = load_cache()
    if not external:
        print(f"No cache at {CACHE_PATH} — run with --fetch first.", file=sys.stderr)
        raise SystemExit(1)
    print(f"{len(external)} external figures cached.", file=sys.stderr)

    db = SessionLocal()
    try:
        stmt = select(Fundamental)
        if args.ticker:
            stmt = stmt.where(Fundamental.ticker == args.ticker)
        rows = db.scalars(stmt).all()

        # buckets: (tier, verdict) -> list of (row, theirs, field)
        buckets: dict[tuple[str, str], list] = defaultdict(list)
        stored_by_filing: dict[tuple, dict[str, Decimal]] = defaultdict(dict)
        row_by_key: dict[tuple, Fundamental] = {}
        for row in rows:
            canonical = row.statement_line
            filing = (row.ticker, row.period_end, row.period_type)
            stored_by_filing[filing][canonical] = Decimal(row.value)
            row_by_key[(row.ticker, row.period_end, row.period_type, canonical)] = row
            key = (row.ticker, row.period_end.isoformat(), row.period_type, canonical)
            hit = external.get(key)
            if hit is None:
                continue
            theirs, field, _url = hit
            tier = "hard" if HARD_MAP.get(field) == canonical else "soft"
            verdict = classify(Decimal(row.value), theirs)
            pending = row.provenance_tier == ProvenanceTier.AI_ASSISTED
            buckets[(tier, verdict, "pending" if pending else "confirmed")].append((row, theirs, field))

        def n(*k) -> int:
            return len(buckets.get(k, []))

        print()
        print("                     pending   confirmed")
        for tier in ("hard", "soft"):
            for verdict in ("agree", "conflict", "minor"):
                print(f"  {tier:<5} {verdict:<9} {n(tier, verdict, 'pending'):>7}   {n(tier, verdict, 'confirmed'):>7}")

        # ACTIONABLE SETS. A conflict on its own is NOT actionable — measured
        # across the universe, 2,570 of the 3,409 hard conflicts have no
        # mechanical signature and are a genuine definitional difference
        # (three-months-ended vs cumulative, group vs parent). Only the two
        # sets below get written; everything else is reported for a human.
        to_confirm = buckets.get(("hard", "agree", "pending"), [])
        to_correct: list[tuple] = []  # (row, theirs, field, signature)
        ambiguous: list[tuple] = []
        for state in ("pending", "confirmed"):
            for row, theirs, field in buckets.get(("hard", "conflict", state), []):
                sig = signature(Decimal(row.value), theirs)
                (to_correct if sig else ambiguous).append((row, theirs, field, sig))

        # A correction must leave its filing internally consistent — see
        # enforce_filing_coherence for the real CBNK.N0000 case.
        to_correct, derived_extra, dropped_incoherent = enforce_filing_coherence(
            to_correct, stored_by_filing
        )

        sig_counts: dict[str, int] = defaultdict(int)
        for _r, _t, _f, sig in to_correct:
            sig_counts[sig] += 1

        lines = [
            f"# External cross-check — {dt.date.today().isoformat()}",
            "",
            f"Source: {SOURCE}. {len(external)} external figures cached.",
            "",
            "Only HARD-mapped lines (where the publisher's field unambiguously means "
            "our canonical line) are ever acted on. SOFT-mapped lines are reported for "
            "a human and never auto-confirmed — see the script's own SOFT_MAP comment "
            "for the real RICH.N0000 case that proves why.",
            "",
            "| tier | verdict | pending | already confirmed |",
            "|---|---|---|---|",
        ]
        for tier in ("hard", "soft"):
            for verdict in ("agree", "conflict", "minor"):
                lines.append(
                    f"| {tier} | {verdict} | {n(tier, verdict, 'pending')} | {n(tier, verdict, 'confirmed')} |"
                )
        lines += [
            "",
            "## What is acted on, and what is not",
            "",
            f"- **{len(to_confirm)} pending rows confirmed** — an independent publisher "
            "reports the same figure (within 0.1%).",
            f"- **{len(to_correct)} rows corrected** to the external figure — these carry a "
            "mechanical misread signature (identical digit string, differing only by a "
            "power of ten or a missing prefix), which a definitional difference cannot "
            "produce. Breakdown: "
            + ", ".join(f"{k} {v}" for k, v in sorted(sig_counts.items())) + ".",
            f"- **{len(derived_extra)} further lines derived** from the accounting "
            "identity, where the external source covered only part of a balance sheet "
            "whose every line had lost the same prefix — correcting the covered lines "
            "alone would have broken a filing that previously balanced.",
            f"- **{len(dropped_incoherent)} corrections dropped** because they could not "
            "be applied coherently: they would have left their filing internally "
            "inconsistent and the odd line out could not be derived.",
            f"- **{len(ambiguous)} conflicts left completely untouched** — a real "
            "disagreement with no mechanical signature. These are mostly a quarterly "
            "filing's three-months-ended column against a cumulative one, or a group "
            "figure against a parent one; neither side is provably wrong, so a human "
            "decides. Listed below.",
            "",
            "## Lines derived from the accounting identity to keep a filing coherent",
            "",
            "| ticker | period | type | line | ours | derived |",
            "|---|---|---|---|---|---|",
        ]
        for (tk, pe, pt), line, old, new in sorted(derived_extra, key=lambda x: (x[0][0], x[0][1])):
            lines.append(f"| {tk} | {pe} | {pt} | {line} | {old:,} | {new:,} |")
        lines += [
            "",
            "## Rows corrected (mechanical misread, external figure is the true one)",
            "",
            "| ticker | line | period | type | ours | theirs | signature |",
            "|---|---|---|---|---|---|---|",
        ]
        for row, theirs, _f, sig in sorted(to_correct, key=lambda x: (x[0].ticker, x[0].period_end)):
            lines.append(
                f"| {row.ticker} | {row.statement_line} | {row.period_end} | {row.period_type} "
                f"| {Decimal(row.value):,} | {theirs:,} | {sig} |"
            )
        lines += [
            "",
            "## Unresolved conflicts — NOT touched, need a human",
            "",
            "| ticker | line | period | type | tier | ours | theirs |",
            "|---|---|---|---|---|---|---|",
        ]
        for row, theirs, _f, _s in sorted(ambiguous, key=lambda x: (x[0].ticker, x[0].period_end)):
            state = "pending" if row.provenance_tier == ProvenanceTier.AI_ASSISTED else "CONFIRMED"
            lines.append(
                f"| {row.ticker} | {row.statement_line} | {row.period_end} | {row.period_type} "
                f"| {state} | {Decimal(row.value):,} | {theirs:,} |"
            )
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nWrote {REPORT_PATH}")
        print(f"  confirm {len(to_confirm)} | correct {len(to_correct)} {dict(sig_counts)} | derive {len(derived_extra)} | dropped {len(dropped_incoherent)} | leave {len(ambiguous)}")

        if not args.apply:
            print("DRY RUN — nothing written. Re-run with --apply.", file=sys.stderr)
            db.rollback()
            return

        today = dt.date.today().isoformat()
        stamp = dt.datetime.now(dt.timezone.utc)
        for row, theirs, field in to_confirm:
            row.provenance_tier = ProvenanceTier.REPORTED
            row.confirmed_by = f"auto:external-v1 [{SOURCE}:{field}]"
            row.confirmed_at = stamp
            row.source_snippet = (
                f"[EXTERNAL-CONFIRM {today}] {SOURCE} independently publishes "
                f"{theirs:,} for this line and period, matching the stored value within "
                f"0.1%. Revert: scripts/external_crosscheck.py --revert.\n\n"
                + (row.source_snippet or "")
            )
        for row, theirs, field, sig in to_correct:
            original = Decimal(row.value)
            row.value = theirs
            row.provenance_tier = ProvenanceTier.REPORTED
            row.confirmed_by = f"auto:external-v1/{sig} [{SOURCE}:{field}]"
            row.confirmed_at = stamp
            row.source_snippet = (
                f"[EXTERNAL-CORRECT {today}] stored value {original:,} was a mechanical "
                f"misread ({sig}) — its digit string is identical to {SOURCE}'s "
                f"independently published {theirs:,} apart from scale/a missing prefix, "
                f"which a group-vs-parent or period-basis difference cannot produce. "
                f"Corrected to the external figure. Revert: "
                f"scripts/external_crosscheck.py --revert.\n\n"
                + (row.source_snippet or "")
            )
        for (tk, pe, pt), line, old, new in derived_extra:
            row = row_by_key.get((tk, pe, pt, line))
            if row is None:
                continue
            row.value = new
            row.provenance_tier = ProvenanceTier.REPORTED
            row.confirmed_by = f"auto:external-v1/derived [{SOURCE}]"
            row.confirmed_at = stamp
            row.source_snippet = (
                f"[EXTERNAL-CORRECT {today}] stored value {old:,} was a mechanical "
                f"misread (dropped prefix). Its siblings on this filing were corrected "
                f"against {SOURCE}; this line is not published there, so it was derived "
                f"from the balance-sheet identity as {new:,} — which restores the exact "
                f"prefix its siblings had lost, and keeps the filing balanced. Revert: "
                f"scripts/external_crosscheck.py --revert.\n\n"
                + (row.source_snippet or "")
            )
        db.commit()
        print(
            f"APPLIED — {len(to_confirm)} confirmed, {len(to_correct)} corrected, "
            f"{len(derived_extra)} derived, {len(ambiguous)} left for a human."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
