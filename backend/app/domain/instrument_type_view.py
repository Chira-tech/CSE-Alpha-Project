"""
DB-wired resolution of an issuer's PRIMARY listed line, with a confidence
that travels with the binding — `docs/CSE_Universe_Integrity_Rollout.md`
§1.3. The pure suffix classification lives in `app.domain.instrument_type`;
this adds the "which of an issuer's lines is THE line, and how sure are
we" decision, which needs the database (every line of the issuer, plus
recent turnover to break a tie).

The three rules that would each independently have saved the AAF binding:
a rights / preference / debenture / unit / warrant line can never be
primary (excluded by type before anything else); the resolution is
deterministic and auditable; and a LOW / NONE confidence binding is
carried all the way to the UI so it cannot silently produce a
maximum-conviction verdict.
"""
from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.prices import PriceDaily
from app.models.securities import Security

_TURNOVER_WINDOW_DAYS = 365


class BindingConfidence(str, enum.Enum):
    HIGH = "high"
    """Exactly one active ordinary voting line — no ambiguity."""
    MEDIUM = "medium"
    """No voting line at all, but exactly one active non-voting line —
    investable, but flagged `NO_VOTING_LINE`."""
    LOW = "low"
    """More than one active voting line — resolved by 12-month turnover,
    but a human should confirm."""
    NONE = "none"
    """No ordinary or non-voting line at all — cannot be resolved; the
    issuer renders identity only (spec Part 4's UNRESOLVED)."""


@dataclass(frozen=True)
class PrimaryLine:
    ticker: str | None
    confidence: BindingConfidence
    flags: tuple[str, ...] = ()
    reason: str = ""


def _turnover_12m(db: Session, ticker: str, as_of: dt.date) -> Decimal:
    since = as_of - dt.timedelta(days=_TURNOVER_WINDOW_DAYS)
    total = db.scalar(
        select(func.coalesce(func.sum(PriceDaily.turnover), 0)).where(
            PriceDaily.ticker == ticker,
            PriceDaily.date >= since,
            PriceDaily.date <= as_of,
        )
    )
    return Decimal(total or 0)


def resolve_primary_line(
    db: Session, issuer_code: str, *, as_of: dt.date | None = None
) -> PrimaryLine:
    """The deterministic primary-line resolution from spec §1.3. `issuer_
    code` is the stem shared by every line of one company (`app.domain.
    instrument_type.issuer_code` — `COMB.N0000` and `COMB.X0000` both →
    `COMB`)."""
    stamp = as_of or dt.date.today()
    lines = list(
        db.scalars(
            select(Security).where(Security.issuer_code == issuer_code).order_by(Security.ticker)
        )
    )
    active = [s for s in lines if s.delisting_date is None]

    ordinary = [s for s in active if s.instrument_type == "ordinary"]
    non_voting = [s for s in active if s.instrument_type == "non_voting"]

    if len(ordinary) == 1:
        return PrimaryLine(ordinary[0].ticker, BindingConfidence.HIGH, reason="single active ordinary voting line")

    if len(ordinary) > 1:
        best = max(ordinary, key=lambda s: _turnover_12m(db, s.ticker, stamp))
        return PrimaryLine(
            best.ticker,
            BindingConfidence.LOW,
            flags=("MULTIPLE_VOTING_LINES",),
            reason=(
                f"{len(ordinary)} active ordinary voting lines for issuer {issuer_code!r} "
                f"({', '.join(s.ticker for s in ordinary)}); picked the one with the highest "
                "12-month turnover — a human should confirm."
            ),
        )

    if len(non_voting) == 1:
        return PrimaryLine(
            non_voting[0].ticker,
            BindingConfidence.MEDIUM,
            flags=("NO_VOTING_LINE",),
            reason=f"no ordinary voting line for issuer {issuer_code!r}; using the sole non-voting line",
        )

    return PrimaryLine(
        None,
        BindingConfidence.NONE,
        reason=(
            f"issuer {issuer_code!r} has no active ordinary or non-voting line "
            f"({len(lines)} line(s) on file) — nothing to value as its equity."
        ),
    )
