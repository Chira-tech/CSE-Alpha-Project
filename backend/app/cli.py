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
from app.ingestion.issuer_registry_loader import ingest_issuer_registry
from app.ingestion.sector_loader import ingest_sectors
from app.ingestion.market_internals import ingest_market_internals
from app.ingestion.corporate_actions_loader import ingest_corporate_actions_for_ticker
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
            "Note: cse_sector and archetype are NOT set — neither exists on the CSE API, and "
            "archetype drives the valuation model router, so it needs a deliberate mapping "
            "(Master Spec Appendix P2)."
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
    p_ca.set_defaults(func=cmd_ingest_corporate_actions)

    p_en = sub.add_parser("enrich", help="fill ISIN / listing date / shares issued per company")
    p_en.add_argument("--ticker", action="append", help="limit to specific ticker(s); repeatable")
    p_en.add_argument("--limit", type=int, help="only process the first N tickers")
    p_en.set_defaults(func=cmd_enrich)

    p_cm = sub.add_parser("capture-market", help="store today's market internals into macro_series")
    p_cm.set_defaults(func=cmd_capture_market)

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
