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
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.domain.instrument_type import issuer_code as issuer_code_of
from app.domain.instrument_type_view import BindingConfidence, resolve_primary_line
from app.domain.provenance import can_enter_valuation
from app.domain.universe_integrity import (
    HARD_ALERT_TYPES,
    SOFT_ALERT_TYPES,
    check_profitability_trend_consistency,
)
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

#: Spec §Check 8: how many confirmed annual `net_income` periods are
#: needed before "declining" is a trend rather than noise. The spec talks
#: in "3-year" / "5-year" terms; 3 is the floor.
_MIN_ANNUAL_PERIODS_FOR_TREND = 3


def _confirmed_annual_net_income(
    db: Session, ticker: str, as_of: dt.date, *, limit: int = 5
) -> list[Decimal]:
    """The last `limit` confirmed (`can_enter_valuation`) annual
    `net_income` figures for `ticker`, point-in-time as of `as_of`,
    oldest → newest, one value per `period_end` (highest `version` wins a
    restatement)."""
    enterable = [t for t in ProvenanceTier if can_enter_valuation(t)]
    rows = db.execute(
        select(Fundamental.period_end, Fundamental.version, Fundamental.value)
        .where(
            Fundamental.ticker == ticker,
            Fundamental.statement_line == "net_income",
            Fundamental.period_type == "annual",
            Fundamental.first_available_date <= as_of,
            Fundamental.provenance_tier.in_(enterable),
        )
        .order_by(Fundamental.period_end.desc(), Fundamental.version.desc())
    ).all()
    seen: set[dt.date] = set()
    picked: list[tuple[dt.date, Decimal]] = []
    for period_end, _version, value in rows:
        if period_end in seen:
            continue
        seen.add(period_end)
        picked.append((period_end, value))
        if len(picked) >= limit:
            break
    return [v for _pe, v in reversed(picked)]


def negative_and_declining_earnings(
    db: Session, ticker: str, as_of: dt.date
) -> tuple[Decimal | None, bool, int]:
    """`(trailing_net_income, trend_declining, n_periods)` for spec
    §Check 8. `trend_declining` is a net decline across the confirmed
    annual window (newest < oldest), which is what HDFC's "~30%/yr
    decline over five years" looks like — not a strict period-by-period
    monotonic drop."""
    history = _confirmed_annual_net_income(db, ticker, as_of)
    if len(history) < _MIN_ANNUAL_PERIODS_FOR_TREND:
        return None, False, len(history)
    trailing = history[-1]
    declining = history[-1] < history[0]
    return trailing, declining, len(history)


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
    verdict_cap: str | None = None
    """Spec §Check 8 — `"hold"` when a trailing net loss on a declining
    earnings trend means no Buy-side verdict may be published for this
    name regardless of what the fair-value models output. `None`
    otherwise (the ordinary PROVISIONAL "no maximum-conviction verdict"
    rule still applies, but the rating is not capped at Hold)."""


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


@dataclass(frozen=True)
class UniverseStatusSummary:
    """Universe-wide count of the four `SecurityStatus` states — the
    homepage trust bar (`docs/CSE_Company_Page_And_Homepage_Redesign.md`
    §6: "248 clean · 41 provisional · 23 quarantined"). One row per
    `Security`, classified by the SAME precedence
    `security_status_for` applies to a single ticker
    (UNRESOLVED → QUARANTINED → PROVISIONAL → CLEAN); `test_security_
    status_view` cross-checks a sample of tickers between the two so the
    batch cannot silently drift from the per-ticker read.

    Built from four aggregate queries rather than ~290 calls to
    `security_status_for`, which issues five queries apiece and is far
    too slow for a screen the UI spec wants readable in under two
    minutes. The multi-voting-line tie-break (`_turnover_12m`) is the
    only per-ticker query dropped: it only changes WHICH ordinary line
    is primary, never the binding confidence class or the resulting
    status, so it is irrelevant to a count."""

    clean: int
    provisional: int
    quarantined: int
    unresolved: int
    total: int


#: (ticker, instrument_type, issuer_code, is_active, trading_status) — the
#: only `Security` columns the batch classification reads.
_SecRow = tuple[str, str | None, str | None, bool, str]


