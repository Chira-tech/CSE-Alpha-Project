"""
TASK 0.1's own spec: "Add the market-cap cross-check as a nightly
data-quality check (Phase 1 guide §9): `mcap / (price x shares) outside
0.98-1.02` -> alert."

Distinct from `app.domain.sanity`'s `share_count_reconciles` RULE, which
is the SAME comparison but run live, per company, at valuation time, and
which only WITHHOLDS that one company's ladder — it never raises a
standing, visible `DataAlert` a human would see on the Data Health
screen unless that company happens to get viewed. This job is the
proactive, nightly sweep TASK 0.1 also asks for: it checks the WHOLE
universe once a night, independent of whether anyone looks at any one
company, so a real drift (a stale `FloatData` snapshot going unnoticed
for weeks on a company nobody happens to open) still surfaces.

Reuses `app.models.data_quality.DataAlert` and the same idempotent
"only one open alert per ticker" pattern `app.domain.valuation_
quarantine_view.record_sanity_result` already established for the live
path — see that module's own docstring for why a new table was not
added. `alert_type="market_cap_mismatch"` is a fourth value alongside
`reconciliation_mismatch`, `second_source_mismatch` and `valuation_
sanity_block`, each a genuinely distinct failure mode sharing one
mechanism.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.market_cap_view import (
    latest_shares_issued,
    published_market_cap_for,
    published_price_for,
)
from app.models.data_quality import DataAlert
from app.models.prices import PriceDaily

logger = logging.getLogger("cse_alpha.jobs.market_cap_reconciliation")

ALERT_TYPE = "market_cap_mismatch"
_TOLERANCE_PCT = Decimal("0.02")  # TASK 0.1's own stated 0.98-1.02 band


def _latest_close(db: Session, ticker: str, as_of: dt.date) -> Decimal | None:
    return db.scalar(
        select(PriceDaily.close)
        .where(PriceDaily.ticker == ticker, PriceDaily.date <= as_of, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )


def check_ticker(db: Session, ticker: str, as_of: dt.date) -> DataAlert | None:
    """Returns the (already-committed) `DataAlert` if this ticker's
    published market cap disagrees with `price x shares` by more than
    2%; `None` if it reconciles OR any required input is missing (never
    alerts on an absence — see `app.domain.sanity`'s own "skipped, never
    a silent pass" rule, mirrored here as "skipped, never a silent
    alert")."""
    published = published_market_cap_for(db, ticker, as_of)
    shares = latest_shares_issued(db, ticker, as_of)
    # Prefer the last-traded price CSE published in the SAME reqSymbolInfo
    # payload as `published` — reconciling those two is a genuine
    # share-count / share-class check. Falling back to the EOD
    # `prices_daily.close` (a different feed, often an older session)
    # makes this fire whenever the price has simply moved since the last
    # capture — a staleness artefact, not a data error (same fix as
    # `app.domain.sanity.share_count_reconciles`, 2 Sep 2026).
    price = published_price_for(db, ticker, as_of) or _latest_close(db, ticker, as_of)

    existing = db.scalar(
        select(DataAlert)
        .where(DataAlert.ticker == ticker, DataAlert.alert_type == ALERT_TYPE, DataAlert.resolved.is_(False))
        .order_by(DataAlert.raised_at.desc())
        .limit(1)
    )

    if published is None or not shares or price is None or price == 0:
        return None  # genuinely unevaluable — not a pass, not a failure

    local = price * Decimal(shares)
    mismatch = abs(published / local - 1) if local != 0 else None
    if mismatch is None or mismatch <= _TOLERANCE_PCT:
        if existing is not None:
            existing.resolved = True
            existing.resolved_at = dt.datetime.now(dt.timezone.utc)
            existing.resolved_by = "system:market_cap_recheck_passed"
            db.commit()
        return None

    if existing is not None:
        return existing  # already open — don't spam a new row every night

    alert = DataAlert(
        ticker=ticker,
        alert_type=ALERT_TYPE,
        detail=(
            f"CSE's published market cap ({published:,.0f}) disagrees with price x shares "
            f"({local:,.0f}) by {mismatch:.2%}, outside the 2% tolerance (TASK 0.1). Likely "
            f"cause: a stale FloatData share count, or a voting/non-voting share-class mixup."
        ),
        mismatch_pct=float(mismatch),
        raised_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(alert)
    db.commit()
    logger.warning("market-cap mismatch for %s: %.2f%%", ticker, mismatch * 100)
    return alert


def run_nightly_market_cap_check(db: Session, tickers: list[str], as_of: dt.date) -> dict[str, DataAlert | None]:
    return {ticker: check_ticker(db, ticker, as_of) for ticker in tickers}
