"""
Master Spec §52 job table, wired with APScheduler. Deliberately sparse:
only the jobs whose implementation actually exists in this phase are
scheduled. Everything else in the table (order book polling, macro
re-estimation, factor regressions...) is a later-phase no-op placeholder
here so the schedule's *shape* is right from day one, per the spec's own
framing: "what runs continuously is the scheduler, the monitor and the
overnight batch, not a firehose of redundant polling."

Endpoint semantics (POST, JSON vs form-urlencoded) are verified against
the live API — see app/ingestion/README_ENDPOINTS.md.
"""
from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.corporate_actions_loader import ingest_corporate_actions_for_ticker
from app.ingestion.cbsl_client import CbslClient
from app.ingestion.cbsl_loader import ingest_range as ingest_cbsl_range
from app.ingestion.cse_client import CseClient
from app.ingestion.financial_pdf_extractor import ingest_financial_statements_for_known_tickers
from app.ingestion.index_history_loader import ingest_index_history
from app.ingestion.company_price_history_loader import backfill_company_price_history
from app.ingestion.issuer_registry_loader import ingest_issuer_registry
from app.ingestion.sector_loader import ingest_sectors
from app.ingestion.market_internals import ingest_market_internals
from app.ingestion.price_loader import fetch_eod_prices, infer_session_date, upsert_eod_prices
from app.jobs.reconciliation import run_nightly_reconciliation
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.jobs.scheduler")

MARKET_TZ = ZoneInfo("Asia/Colombo")


def _all_tickers(db) -> list[str]:
    return [t for (t,) in db.execute(select(Security.ticker)).all()]


def _job_eod_snapshot() -> None:
    """§52: "EOD snapshot + adjustment  15:00 daily".

    The session date comes from the feed's own timestamps, not from
    `date.today()` — the job is scheduled Mon-Fri after close, but a
    public holiday, an unscheduled closure, or a late/missed run would
    otherwise write the previous session's prices under today's date.
    See `infer_session_date`; §6 depends on this being right.
    """
    db = SessionLocal()
    try:
        with CseClient() as client:
            rows = fetch_eod_prices(client)

        session_date = infer_session_date(rows)
        if session_date is None:
            logger.error("EOD snapshot: could not determine session date from feed; nothing written")
            return

        written = upsert_eod_prices(db, session_date, rows)
        logger.info("EOD snapshot: wrote %d rows for session %s", written, session_date)
    except Exception:
        logger.exception("EOD snapshot job failed")
    finally:
        db.close()


def _job_capture_market_internals() -> None:
    """§29's variable set under "Market internals": market-wide earnings
    yield, turnover, foreign net flow. Runs with the EOD snapshot because
    it comes from the same end-of-session publication, and because the
    earnings-yield half of the hero spread is only as current as this job.
    """
    db = SessionLocal()
    try:
        with CseClient() as client:
            written = ingest_market_internals(client, db)
        logger.info("market internals: wrote %d new observation(s)", written)
    except Exception:
        logger.exception("market internals capture failed")
    finally:
        db.close()


def _job_repair_price_gaps() -> None:
    """Sweep every security through `companyChartDataByStock` to fill any
    hole in the last ~year of daily prices (§7's "single point of
    failure" concern, applied to price history rather than the live
    feed).

    Weekly and slow — up to 283 calls at >=2s pacing, ~10 minutes — so it
    runs overnight on a quiet day rather than alongside the trading-day
    jobs. `upsert_company_price_history` only ever fills a gap; a date
    already captured live at the close is never touched, so this cannot
    make today's data worse, only yesterday's gaps smaller. A missed EOD
    snapshot (a worker outage, a host restart) is exactly the case this
    exists to repair — without it, that day would otherwise be gone for
    good the way pre-existing gaps in this series already are.
    """
    db = SessionLocal()
    try:
        tickers = _all_tickers(db)
        with CseClient() as client:
            summary = backfill_company_price_history(client, db, tickers)
        logger.info("weekly price-gap repair: %s", summary)
    except Exception:
        logger.exception("price-gap repair failed")
    finally:
        db.close()


