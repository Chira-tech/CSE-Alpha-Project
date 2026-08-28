"""
Operator CLI. Run with `python -m app.cli <command>`.

Kept deliberately small — these are the operations a human needs to run by
hand (first-time setup, manual ingestion triggers). Everything recurring
belongs in the scheduler (§52), not here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from decimal import Decimal

from app.config import settings
from app.db.session import SessionLocal
from app.domain.macro import SERIES_TBILL_364D
from app.domain.macro_view import current_spread, record_observation
from app.ingestion.bootstrap import run_bootstrap
from app.ingestion.cbsl_client import CbslClient
from app.ingestion.cbsl_loader import ingest_range
from app.ingestion.index_history_loader import ingest_index_history
from app.ingestion.archetype_loader import apply_archetype_proposals
from app.jobs.second_source_reconciliation import StaleComparisonError, check_against_second_source
from app.ingestion.company_price_history_loader import backfill_company_price_history
from app.ingestion.financial_reports_archive_loader import ingest_report_archive_for_ticker
from app.ingestion.financial_pdf_extractor import sweep_stale_fundamentals
from app.ingestion.issuer_registry_loader import ingest_issuer_registry
from app.ingestion.sector_loader import ingest_sectors
from app.ingestion.market_internals import ingest_market_internals
from app.ingestion.corporate_actions_loader import (
    ingest_corporate_actions_for_ticker,
    recently_scanned_tickers,
)
from app.ingestion.cse_client import CseClient
from app.ingestion.security_enrichment import enrich_securities
from app.models.securities import Security
from sqlalchemy import select


def _configure_logging() -> None:
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Populate securities + latest prices from the live CSE API."""
    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else None
    db = SessionLocal()
    try:
        result = run_bootstrap(db, as_of)
    finally:
        db.close()
    print(
        f"Bootstrap complete: {result['securities_inserted']} new securities "
        f"({result['securities_already_known']} already known), "
        f"{result['price_rows']} price rows written for session {result['session_date']}."
    )
    return 0


def cmd_ingest_corporate_actions(args: argparse.Namespace) -> int:
    """Scrape corporate-action announcements into the confirm queue.

    Every ticker means ~283 companies x at least 1 request each, paced at
    >=2s (§5) — that's 10+ minutes minimum, longer with detail lookups.
    `--limit` exists so a first run can be sanity-checked on a handful of
    names before committing to the full sweep.

    RESUMABLE ACROSS INTERRUPTED RUNS BY DEFAULT. A real, structural gap
    found live (18 Aug 2026): every invocation used to restart from
    ticker #1 in alphabetical order, with no memory of a previous run —
    so an environment that kills a long-running process a few minutes
    in (observed repeatedly, real and reproducible, independent of this
    specific command) meant a full sweep could NEVER progress past
    whatever a single few-minute window covered, no matter how many
    times it was retried. `CorporateActionScanLog` (see its own
    docstring) now records a real scan timestamp per ticker regardless
    of outcome, and a full sweep (no `--ticker` given) skips anything
    scanned within the last `--rescan-after-hours` (default 20, just
    under §52's own real daily production cadence, so a normal
    scheduled run is never accidentally skipped) — pass `--force` to
    scan everything regardless. An explicit `--ticker` always runs,
    recency aside — a human asking about one specific company should
    never be silently skipped.
    """
    db = SessionLocal()
    try:
        tickers = [t for (t,) in db.execute(select(Security.ticker).order_by(Security.ticker)).all()]
        if not tickers:
            print("No matching tickers. Run `bootstrap` first?", file=sys.stderr)
            return 1
        if args.ticker:
            tickers = [t for t in tickers if t in set(args.ticker)]
        elif not args.force:
            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=args.rescan_after_hours)
            already_done = recently_scanned_tickers(db, cutoff)
            skipped = len(already_done)
            tickers = [t for t in tickers if t not in already_done]
            if skipped:
                print(
                    f"Skipping {skipped} ticker(s) scanned within the last {args.rescan_after_hours}h "
                    "(resuming a sweep, not restarting it — pass --force to rescan everything)."
                )
        if args.limit:
            tickers = tickers[: args.limit]
        if not tickers:
            print("Nothing left to scan — every ticker was already covered within the rescan window.")
            return 0

        print(f"Scanning {len(tickers)} ticker(s) — paced at >={settings.cse_min_seconds_between_calls}s/request.")
        total = 0
        with CseClient() as client:
            for ticker in tickers:
                try:
                    drafted = ingest_corporate_actions_for_ticker(client, db, ticker)
                    total += drafted
                    if drafted:
                        print(f"  {ticker}: {drafted} new draft(s)")
                except Exception as exc:  # noqa: BLE001 — one bad ticker must not abort the sweep
                    print(f"  {ticker}: FAILED ({exc})", file=sys.stderr)
        print(f"Done. {total} draft(s) awaiting review at /corporate-actions.")
    finally:
        db.close()
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    """Fill ISIN / listing date / shares issued from companyInfoSummery.

    One request per company at >=2s pacing (§5), so a full sweep of ~283
    names is roughly 10 minutes. `--limit` exists to sanity-check a few
    first.
    """
    db = SessionLocal()
    try:
        tickers = [t for (t,) in db.execute(select(Security.ticker).order_by(Security.ticker)).all()]
        if args.ticker:
            tickers = [t for t in tickers if t in set(args.ticker)]
        if args.limit:
            tickers = tickers[: args.limit]
        if not tickers:
            print("No matching tickers. Run `bootstrap` first?", file=sys.stderr)
            return 1

        est = len(tickers) * settings.cse_min_seconds_between_calls / 60
        print(f"Enriching {len(tickers)} ticker(s) — roughly {est:.0f} min at the configured pacing.")
        with CseClient() as client:
            result = enrich_securities(client, db, tickers)
        print(
            f"Done. {result['enriched']} updated, {result['skipped']} already complete or empty, "
            f"{result['failed']} failed."
        )
        print(
            "Note: this command does not touch cse_sector or archetype. Run `sectors` for the "
            "exchange's own GICS classification and `archetypes` to propose §16 valuation "
            "archetypes from it (Appendix P2 — every proposal still needs a human)."
        )
    finally:
        db.close()
    return 0