def _issuer_binding_confidence_batch(
    rows: list[_SecRow],
) -> dict[str, BindingConfidence]:
    """`resolve_primary_line`'s confidence class for every issuer, in
    memory — same rules, minus the turnover tie-break that a status count
    doesn't need. Keyed by `issuer_code`."""
    by_issuer: dict[str, list[_SecRow]] = {}
    for row in rows:
        ticker, _it, code, _active, _ts = row
        by_issuer.setdefault(code or issuer_code_of(ticker), []).append(row)

    out: dict[str, BindingConfidence] = {}
    for code, lines in by_issuer.items():
        active = [r for r in lines if r[3]]
        ordinary = sum(1 for r in active if r[1] == "ordinary")
        non_voting = sum(1 for r in active if r[1] == "non_voting")
        if ordinary == 1:
            out[code] = BindingConfidence.HIGH
        elif ordinary > 1:
            out[code] = BindingConfidence.LOW
        elif non_voting == 1:
            out[code] = BindingConfidence.MEDIUM
        else:
            out[code] = BindingConfidence.NONE
    return out


def universe_status_summary(
    db: Session, *, as_of: dt.date | None = None
) -> UniverseStatusSummary:
    stamp = as_of or dt.date.today()

    securities: list[_SecRow] = [
        (ticker, it, code, delist is None, ts or "active")
        for ticker, it, code, delist, ts in db.execute(
            select(
                Security.ticker,
                Security.instrument_type,
                Security.issuer_code,
                Security.delisting_date,
                Security.trading_status,
            )
        )
    ]

    binding = _issuer_binding_confidence_batch(securities)

    alert_types_by_ticker: dict[str, set[str]] = {}
    for tkr, atype in db.execute(
        select(DataAlert.ticker, DataAlert.alert_type).where(DataAlert.resolved.is_(False))
    ):
        alert_types_by_ticker.setdefault(tkr, set()).add(atype)

    # A ticker is "stale" only if it HAS price history AND its last trade
    # is older than the window — a ticker with no price rows at all is
    # NOT stale-flagged (it fails other checks or stays clean), matching
    # `_days_since_last_trade` returning None. `HAVING max(date)` lets the
    # (ticker, date) index carry this in one pass.
    stale_before = stamp - dt.timedelta(days=STALE_PRICE_DAYS)
    stale_tickers: set[str] = {
        tkr
        for (tkr,) in db.execute(
            select(PriceDaily.ticker)
            .where(PriceDaily.close.is_not(None), PriceDaily.date <= stamp)
            .group_by(PriceDaily.ticker)
            .having(func.max(PriceDaily.date) <= stale_before)
        )
    }

    reported = case((Fundamental.provenance_tier == ProvenanceTier.REPORTED, 1), else_=0)
    pending = case(
        (
            (Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED)
            & Fundamental.confirmed_by.is_(None),
            1,
        ),
        else_=0,
    )
    core_state: dict[str, list[tuple[int, int]]] = {}
    for tkr, _line, rep, pen in db.execute(
        select(
            Fundamental.ticker,
            Fundamental.statement_line,
            func.sum(reported),
            func.sum(pending),
        )
        .where(Fundamental.statement_line.in_(_CORE_VALUATION_LINES))
        .group_by(Fundamental.ticker, Fundamental.statement_line)
    ):
        core_state.setdefault(tkr, []).append((rep or 0, pen or 0))
    unconfirmed_core = {
        tkr for tkr, rows in core_state.items() if any(rep == 0 and pen > 0 for rep, pen in rows)
    }

    # --- Spec §Check 8, batched: confirmed annual net_income history per
    # ticker (one value per period_end, latest version), then the same
    # "trailing loss + net decline over >= 3 periods" test the per-ticker
    # `negative_and_declining_earnings` applies.
    enterable = [t for t in ProvenanceTier if can_enter_valuation(t)]
    ni_history: dict[str, list[tuple[dt.date, int, Decimal]]] = {}
    for tkr, period_end, version, value in db.execute(
        select(Fundamental.ticker, Fundamental.period_end, Fundamental.version, Fundamental.value)
        .where(
            Fundamental.statement_line == "net_income",
            Fundamental.period_type == "annual",
            Fundamental.first_available_date <= stamp,
            Fundamental.provenance_tier.in_(enterable),
        )
        .order_by(Fundamental.period_end.asc(), Fundamental.version.asc())
    ):
        # asc period_end + asc version → the last write per period_end wins
        hist = ni_history.setdefault(tkr, [])
        if hist and hist[-1][0] == period_end:
            hist[-1] = (period_end, version, value)
        else:
            hist.append((period_end, version, value))
    check8_tickers = {
        tkr
        for tkr, hist in ni_history.items()
        if len(hist) >= _MIN_ANNUAL_PERIODS_FOR_TREND
        and hist[-1][2] < 0
        and hist[-1][2] < hist[0][2]
    }

    counts = {s: 0 for s in SecurityStatus}
    for ticker, instrument_type, issuer_code, _active, trading_status in securities:
        confidence = binding.get(issuer_code or issuer_code_of(ticker), BindingConfidence.NONE)

        if instrument_type in (None, "unknown") or confidence is BindingConfidence.NONE:
            counts[SecurityStatus.UNRESOLVED] += 1
            continue

        if trading_status in ("suspended", "delisted"):
            counts[SecurityStatus.QUARANTINED] += 1
            continue

        alert_types = alert_types_by_ticker.get(ticker, set())
        if any(a not in SOFT_ALERT_TYPES for a in alert_types):
            # HARD_ALERT_TYPES and any unclassified type both quarantine,
            # matching `security_status_for`'s "unclassified → hard" rule.
            counts[SecurityStatus.QUARANTINED] += 1
            continue

        provisional = (
            bool(alert_types)  # a soft alert
            or confidence in (BindingConfidence.LOW, BindingConfidence.MEDIUM)
            or ticker in stale_tickers
            or ticker in unconfirmed_core
            or ticker in check8_tickers
        )
        counts[SecurityStatus.PROVISIONAL if provisional else SecurityStatus.CLEAN] += 1

    return UniverseStatusSummary(
        clean=counts[SecurityStatus.CLEAN],
        provisional=counts[SecurityStatus.PROVISIONAL],
        quarantined=counts[SecurityStatus.QUARANTINED],
        unresolved=counts[SecurityStatus.UNRESOLVED],
        total=len(securities),
    )


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

    # --- QUARANTINED by trading state: the exchange has halted this line,
    # so there is no live price to value or rank against (spec Part 4 /
    # golden case 6). Checked before the data-quality alerts because it is
    # a harder fact than any of them — a suspended name has no number to
    # dispute.
    if security.trading_status in ("suspended", "delisted"):
        state = security.trading_status
        return SecurityStatusView(
            ticker,
            SecurityStatus.QUARANTINED,
            blockers=(
                f"{ticker} is {state} — trading has stopped, so there is no current price "
                "to value against and no ranking would be on live data. Facts and history "
                "only; no fair value, no verdict, no scoreboard rank.",
            ),
            soft_flags=(),
            primary_line_ticker=primary.ticker,
            primary_line_confidence=primary.confidence,
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

    # --- Spec §Check 8: trailing net loss on a declining earnings trend.
    # Computed live here (the nightly job also raises it as a DataAlert
    # for the Data Health list, but only the live read can set
    # `verdict_cap`). If the alert is already open, it is in `soft` above
    # — don't add the sentence twice.
    verdict_cap: str | None = None
    trailing_ni, declining, n_periods = negative_and_declining_earnings(db, ticker, stamp)
    check8 = check_profitability_trend_consistency(
        ticker, trailing_ni, declining, trend_periods=n_periods
    )
    if check8 is not None:
        verdict_cap = "hold"
        already_alerted = any(a.alert_type == check8.check for a in soft)
        if not already_alerted:
            soft_flags.append(check8.detail)

    if soft_flags:
        return SecurityStatusView(
            ticker, SecurityStatus.PROVISIONAL, (), tuple(soft_flags),
            primary.ticker, primary.confidence, verdict_cap,
        )

    return SecurityStatusView(
        ticker, SecurityStatus.CLEAN, (), (), primary.ticker, primary.confidence
    )
