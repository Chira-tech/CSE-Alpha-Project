"""
The formal 4-state security status from `docs/CSE_Universe_Integrity_
Rollout.md` Part 4 — CLEAN / PROVISIONAL / QUARANTINED / UNRESOLVED — and
the blockers behind it.

COMPUTED, NOT STORED. Exactly like `app.jobs.reconciliation.is_quarantined`
(which is a query over open `DataAlert`s, not a column), this derives the
status from signals that already have storage: open `DataAlert` rows, the
instrument type on `Security`, the primary-line resolution, price
staleness, and whether a valuation input is still unconfirmed. No new
table, no nightly write to keep in sync, no migration.

`is_quarantined` stays as the coarse "exclude from every model" gate every
ranking view already calls. `security_status_for` is the richer read the
UI uses to decide what it may PUBLISH: a QUARANTINED name shows facts
only, a PROVISIONAL one shows a valuation but no maximum-conviction
verdict, an UNRESOLVED one shows identity only.
"""
from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.domain.instrument_type import issuer_code as issuer_code_of
from app.domain.instrument_type_view import BindingConfidence, resolve_primary_line
from app.domain.universe_integrity import HARD_ALERT_TYPES, SOFT_ALERT_TYPES
from app.models.data_quality import DataAlert
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

#: Last trade older than this (calendar days) → the price is stale enough
#: that a signal built on it is provisional, not current. ~10 calendar
#: days ≈ 7 trading days plus a weekend (spec §class 10).
STALE_PRICE_DAYS = 10

#: The confirmed core lines a fair value cannot be built without — an
#: unconfirmed AI-assisted version of any of these is a soft caveat on
#: whatever the engine currently publishes for the name.
_CORE_VALUATION_LINES = ("total_equity", "net_income", "total_assets")


class SecurityStatus(str, enum.Enum):
    CLEAN = "clean"
    PROVISIONAL = "provisional"
    QUARANTINED = "quarantined"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class SecurityStatusView:
    ticker: str
    status: SecurityStatus
    blockers: tuple[str, ...]
    """Why the name is QUARANTINED or UNRESOLVED — the sentences that
    replace the verdict on the company page. Empty for CLEAN / PROVISIONAL."""
    soft_flags: tuple[str, ...]
    """Why the name is PROVISIONAL — shown as caution, the valuation still
    published but the verdict capped. Empty for CLEAN."""
    primary_line_ticker: str | None
    primary_line_confidence: BindingConfidence


def _open_alerts(db: Session, ticker: str) -> list[DataAlert]:
    return list(
        db.scalars(
            select(DataAlert)
            .where(DataAlert.ticker == ticker, DataAlert.resolved.is_(False))
            .order_by(DataAlert.raised_at.desc())
        )
    )


def _days_since_last_trade(db: Session, ticker: str, as_of: dt.date) -> int | None:
    last = db.scalar(
        select(PriceDaily.date)
        .where(PriceDaily.ticker == ticker, PriceDaily.date <= as_of, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )
    return (as_of - last).days if last is not None else None


def _has_unconfirmed_core_line(db: Session, ticker: str) -> bool:
    """True only when a core valuation line exists for this ticker SOLELY
    as an unconfirmed AI-assisted figure — i.e. there is no REPORTED
    version of it anywhere. A company that has a confirmed 2023 annual and
    a pending AI-assisted 2024 draft is NOT provisional: the valuation
    already runs on the confirmed line (§8), so flagging it here would
    make almost the whole universe provisional for a queue backlog that
    doesn't actually touch its published number."""
    reported = case((Fundamental.provenance_tier == ProvenanceTier.REPORTED, 1), else_=0)
    pending = case(
        (
            (Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED)
            & Fundamental.confirmed_by.is_(None),
            1,
        ),
        else_=0,
    )
    rows = db.execute(
        select(Fundamental.statement_line, func.sum(reported), func.sum(pending))
        .where(Fundamental.ticker == ticker, Fundamental.statement_line.in_(_CORE_VALUATION_LINES))
        .group_by(Fundamental.statement_line)
    ).all()
    return any((rep or 0) == 0 and (pen or 0) > 0 for _line, rep, pen in rows)


def security_status_for(
    db: Session, ticker: str, *, as_of: dt.date | None = None
) -> SecurityStatusView:
    stamp = as_of or dt.date.today()
    security = db.get(Security, ticker)
    if security is None:
        return SecurityStatusView(
            ticker, SecurityStatus.UNRESOLVED,
            blockers=(f"{ticker!r} is not a known security.",),
            soft_flags=(), primary_line_ticker=None, primary_line_confidence=BindingConfidence.NONE,
        )

    code = security.issuer_code or issuer_code_of(ticker)
    primary = resolve_primary_line(db, code, as_of=stamp)

    # --- UNRESOLVED: we cannot even say what this line is.
    unresolved_blockers: list[str] = []
    if security.instrument_type in (None, "unknown"):
        unresolved_blockers.append(
            f"{ticker} has no confirmed instrument type — it cannot be classified as ordinary, "
            "non-voting, preference, debenture, rights, unit or warrant."
        )
    if primary.confidence is BindingConfidence.NONE:
        unresolved_blockers.append(primary.reason)
    if unresolved_blockers:
        return SecurityStatusView(
            ticker, SecurityStatus.UNRESOLVED, tuple(unresolved_blockers), (),
            primary.ticker, primary.confidence,
        )

    alerts = _open_alerts(db, ticker)
    hard = [a for a in alerts if a.alert_type in HARD_ALERT_TYPES]
    soft = [a for a in alerts if a.alert_type in SOFT_ALERT_TYPES]
    # An alert type this module hasn't classified is treated as hard —
    # a new failure mode should quarantine, not be silently ignored.
    unclassified = [a for a in alerts if a.alert_type not in HARD_ALERT_TYPES | SOFT_ALERT_TYPES]
    hard += unclassified

    if hard:
        return SecurityStatusView(
            ticker, SecurityStatus.QUARANTINED,
            blockers=tuple(f"{a.alert_type}: {a.detail}" for a in hard),
            soft_flags=tuple(f"{a.alert_type}: {a.detail}" for a in soft),
            primary_line_ticker=primary.ticker, primary_line_confidence=primary.confidence,
        )

    # --- PROVISIONAL: trusted, but with a named caveat.
    soft_flags: list[str] = [f"{a.alert_type}: {a.detail}" for a in soft]
    if primary.confidence is BindingConfidence.LOW:
        soft_flags.append(primary.reason)
    if primary.confidence is BindingConfidence.MEDIUM:
        soft_flags.append(primary.reason)
    days = _days_since_last_trade(db, ticker, stamp)
    if days is not None and days > STALE_PRICE_DAYS:
        soft_flags.append(f"last trade was {days} days ago — price is stale.")
    if _has_unconfirmed_core_line(db, ticker):
        soft_flags.append(
            "a core statement line (equity / earnings / assets) is still AI-assisted and "
            "unconfirmed — any fair value shown leans on it."
        )

    if soft_flags:
        return SecurityStatusView(
            ticker, SecurityStatus.PROVISIONAL, (), tuple(soft_flags),
            primary.ticker, primary.confidence,
        )

    return SecurityStatusView(
        ticker, SecurityStatus.CLEAN, (), (), primary.ticker, primary.confidence
    )
