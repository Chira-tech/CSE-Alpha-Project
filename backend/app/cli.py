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

from app.config import settings
from app.db.session import SessionLocal
from app.ingestion.bootstrap import run_bootstrap
from app.ingestion.corporate_actions_loader import ingest_corporate_actions_for_ticker
from app.ingestion.cse_client import CseClient
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
