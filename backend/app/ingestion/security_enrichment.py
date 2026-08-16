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

    # Shares issued is a point-in-time fact, so it gets a dated row rather
    # than being stamped onto the security record. public_float_pct stays
    # NULL — see the module docstring for why foreignPercentage is not a
    # substitute for it.
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
                )
            )
            wrote = True

    return wrote


def enrich_securities(
    client: CseClient, db: Session, tickers: list[str], as_of: dt.date | None = None
) -> dict[str, int]:
    """Sweeps the given tickers. One bad company never aborts the run —
    with an unofficial upstream and ~283 calls, a mid-sweep failure that
    discarded everything already fetched would make the command
    practically unusable."""
    stamp = as_of or dt.date.today()
    enriched = 0
    skipped = 0
    failed = 0

    for ticker in tickers:
        try:
            info = fetch_company_info(client, ticker)
        except Exception:  # noqa: BLE001 — unofficial upstream, many failure modes
            logger.exception("enrichment fetch failed for %s", ticker)
            failed += 1
            continue

        if info is None:
            skipped += 1
            continue

        if enrich_security(db, ticker, info, stamp):
            enriched += 1
        else:
            skipped += 1

    db.commit()
    logger.info("enrichment: %d updated, %d unchanged, %d failed", enriched, skipped, failed)
    return {"enriched": enriched, "skipped": skipped, "failed": failed}