def _job_refresh_sectors() -> None:
    """Re-read the exchange's GICS classification (§12).

    Weekly and after the registry, so a newly listed company picked up by
    the registry gets classified in the same window. Hand-set
    classifications are preserved — Appendix P2 expects them, because GICS
    files diversified CSE conglomerates under whichever industry group
    their largest segment falls into.
    """
    db = SessionLocal()
    try:
        with CseClient() as client:
            summary = ingest_sectors(client, db)
        if summary["unclassified"]:
            logger.info(
                "sector refresh: %d securities remain outside the exchange's GICS publication",
                summary["unclassified"],
            )
    except Exception:
        logger.exception("sector refresh failed")
    finally:
        db.close()


def _job_refresh_issuer_registry() -> None:
    """§7 survivorship: keep the exchange's own issuer list, including the
    names it has flagged as gone.

    Weekly rather than daily because delistings are rare and the endpoint
    is a full dump. The value compounds with time — `first_seen` and
    `last_seen` are the only bounds this exchange gives on when a company
    stopped existing, and they only tighten by being observed.
    """
    db = SessionLocal()
    try:
        with CseClient() as client:
            summary = ingest_issuer_registry(client, db)
        if summary["newly_delisted"]:
            logger.warning(
                "issuer registry: %d issuer(s) newly flagged delisted", summary["newly_delisted"]
            )
    except Exception:
        logger.exception("issuer registry refresh failed")
    finally:
        db.close()


def _job_backfill_index_history() -> None:
    """Re-pull the ~1 year ASPI series from `chartData` and fill any gap.

    Weekly, not daily: the same-day close already arrives via
    `_job_capture_market_internals`, and existing rows are never
    overwritten, so this only ever repairs holes.

    That repair is the point. Prices accumulate forward and a missed day
    is gone forever, but the index series can be reconstructed for up to
    a year afterwards — so an outage that permanently damages the price
    history leaves the ASPI series recoverable.
    """
    db = SessionLocal()
    try:
        with CseClient() as client:
            written = ingest_index_history(client, db)
        logger.info("ASPI history backfill: wrote %d new close(s)", written)
    except Exception:
        logger.exception("ASPI history backfill failed")
    finally:
        db.close()


def _job_cbsl_indicators() -> None:
    """§5: "Policy rate, AWPLR, T-bill and bond yields ... CBSL ... API +
    scrape, release-calendar driven."

    Fetches a short trailing window rather than just today, because CBSL
    publishes an edition a day AFTER its cover date and this host 404s
    transiently — so a date that failed yesterday gets another go without
    anyone noticing. Re-recording an edition already stored is a no-op
    beyond the request itself.

    Paced at CBSL's published Crawl-delay of 10s, so a 5-weekday window
    costs about a minute.
    """
    db = SessionLocal()
    try:
        end = dt.date.today()
        start = end - dt.timedelta(days=6)
        with CbslClient() as client:
            result = ingest_cbsl_range(client, db, start, end)
        logger.info(
            "CBSL: %d edition(s), %d observation(s), %d unavailable",
            result["editions"], result["observations"], len(result["unavailable"]),
        )
    except Exception:
        logger.exception("CBSL indicator ingestion failed")
    finally:
        db.close()


def _job_nightly_reconciliation() -> None:
    """§7 / §52: reconciliation test, run immediately after the EOD
    snapshot lands."""
    db = SessionLocal()
    try:
        tickers = _all_tickers(db)
        results = run_nightly_reconciliation(db, tickers)
        failures = [t for t, alert in results.items() if alert is not None]
        if failures:
            logger.warning("reconciliation raised alerts for: %s", failures)
    finally:
        db.close()


def _job_corporate_actions_scan() -> None:
    """Not in the §52 table under this name, but implements "Corporate
    actions (splits, rights, bonus, dividends) — Event-driven — Scrape +
    mandatory human confirm" from §5. Polling per-ticker on a schedule
    (rather than truly event-driven) is a deliberate Phase-1
    simplification — a webhook/push source for CSE announcements wasn't
    identified during API verification (README_ENDPOINTS.md). Every draft
    this writes has confirmed_by=None; nothing here can affect a price.
    """
    db = SessionLocal()
    try:
        tickers = _all_tickers(db)
        with CseClient() as client:
            total_drafted = 0
            for ticker in tickers:
                try:
                    total_drafted += ingest_corporate_actions_for_ticker(client, db, ticker)
                except Exception:
                    logger.exception("corporate-actions ingest failed for %s", ticker)
        if total_drafted:
            logger.info("corporate actions: drafted %d new rows awaiting human confirmation", total_drafted)
    finally:
        db.close()


