"""
The enforcing side of `docs/CSE_Universe_Integrity_Rollout.md` Phase 2 —
the universe-wide detectors that had no nightly job yet, run once a night
across every line and turned into `DataAlert` quarantine rows.

SCOPE — what this job does and, deliberately, does NOT.

  DOES:  rights-price coherence (Check 2), the nil-paid-rights price
         fingerprint (Check 3), a raw 1-day price discontinuity with no
         corporate action (Check 6 line 1), and rights-line reaping.
  DOES NOT re-run: the market-cap identity check (already nightly, in
         `app.jobs.market_cap_reconciliation`), the adjustment-factor
         reconciliation (already nightly, `app.jobs.reconciliation`), or
         the implied-multiple plausibility band (Check 4) — that now runs
         at valuation time inside `app.domain.sanity` and persists through
         `app.domain.valuation_quarantine_view`, so re-checking it here
         would double the write path for the same finding.

Every alert is idempotent per (ticker, alert_type): a still-failing check
leaves an existing open row untouched, a now-passing check auto-resolves
one — the exact pattern `app.jobs.market_cap_reconciliation.check_ticker`
established, and for the same reason (a nightly sweep must not spam a new
row every night for the same ongoing failure).

The check LOGIC is the pure predicates in `app.domain.universe_integrity`,
shared verbatim with the report-only `scripts.audit_universe_integrity`
so the two cannot silently diverge.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import universe_integrity as ui
from app.models.corporate_actions import CorporateAction, CorporateActionType
from app.models.data_quality import DataAlert
from app.models.prices import PriceDaily
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.jobs.universe_integrity_checks")

RIGHTS_OPEN_WINDOW_DAYS = 90

_ENFORCED_TYPES = (
    ui.ALERT_RIGHTS_PRICE_INCOHERENT,
    ui.ALERT_WRONG_LINE_FINGERPRINT,
    ui.ALERT_PRICE_DISCONTINUITY,
    ui.ALERT_RIGHTS_LINE_EXPIRED,
)


def _latest_close(db: Session, ticker: str, as_of: dt.date) -> tuple[Decimal | None, dt.date | None]:
    row = db.scalar(
        select(PriceDaily)
        .where(
            PriceDaily.ticker == ticker,
            PriceDaily.date <= as_of,
            PriceDaily.close.is_not(None),
            PriceDaily.close > 0,
        )
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )
    return (row.close, row.date) if row is not None else (None, None)


def _recent_rights_action(db: Session, ticker: str, as_of: dt.date) -> CorporateAction | None:
    return db.scalar(
        select(CorporateAction)
        .where(
            CorporateAction.ticker == ticker,
            CorporateAction.type == CorporateActionType.RIGHTS_ISSUE,
            CorporateAction.ex_date >= as_of - dt.timedelta(days=RIGHTS_OPEN_WINDOW_DAYS),
            CorporateAction.ex_date <= as_of + dt.timedelta(days=RIGHTS_OPEN_WINDOW_DAYS),
        )
        .order_by(CorporateAction.ex_date.desc())
        .limit(1)
    )


def _worst_recent_discontinuity(
    db: Session, ticker: str, as_of: dt.date, *, lookback_days: int = 400
) -> tuple[dt.date, Decimal] | None:
    """The single largest |1-day return| in the recent window that does
    NOT sit on a corporate-action ex-date. One example is enough to
    quarantine — the human worklist is per ticker, not per bad print."""
    rows = list(
        db.execute(
            select(PriceDaily.date, PriceDaily.close)
            .where(
                PriceDaily.ticker == ticker,
                PriceDaily.date >= as_of - dt.timedelta(days=lookback_days),
                PriceDaily.date <= as_of,
                PriceDaily.close.is_not(None),
                PriceDaily.close > 0,
            )
            .order_by(PriceDaily.date)
        ).all()
    )
    if len(rows) < 2:
        return None
    ca_dates = {
        d for (d,) in db.execute(select(CorporateAction.ex_date).where(CorporateAction.ticker == ticker)).all()
    }
    worst: tuple[dt.date, Decimal] | None = None
    for (d0, c0), (d1, c1) in zip(rows, rows[1:]):
        if d1 in ca_dates:
            continue
        ret = (c1 - c0) / c0
        if worst is None or abs(ret) > abs(worst[1]):
            worst = (d1, ret)
    return worst


def _open_alert(db: Session, ticker: str, alert_type: str) -> DataAlert | None:
    return db.scalar(
        select(DataAlert)
        .where(
            DataAlert.ticker == ticker,
            DataAlert.alert_type == alert_type,
            DataAlert.resolved.is_(False),
        )
        .order_by(DataAlert.raised_at.desc())
        .limit(1)
    )


def _apply(db: Session, ticker: str, finding: ui.IntegrityFinding | None, alert_type: str) -> DataAlert | None:
    """Idempotent raise/resolve for one (ticker, alert_type). Mirrors
    `app.jobs.market_cap_reconciliation.check_ticker`."""
    existing = _open_alert(db, ticker, alert_type)
    if finding is None:
        if existing is not None:
            existing.resolved = True
            existing.resolved_at = dt.datetime.now(dt.timezone.utc)
            existing.resolved_by = "system:universe_integrity_recheck_passed"
        return None
    if existing is not None:
        return existing
    alert = DataAlert(
        ticker=ticker,
        alert_type=alert_type,
        detail=finding.detail[:1000],
        mismatch_pct=None,
        raised_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(alert)
    return alert


def check_ticker(db: Session, ticker: str, as_of: dt.date) -> list[DataAlert]:
    """Runs the enforced universe-integrity checks for one line, raising or
    auto-resolving `DataAlert`s. Also reaps an expired rights line by
    stamping `Security.delisting_date`. Does not commit — the caller
    (`run_nightly_universe_integrity`) commits once per ticker."""
    security = db.get(Security, ticker)
    if security is None:
        return []

    close, close_date = _latest_close(db, ticker, as_of)
    raised: list[DataAlert] = []

    # --- Rights-line reaping (soft) + expiry alert
    expired = ui.check_rights_line_expired(ticker, security.instrument_type, close_date, as_of)
    if expired is not None and security.delisting_date is None:
        security.delisting_date = close_date
    alert = _apply(db, ticker, expired, ui.ALERT_RIGHTS_LINE_EXPIRED)
    if alert is not None:
        raised.append(alert)

    # --- Rights-price coherence + nil-paid fingerprint (only for an
    # ordinary/non-voting line with an open rights offer).
    rights = _recent_rights_action(db, ticker, as_of)
    coherence = fingerprint = None
    if rights is not None and security.instrument_type in ("ordinary", "non_voting"):
        coherence = ui.check_rights_price_coherence(ticker, close, rights.subscription_price)
        fingerprint = ui.check_nil_paid_fingerprint(ticker, close, rights.subscription_price, rights.terp)
    for f, t in ((coherence, ui.ALERT_RIGHTS_PRICE_INCOHERENT), (fingerprint, ui.ALERT_WRONG_LINE_FINGERPRINT)):
        alert = _apply(db, ticker, f, t)
        if alert is not None:
            raised.append(alert)

    # --- Unexplained 1-day price discontinuity
    worst = _worst_recent_discontinuity(db, ticker, as_of)
    disc = (
        ui.check_price_discontinuity(ticker, worst[1], worst[0], has_corporate_action_on_date=False)
        if worst is not None
        else None
    )
    alert = _apply(db, ticker, disc, ui.ALERT_PRICE_DISCONTINUITY)
    if alert is not None:
        raised.append(alert)

    return raised


def run_nightly_universe_integrity(
    db: Session, tickers: list[str], as_of: dt.date, *, on_progress=None
) -> dict[str, list[DataAlert]]:
    """§52-style nightly sweep, called after the EOD snapshot lands.
    Mirrors `run_nightly_reconciliation` / `run_nightly_market_cap_check`."""
    results: dict[str, list[DataAlert]] = {}
    total = len(tickers)
    for i, ticker in enumerate(tickers, start=1):
        try:
            results[ticker] = check_ticker(db, ticker, as_of)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("universe integrity check failed for %s", ticker)
            results[ticker] = []
        if on_progress is not None and (i % 25 == 0 or i == total):
            if on_progress(i, total, ticker) is False:
                break
    flagged = {t: a for t, a in results.items() if a}
    if flagged:
        logger.warning("universe integrity raised alerts for %d ticker(s)", len(flagged))
    return results