def cmd_capture_market(args: argparse.Namespace) -> int:
    """Store the day's market internals (P/E, PBV, DY, ASPI, turnover,
    foreign flow) into macro_series."""
    db = SessionLocal()
    try:
        with CseClient() as client:
            written = ingest_market_internals(client, db)
        print(f"Wrote {written} new macro observation(s).")
    finally:
        db.close()
    return 0


def cmd_backfill_index(args: argparse.Namespace) -> int:
    """Backfill ~1 year of ASPI closes from `chartData`.

    The only genuine historical series on the public CSE API, and index-
    only — this does not give per-company price history.
    """
    db = SessionLocal()
    try:
        with CseClient() as client:
            written = ingest_index_history(client, db)
        print(f"Wrote {written} new ASPI close(s).")
        if not written:
            print("Nothing new — the series was already complete.")
    finally:
        db.close()
    return 0


def cmd_archetypes(args: argparse.Namespace) -> int:
    """Propose §16 valuation archetypes from the GICS classification
    (`app.domain.archetype`). NOT a substitute for the Appendix P2 review
    exercise — every proposal should be checked, and anything flagged
    "needs review" (mostly diversified conglomerates GICS misclassifies)
    was deliberately left for a human rather than guessed."""
    db = SessionLocal()
    try:
        summary = apply_archetype_proposals(db, overwrite_manual=args.overwrite_manual)
        print(
            f"Proposed {summary['proposed']} archetype(s); "
            f"{summary['classified']} of {summary['securities']} securities now classified."
        )
        if summary["skipped_manual"]:
            print(f"  {summary['skipped_manual']} left alone (hand-set already).")
        review = summary["needs_review"]
        if review:
            print(f"  {len(review)} need a human — this is the Appendix P2 exercise, not a bug:")
            for ticker, reason in review[: args.show_review]:
                print(f"    {ticker:14} {reason}")
            if len(review) > args.show_review:
                print(f"    ... and {len(review) - args.show_review} more (--show-review to see more)")
    finally:
        db.close()
    return 0


def cmd_second_source_check(args: argparse.Namespace) -> int:
    """Cross-check today's captured closes against TradingView (Part II
    §5.2) — the first genuinely external second source in this system,
    distinct from the internal adj_factor reconciliation. TradingView
    carries a live quote only, no history, so this can ONLY compare
    today's date — `--date` exists for explicitness, not to backdate."""
    db = SessionLocal()
    try:
        as_of = args.date or dt.date.today()
        tickers = [t for (t,) in db.execute(select(Security.ticker)).all()]
        try:
            summary = check_against_second_source(db, tickers, as_of=as_of)
        except StaleComparisonError as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 1
        print(
            f"Checked {summary['checked']} ticker(s) with a stored close for {as_of}: "
            f"{summary['matched']} matched, {summary['mismatched']} mismatched."
        )
        if summary["mismatched"]:
            print(f"  {summary['mismatched']} ticker(s) newly quarantined — see data_alerts.")
        if summary["no_quote"]:
            print(f"  {summary['no_quote']} had no TradingView coverage (not a mismatch).")
    finally:
        db.close()
    return 0


