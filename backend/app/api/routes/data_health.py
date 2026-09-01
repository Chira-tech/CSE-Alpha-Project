"""
Data health — UI & Experience Specification screen 9, and the visible face
of Master Spec §8 (freshness) and §50 (monitoring).

The spec is blunt that this deserves a real screen rather than an admin
afterthought, because "this queue is where data quality is actually
maintained." For Phase 1 that means: how much data do we actually have,
how stale is it, what's quarantined, and how much is sitting unreviewed.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.corporate_actions import CorporateAction
from app.models.data_quality import DataAlert
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.job_run import JobRun
from app.models.prices import PriceDaily
from app.models.registry import IssuerRegistry
from app.models.securities import Security
from app.domain import universe_integrity as ui
from app.domain.security_status_view import universe_status_summary

#: `docs/CSE_Data_Health_Diagnosis_And_Protocol.md` §5 — a "trading day"
#: with no exchange holiday calendar on file yet is approximated as a
#: weekday (Mon–Fri). A CSE public holiday falling on a weekday will
#: therefore read as a spurious missing session until a real holiday
#: list is ingested; documented rather than silently wrong.
_MARKET_CAP_IDENTITY_TOLERANCE = Decimal("0.02")


def _weekdays_in(start_exclusive: dt.date, end_inclusive: dt.date) -> list[dt.date]:
    """Weekday dates in ``(start_exclusive, end_inclusive]``, oldest first.
    Empty when the range is empty or inverted."""
    out: list[dt.date] = []
    d = start_exclusive + dt.timedelta(days=1)
    while d <= end_inclusive:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def _last_successful_run(db: Session, job: str) -> dt.datetime | None:
    ts = db.scalar(
        select(JobRun.finished_at)
        .where(JobRun.job == job, JobRun.status == "success")
        .order_by(JobRun.finished_at.desc())
        .limit(1)
    )
    # SQLite round-trips DateTime without tz; normalise so callers can do
    # aware arithmetic against `datetime.now(timezone.utc)`.
    if ts is not None and ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts


router = APIRouter(prefix="/data-health", tags=["data-health"])


class QuarantinedTicker(BaseModel):
    ticker: str
    alert_type: str
    detail: str
    raised_at: dt.datetime


class TickerPendingCount(BaseModel):
    ticker: str
    count: int


class UniverseStatusCounts(BaseModel):
    """The homepage trust bar (`docs/CSE_Company_Page_And_Homepage_
    Redesign.md` §6). One row per `Security`, classified by the formal
    4-state status (`app.domain.security_status_view`)."""

    clean: int
    provisional: int
    quarantined: int
    unresolved: int
    total: int


class CheckLedgerRow(BaseModel):
    """`docs/CSE_Data_Health_Diagnosis_And_Protocol.md` E0 / §9.1 — one row
    per universe-wide check, split three ways so "could not be checked" is
    never silently counted as "passed" (the denominator bug §0 calls out).

    `blocking` means a failure quarantines the line (no verdict, no rank).
    `checkable_pct` — (passed + failed) ÷ scope_total — is the number §11
    says to watch: the share of the universe this check has any right to
    an opinion on. `pass_pct_of_checkable` is the honest pass rate, not
    diluted by the lines it could not evaluate."""

    check: str
    label: str
    passed: int
    failed: int
    not_evaluable: int
    not_evaluable_reasons: dict[str, int]
    """reason code → count. Every not-evaluable line is accounted for by
    exactly one code."""
    blocking: bool
    scope_total: int
    checkable_pct: Decimal | None
    pass_pct_of_checkable: Decimal | None


class UniverseIntegrityMetrics(BaseModel):
    """`docs/CSE_Universe_Integrity_Rollout.md` Part 7 — the weekly-tracked
    numbers that turn "measurable progress" from theoretical into visible.
    Every figure is a cheap aggregate query; the proxy nature of a couple
    of them is named, not hidden."""

    issuers_total: int
    issuers_with_a_primary_line: int
    """Issuers with at least one non-delisted ordinary or non-voting
    line — the resolvable ones. The rest render identity only."""
    issuers_high_confidence_binding: int
    """Issuers with exactly one non-delisted ordinary voting line — no
    tie-break needed, so the binding is HIGH confidence."""
    lines_unknown_instrument_type: int
    open_alerts_by_type: dict[str, int]
    quarantined_line_count: int
    """Distinct lines with at least one unresolved DataAlert — the real
    "excluded from every model right now" count. A rising number early in
    the rollout is detection working; watch it after remediation."""
    market_cap_identity_pass_pct: Decimal | None
    """`passed ÷ (passed + failed)` for the `market_cap_identity` check —
    the honest pass rate over the lines that could actually be checked
    (all three of published market cap, share count and price present).
    See `check_ledger` for the pass / fail / not-evaluable split."""
    price_ratio_actions_confirmed_pct: Decimal | None
    """`confirmed ÷ (confirmed + rejected)` for price-ratio corporate
    actions. Pending (unreviewed) actions are not-evaluable, not
    failures — the old definition counted every unreviewed action as a
    miss, which is why this read 15%. See `check_ledger`."""
    median_price_staleness_days: int | None
    suspended_or_delisted_lines: int
    """`docs/CSE_Universe_Integrity_Rollout.md` Part 4 / golden case 6 —
    lines whose `trading_status` is suspended or delisted. They are
    QUARANTINED (no verdict, no rank) but carry no `DataAlert`, so they
    do not appear in the alert-driven quarantine list above."""
    cost_of_equity_available_pct: Decimal | None
    """`docs/CSE_Universe_Integrity_Rollout.md` Part 7 — target 100%.
    PROXY: of the financial-sector lines whose valuation models all need a
    cost of equity, the share with enough recent price history for a
    computable beta (the one per-name input a Ke needs — the risk-free
    rate and ERP are universe-wide). Measured against the real per-name
    resolve once, this tracks it within a line or two. The rollout spec
    was drafted with this "near 0"; the CoE service now exists, so it
    should read high."""
    buy_side_verdicts_on_negative_earnings_trend: int
    """`docs/CSE_Universe_Integrity_Rollout.md` Part 7 / §Check 8 — target
    0. The count of lines where a trailing net loss on a declining
    multi-year earnings trend has forced the verdict to be capped at
    Hold: these names cannot publish a Buy-side verdict whatever the
    fair-value models output, so the number of *published* buy-side
    verdicts on negative-trend names is held at 0 by construction. This
    figure tracks how many names the cap is currently acting on."""


class DataHealth(BaseModel):
    securities_count: int
    issuer_count: int
    """Distinct issuers behind those lines. Lower than `securities_count`
    because banks in particular list voting and non-voting lines
    separately."""

    registry_issuers: int
    registry_delisted: int
    registry_unknown_status: int
    """Known to the exchange, not trading, and not flagged delisted —
    debt-only issuers, suspensions and merely-illiquid names, which this
    source cannot tell apart. Reported rather than assumed either way."""

    price_rows: int
    latest_price_date: dt.date | None
    price_feed_age_days: int | None
    """Calendar days since the newest price row. Kept for continuity; the
    trading-day figures below are the ones to read (§5: a weekend is not a
    gap, a missed Monday is)."""
    securities_with_no_price: int

    # --- Freshness, split (`docs/CSE_Data_Health_Diagnosis_And_Protocol.md`
    # §5 / E8). "How old is the newest data" and "when did the job last
    # succeed" are two quantities that were wearing one label.
    price_data_age_trading_days: int | None
    """Weekday sessions between the newest price row and today — a weekend
    reads as fresh, a missed weekday reads as a gap."""
    missing_trading_days: list[dt.date]
    """Weekday sessions after the newest price row with no price data at
    all, oldest first (capped). Non-empty here means the capture is
    genuinely behind, not just that it's the weekend."""
    price_capture_last_success_at: dt.datetime | None
    """When the `capture_prices` job last finished with status success —
    `null` if it has never succeeded, which is a different and worse state
    than 'data is a few days old'."""
    price_capture_last_success_age_days: int | None
    macro_feed_last_success_at: dt.datetime | None
    """When `capture_macro` (the CBSL risk-free / macro series feed) last
    succeeded. `null` means every cost of equity in the system is on the
    proxy (§4)."""

    corporate_actions_total: int
    corporate_actions_pending: int
    corporate_actions_confirmed: int
    corporate_actions_rejected: int

    fundamentals_total: int
    fundamentals_pending_confirmation: int
    fundamentals_confirmed: int

    fundamentals_confirmed_last_7d: int
    corporate_actions_confirmed_last_7d: int
    """Rolling 7-day confirm counts — the burn-down signal the redesign
    doc (§3.6) asks for on this screen: "Queue: 340 → 12 this week" is
    only legible if the rate things are being cleared is visible next to
    the backlog size."""

    quarantined: list[QuarantinedTicker]
    universe_integrity: UniverseIntegrityMetrics
    universe_status: UniverseStatusCounts
    check_ledger: list[CheckLedgerRow]
    """`docs/CSE_Data_Health_Diagnosis_And_Protocol.md` E0 — every
    universe-wide check as pass / fail / not-evaluable, so a metric that
    moved because coverage changed can be told apart from one that moved
    because the data improved."""

    fundamentals_pending_by_ticker: list[TickerPendingCount]
    """R1 T4.1.5: top tickers by pending-figure count — a real, cheap
    proxy for "where confirming pays off most", NOT the brief's own
    literal "unblocks fair value for N companies" framing. That framing
    needs a full per-ticker valuation pass (the same ~30s-for-the-
    universe cost `app.domain.opportunity_ranking_view`'s own docstring
    already measures) to state truthfully — too slow to run on every
    load of a screen meant to be readable in under two minutes, and a
    stale/wrong "unblocks N" claim would be exactly the kind of
    confident-but-unverified number this project avoids everywhere else.
    Named here as a real, disclosed scope decision, not silently
    downgraded."""


