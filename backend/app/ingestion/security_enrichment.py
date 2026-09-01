"""
Per-company enrichment from `companyInfoSummery` — ISIN, listing date,
shares issued, market cap, foreign holdings, and CSE's own published
beta.

WHY THIS MATTERS: `bootstrap` gets the universe and prices from a single
`tradeSummary` call, but that response carries no ISIN, no listing date
and no share count. Gate 2 (§11.1) tests market cap >= LKR 1.0bn, free
float >= 15% and listing age >= 12 months — none of which can be
evaluated without this data. Enrichment is what makes the coverage gates
able to run at all.

WHAT IT DELIBERATELY DOESN'T DO:

  * It does not set `cse_sector` or `archetype`. Neither is available
    anywhere on the CSE API (verified — see README_ENDPOINTS.md), and
    archetype drives the valuation model router (§15/§16) where a wrong
    value silently routes a bank through an industrial DCF (Part N #7).
    Appendix P2 says that mapping is "maintained as a version-controlled
    file with manual overrides"; guessing it here would be worse than
    leaving it null.

  * It does not derive `public_float_pct` from `foreignPercentage`.
    Foreign holding is not free float — a family-controlled conglomerate
    can be 95% domestically held and 5% foreign with a 10% float. §5
    sources float from quarterly shareholding disclosures, which aren't
    ingested yet, so the column stays NULL and Gate 2 reports it as
    unknown rather than passing on a lookalike number.

  * It does not overwrite a non-null value a human may have set by hand
    (archetype in particular). Re-running is safe.

Cost: one request per company at >=2s pacing (§5), so a full sweep of
~283 names takes roughly 10 minutes. That's why it's a CLI command rather
than part of bootstrap.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.cse_client import CseClient
from app.ingestion.schemas import CompanyInfoSummary
from app.models.float_data import FloatData
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.ingestion.security_enrichment")


def fetch_company_info(client: CseClient, ticker: str) -> CompanyInfoSummary | None:
    response = client.post_form(
        "companyInfoSummery", model=CompanyInfoSummary, data={"symbol": ticker}, allow_empty=True
    )
    if response is None:
        return None
    assert isinstance(response, CompanyInfoSummary)
    return response


def parse_issue_date(text: str | None) -> dt.date | None:
    """CSE renders listing dates as "12/JAN/2012" — verified live."""
    if not text:
        return None
    try:
        return dt.datetime.strptime(text.strip(), "%d/%b/%Y").date()
    except ValueError:
        logger.warning("could not parse issue date %r", text)
        return None


def enrich_security(db: Session, ticker: str, info: CompanyInfoSummary, as_of: dt.date) -> bool:
    """Returns True if anything was written. Only fills fields that are
    currently empty, except for the float_data snapshot which is keyed by
    `as_of` and so is genuinely new information each time it's taken."""
    security = db.get(Security, ticker)
    if security is None:
        return False

    symbol_info = info.reqSymbolInfo
    wrote = False

    # Only fill what's missing — never clobber a human-set value.
    if security.isin is None and symbol_info.isin:
        security.isin = symbol_info.isin
        wrote = True
    if security.listing_date is None:
        listing = parse_issue_date(symbol_info.issueDate)
        if listing is not None:
            security.listing_date = listing
            wrote = True

    # Refreshed every run rather than "only if empty" — unlike ISIN or
    # listing date, this is CSE's own trailing beta and genuinely changes
    # quarter to quarter (the period label is what lets a reader see when
    # it last moved).
    beta_info = info.reqSymbolBetaInfo
    if beta_info is not None:
        if beta_info.triASIBetaValue is not None:
            security.published_beta_asi = Decimal(str(beta_info.triASIBetaValue))
            wrote = True
        if beta_info.betaValueSPSL is not None:
            security.published_beta_sp_sl20 = Decimal(str(beta_info.betaValueSPSL))
            wrote = True
        if beta_info.triASIBetaPeriod:
            period = beta_info.triASIBetaPeriod
            if beta_info.quarter:
                period = f"{period} Q{beta_info.quarter}"
            security.published_beta_period = period

    # Shares issued is a point-in-time fact, so it gets a dated row rather
    # than being stamped onto the security record. public_float_pct stays
    # NULL — see the module docstring for why foreignPercentage is not a
    # substitute for it. published_market_cap rides along in the same row
    # — it's the exchange's own figure for this same symbol on this same
    # day, not a separately-dated fact (see FloatData.published_market_cap's
    # own docstring for why this is captured now: TASK 0.1's plausibility
    # gate needs a genuinely independent market-cap cross-check).
    if symbol_info.quantityIssued:
        existing = db.scalar(
            select(FloatData).where(FloatData.ticker == ticker, FloatData.as_of == as_of)
        )
        if existing is None:
            db.add(
                FloatData(
                    ticker=ticker,
                    as_of=as_of,
                    shares_issued=symbol_info.quantityIssued,
                    public_float_pct=None,
                    top20_pct=None,
                    controlling_holder=None,
                    published_market_cap=(
                        Decimal(str(symbol_info.marketCap))
                        if symbol_info.marketCap is not None
                        else None
                    ),
                    # The exchange's own price from this same payload — see
                    # FloatData.published_price and the E3 note.
                    published_price=(
                        Decimal(str(symbol_info.lastTradedPrice))
                        if symbol_info.lastTradedPrice is not None
                        else None
                    ),
                )
            )
            wrote = True

    return wrote


