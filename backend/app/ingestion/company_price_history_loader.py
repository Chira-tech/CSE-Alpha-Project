"""
Backfill ~1 year of daily price history per company from
`companyChartDataByStock`.

See `app.domain.company_price_history` for what this endpoint is, how it
was found, and the evidence that it can be trusted. In one sentence: a
prior survey tested `chartData` against every security id, got `[]` for
all of them, and concluded per-company history did not exist on this
API. `companyChartDataByStock` uses a different id space entirely
(`stockId`, from `allSecurityCode`'s `id`) and was never tried.

RATE LIMITING. One request per line, plus one to look up ids
(`allSecurityCode`), through the same `CseClient` used everywhere else —
its built-in >=2s pacing (§5) applies automatically. A full 283-line
sweep is therefore ~10 minutes, the same order as `enrich`.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.company_price_history import (
    PERIOD_ONE_YEAR,
    CompanyPriceHistoryError,
    DailyBar,
    parse_bars,
)
from app.ingestion.cse_client import CseClient
from app.models.prices import PriceDaily

logger = logging.getLogger("cse_alpha.ingestion.company_price_history")

SOURCE = "cse.lk:companyChartDataByStock"


def fetch_stock_id_map(client: CseClient) -> dict[str, int]:
    """`{ticker: stockId}` from `allSecurityCode` — a GET, no pacing cost
    beyond the one call. This id space is NOT the same as `cntSecurity`'s
    `securityId` (issuer-level, no line suffix) or `chartData`'s
    `chartId` (index-level only); conflating any of the three would send
    every subsequent request to the wrong line."""
    payload = client.get_json("allSecurityCode")
    if not isinstance(payload, list) or not payload:
        raise CompanyPriceHistoryError("allSecurityCode returned no usable list")
    mapping: dict[str, int] = {}
    for row in payload:
        symbol = str(row.get("symbol") or "").strip().upper()
        stock_id = row.get("id")
        if symbol and isinstance(stock_id, int):
            mapping[symbol] = stock_id
    return mapping


def fetch_company_price_history(
    client: CseClient, stock_id: int, *, period: int = PERIOD_ONE_YEAR
) -> list[DailyBar]:
    payload = client.post_form(
        "companyChartDataByStock", data={"stockId": stock_id, "period": period}
    )
    bars, warnings = parse_bars(payload)
    for warning in warnings:
        logger.warning("stockId %s: %s", stock_id, warning)
    return bars


def upsert_company_price_history(
    db: Session, ticker: str, bars: list[DailyBar], *, today: dt.date | None = None
) -> int:
    """Fill gaps only. Two deliberate exclusions:

    - Dates that already have a `prices_daily` row are left untouched.
      The daily EOD job observes the session directly at the close (§6);
      this endpoint is a same-institution resample and must never
      overwrite a live-captured figure with a recomputed one, even if the
      two would likely agree.
    - Today's date (Colombo) is always skipped. Before the 14:30 close
      the day's bar is still forming, and this loader has no post-close
      signal to distinguish a settled bar from an in-progress one the way
      `index_history` does for the ASPI. The daily EOD job owns today;
      this loader owns the gaps behind it.
    """
    today = today or dt.datetime.now(dt.timezone.utc).astimezone(
        dt.timezone(dt.timedelta(hours=5, minutes=30))
    ).date()

    existing = set(
        db.scalars(
            select(PriceDaily.date).where(PriceDaily.ticker == ticker)
        ).all()
    )

    written = 0
    now = dt.datetime.now(dt.timezone.utc)
    for bar in bars:
        if bar.date >= today or bar.date in existing:
            continue
        db.add(
            PriceDaily(
                ticker=ticker,
                date=bar.date,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                fetched_at=now,
                source=SOURCE,
            )
        )
        written += 1

    if written:
        db.commit()
    return written


def backfill_company_price_history(
    client: CseClient,
    db: Session,
    tickers: list[str],
    *,
    period: int = PERIOD_ONE_YEAR,
) -> dict[str, int]:
    """Sweep the given tickers. One bad line never aborts the run — with
    an unofficial upstream and up to 283 calls, a mid-sweep failure that
    discarded everything already fetched would make the command
    practically unusable (same reasoning as `security_enrichment`)."""
    stock_ids = fetch_stock_id_map(client)

    written = no_id = failed = 0
    for ticker in tickers:
        stock_id = stock_ids.get(ticker.upper())
        if stock_id is None:
            logger.warning("no stockId for %s — not in allSecurityCode", ticker)
            no_id += 1
            continue
        try:
            bars = fetch_company_price_history(client, stock_id, period=period)
        except Exception:  # noqa: BLE001 — unofficial upstream, many failure modes
            logger.exception("price history fetch failed for %s", ticker)
            failed += 1
            continue

        written += upsert_company_price_history(db, ticker, bars)

    summary = {
        "tickers": len(tickers),
        "rows_written": written,
        "no_stock_id": no_id,
        "failed": failed,
    }
    logger.info("company price history backfill: %s", summary)
    return summary
