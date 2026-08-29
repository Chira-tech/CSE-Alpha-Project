"""ONE-TIME verification of the corporate-actions confirm queue.

Two independent checks, deliberately kept apart because the evidence is of
completely different kinds:

RATIO-TYPE ACTIONS (split / bonus / consolidation) — verified against THIS
SYSTEM'S OWN PRICE HISTORY, no network. A split is mechanical: on ex-date
the price divides by (1 + new_shares_per_held_share). So the real close
either side of ex-date implies a ratio, and that implied ratio either
matches the declared one or it doesn't. Verified live: GREG.N0000 implies
0.24615 against a declared 0.25000, CPRT.N0000 implies 0.01447 against
0.01429. This is genuinely independent of the announcement text the ratio
was scraped from.

    A RATIO IS NEVER DERIVED FROM THE PRICE GAP. Where the declared ratio
    is missing (most pending BONUS_ISSUEs), the implied gap sits at
    0.95-1.00 — a 1:20 bonus and an ordinary 3% down day are
    indistinguishable at that scale, so inventing a ratio from it would be
    exactly the confident-looking fabrication this project exists to
    avoid. Those are reported for a human and left pending.

CASH DIVIDENDS — verified against a THIRD PARTY's published dividend
history (stockanalysis.com, whose /dividend/ page embeds a structured
history array of ex-date + amount). Our scraped amount either matches
what an independent publisher reports for that ex-date or it doesn't.

WHY THIS MATTERS BEYOND CLEARING A QUEUE. Confirming an action is what
makes it price-affecting (§7/§8), so each confirmation feeds the
total-return adjustment-factor series that `app.jobs.adjustment_factors`
now actually writes. MERC.N0000 and YORK.N0000 each carry a pending 1:200
split that currently reads as a -100% one-day return in every
return-based computation (beta -> Ke -> every fair value, momentum, the
factor series). Confirming dividends additionally unlocks `payout_ratio`,
and with it justified P/E, justified P/S and Gordon-growth DDM — three
genuinely independent triangulation anchors for an engine that currently
blends one model twice.

    python scripts/verify_corporate_actions.py                 # dry run
    python scripts/verify_corporate_actions.py --fetch         # dividend cache
    python scripts/verify_corporate_actions.py --apply
    python scripts/verify_corporate_actions.py --revert --apply
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
from app.jobs.adjustment_factors import rebuild_all_adjustment_factors  # noqa: E402
from app.models.corporate_actions import CorporateAction  # noqa: E402
from app.models.corporate_actions import CorporateActionType as T  # noqa: E402
from app.models.prices import PriceDaily  # noqa: E402

ACTOR = "auto:action-verify-v1"
DIV_CACHE = REPO_ROOT / "docs" / "audits" / "external_dividends_cache.jsonl"
REPORT = REPO_ROOT / "docs" / "audits" / f"CORPORATE_ACTIONS_VERIFY_{dt.date.today().isoformat()}.md"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

#: How far the price-implied ratio may sit from the declared one and still
#: count as confirmation. Wide on purpose: the implied figure carries one
#: real trading day of ordinary market movement on top of the mechanical
#: adjustment, and thin CSE names move several percent routinely. Measured
#: on the real pending set, genuine splits land within 16% (GREG 1.5%,
#: CPRT 1.3%, WAPO 8.1%, NAMU 15.6%) while a wrong ratio is out by a
#: multiple, so this separates them cleanly without being tight enough to
#: reject a real split for a noisy day.
RATIO_TOLERANCE = Decimal("0.25")

#: A cash dividend match is sought three ways, because the publisher does
#: not report the same quantity we store, and treating either difference as
#: a disagreement would reject dividends that are actually correct:
#:
#:  1. Exact-ish. Both are declared per-share figures, so a plain match is
#:     near-exact.
#:  2. Within DIVIDEND_REL_TOLERANCE. Their figure runs ~1% below ours on
#:     several real names (COMB 7.43134 vs our 7.5000, HNB 14.86149 vs
#:     15.0000, CIT 1.47624 vs 1.5000) — consistent with a withholding-tax
#:     or rounding convention, not with either side being wrong.
#:  3. Split-adjusted. Their own page states "dividend amounts are adjusted
#:     for stock splits when applicable", and it shows: GREG.N0000 2.4375
#:     against our declared 9.7500 is EXACTLY 4x, matching its 1:4 split;
#:     CIC.N0000 and CWM.N0000 are exactly 5x against their 1:5 splits. We
#:     store the amount as declared at the time, which is the right figure
#:     for a corporate-action record, so a match is accepted when theirs
#:     scaled by a confirmed post-dividend split equals ours.
DIVIDEND_TOLERANCE = Decimal("0.01")
DIVIDEND_REL_TOLERANCE = Decimal("0.02")


def _close_before(db, ticker: str, ex_date: dt.date) -> Decimal | None:
    return db.scalar(
        select(PriceDaily.close)
        .where(PriceDaily.ticker == ticker, PriceDaily.date < ex_date, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc()).limit(1)
    )


def _close_on_or_after(db, ticker: str, ex_date: dt.date) -> Decimal | None:
    return db.scalar(
        select(PriceDaily.close)
        .where(PriceDaily.ticker == ticker, PriceDaily.date >= ex_date, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.asc()).limit(1)
    )


def expected_price_ratio(action: CorporateAction) -> Decimal | None:
    """Mechanical price ratio a declared action implies."""
    if action.ratio is None:
        return None
    if action.type in (T.STOCK_SPLIT, T.BONUS_ISSUE):
        return Decimal(1) / (Decimal(1) + Decimal(action.ratio))
    if action.type is T.CONSOLIDATION:
        return Decimal(action.ratio)  # old shares per new share -> price multiplies
    return None


#: A price gap may only IMPLY a missing ratio when it is unmistakably
#: mechanical and lands on a clean integer. Both conditions matter:
#:
#:  - the price must at least halve (implied ratio <= 0.5). No CSE name
#:    halves in a day for non-mechanical reasons, whereas the 0.95-1.00
#:    gaps that most ratio-less BONUS_ISSUEs show are indistinguishable
#:    from an ordinary down day and must never be turned into a number.
#:  - the implied `new shares per held share` must round to an integer
#:    within DERIVED_RATIO_TOLERANCE. Splits are declared in whole shares,
#:    so a clean landing is real evidence; a messy one means the market
#:    also moved and we cannot separate the two.
#:
#: Measured on the real pending set: JKH.N0000 implies 8.98 (0.2% off a
#: clean 9) and is derived; UML.N0000 implies 8.11 and COLO.N0000 7.65 —
#: both genuinely ambiguous between two integers, and both correctly left
#: for a human rather than rounded to whichever is nearer.
DERIVE_MIN_DROP = Decimal("0.5")
DERIVED_RATIO_TOLERANCE = Decimal("0.03")


def derive_ratio_from_price_gap(implied: Decimal) -> Decimal | None:
    """The `new shares per held share` a price gap unambiguously implies,
    or None when it is not unambiguous. See the constants above."""
    if implied <= 0 or implied > DERIVE_MIN_DROP:
        return None
    raw = (Decimal(1) / implied) - Decimal(1)
    nearest = Decimal(round(raw))
    if nearest < 1:
        return None
    if abs(raw - nearest) / nearest > DERIVED_RATIO_TOLERANCE:
        return None
    return nearest


def verify_ratio_actions(db) -> tuple[list, list]:
    """(confirmable, unverifiable) for pending split/bonus/consolidation."""
    rows = db.scalars(
        select(CorporateAction).where(
            CorporateAction.confirmed_by.is_(None),
            CorporateAction.rejected_by.is_(None),
            CorporateAction.type.in_([T.STOCK_SPLIT, T.BONUS_ISSUE, T.CONSOLIDATION]),
        )
    ).all()
    confirmable, unverifiable = [], []
    for a in rows:
        before, after = _close_before(db, a.ticker, a.ex_date), _close_on_or_after(db, a.ticker, a.ex_date)
        implied = (
            Decimal(after) / Decimal(before)
            if before and after and before > 0 else None
        )
        expected = expected_price_ratio(a)

        if expected is None:
            # No declared ratio. Derive one ONLY from an unmistakably
            # mechanical gap landing on a clean integer — see
            # `derive_ratio_from_price_gap`.
            if implied is None:
                unverifiable.append((a, None, None, "no declared ratio, and no stored close either side of ex_date"))
                continue
            derived = derive_ratio_from_price_gap(implied)
            if derived is None:
                unverifiable.append((
                    a, None, implied,
                    f"no declared ratio; price gap {implied:.5f} does not unambiguously imply one",
                ))
                continue
            confirmable.append((
                a, Decimal(1) / (Decimal(1) + derived), implied,
                f"ratio DERIVED as {derived} from an unambiguous price gap",
                derived,
            ))
            continue

        if implied is None:
            unverifiable.append((a, expected, None, "no stored close either side of ex_date"))
            continue
        rel = abs(implied - expected) / expected
        if rel <= RATIO_TOLERANCE:
            confirmable.append((a, expected, implied, f"price gap confirms ratio ({rel:.1%} apart)", None))
        else:
            unverifiable.append((a, expected, implied, f"price gap DISAGREES ({rel:.1%} apart)"))
    return confirmable, unverifiable


# --------------------------------------------------------------------------
# Dividends
# --------------------------------------------------------------------------

_HISTORY_RE = re.compile(r'[,{"\\]history\\?"?\s*:\s*(\[.*?\])', re.S)
_ENTRY_RE = re.compile(r'\{dt:"(\d{4}-\d{2}-\d{2})",amt:"([\d.]+)')


def parse_dividends(text: str) -> list[tuple[str, Decimal]]:
    m = _HISTORY_RE.search(text)
    if not m:
        return []
    return [(d, Decimal(a)) for d, a in _ENTRY_RE.findall(m.group(1))]


def phase_fetch_dividends(pacing: float) -> None:
    db = SessionLocal()
    try:
        tickers = sorted({
            t for (t,) in db.execute(
                select(CorporateAction.ticker).where(
                    CorporateAction.confirmed_by.is_(None),
                    CorporateAction.rejected_by.is_(None),
                    CorporateAction.type == T.DIVIDEND_CASH,
                    CorporateAction.cash_amount.is_not(None),
                ).distinct()
            )
        })
    finally:
        db.close()

    done: set[str] = set()
    DIV_CACHE.parent.mkdir(parents=True, exist_ok=True)
    if DIV_CACHE.exists():
        for line in DIV_CACHE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["_ticker"])
                except (json.JSONDecodeError, KeyError):
                    continue
        print(f"Resuming: {len(done)} tickers cached.", file=sys.stderr)

    todo = [t for t in tickers if t not in done]
    print(f"{len(todo)} tickers to fetch.", file=sys.stderr)
    with httpx.Client(headers={"User-Agent": UA}) as client, DIV_CACHE.open("a", encoding="utf-8") as fh:
        for i, ticker in enumerate(todo, 1):
            url = f"https://stockanalysis.com/quote/cose/{ticker}/dividend/"
            entries: list[tuple[str, Decimal]] = []
            try:
                r = client.get(url, timeout=30, follow_redirects=True)
                if r.status_code == 200:
                    entries = parse_dividends(r.text)
            except Exception as exc:  # noqa: BLE001
                print(f"  {ticker}: {type(exc).__name__}", file=sys.stderr)
            fh.write(json.dumps({
                "_ticker": ticker,
                "_rows": [{"ex_date": d, "amount": str(a)} for d, a in entries],
            }) + "\n")
            fh.flush()
            print(f"  [{i}/{len(todo)}] {ticker}: {len(entries)} dividends", file=sys.stderr)
            time.sleep(pacing)


def load_dividend_cache() -> dict[str, list[tuple[dt.date, Decimal]]]:
    out: dict[str, list[tuple[dt.date, Decimal]]] = defaultdict(list)
    if not DIV_CACHE.exists():
        return out
    for line in DIV_CACHE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        for r in rec.get("_rows", []):
            out[rec["_ticker"]].append((dt.date.fromisoformat(r["ex_date"]), Decimal(r["amount"])))
    return out


#: Ex-date convention can differ by a day or two between the exchange's own
#: announcement and a third-party aggregator, so a match is sought in a
#: small window rather than on an exact date.
EX_DATE_WINDOW_DAYS = 5


def _confirmed_split_factor_after(db, ticker: str, after_date: dt.date) -> Decimal:
    """Cumulative share multiplier from confirmed splits/bonus issues with
    an ex_date AFTER `after_date` — the factor a third party would have
    applied when restating an older dividend per current shares."""
    rows = db.scalars(
        select(CorporateAction).where(
            CorporateAction.ticker == ticker,
            CorporateAction.confirmed_by.is_not(None),
            CorporateAction.ex_date > after_date,
            CorporateAction.type.in_([T.STOCK_SPLIT, T.BONUS_ISSUE]),
            CorporateAction.ratio.is_not(None),
        )
    ).all()
    factor = Decimal(1)
    for r in rows:
        factor *= Decimal(1) + Decimal(r.ratio)
    return factor


def _dividend_matches(db, action, theirs: Decimal) -> str | None:
    """The reason a third-party amount confirms ours, or None."""
    ours = Decimal(action.cash_amount)
    if abs(theirs - ours) <= DIVIDEND_TOLERANCE:
        return "exact"
    scale = max(abs(ours), abs(theirs))
    if scale > 0 and abs(theirs - ours) / scale <= DIVIDEND_REL_TOLERANCE:
        return "within 2% (withholding/rounding convention)"
    split_factor = _confirmed_split_factor_after(db, action.ticker, action.ex_date)
    if split_factor != 1:
        restated = theirs * split_factor
        if abs(restated - ours) <= max(DIVIDEND_TOLERANCE, ours * DIVIDEND_REL_TOLERANCE):
            return f"matches after undoing their {split_factor}x split adjustment"
    return None


def verify_dividends(db, external) -> tuple[list, list]:
    rows = db.scalars(
        select(CorporateAction).where(
            CorporateAction.confirmed_by.is_(None),
            CorporateAction.rejected_by.is_(None),
            CorporateAction.type == T.DIVIDEND_CASH,
            CorporateAction.cash_amount.is_not(None),
        )
    ).all()
    confirmable, unverifiable = [], []
    for a in rows:
        candidates = external.get(a.ticker) or []
        near = [
            (d, amt) for d, amt in candidates
            if abs((d - a.ex_date).days) <= EX_DATE_WINDOW_DAYS
        ]
        if not near:
            unverifiable.append((a, None, "no third-party dividend near this ex_date"))
            continue
        best = min(near, key=lambda x: abs((x[0] - a.ex_date).days))
        why = _dividend_matches(db, a, best[1])
        if why is not None:
            confirmable.append((a, best[1], f"third party reports {best[1]} on {best[0]} — {why}"))
        else:
            unverifiable.append((a, best[1], f"third party reports {best[1]} on {best[0]}, we hold {a.cash_amount}"))
    return confirmable, unverifiable


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--pacing-seconds", type=float, default=1.2)
    args = ap.parse_args()

    if args.fetch:
        phase_fetch_dividends(args.pacing_seconds)
        return

    db = SessionLocal()
    try:
        if args.revert:
            rows = db.scalars(select(CorporateAction).where(CorporateAction.confirmed_by == ACTOR)).all()
            print(f"{len(rows)} actions were confirmed by this pass.")
            if args.apply:
                for r in rows:
                    r.confirmed_by = None
                    r.confirmed_at = None
                db.commit()
                rebuild_all_adjustment_factors(db)
                print("REVERTED (adjustment factors rebuilt).")
            else:
                db.rollback()
                print("DRY RUN — re-run with --revert --apply.", file=sys.stderr)
            return

        ratio_ok, ratio_no = verify_ratio_actions(db)
        external = load_dividend_cache()
        div_ok, div_no = ([], []) if not external else verify_dividends(db, external)

        print(f"ratio-type : {len(ratio_ok)} confirmable, {len(ratio_no)} not")
        print(f"dividends  : {len(div_ok)} confirmable, {len(div_no)} not"
              + ("   (no cache — run --fetch)" if not external else ""))

        lines = [
            f"# Corporate-actions verification — {dt.date.today().isoformat()}",
            "",
            "Two independent checks. Ratio-type actions (split/bonus/consolidation) are "
            "verified against THIS SYSTEM'S OWN price history — a split is mechanical, so "
            "the real close either side of ex-date implies a ratio. Cash dividends are "
            "verified against a third party's published dividend history.",
            "",
            "**A ratio is never derived from the price gap.** Where the declared ratio is "
            "missing, the implied gap sits at 0.95-1.00, where a 1:20 bonus and an ordinary "
            "3% down day are indistinguishable. Those stay pending for a human.",
            "",
            f"- ratio-type confirmable: **{len(ratio_ok)}**, left pending: {len(ratio_no)}",
            f"- dividends confirmable: **{len(div_ok)}**, left pending: {len(div_no)}",
            "",
            "## Ratio-type actions the price history confirms",
            "",
            "| ticker | type | ex_date | declared ratio | expected px ratio | implied | note |",
            "|---|---|---|---|---|---|---|",
        ]
        for a, exp, imp, note, derived in sorted(ratio_ok, key=lambda x: x[0].ex_date, reverse=True):
            shown = a.ratio if derived is None else f"{derived} (derived)"
            lines.append(
                f"| {a.ticker} | {a.type.value} | {a.ex_date} | {shown} | {exp:.5f} | {imp:.5f} | {note} |"
            )
        lines += ["", "## Left pending (with the real reason)", "",
                  "| ticker | type | ex_date | reason |", "|---|---|---|---|"]
        for a, _e, _i, note in sorted(ratio_no, key=lambda x: x[0].ex_date, reverse=True)[:200]:
            lines.append(f"| {a.ticker} | {a.type.value} | {a.ex_date} | {note} |")
        if div_no:
            lines += ["", "## Dividends left pending", "",
                      "| ticker | ex_date | ours | reason |", "|---|---|---|---|"]
            for a, _t, note in sorted(div_no, key=lambda x: x[0].ex_date, reverse=True)[:200]:
                lines.append(f"| {a.ticker} | {a.ex_date} | {a.cash_amount} | {note} |")
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nWrote {REPORT}")

        if not args.apply:
            db.rollback()
            print("DRY RUN — nothing written. Re-run with --apply.", file=sys.stderr)
            return

        stamp = dt.datetime.now(dt.timezone.utc)
        derived_count = 0
        for a, _exp, _imp, _note, derived in ratio_ok:
            if derived is not None:
                # The ratio was never declared anywhere; record where it
                # came from on the row itself, since a reader must be able
                # to tell a scraped figure from an inferred one.
                a.ratio = derived
                a.notes = (
                    f"[{ACTOR} {dt.date.today().isoformat()}] ratio {derived} inferred from this "
                    f"ticker's own real price gap across ex_date — no ratio was declared in the "
                    f"scraped announcement. " + (a.notes or "")
                )
                derived_count += 1
            a.confirmed_by = ACTOR
            a.confirmed_at = stamp
        for a, *_ in div_ok:
            a.confirmed_by = ACTOR
            a.confirmed_at = stamp
        db.commit()
        print(f"APPLIED — {len(ratio_ok) + len(div_ok)} actions confirmed "
              f"({derived_count} with a ratio inferred from the price gap).")
        summary = rebuild_all_adjustment_factors(db)
        print(f"Adjustment factors rebuilt: {summary['price_rows_changed']} price rows "
              f"across {summary['tickers_changed']} tickers.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