def enrich_securities(
    client: CseClient, db: Session, tickers: list[str], as_of: dt.date | None = None,
    *, on_ticker: Callable[[int, int, str], bool | None] | None = None,
) -> dict[str, int]:
    """Sweeps the given tickers. One bad company never aborts the run —
    with an unofficial upstream and ~283 calls, a mid-sweep failure that
    discarded everything already fetched would make the command
    practically unusable.

    `on_ticker`, when given, is called after EVERY ticker (not just the
    successful ones) with `(index_completed, total, ticker)` — TASK
    1.1's own "Prices · 148 / 286 tickers"-style live progress needs a
    hook exactly like this, and this is the one real per-ticker,
    minutes-long sweep in this codebase where that kind of granular
    progress is both honest and worth showing (unlike e.g. EOD prices,
    which is a single bulk `tradeSummary` call with no per-ticker steps
    to report). Optional and keyword-only so every existing caller
    (`app.cli`, `app.jobs.scheduler` if ever wired there) is unaffected.

    Returning `False` from `on_ticker` stops the sweep after the ticker
    that just completed — TASK 1.1's own cooperative cancel ("scraper
    checks a flag between tickers"). This is a real, honoured signal, not
    cosmetic: a caller that only RECORDS a cancel request without
    actually breaking this loop (an earlier version of `app.jobs.runner`
    did exactly that) leaves the sweep running to completion regardless
    of what the UI shows — caught live, clicking Cancel in the browser
    and watching the worker's own log keep fetching ticker after ticker
    for a full minute afterwards. Any other return value, including
    `None` (what every caller returned before this signal existed),
    continues the sweep unchanged.
    """
    stamp = as_of or dt.date.today()
    enriched = 0
    skipped = 0
    failed = 0

    total = len(tickers)
    for i, ticker in enumerate(tickers, start=1):
        try:
            info = fetch_company_info(client, ticker)
        except Exception:  # noqa: BLE001 — unofficial upstream, many failure modes
            logger.exception("enrichment fetch failed for %s", ticker)
            failed += 1
            if on_ticker is not None and on_ticker(i, total, ticker) is False:
                break
            continue

        if info is None:
            skipped += 1
        elif enrich_security(db, ticker, info, stamp):
            enriched += 1
        else:
            skipped += 1

        if on_ticker is not None and on_ticker(i, total, ticker) is False:
            break

    db.commit()
    logger.info("enrichment: %d updated, %d unchanged, %d failed", enriched, skipped, failed)
    return {"enriched": enriched, "skipped": skipped, "failed": failed}