def cmd_backfill_financials(args: argparse.Namespace) -> int:
    """Backfill each company's financial-statement history from
    /api/financials — annual and quarterly filings, years deeper than
    `financial-statement-scan`'s single most-recent filing per company.

    One request to list the archive plus one download per PDF, all
    through the paced CseClient (§5) — a single company with a long
    history (e.g. COMB.N0000: 16 annual + 59 quarterly reports) is
    75+ requests on its own, so a FULL-DEPTH universe sweep (no
    `--recent`) genuinely takes hours and, run alphabetically, can spend
    an entire run on the first few filing-heavy companies before
    reaching the rest. `--recent N` switches to breadth-first — the N
    most recent filings of each type per ticker — so a universe-wide
    pass reaches every company's current period first; a later,
    separate full-depth pass still backfills the rest without redoing
    anything (idempotent on the exact PDF URL). Every draft still lands
    in the confirm queue (§8) exactly like the single-filing scan;
    nothing here is auto-promoted to Reported.

    `--reconcile` — for when a parser fix or a new canonical-label alias
    needs to reach filings ingested BEFORE it existed. The ordinary
    (non-reconcile) run above skips a filing outright once it has ANY
    row on file, however incomplete that extraction was — see
    `ingest_archived_report`'s own docstring for why, and for the
    guarantee that matters most here: reconcile mode only ever ADDS a
    statement line genuinely missing from a filing's existing rows, and
    NEVER touches, replaces, or deletes one already there, confirmed or
    not. Costs the same request budget as a fresh run — every filing is
    still re-downloaded and re-parsed, since there's no cheaper way to
    find out whether anything new is now extractable from it.
    """
    db = SessionLocal()
    try:
        tickers = [t for (t,) in db.execute(select(Security.ticker).order_by(Security.ticker)).all()]
        if args.ticker:
            tickers = [t for t in tickers if t in set(args.ticker)]
        if args.after:
            # A real, measured inefficiency, not a hypothetical one: this
            # command is idempotent, so a KILLED/resumed run always
            # RE-VERIFIES every already-processed ticker alphabetically
            # before reaching new ground — cheap per ticker (one archive
            # listing request) but linear in how many tickers are already
            # done, so it keeps eating a growing share of each restart's
            # own time budget the further the backfill progresses.
            # --after skips that re-verification outright by starting the
            # ticker list past a known-done point.
            tickers = [t for t in tickers if t > args.after]
        if args.limit:
            tickers = tickers[: args.limit]
        if not tickers:
            print("No matching tickers. Run `bootstrap` first?", file=sys.stderr)
            return 1

        depth = f"the {args.recent} most recent filing(s) per period_type" if args.recent else "full history"
        print(f"Backfilling financial statement history for {len(tickers)} ticker(s) — {depth}.")
        totals = {"drafted": 0, "unavailable": 0, "failed": 0}
        with CseClient() as client:
            for ticker in tickers:
                try:
                    summary = ingest_report_archive_for_ticker(
                        client, db, ticker, max_per_type=args.recent, reconcile=args.reconcile
                    )
                except Exception as exc:  # noqa: BLE001 — one bad ticker must not abort the sweep
                    print(f"  {ticker}: FAILED ({exc})", file=sys.stderr)
                    continue
                for k in totals:
                    totals[k] += summary[k]
                if summary["drafted"]:
                    print(
                        f"  {ticker}: {summary['drafted']} new draft(s), "
                        f"{summary['unavailable']} unavailable, {summary['failed']} failed"
                    )
        print(
            f"Done. {totals['drafted']} draft(s) awaiting review at /fundamentals. "
            f"{totals['unavailable']} filing(s) listed but not retrievable from the CDN "
            f"even after the cmt/ normalization, {totals['failed']} genuine failures."
        )
    finally:
        db.close()
    return 0