def _job_financial_statement_scan() -> None:
    """§5: "Quarterly / annual — PDF table extraction -> LLM-assisted
    line-item mapping -> mandatory human confirm queue." See
    app.ingestion.financial_pdf_extractor's module docstring for what this
    Phase-1 version actually does instead of the LLM step. The feed this
    polls (getFinancialAnnouncement) returns the ~180 most recent filings
    platform-wide with no per-company filter available server-side — see
    README_ENDPOINTS.md — so this job fetches once and matches client-side
    against every known ticker, same shape as the corporate-actions scan.
    """
    db = SessionLocal()
    try:
        tickers = _all_tickers(db)
        with CseClient() as client:
            try:
                total_drafted = ingest_financial_statements_for_known_tickers(client, db, tickers)
            except Exception:
                logger.exception("financial statement scan failed")
                return
        if total_drafted:
            logger.info(
                "financial statements: drafted %d new AI-assisted fundamentals awaiting confirmation",
                total_drafted,
            )
    finally:
        db.close()


def _colombo_cron(hour: int, minute: int) -> CronTrigger:
    """Every schedule in this system is anchored to the exchange's clock,
    never the host's.

    `CronTrigger` resolves its timezone AT CONSTRUCTION, defaulting to the
    machine's local zone — passing the scheduler a tz does NOT retro-fit a
    trigger that was built without one. On a host in, say, Australia/Perth
    (+08:00) that silently turns "15:00" into 12:30 Colombo, i.e. two
    hours BEFORE the CSE closes at 14:30 — so the "end of day" snapshot
    would capture a mid-session price and file it as the close. Caught on
    a real machine; hence the explicit timezone here and the test in
    tests/test_scheduler.py that pins it.
    """
    return CronTrigger(hour=hour, minute=minute, day_of_week="mon-fri", timezone=MARKET_TZ)


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=MARKET_TZ)

    # §52: "EOD snapshot + adjustment  15:00 daily" — 30 minutes after the
    # 14:30 Colombo close.
    scheduler.add_job(
        _job_eod_snapshot,
        _colombo_cron(15, 0),
        id="eod_snapshot",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_capture_market_internals,
        _colombo_cron(15, 2),
        id="capture_market_internals",
        replace_existing=True,
    )
    # After the CSE close, and late enough that CBSL's same-day edition
    # (published the following morning) has had time to appear.
    scheduler.add_job(
        _job_cbsl_indicators,
        _colombo_cron(16, 45),
        id="cbsl_indicators",
        replace_existing=True,
    )
    # Saturday: the week's sessions have all settled and nothing else is
    # contending for the API.
    scheduler.add_job(
        _job_backfill_index_history,
        CronTrigger(day_of_week="sat", hour=6, minute=0, timezone=MARKET_TZ),
        id="index_history_backfill",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_refresh_issuer_registry,
        CronTrigger(day_of_week="sat", hour=6, minute=20, timezone=MARKET_TZ),
        id="issuer_registry_refresh",
        replace_existing=True,
    )
    # After the registry, so a newly listed company is classified in the
    # same window it is first seen.
    scheduler.add_job(
        _job_refresh_sectors,
        CronTrigger(day_of_week="sat", hour=6, minute=40, timezone=MARKET_TZ),
        id="sector_refresh",
        replace_existing=True,
    )
    # After sectors, and given the most idle window: up to 283 paced
    # calls, ~10 minutes.
    scheduler.add_job(
        _job_repair_price_gaps,
        CronTrigger(day_of_week="sat", hour=7, minute=0, timezone=MARKET_TZ),
        id="price_gap_repair",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_nightly_reconciliation,
        _colombo_cron(15, 5),
        id="nightly_reconciliation",
        replace_existing=True,
    )
    # §5: announcements are "event-driven" in principle; polled daily here
    # as the closest Phase-1-achievable approximation (see docstring above).
    scheduler.add_job(
        _job_corporate_actions_scan,
        _colombo_cron(16, 0),
        id="corporate_actions_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_financial_statement_scan,
        _colombo_cron(16, 30),
        id="financial_statement_scan",
        replace_existing=True,
    )

    return scheduler
