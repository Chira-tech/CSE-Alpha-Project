"""
Master Spec §7: "A nightly reconciliation test: recompute each stock's
total return from adjusted prices, and independently from raw prices plus
declared actions. Any mismatch >0.5% raises a data alert and quarantines
that ticker from every model until a human resolves it."

This is the job that makes the corporate-actions math in
app.domain.corporate_actions trustworthy in production rather than just in
unit tests: it checks that the *stored* adj_factor series (built from
confirmed actions) actually agrees with an independent recomputation from
raw prices, for every ticker, every night.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.corporate_actions import (
    ActionKind,
    CorporateActionEvent,
    build_adjustment_factor_series,
)
from app.models.corporate_actions import CorporateAction
from app.models.corporate_actions import CorporateActionType as DbActionType
from app.models.data_quality import DataAlert
from app.models.prices import PriceDaily
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.jobs.reconciliation")

_DB_TO_DOMAIN_KIND = {
    DbActionType.DIVIDEND_CASH: ActionKind.DIVIDEND_CASH,
    DbActionType.BONUS_ISSUE: ActionKind.BONUS_ISSUE,
    DbActionType.STOCK_SPLIT: ActionKind.STOCK_SPLIT,
    DbActionType.CONSOLIDATION: ActionKind.CONSOLIDATION,
    DbActionType.RIGHTS_ISSUE: ActionKind.RIGHTS_ISSUE,
}


def _load_confirmed_events(db: Session, ticker: str) -> list[CorporateActionEvent]:
    rows = db.scalars(
        select(CorporateAction).where(
            CorporateAction.ticker == ticker,
            CorporateAction.confirmed_by.is_not(None),
        )
    )
    events: list[CorporateActionEvent] = []
    for row in rows:
        kind = _DB_TO_DOMAIN_KIND.get(row.type)
        if kind is None:
            continue  # delisting/suspension aren't price-ratio events
        if kind is ActionKind.DIVIDEND_CASH:
            events.append(
                CorporateActionEvent(
                    ex_date=row.ex_date,
                    kind=kind,
                    cash_amount=row.cash_amount,
                    close_price_day_before_ex=_price_day_before(db, ticker, row.ex_date),
                )
            )
        elif kind in (ActionKind.BONUS_ISSUE, ActionKind.STOCK_SPLIT):
            events.append(
                CorporateActionEvent(ex_date=row.ex_date, kind=kind, new_shares_per_held_share=row.ratio)
            )
        elif kind is ActionKind.CONSOLIDATION:
            events.append(
                CorporateActionEvent(ex_date=row.ex_date, kind=kind, old_shares_per_new_share=row.ratio)
            )
        elif kind is ActionKind.RIGHTS_ISSUE:
            events.append(
                CorporateActionEvent(
                    ex_date=row.ex_date,
                    kind=kind,
                    shares_held_n=Decimal(1),
                    shares_subscribed_s=row.ratio,
                    subscription_price=row.subscription_price,
                    cum_rights_price=row.cum_rights_price,
                )
            )
    return events


def _price_day_before(db: Session, ticker: str, ex_date: dt.date) -> Decimal | None:
    row = db.scalar(
        select(PriceDaily)
        .where(PriceDaily.ticker == ticker, PriceDaily.date < ex_date)
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )
    return row.close if row else None


def reconcile_ticker(db: Session, ticker: str) -> DataAlert | None:
    """Returns the DataAlert raised (already added+flushed) if the stored
    adj_factor series disagrees with an independent recomputation by more
    than the configured threshold; None if reconciliation passes.
    """
    price_rows = list(
        db.scalars(select(PriceDaily).where(PriceDaily.ticker == ticker).order_by(PriceDaily.date))
    )
    if len(price_rows) < 2:
        return None  # nothing to reconcile yet

    dates = [r.date for r in price_rows]
    # Use the SAME event set the stored-factor builder uses
    # (`app.jobs.adjustment_factors.rebuild_adjustment_factors_for_ticker`)
    # — `usable_events` drops an event that predates the price history
    # (it affects no stored date) and one whose ratio can't be computed
    # (a dividend with no close on the day before its ex-date). Calling
    # `build_adjustment_factor_series` on the raw list instead let a
    # single unpriceable dividend raise a ValueError that aborted the
    # WHOLE nightly reconciliation for every ticker (found live 3 Sep
    # 2026, first night the in-process scheduler actually ran this job).
    from app.jobs.adjustment_factors import usable_events

    events, skipped = usable_events(_load_confirmed_events(db, ticker), dates[0])
    if skipped:
        logger.warning(
            "reconciliation for %s: %d confirmed event(s) not priceable, excluded from "
            "the recomputation: %s",
            ticker, len(skipped), "; ".join(skipped),
        )
    recomputed_factors = build_adjustment_factor_series(dates, events)

    max_mismatch = Decimal(0)
    for row in price_rows:
        recomputed = recomputed_factors.get(row.date, Decimal(1))
        stored = row.adj_factor or Decimal(1)
        if stored == 0:
            continue
        mismatch = abs(recomputed - stored) / stored
        max_mismatch = max(max_mismatch, mismatch)

    if max_mismatch > settings.reconciliation_mismatch_threshold_pct:
        alert = DataAlert(
            ticker=ticker,
            alert_type="reconciliation_mismatch",
            detail=(
                f"stored adj_factor diverges from independently recomputed factor by "
                f"{max_mismatch:.4%}, exceeding the {settings.reconciliation_mismatch_threshold_pct:.2%} "
                f"threshold. Likely cause: an unconfirmed or missing corporate action, or a "
                f"mismapped ratio. Ticker quarantined from all models until resolved."
            ),
            mismatch_pct=float(max_mismatch),
            raised_at=dt.datetime.now(dt.timezone.utc),
        )
        db.add(alert)
        db.commit()
        logger.error("reconciliation FAILED for %s: %.4f%% mismatch", ticker, max_mismatch * 100)
        return alert

    logger.info("reconciliation passed for %s (max mismatch %.4f%%)", ticker, max_mismatch * 100)
    return None


def is_quarantined(db: Session, ticker: str) -> bool:
    """§7 / §50: a quarantined ticker must be excluded from every model
    until a human resolves the underlying alert.

    Two kinds of quarantine collapse to one boolean here: an unresolved
    `DataAlert` (a data-quality failure), and a `trading_status` of
    `suspended` / `delisted` (`docs/CSE_Universe_Integrity_Rollout.md`
    golden case 6 — the exchange has halted trading, so there is no live
    price to rank on). Callers that need the specific reason use
    `app.domain.security_status_view.security_status_for`."""
    unresolved = db.scalar(
        select(DataAlert).where(DataAlert.ticker == ticker, DataAlert.resolved.is_(False)).limit(1)
    )
    if unresolved is not None:
        return True
    status = db.scalar(select(Security.trading_status).where(Security.ticker == ticker))
    return status in ("suspended", "delisted")


def run_nightly_reconciliation(db: Session, tickers: list[str]) -> dict[str, DataAlert | None]:
    """§52: "EOD snapshot + adjustment", 15:00 daily includes "reconciliation
    test." Call this once per ticker after the day's snapshot lands."""
    results: dict[str, DataAlert | None] = {}
    for ticker in tickers:
        try:
            results[ticker] = reconcile_ticker(db, ticker)
        except Exception:  # noqa: BLE001 — one bad ticker must not abort the sweep
            logger.exception("reconciliation errored for %s — skipped this run", ticker)
            db.rollback()
            results[ticker] = None
    return results