def cmd_refresh_stale_fundamentals(args: argparse.Namespace) -> int:
    """For each given ticker, find every (period_end, period_type) filing
    whose CURRENTLY STORED fundamentals fail `check_extraction_quality`
    (an accounting identity, or the magnitude-plausibility floor),
    re-download that filing's PDF, and re-run today's extractor against
    it — repairing any row a since-fixed extraction bug left wrong
    (`app.ingestion.financial_pdf_extractor.refresh_stale_fundamentals`'s
    own docstring has the real cases this exists for: HNB.N0000/X0000,
    CALH.N0000, COCR.N0000). `backfill-financials` itself will never
    revisit these on its own — it treats "a filing already has stored
    rows" as done, no matter how wrong they are.

    Only ever touches still-unconfirmed AI-assisted rows; a fresh
    extraction that still doesn't balance changes nothing and is reported
    as such, not silently retried or forced in. Thin wrapper around
    `app.ingestion.financial_pdf_extractor.sweep_stale_fundamentals` —
    all the real logic (and the same sweep `app.jobs.runner`'s scheduled
    job runs) lives there; this command just prints it.
    """
    db = SessionLocal()
    try:
        tickers = [t for (t,) in db.execute(select(Security.ticker).order_by(Security.ticker)).all()]
        if args.ticker:
            tickers = [t for t in tickers if t in set(args.ticker)]
        if not tickers:
            print("No matching tickers.", file=sys.stderr)
            return 1

        def on_filing(i: int, total: int, label: str) -> None:
            print(f"  [{i}/{total}] checking {label}...", file=sys.stderr)

        outcomes = sweep_stale_fundamentals(db, tickers, on_filing=on_filing)
        totals = {"repaired": 0, "still_failing": 0, "no_source": 0, "error": 0}
        for o in outcomes:
            if o.status == "repaired":
                print(f"  {o.ticker} {o.period_end} {o.period_type}: repaired {list(o.updated_lines)}")
            elif o.status == "still_failing":
                print(f"  {o.ticker} {o.period_end} {o.period_type}: still fails after re-extraction — {o.detail}")
            elif o.status == "no_source":
                print(f"  {o.ticker} {o.period_end} {o.period_type}: no source_url stored, cannot refresh")
            elif o.status == "error":
                print(f"  {o.ticker} {o.period_end} {o.period_type}: FAILED ({o.detail})", file=sys.stderr)
            else:
                print(f"  {o.ticker} {o.period_end} {o.period_type}: {o.detail}")
            if o.status in totals:
                totals[o.status] += 1
        print(
            f"Done. {len(outcomes)} filing(s) currently fail an accounting identity or magnitude check; "
            f"{totals['repaired']} repaired, {totals['still_failing']} still fail after "
            f"re-extraction, {totals['no_source']} had no stored source_url, {totals['error']} errored."
        )
    finally:
        db.close()
    return 0