def _universe_integrity_metrics(
    db: Session,
    *,
    market_cap_identity_pass_pct: Decimal | None,
    price_ratio_actions_confirmed_pct: Decimal | None,
) -> UniverseIntegrityMetrics:
    """The two pass-rate arguments are derived from the E0 check ledger
    (`_check_ledger`) and passed in so this function and the ledger cannot
    report different numbers for the same check. Both are now
    `passed ÷ (passed + failed)` — lines that could not be evaluated are
    excluded from the denominator, not counted as failures (§0)."""
    today = dt.date.today()

    issuer_codes = [
        c for (c,) in db.execute(select(func.distinct(Security.issuer_code))).all() if c is not None
    ]
    active_equity = db.execute(
        select(Security.issuer_code, Security.instrument_type).where(
            Security.delisting_date.is_(None),
            Security.instrument_type.in_(("ordinary", "non_voting")),
        )
    ).all()
    by_issuer: dict[str, list[str]] = {}
    for code, it in active_equity:
        by_issuer.setdefault(code, []).append(it)
    with_primary = sum(1 for c in issuer_codes if by_issuer.get(c))
    high_conf = sum(1 for c in issuer_codes if by_issuer.get(c, []).count("ordinary") == 1)

    unknown_type = db.scalar(
        select(func.count()).select_from(Security).where(
            Security.instrument_type.is_(None) | (Security.instrument_type == "unknown")
        )
    ) or 0

    open_by_type = {
        t: c
        for t, c in db.execute(
            select(DataAlert.alert_type, func.count())
            .where(DataAlert.resolved.is_(False))
            .group_by(DataAlert.alert_type)
        ).all()
    }
    quarantined_lines = db.scalar(
        select(func.count(func.distinct(DataAlert.ticker))).where(DataAlert.resolved.is_(False))
    ) or 0

    last_dates = [
        d
        for (d,) in db.execute(
            select(func.max(PriceDaily.date)).where(PriceDaily.close.is_not(None)).group_by(PriceDaily.ticker)
        ).all()
        if d is not None
    ]
    if last_dates:
        ages = sorted((today - d).days for d in last_dates)
        median_stale = ages[len(ages) // 2]
    else:
        median_stale = None

    # --- CoE availability (Part 7). PROXY, computed as two aggregate
    # queries rather than a per-name resolve (which is a Dimson-beta
    # computation apiece — ~25s for the ~60 financial lines against real
    # price history, far too slow for a page load). The one per-name
    # input a cost of equity needs is a computable beta; a beta needs at
    # least `beta.MIN_OBSERVATIONS` price sessions in its window. So:
    # financial-sector lines with that much recent price history, as a
    # share of all financial-sector lines. Measured against the real
    # resolve once, this tracks it within a line or two.
    from app.domain.beta import MIN_OBSERVATIONS

    _FIN = ("bank", "non_bank_finance", "insurance")
    fin_total = db.scalar(
        select(func.count())
        .select_from(Security)
        .where(Security.archetype.in_(_FIN), Security.delisting_date.is_(None))
    ) or 0
    beta_window_start = today - dt.timedelta(days=180)
    fin_with_history = db.scalar(
        select(func.count())
        .select_from(
            select(PriceDaily.ticker)
            .join(Security, Security.ticker == PriceDaily.ticker)
            .where(
                Security.archetype.in_(_FIN),
                Security.delisting_date.is_(None),
                PriceDaily.close.is_not(None),
                PriceDaily.date >= beta_window_start,
                PriceDaily.date <= today,
            )
            .group_by(PriceDaily.ticker)
            .having(func.count() >= MIN_OBSERVATIONS)
            .subquery()
        )
    ) or 0
    coe_pct = (
        (Decimal(fin_with_history) / Decimal(fin_total) * 100).quantize(Decimal("0.1"))
        if fin_total
        else None
    )

    suspended_or_delisted = db.scalar(
        select(func.count())
        .select_from(Security)
        .where(Security.trading_status.in_(("suspended", "delisted")))
    ) or 0

    return UniverseIntegrityMetrics(
        issuers_total=len(issuer_codes),
        issuers_with_a_primary_line=with_primary,
        issuers_high_confidence_binding=high_conf,
        lines_unknown_instrument_type=unknown_type,
        open_alerts_by_type=open_by_type,
        quarantined_line_count=quarantined_lines,
        market_cap_identity_pass_pct=market_cap_identity_pass_pct,
        price_ratio_actions_confirmed_pct=price_ratio_actions_confirmed_pct,
        median_price_staleness_days=median_stale,
        suspended_or_delisted_lines=suspended_or_delisted,
        cost_of_equity_available_pct=coe_pct,
        buy_side_verdicts_on_negative_earnings_trend=open_by_type.get(
            ui.ALERT_NEGATIVE_EARNINGS_TREND, 0
        ),
    )


def _pct(numer: int, denom: int) -> Decimal | None:
    return (Decimal(numer) / Decimal(denom) * 100).quantize(Decimal("0.1")) if denom else None


def _check_ledger(db: Session) -> list[CheckLedgerRow]:
    """`docs/CSE_Data_Health_Diagnosis_And_Protocol.md` E0 — every
    universe-wide check as pass / fail / not-evaluable with reason codes.
    No data is changed; this only re-expresses what the checks already
    know."""
    tickers = [t for (t,) in db.execute(select(Security.ticker))]
    scope = len(tickers)

    open_by_type: dict[str, int] = {
        t: c
        for t, c in db.execute(
            select(DataAlert.alert_type, func.count())
            .where(DataAlert.resolved.is_(False))
            .group_by(DataAlert.alert_type)
        )
    }

    # Latest published market cap + share count per ticker (FloatData is
    # ~one row per ticker per enrichment run — small).
    mcap: dict[str, Decimal] = {}
    shares: dict[str, int] = {}
    for tkr, pmc, sh in db.execute(
        select(FloatData.ticker, FloatData.published_market_cap, FloatData.shares_issued).order_by(
            FloatData.ticker, FloatData.as_of.desc()
        )
    ):
        if tkr in mcap or tkr in shares:
            continue
        if pmc is not None:
            mcap[tkr] = pmc
        if sh is not None:
            shares[tkr] = sh
    # `last_close` is only consulted for the market_cap_identity check,
    # which is not-evaluable without a published market cap anyway — so
    # only fetch closes for the handful of tickers that have one, rather
    # than scanning the whole price table.
    last_close: dict[str, Decimal] = {}
    if mcap:
        for tkr, c in db.execute(
            select(PriceDaily.ticker, PriceDaily.close)
            .where(PriceDaily.ticker.in_(list(mcap)), PriceDaily.close.is_not(None))
            .order_by(PriceDaily.ticker, PriceDaily.date.desc())
        ):
            last_close.setdefault(tkr, c)

    rows: list[CheckLedgerRow] = []

    # --- market_cap_identity: price × shares vs the exchange's published
    # figure, within 2%. Not evaluable without all three inputs.
    passed = failed = 0
    reasons: dict[str, int] = {}
    for t in tickers:
        pmc, sh, px = mcap.get(t), shares.get(t), last_close.get(t)
        if pmc is None:
            reasons["no_published_market_cap"] = reasons.get("no_published_market_cap", 0) + 1
        elif not sh:
            reasons["no_share_count"] = reasons.get("no_share_count", 0) + 1
        elif px is None:
            reasons["no_price_on_file"] = reasons.get("no_price_on_file", 0) + 1
        else:
            local = px * Decimal(sh)
            off = abs(pmc - local) / pmc if pmc else None
            if off is not None and off <= _MARKET_CAP_IDENTITY_TOLERANCE:
                passed += 1
            else:
                failed += 1
    ne = sum(reasons.values())
    rows.append(
        CheckLedgerRow(
            check="market_cap_identity",
            label="Market-cap identity (price × shares vs exchange)",
            passed=passed, failed=failed, not_evaluable=ne, not_evaluable_reasons=reasons,
            blocking=True, scope_total=scope,
            checkable_pct=_pct(passed + failed, scope),
            pass_pct_of_checkable=_pct(passed, passed + failed),
        )
    )

    # --- second_source_price: the reconciliation job (`app.jobs.second_
    # source_reconciliation`) only writes a row on MISMATCH — it keeps no
    # record of a line it checked and found fine — so a pass cannot be
    # counted, only a fail. Every other line is not-evaluable for that
    # reason, and saying so is the point of E0.
    ss_fail = open_by_type.get("second_source_mismatch", 0)
    rows.append(
        CheckLedgerRow(
            check="second_source_price",
            label="Price vs independent second source",
            passed=0, failed=ss_fail, not_evaluable=scope - ss_fail,
            not_evaluable_reasons={"check_records_no_passes": scope - ss_fail},
            blocking=True, scope_total=scope,
            checkable_pct=_pct(ss_fail, scope),
            pass_pct_of_checkable=_pct(0, ss_fail),
        )
    )

    # --- corporate_action_ratio: confirmed = pass, rejected = fail,
    # pending = not-evaluable. Replaces the old two-way "confirmed %"
    # which counted every unreviewed action as a failure.
    price_ratio_types = ("bonus_issue", "stock_split", "consolidation", "rights_issue")
    ca_confirmed = db.scalar(
        select(func.count()).select_from(CorporateAction).where(
            CorporateAction.type.in_(price_ratio_types), CorporateAction.confirmed_by.is_not(None)
        )
    ) or 0
    ca_rejected = db.scalar(
        select(func.count()).select_from(CorporateAction).where(
            CorporateAction.type.in_(price_ratio_types), CorporateAction.rejected_by.is_not(None)
        )
    ) or 0
    ca_total = db.scalar(
        select(func.count()).select_from(CorporateAction).where(
            CorporateAction.type.in_(price_ratio_types)
        )
    ) or 0
    ca_pending = ca_total - ca_confirmed - ca_rejected
    ca_feed_ran = _last_successful_run(db, "capture_corporate_actions") is not None
    ca_reason = "awaiting_review" if ca_feed_ran else "ca_feed_never_succeeded"
    rows.append(
        CheckLedgerRow(
            check="corporate_action_ratio",
            label="Corporate action → applied adjustment factor",
            passed=ca_confirmed, failed=ca_rejected, not_evaluable=ca_pending,
            not_evaluable_reasons={ca_reason: ca_pending} if ca_pending else {},
            blocking=False, scope_total=ca_total,
            checkable_pct=_pct(ca_confirmed + ca_rejected, ca_total),
            pass_pct_of_checkable=_pct(ca_confirmed, ca_confirmed + ca_rejected),
        )
    )

    # --- price_discontinuity: the check reads a corporate-action calendar
    # to decide whether a >30% one-day move is explained. If that feed
    # has never populated the table, every "unexplained" flag is
    # not-evaluable, not a fail (§3).
    disc_open = open_by_type.get(ui.ALERT_PRICE_DISCONTINUITY, 0)
    lines_with_history = db.scalar(
        select(func.count()).select_from(
            select(PriceDaily.ticker).group_by(PriceDaily.ticker).having(func.count() >= 2).subquery()
        )
    ) or 0
    if ca_feed_ran:
        disc_pass = max(0, lines_with_history - disc_open)
        rows.append(
            CheckLedgerRow(
                check="price_discontinuity",
                label="One-day price move vs corporate-action calendar",
                passed=disc_pass, failed=disc_open,
                not_evaluable=max(0, scope - lines_with_history),
                not_evaluable_reasons={"under_two_price_rows": max(0, scope - lines_with_history)},
                blocking=True, scope_total=scope,
                checkable_pct=_pct(disc_pass + disc_open, scope),
                pass_pct_of_checkable=_pct(disc_pass, disc_pass + disc_open),
            )
        )
    else:
        rows.append(
            CheckLedgerRow(
                check="price_discontinuity",
                label="One-day price move vs corporate-action calendar",
                passed=0, failed=0, not_evaluable=scope,
                not_evaluable_reasons={
                    "corporate_action_table_unpopulated": lines_with_history,
                    "under_two_price_rows": max(0, scope - lines_with_history),
                },
                blocking=True, scope_total=scope,
                checkable_pct=_pct(0, scope), pass_pct_of_checkable=None,
            )
        )

    # --- valuation_sanity: the §sanity gate (bvps>0, roe band, fv within
    # 5×, units) runs at valuation time, not here. Only its failures are
    # visible universe-wide as open alerts; the rest of the universe has
    # not been re-checked by this route, so it is not-evaluable here
    # rather than assumed to pass.
    vs_fail = open_by_type.get("valuation_sanity_block", 0)
    rows.append(
        CheckLedgerRow(
            check="valuation_sanity",
            label="Valuation plausibility gate (bvps, ROE, FV band, units)",
            passed=0, failed=vs_fail, not_evaluable=scope - vs_fail,
            not_evaluable_reasons={"only_evaluated_at_valuation_time": scope - vs_fail},
            blocking=True, scope_total=scope,
            checkable_pct=_pct(vs_fail, scope), pass_pct_of_checkable=_pct(0, vs_fail),
        )
    )

    return rows


@router.get("", response_model=DataHealth)
def data_health(db: Session = Depends(get_db)) -> DataHealth:
    securities_count = db.scalar(select(func.count()).select_from(Security)) or 0
    price_rows = db.scalar(select(func.count()).select_from(PriceDaily)) or 0
    latest_price_date = db.scalar(select(func.max(PriceDaily.date)))

    # Age is computed against the latest date we HAVE, not against
    # "expected" — the UI shows the number and lets a human judge it, per
    # §8's rule that stale data is labelled plainly rather than silently
    # rendered as current.
    today = dt.date.today()
    age_days = (today - latest_price_date).days if latest_price_date else None

    # --- Freshness, split (§5 / E8). Trading-day age counts weekdays only,
    # so a Friday-to-Monday gap over a weekend reads as fresh while a
    # missed weekday reads as a real gap. `missing_trading_days` lists the
    # weekday sessions after the newest row that have no price data at all.
    price_dates: set[dt.date] = set()
    missing_trading_days: list[dt.date] = []
    trading_day_age: int | None = None
    if latest_price_date is not None:
        price_dates = {
            d for (d,) in db.execute(
                select(func.distinct(PriceDaily.date)).where(
                    PriceDaily.date > latest_price_date - dt.timedelta(days=30)
                )
            )
        }
        weekdays_since = _weekdays_in(latest_price_date, today)
        trading_day_age = len(weekdays_since)
        missing_trading_days = [d for d in weekdays_since if d not in price_dates][:15]
    capture_last_ok = _last_successful_run(db, "capture_prices")
    macro_last_ok = _last_successful_run(db, "capture_macro")

    tickers_with_price = select(PriceDaily.ticker).distinct().subquery()
    securities_with_no_price = (
        db.scalar(
            select(func.count())
            .select_from(Security)
            .where(Security.ticker.not_in(select(tickers_with_price.c.ticker)))
        )
        or 0
    )

    issuer_count = (
        db.scalar(select(func.count(func.distinct(Security.issuer_code)))) or 0
    )
    registry_issuers = db.scalar(select(func.count()).select_from(IssuerRegistry)) or 0
    registry_delisted = (
        db.scalar(
            select(func.count()).select_from(IssuerRegistry).where(IssuerRegistry.delisted.is_(True))
        )
        or 0
    )
    registry_trading = (
        db.scalar(
            select(func.count())
            .select_from(IssuerRegistry)
            .where(IssuerRegistry.currently_trading.is_(True))
        )
        or 0
    )

    ca_total = db.scalar(select(func.count()).select_from(CorporateAction)) or 0
    ca_confirmed = (
        db.scalar(
            select(func.count()).select_from(CorporateAction).where(CorporateAction.confirmed_by.is_not(None))
        )
        or 0
    )
    ca_rejected = (
        db.scalar(
            select(func.count()).select_from(CorporateAction).where(CorporateAction.rejected_by.is_not(None))
        )
        or 0
    )

    f_total = db.scalar(select(func.count()).select_from(Fundamental)) or 0
    f_pending = (
        db.scalar(
            select(func.count())
            .select_from(Fundamental)
            .where(
                Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED,
                Fundamental.confirmed_by.is_(None),
            )
        )
        or 0
    )
    f_confirmed = (
        db.scalar(
            select(func.count()).select_from(Fundamental).where(Fundamental.confirmed_by.is_not(None))
        )
        or 0
    )

    week_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    f_confirmed_7d = (
        db.scalar(
            select(func.count())
            .select_from(Fundamental)
            .where(Fundamental.confirmed_at.is_not(None), Fundamental.confirmed_at >= week_ago)
        )
        or 0
    )
    ca_confirmed_7d = (
        db.scalar(
            select(func.count())
            .select_from(CorporateAction)
            .where(CorporateAction.confirmed_at.is_not(None), CorporateAction.confirmed_at >= week_ago)
        )
        or 0
    )

    alerts = db.scalars(
        select(DataAlert).where(DataAlert.resolved.is_(False)).order_by(DataAlert.raised_at.desc())
    ).all()

    f_pending_by_ticker = db.execute(
        select(Fundamental.ticker, func.count())
        .where(Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED, Fundamental.confirmed_by.is_(None))
        .group_by(Fundamental.ticker)
        .order_by(func.count().desc())
        .limit(8)
    ).all()

    ledger = _check_ledger(db)
    _by_check = {r.check: r for r in ledger}

    return DataHealth(
        securities_count=securities_count,
        issuer_count=issuer_count,
        registry_issuers=registry_issuers,
        registry_delisted=registry_delisted,
        registry_unknown_status=max(registry_issuers - registry_trading - registry_delisted, 0),
        price_rows=price_rows,
        latest_price_date=latest_price_date,
        price_feed_age_days=age_days,
        securities_with_no_price=securities_with_no_price,
        price_data_age_trading_days=trading_day_age,
        missing_trading_days=missing_trading_days,
        price_capture_last_success_at=capture_last_ok,
        price_capture_last_success_age_days=(
            (dt.datetime.now(dt.timezone.utc) - capture_last_ok).days
            if capture_last_ok is not None
            else None
        ),
        macro_feed_last_success_at=macro_last_ok,
        corporate_actions_total=ca_total,
        corporate_actions_pending=ca_total - ca_confirmed - ca_rejected,
        corporate_actions_confirmed=ca_confirmed,
        corporate_actions_rejected=ca_rejected,
        fundamentals_total=f_total,
        fundamentals_pending_confirmation=f_pending,
        fundamentals_confirmed=f_confirmed,
        fundamentals_confirmed_last_7d=f_confirmed_7d,
        corporate_actions_confirmed_last_7d=ca_confirmed_7d,
        fundamentals_pending_by_ticker=[
            TickerPendingCount(ticker=t, count=c) for t, c in f_pending_by_ticker
        ],
        quarantined=[
            QuarantinedTicker(
                ticker=a.ticker, alert_type=a.alert_type, detail=a.detail, raised_at=a.raised_at
            )
            for a in alerts
        ],
        universe_integrity=_universe_integrity_metrics(
            db,
            market_cap_identity_pass_pct=_by_check["market_cap_identity"].pass_pct_of_checkable,
            price_ratio_actions_confirmed_pct=_by_check["corporate_action_ratio"].pass_pct_of_checkable,
        ),
        universe_status=UniverseStatusCounts(**vars(universe_status_summary(db))),
        check_ledger=ledger,
    )