def cmd_auto_confirm_fundamentals(args: argparse.Namespace) -> int:
    """One-time mathematical cross-check of the AI-assisted confirm queue
    (§8). Scores every pending row against independent signals — the
    accounting-identity web, a fresh re-extraction of the source PDF,
    cross-source agreement, annual/quarterly reconciliation, dual-listing
    agreement — and auto-confirms only rows with >=2 signals (one of them
    the re-extraction) and zero vetoes. See `app.domain.fundamental_
    cross_check` for the full battery.

    Dry-run by default: writes docs/audits/AUTO_CONFIRM_<date>.md and
    changes nothing. `--apply` promotes the auto-confirmable rows to
    REPORTED with confirmed_by="auto:cross-check-v1 [...]" and writes a
    confidence band into every other pending row's source_snippet.
    `scripts/revert_auto_confirm.py` undoes the whole pass.
    """
    import json as _json
    from pathlib import Path

    from app.domain.fundamental_cross_check_view import cross_check_all
    from app.models.enums import ProvenanceTier
    from app.models.fundamentals import Fundamental

    if args.no_reextract and args.apply:
        print(
            "--no-reextract cannot be combined with --apply: re-extraction (S2) is "
            "required for auto-confirm. Drop --apply for a triage-only report.",
            file=sys.stderr,
        )
        return 1

    repo_root = Path(__file__).resolve().parents[2]
    out_path = repo_root / "docs" / "audits" / f"AUTO_CONFIRM_{dt.date.today().isoformat()}.md"
    # ".partial.jsonl" so it matches .gitignore's resumable-checkpoint rule
    checkpoint_path = out_path.parent / (out_path.stem + ".reextract.partial.jsonl")

    db = SessionLocal()
    verdicts = []
    try:
        def _progress(i: int, total: int, group) -> None:
            if i == 1 or i % 50 == 0 or i == total:
                print(f"  [{i}/{total}] {group.ticker} {group.period_end} {group.period_type}", file=sys.stderr)

        for v in cross_check_all(
            db,
            reextract=not args.no_reextract,
            user_agent=settings.cse_user_agent,
            checkpoint_path=checkpoint_path if not args.no_reextract else None,
            pacing_seconds=args.pacing_seconds,
            min_signals=args.min_signals,
            only_ticker=args.ticker,
            progress=_progress,
        ):
            verdicts.append(v)

        auto = [v for v in verdicts if v.auto_confirm]
        by_band: dict[str, int] = {}
        by_combo: dict[str, int] = {}
        by_line_auto: dict[str, int] = {}
        for v in verdicts:
            by_band[v.confidence] = by_band.get(v.confidence, 0) + 1
            by_combo[v.describe()] = by_combo.get(v.describe(), 0) + 1
            if v.auto_confirm:
                by_line_auto[v.statement_line] = by_line_auto.get(v.statement_line, 0) + 1

        lines = [
            f"# Auto-confirm cross-check — {dt.date.today().isoformat()}",
            "",
            f"Re-extraction: {'OFF (triage only)' if args.no_reextract else 'ON'}. "
            f"Min signals: {args.min_signals}. Scope: {args.ticker or 'whole queue'}.",
            "",
            f"**{len(verdicts)} pending rows scored. {len(auto)} auto-confirmable "
            f"({len(auto) * 100 // max(len(verdicts), 1)}%).**",
            "",
            "## By confidence band",
            "",
            "| band | rows |",
            "|---|---|",
        ]
        for band in ("auto-confirm", "high", "medium", "needs-review"):
            lines.append(f"| {band} | {by_band.get(band, 0)} |")
        lines += ["", "## Auto-confirm by statement line", "", "| line | rows |", "|---|---|"]
        for line, n in sorted(by_line_auto.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {line} | {n} |")
        lines += ["", "## Signal / veto combinations", "", "| combination | rows |", "|---|---|"]
        for combo, n in sorted(by_combo.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {combo} | {n} |")
        lines += [
            "",
            "## Every auto-confirmable row",
            "",
            "| ticker | line | period | type | value | signals |",
            "|---|---|---|---|---|---|",
        ]
        for v in sorted(auto, key=lambda v: (v.ticker, v.period_end, v.statement_line)):
            lines.append(
                f"| {v.ticker} | {v.statement_line} | {v.period_end} | {v.period_type} "
                f"| {v.value:,} | {'+'.join(sorted(v.signals))} |"
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nWrote {out_path}")
        print(f"{len(verdicts)} scored, {len(auto)} auto-confirmable, bands={by_band}")

        if not args.apply:
            print("DRY RUN — nothing written to the database. Re-run with --apply.")
            return 0

        confirmed = 0
        banded = 0
        stamp = dt.datetime.now(dt.timezone.utc)
        for v in verdicts:
            rows = db.scalars(
                select(Fundamental).where(
                    Fundamental.ticker == v.ticker,
                    Fundamental.period_end == dt.date.fromisoformat(v.period_end),
                    Fundamental.period_type == v.period_type,
                    Fundamental.statement_line == v.statement_line,
                    Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED,
                    Fundamental.value == v.value,
                )
            ).all()
            for row in rows:
                if v.auto_confirm:
                    sig = "+".join(sorted(v.signals))
                    row.provenance_tier = ProvenanceTier.REPORTED
                    row.confirmed_by = f"auto:cross-check-v1 [{sig}]"
                    row.confirmed_at = stamp
                    row.source_snippet = (
                        f"[AUTO-CONFIRM {dt.date.today().isoformat()}] machine cross-check "
                        f"passed on {sig} with no veto — promoted to REPORTED by "
                        f"`app.domain.fundamental_cross_check`. Revert: "
                        f"scripts/revert_auto_confirm.py.\n\n" + (row.source_snippet or "")
                    )
                    confirmed += 1
                else:
                    note = f"[cross-check {dt.date.today().isoformat()}: {v.confidence} — {v.describe()}]"
                    if not (row.source_snippet or "").startswith("[cross-check "):
                        row.source_snippet = note + " " + (row.source_snippet or "")
                        banded += 1
        db.commit()
        print(f"APPLIED — {confirmed} rows promoted to REPORTED, {banded} rows tagged with a confidence band.")
    finally:
        db.close()
    return 0


def cmd_backfill_prices(args: argparse.Namespace) -> int:
    """Backfill ~1 year of daily price history per company from
    companyChartDataByStock — fills gaps only, never touches a date
    already captured live, and never touches today (§6: the EOD job owns
    it). One request per line at >=2s pacing, so a full sweep is ~10 min.
    """
    db = SessionLocal()
    try:
        tickers = [t for (t,) in db.execute(select(Security.ticker).order_by(Security.ticker)).all()]
        if args.ticker:
            tickers = [t for t in tickers if t in set(args.ticker)]
        if args.limit:
            tickers = tickers[: args.limit]
        if not tickers:
            print("No matching tickers. Run `bootstrap` first?", file=sys.stderr)
            return 1

        est = len(tickers) * settings.cse_min_seconds_between_calls / 60
        print(f"Backfilling {len(tickers)} ticker(s) — roughly {est:.0f} min at the configured pacing.")
        with CseClient() as client:
            summary = backfill_company_price_history(client, db, tickers)
        print(
            f"Wrote {summary['rows_written']} price row(s) across {summary['tickers']} ticker(s)."
        )
        if summary["failed"]:
            print(f"  {summary['failed']} ticker(s) failed and can be retried by re-running.")
        if summary["no_stock_id"]:
            print(f"  {summary['no_stock_id']} ticker(s) had no stockId in allSecurityCode.")
    finally:
        db.close()
    return 0


def cmd_sectors(args: argparse.Namespace) -> int:
    """Classify securities into the GICS industry groups the exchange
    publishes (§12 sector-relative percentiles)."""
    db = SessionLocal()
    try:
        with CseClient() as client:
            s = ingest_sectors(client, db, overwrite_manual=args.overwrite_manual)
        print(
            f"Classified {s['classified']} of {s['securities']} securities "
            f"({s['updated']} updated, {s['unchanged']} already correct)."
        )
        if s["skipped_manual"]:
            print(
                f"  {s['skipped_manual']} left alone because they carry a hand-set "
                f"classification (pass --overwrite-manual to replace them)."
            )
        if s["unclassified"]:
            print(
                f"  {s['unclassified']} remain unclassified — the exchange's GICS "
                f"publication does not cover them."
            )
        print("  Archetype (§16) is NOT set by this command; it stays hand-maintained.")
    finally:
        db.close()
    return 0


def cmd_registry(args: argparse.Namespace) -> int:
    """Refresh the issuer registry (§7 survivorship)."""
    db = SessionLocal()
    try:
        with CseClient() as client:
            s = ingest_issuer_registry(client, db)
        print(
            f"Registry: {s['registry_issuers']} issuers known to the exchange "
            f"({s['inserted']} new, {s['updated']} refreshed)."
        )
        print(f"  {s['trading']} currently have a tradeable line.")
        print(f"  {s['delisted']} are flagged delisted by the exchange.")
        unknown = s["registry_issuers"] - s["trading"] - s["delisted"]
        print(
            f"  {unknown} are neither trading nor flagged — status genuinely unknown, "
            f"not assumed live."
        )
        if s["newly_delisted"]:
            print(f"  {s['newly_delisted']} newly flagged delisted since the last run.")
    finally:
        db.close()
    return 0


def cmd_record_macro(args: argparse.Namespace) -> int:
    """Record a macro observation by hand — for CBSL series until a
    scraper exists (their pages are JavaScript-rendered, so it's a real
    integration rather than a fetch).

    Rates are entered as percentages because that is how CBSL publishes
    them, and stored as decimal fractions because that is how every
    calculation consumes them. Doing that conversion once, here, is
    deliberate: a percentage leaking into a spread calculation produces a
    number wrong by 100x that still looks plausible.
    """
    value = Decimal(str(args.value))
    if args.percent:
        value = value / 100

    obs_date = dt.date.fromisoformat(args.date)
    available = dt.date.fromisoformat(args.available) if args.available else None

    db = SessionLocal()
    try:
        row = record_observation(
            db,
            series_id=args.series,
            obs_date=obs_date,
            value=value,
            first_available_date=available,
            source=args.source,
        )
        print(
            f"Recorded {row.series_id} = {row.value} (obs {row.obs_date}, "
            f"first available {row.first_available_date}, source '{row.source}')."
        )
        if args.percent:
            print(f"  Entered as {args.value}% and stored as the fraction {row.value}.")
    finally:
        db.close()
    return 0


def cmd_show_spread(args: argparse.Namespace) -> int:
    """§29's hero variable: equity earnings yield minus the 364-day
    T-bill yield."""
    db = SessionLocal()
    try:
        spread = current_spread(db)
        if spread is None:
            print(
                "Cannot compute the spread yet. It needs both:\n"
                "  - a market P/E   (run `capture-market`)\n"
                "  - a 364-day T-bill yield (run `record-macro --series cbsl.tbill_364d ...`)",
                file=sys.stderr,
            )
            return 1
        print(f"As at {spread.obs_date}")
        print(f"  Market P/E            {spread.market_per}")
        print(f"  Earnings yield        {spread.earnings_yield * 100:.2f}%")
        print(
            f"  364-day T-bill yield  {spread.tbill_yield * 100:.2f}%  "
            f"(obs {spread.tbill_obs_date}, source '{spread.tbill_source}')"
        )
        print(f"  SPREAD                {spread.spread * 100:+.2f}pp")
    finally:
        db.close()
    return 0


def cmd_cbsl(args: argparse.Namespace) -> int:
    """Ingest CBSL Daily Economic Indicators — the source for the
    risk-free rate, policy rate, inflation and FX (§29's variable set).

    Paced at CBSL's own published Crawl-delay of 10 seconds, so a long
    backfill genuinely takes a while. That is the site operator's
    request, not a tunable.
    """
    end = dt.date.fromisoformat(args.end) if args.end else dt.date.today()
    start = dt.date.fromisoformat(args.start) if args.start else end - dt.timedelta(days=args.days - 1)
    weekdays = sum(1 for i in range((end - start).days + 1)
                   if (start + dt.timedelta(days=i)).weekday() < 5)
    print(
        f"Ingesting CBSL editions {start} -> {end} ({weekdays} weekday(s)), "
        f"paced at {settings.cbsl_crawl_delay_seconds:.0f}s per robots.txt "
        f"— roughly {weekdays * settings.cbsl_crawl_delay_seconds / 60:.0f} min."
    )

    def progress(day, written, note):
        print(f"  {day}  " + (f"{written} observation(s)" if note is None else note))

    db = SessionLocal()
    try:
        with CbslClient() as client:
            result = ingest_range(client, db, start, end, on_progress=progress)
    finally:
        db.close()
    print(
        f"Done. {result['editions']} edition(s), {result['observations']} observation(s), "
        f"{result['not_published']} not published, {result['failed']} failed."
    )
    if result["unavailable"]:
        print(
            f"\n  {len(result['unavailable'])} date(s) could NOT be fetched and are of unknown "
            "status — this host 404s transiently, so these are not confirmed absent:"
        )
        for day in result["unavailable"]:
            print(f"    {day}")
        print("  Re-run the same command to retry them.")
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = argparse.ArgumentParser(prog="app.cli", description="CSE Alpha Engine operator commands")
    sub = parser.add_subparsers(dest="command", required=True)

    p_bootstrap = sub.add_parser("bootstrap", help="populate securities + latest prices from the live CSE API")
    p_bootstrap.add_argument(
        "--as-of",
        help=(
            "YYYY-MM-DD to stamp prices with. Defaults to the session date derived from the "
            "feed's own timestamps, which is almost always what you want — only override if "
            "you know the feed's timestamps are wrong."
        ),
    )
    p_bootstrap.set_defaults(func=cmd_bootstrap)

    p_ca = sub.add_parser("ingest-corporate-actions", help="scrape corporate actions into the confirm queue")
    p_ca.add_argument("--ticker", action="append", help="limit to specific ticker(s); repeatable")
    p_ca.add_argument("--limit", type=int, help="only process the first N tickers")
    p_ca.add_argument(
        "--rescan-after-hours", type=float, default=20.0,
        help="skip a ticker already scanned within this many hours, so an interrupted full sweep "
        "resumes instead of restarting from ticker #1 (default 20; ignored with --ticker)",
    )
    p_ca.add_argument(
        "--force", action="store_true",
        help="scan every ticker regardless of --rescan-after-hours",
    )
    p_ca.set_defaults(func=cmd_ingest_corporate_actions)

    p_en = sub.add_parser("enrich", help="fill ISIN / listing date / shares issued per company")
    p_en.add_argument("--ticker", action="append", help="limit to specific ticker(s); repeatable")
    p_en.add_argument("--limit", type=int, help="only process the first N tickers")
    p_en.set_defaults(func=cmd_enrich)

    p_cm = sub.add_parser("capture-market", help="store today's market internals into macro_series")
    p_cm.set_defaults(func=cmd_capture_market)

    p_at = sub.add_parser(
        "archetypes",
        help="propose §16 valuation archetypes from GICS (Appendix P2 — review every proposal)",
    )
    p_at.add_argument("--overwrite-manual", action="store_true")
    p_at.add_argument("--show-review", type=int, default=20)
    p_at.set_defaults(func=cmd_archetypes)

    p_ss = sub.add_parser(
        "second-source-check",
        help="cross-check today's closes against TradingView (Part II §5.2)",
    )
    p_ss.add_argument("--date", type=dt.date.fromisoformat, default=None)
    p_ss.set_defaults(func=cmd_second_source_check)

    p_bf = sub.add_parser(
        "backfill-financials",
        help="backfill each company's full financial-statement history from /api/financials",
    )
    p_bf.add_argument("--limit", type=int, default=None, help="only the first N tickers")
    p_bf.add_argument("--ticker", action="append", help="restrict to one or more tickers")
    p_bf.add_argument(
        "--recent", type=int, default=None,
        help=(
            "only the N most recent annual and N most recent quarterly filings per "
            "ticker (breadth-first: reaches every ticker's current period quickly "
            "instead of one company's full history at a time). Omit for full depth."
        ),
    )
    p_bf.add_argument(
        "--after", type=str, default=None,
        help=(
            "skip straight to tickers alphabetically after this one — for resuming "
            "an interrupted run without re-verifying everything already done "
            "(idempotency still applies even without this; it's purely a speed-up)."
        ),
    )
    p_bf.add_argument(
        "--reconcile", action="store_true",
        help=(
            "re-parse filings already on file too, adding any statement line a parser "
            "fix now extracts but the original pass missed — never touches, replaces, "
            "or deletes an existing row, confirmed or not. Costs the same request "
            "budget as a fresh run (every filing is re-downloaded and re-parsed)."
        ),
    )
    p_bf.set_defaults(func=cmd_backfill_financials)

    p_rs = sub.add_parser(
        "refresh-stale-fundamentals",
        help="re-extract filings whose stored fundamentals fail an accounting identity, "
        "repairing any that a since-fixed extraction bug left wrong",
    )
    p_rs.add_argument("--ticker", action="append", help="restrict to one or more tickers")
    p_rs.set_defaults(func=cmd_refresh_stale_fundamentals)

    p_ac = sub.add_parser(
        "auto-confirm-fundamentals",
        help="one-time mathematical cross-check of the confirm queue: auto-confirm every "
        "pending row provable from >=2 independent signals (identity web, re-extraction, "
        "cross-source, annual/quarterly, dual-listing) with no veto",
    )
    p_ac.add_argument("--ticker", type=str, default=None, help="scope to a single ticker")
    p_ac.add_argument(
        "--no-reextract", action="store_true",
        help="triage report only, from stored data — cannot be combined with --apply "
        "(re-extraction is required to auto-confirm)",
    )
    p_ac.add_argument("--min-signals", type=int, default=2, help="signals required to auto-confirm (default 2)")
    p_ac.add_argument("--pacing-seconds", type=float, default=2.0, help="delay between PDF re-downloads")
    p_ac.add_argument("--apply", action="store_true", help="write the confirmations to the database")
    p_ac.set_defaults(func=cmd_auto_confirm_fundamentals)

    p_bp = sub.add_parser(
        "backfill-prices",
        help="backfill ~1 year of daily price history per company (fills gaps only)",
    )
    p_bp.add_argument("--limit", type=int, default=None, help="only the first N tickers")
    p_bp.add_argument("--ticker", action="append", help="restrict to one or more tickers")
    p_bp.set_defaults(func=cmd_backfill_prices)

    p_sec = sub.add_parser(
        "sectors", help="classify securities into the exchange's GICS industry groups"
    )
    p_sec.add_argument(
        "--overwrite-manual",
        action="store_true",
        help="also replace classifications a human has set by hand",
    )
    p_sec.set_defaults(func=cmd_sectors)

    p_reg = sub.add_parser(
        "registry", help="refresh the issuer registry, including delisted names (§7)"
    )
    p_reg.set_defaults(func=cmd_registry)

    p_bi = sub.add_parser(
        "backfill-index", help="backfill ~1 year of ASPI closes from chartData (index only)"
    )
    p_bi.set_defaults(func=cmd_backfill_index)

    p_rm = sub.add_parser(
        "record-macro",
        help="record a macro observation by hand (CBSL series, until a scraper exists)",
    )
    p_rm.add_argument("--series", required=True, help=f"e.g. {SERIES_TBILL_364D}")
    p_rm.add_argument("--value", required=True, help="the observed figure")
    p_rm.add_argument("--date", required=True, help="observation date, YYYY-MM-DD")
    p_rm.add_argument(
        "--available",
        help=(
            "date the figure became public, YYYY-MM-DD. Defaults to the observation date, "
            "which is right for same-day releases like a T-bill auction but WRONG for lagged "
            "ones like CCPI — set it explicitly for those (§6)."
        ),
    )
    p_rm.add_argument(
        "--percent",
        action="store_true",
        help="value is a percentage (10.2) and should be stored as the fraction 0.102",
    )
    p_rm.add_argument("--source", default="manual", help="provenance note, default 'manual'")
    p_rm.set_defaults(func=cmd_record_macro)

    p_cb = sub.add_parser("cbsl", help="ingest CBSL daily economic indicators (T-bills, policy rate, CPI, FX)")
    p_cb.add_argument("--days", type=int, default=5, help="how many days back from --end (default 5)")
    p_cb.add_argument("--start", help="YYYY-MM-DD; overrides --days")
    p_cb.add_argument("--end", help="YYYY-MM-DD, default today")
    p_cb.set_defaults(func=cmd_cbsl)

    p_sp = sub.add_parser("spread", help="show the equity-earnings-yield-minus-T-bill spread (§29)")
    p_sp.set_defaults(func=cmd_show_spread)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
