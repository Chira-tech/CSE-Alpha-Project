"""
§40's "opportunity ranking" — a REAL, currently-computable subset, not
the full spec. §40 itself defines the target metric as "risk-adjusted
expected return net of the cost of building the position", fed by the
full §38 composite score (valuation 25%, business quality 25%, growth
15%, financial strength 10%, macro & sector fit 10%, timing & momentum
10%, risk 5%, integrity veto) after §39's sequential fusion.

CORRECTED (23 Aug 2026) — the paragraph this replaces claimed Carhart
certification and the timing battery weren't built; both are real and
live now (`app.domain.carhart_regression`, `app.domain.timing_battery`),
folded into the §38 composite score any company file already shows
(`GET /composite-score/{ticker}`). What's still missing, and is the
actual reason this module can't just rank by that score directly: the
composite score is a real per-ticker computation measured at ~11s each
(see `app.domain.sector_drilldown_view`'s own docstring for the live
measurement) — ranking the WHOLE universe by it would mean running that
for every ticker on every request, a real latency cost this module
doesn't pay. Piotroski/Altman/Beneish/Sloan also still aren't wired
into a single automated earnings-integrity veto (§14).

What DOES exist, real and live, is the price ladder (§25-26) — a real
fair value blended from however many of the 3-5 anchors are computable
for a given company, and a real margin-of-safety-adjusted buy-below
price. This module ranks by that alone: `gap_to_buy_below_pct`, the
real, signed distance between the current price and the buy-below
price. This is a genuine, honest, useful ordering — "how far below (or
above) the price you said you'd buy at is this trading right now" — but
it is NOT §40's full risk-adjusted-return-net-of-costs metric, and this
module's own docstring says so rather than letting the screen imply
otherwise.

UNIVERSE: every ticker with at least one CONFIRMED (non-draft)
fundamental line — the same "cannot enter a valuation until a human
confirms it" rule (§8) every other real number in this system already
obeys. A ticker with only draft/AI-assisted fundamentals is excluded
from ranking entirely, not shown with a guessed anchor.

A NEGATIVE OR ZERO BLENDED FAIR VALUE IS A REAL, ALREADY-HANDLED CASE,
NOT A BUG HERE. `app.domain.price_ladder.compute_price_ladder` already
refuses to build zones from a non-positive fair value and says so in
its own `warnings` — found live (18 Aug 2026) on CBNK.N0000, EAST.N0000
and JKH.N0000, whose residual-income/justified-P/B anchors currently
produce a negative blended fair value from their real confirmed
figures. This view surfaces that ticker as excluded-with-reason rather
than silently dropping it or forcing a fake positive number.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.coverage_gates import gate1_liquidity_reason
from app.domain.liquidity import percentile_rank
from app.domain.liquidity_view import liquidity_snapshot_for, universe_amihud_ratios
from app.domain.macro_engine_view import regime_for
from app.domain.provenance import can_enter_valuation
from app.domain.valuation_view import peer_multiples_for, valuation_summary_for
from app.jobs.reconciliation import is_quarantined
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security


@dataclass(frozen=True)
class OpportunityCandidate:
    ticker: str
    name: str
    archetype: str | None
    current_price: Decimal | None
    blended_fair_value_per_share: Decimal | None
    margin_of_safety_pct: Decimal
    price_ladder_zone: str | None
    buy_below_price: Decimal | None
    gap_to_buy_below_pct: Decimal | None
    dispersion_pct: Decimal | None
    verdict: str
    """The final call from `app.domain.decision.compute_decision` —
    Strong Buy / Buy / Accumulate / Hold / Trim / Sell / Insufficient
    data / Withheld. Populated even for `excluded` candidates (it will
    read 'Insufficient data' or 'Withheld' there), so a screen never has
    to infer the reason from an absence."""

    decision_confidence: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityRankingView:
    as_of: dt.date
    ranked: tuple[OpportunityCandidate, ...]
    """Every candidate with a real, computable price-ladder zone AND a
    real, position-independent §11.1 Gate 1 liquidity pass (see
    `gate1_liquidity_reason`) — sorted by `decision_confidence` first
    (high, then medium, then low) and `gap_to_buy_below_pct` only as the
    tie-breaker within a confidence tier. NOT sorted by discount alone:
    a real, live audit (30 Aug 2026) found that ordering let a handful
    of single-anchor, low-confidence, asset/NAV-only reads dominate the
    top of the list, crowding out better-corroborated names further
    down — see this module's own `_opportunity_ranking_for_uncached`
    comment for the full finding."""

    excluded: tuple[OpportunityCandidate, ...]
    """Confirmed-data tickers this view could NOT rank, each with its
    own real `warnings` explaining why — never silently dropped. This
    now includes a real candidate with an otherwise-computable price-
    ladder zone that fails the real §11.1 Gate 1 liquidity check (traded
    too rarely, or too little rupee value per day, to be practically
    buyable) — a real fair-value gap does not make a real opportunity if
    the stock cannot actually be traded."""


def _latest_price(db: Session, ticker: str, as_of: dt.date) -> Decimal | None:
    return db.scalar(
        select(PriceDaily.close)
        .where(PriceDaily.ticker == ticker, PriceDaily.date <= as_of, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )


def _confirmed_tickers(db: Session) -> list[str]:
    """Every ticker with at least one line item whose provenance tier
    `can_enter_valuation` — the same real §8 rule `_confirmable_line_
    items` (app.domain.valuation_view) already enforces per-line, not
    `confirmed_by is not None`: a Reported-tier figure entered directly
    from a filing (never routed through the AI-assisted confirm queue)
    is real and usable without ever having a `confirmed_by` value."""
    enterable = [t for t in ProvenanceTier if can_enter_valuation(t)]
    return sorted(
        t
        for (t,) in db.execute(
            select(Fundamental.ticker).where(Fundamental.provenance_tier.in_(enterable)).distinct()
        ).all()
    )


# R1 — real, measured cost this function's own callers all independently
# pay: ~18-25s per call even after the two O(n^2) fixes documented above,
# because it genuinely does real per-ticker valuation work (cost of
# equity, DCF, triangulation) for every confirmed ticker — this isn't
# wasted/duplicated work left to trim, it's the actual computation. What
# WAS wasteful, found live: a normal cold page load calls this THREE
# times independently within seconds of each other (Today's own board
# section, the Opportunities screen, and Macro's sector drill-down all
# call it), each paying the full cost separately for what is, in
# practice, the identical result. A short, disclosed TTL cache — never
# silently treated as "live" data, `OpportunityRankingView.as_of` still
# reports the real date it was computed for — cuts that 3x real cost
# down to 1x for the common case without touching the actual valuation
# math at all. 45s: long enough to cover the today-load-then-drilldown
# window, short enough that this app's own 12-36 month horizon (this
# session's whole governing framing) is never meaningfully served a
# stale number — the newest confirm/recompute is at most 45s away from
# being reflected, not minutes or hours.
_CACHE_TTL_SECONDS = 45
_cache_lock = threading.Lock()
_cache: dict[dt.date, tuple[float, OpportunityRankingView]] = {}

# Single-flight guard, added 30 Aug 2026. The TTL cache above only helps
# callers that arrive AFTER a compute has finished. On a cold cache the
# frontend fires /opportunities several times within a second (Today's
# board section, the Opportunities screen, and the dev-server data-refresh
# poll all call it), and every one of those callers missed the cache and
# started its OWN full ~20s valuation pass — N passes running at once, all
# contending on the same 129 MB SQLite file, so each ran far slower than
# 20s, the browser timed out at ~30s and retried, and the cache never got
# a chance to populate. Live symptom: the Opportunities tab stuck on its
# loading skeleton forever. Holding one lock per `as_of` stamp collapses
# those N cold callers into 1 real compute + (N-1) cache hits.
_compute_locks_guard = threading.Lock()
_compute_locks: dict[dt.date, threading.Lock] = {}


def _compute_lock_for(stamp: dt.date) -> threading.Lock:
    with _compute_locks_guard:
        lock = _compute_locks.get(stamp)
        if lock is None:
            lock = threading.Lock()
            _compute_locks[stamp] = lock
        return lock


def _cached_view(stamp: dt.date) -> OpportunityRankingView | None:
    with _cache_lock:
        cached = _cache.get(stamp)
        if cached is not None and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]
    return None


def clear_cache() -> None:
    """Test-only escape hatch (and a real, honest one for anything else
    that needs to force a fresh read — e.g. a future 'rebuild now' admin
    action). A module-level cache shared across every caller is exactly
    right for the real dev-server process this exists to speed up (one
    process, one real database), but it is exactly wrong left unguarded
    across a test SUITE: two tests in the same pytest process share this
    same dict, and without a way to reset it a second test seeding its
    own fresh `as_of`-dated data into its own fresh in-memory DB would
    silently be handed the FIRST test's cached result instead — caught
    live building this cache, not hypothetical (see `conftest.py`'s own
    autouse fixture that calls this before every test)."""
    with _cache_lock:
        _cache.clear()
    with _compute_locks_guard:
        _compute_locks.clear()


def opportunity_ranking_for(db: Session, as_of: dt.date | None = None) -> OpportunityRankingView:
    stamp = as_of or dt.date.today()

    cached = _cached_view(stamp)
    if cached is not None:
        return cached

    # Single-flight: the first caller to reach here computes; any others
    # that arrive while it runs block on this lock and then fall straight
    # through to the cache hit below rather than starting their own pass.
    with _compute_lock_for(stamp):
        cached = _cached_view(stamp)
        if cached is not None:
            return cached

        view = _opportunity_ranking_for_uncached(db, stamp)

        with _cache_lock:
            _cache[stamp] = (time.monotonic(), view)
            # Never let this grow across days of dev-server uptime — a
            # correctness non-issue (each entry is real for its own `as_of`
            # forever) but a real, if slow, memory leak otherwise.
            stale_days = [
                d for d in _cache
                if d != stamp and (time.monotonic() - _cache[d][0]) >= _CACHE_TTL_SECONDS
            ]
            for d in stale_days:
                del _cache[d]

    return view


def _opportunity_ranking_for_uncached(db: Session, stamp: dt.date) -> OpportunityRankingView:
    tickers = _confirmed_tickers(db)

    # Computed ONCE and shared across every candidate — see
    # `app.domain.valuation_view.valuation_summary_for`'s own docstring
    # for why (a real 89-second-for-9-positions bug, already fixed once
    # for the portfolio view; the same sharing applies here for the
    # same reason).
    universe_ratios = universe_amihud_ratios(db, stamp)
    # A SECOND, independent half of that same cost class, found live
    # later (20 Aug 2026): sharing `universe_ratios` alone still left
    # `percentile_rank` — an O(n²) full universe re-ranking — running
    # fresh on every one of the ~6 per-ticker calls into `cost_of_equity_
    # for` that `valuation_summary_for` makes. Profiled live: 1,526 calls
    # in one real `/opportunities` request, 61+ million inner
    # comparisons, ~24 of the endpoint's ~25 real seconds. Computed once
    # here instead, exactly the same fix as `universe_ratios` itself —
    # see `app.domain.valuation_view.valuation_summary_for`'s own
    # docstring on `universe_liquidity_percentiles`.
    universe_percentiles = percentile_rank(universe_ratios)
    # Same reasoning, same fix, for the regime read — see `valuation_
    # summary_for`'s own docstring on `regime_view`. This one mattered
    # even more here than in the portfolio view: with the confirm queue
    # growing past ~7,500 confirmed rows across many tickers (a real
    # bulk-confirm pass, not a hypothetical), the per-ticker Markov
    # re-fit made this endpoint take 60+ real seconds and effectively
    # unusable — reproduced live, not assumed, before this fix.
    regime_view = regime_for(db, stamp)
    # §20.1 peer multiples — one universe pass, shared into every
    # per-ticker call, same discipline as `universe_ratios` above.
    peer_multiples = peer_multiples_for(db, stamp)

    ranked: list[OpportunityCandidate] = []
    excluded: list[OpportunityCandidate] = []

    for ticker in tickers:
        security = db.get(Security, ticker)
        name = security.name if security is not None else ticker
        archetype = security.archetype if security is not None else None
        price = _latest_price(db, ticker, stamp)

        # OI-3 (docs/audits/R1_OPEN_ISSUES.md): `is_quarantined`'s own
        # docstring has always claimed a quarantined ticker is "excluded
        # from every model until a human resolves it" (§7/§50) — this is
        # the first place that claim is actually made true. A quarantined
        # ticker is never ranked; it still appears (in `excluded`, never
        # silently dropped), with the quarantine reason as its only
        # warning, so its state is visible rather than just absent.
        if is_quarantined(db, ticker):
            excluded.append(OpportunityCandidate(
                ticker=ticker, name=name, archetype=archetype, current_price=price,
                blended_fair_value_per_share=None, margin_of_safety_pct=Decimal(0),
                price_ladder_zone=None, buy_below_price=None, gap_to_buy_below_pct=None,
                dispersion_pct=None, verdict="Withheld", decision_confidence="low",
                warnings=(
                    f"{ticker!r} is quarantined — an open data-health alert, a failed §7 "
                    "adjustment-factor reconciliation, or a suspended/delisted trading status. "
                    "Its numbers are not trusted for ranking until a human resolves it; the "
                    "specific reason is on the Data Health page.",
                ),
            ))
            continue

        summary = valuation_summary_for(
            db, ticker, archetype, price, stamp,
            universe_liquidity_ratios=universe_ratios,
            universe_liquidity_percentiles=universe_percentiles,
            universe_peer_multiples=peer_multiples,
            regime_view=regime_view,
        )
        ladder = summary.price_ladder
        warnings = list(ladder.warnings) if ladder is not None else []
        if price is None:
            warnings.append(f"No real live price found for {ticker!r} on or before {stamp}.")
        if summary.triangulation.blended_fair_value_per_share is None:
            warnings.append("No triangulated fair value computable from confirmed data yet.")
        elif summary.sanity is not None and summary.sanity.blocked:
            # TASK 0.1: a blended fair value existed but failed the
            # plausibility gate — `ladder` is None for THIS reason, not
            # "no anchors", and that must be visible or this candidate
            # would show up in `excluded` with no stated reason at all.
            warnings.append(
                f"Fair value withheld by the plausibility gate: {', '.join(summary.sanity.block_reasons)}"
            )

        candidate = OpportunityCandidate(
            ticker=ticker,
            name=name,
            archetype=archetype,
            current_price=price,
            blended_fair_value_per_share=summary.triangulation.blended_fair_value_per_share,
            margin_of_safety_pct=summary.margin_of_safety.total_pct,
            price_ladder_zone=ladder.current_zone if ladder is not None else None,
            buy_below_price=ladder.buy_below_price if ladder is not None else None,
            gap_to_buy_below_pct=ladder.gap_to_buy_below_pct if ladder is not None else None,
            dispersion_pct=summary.triangulation.dispersion_pct,
            verdict=summary.decision.verdict,
            decision_confidence=summary.decision.confidence,
            warnings=tuple(warnings),
        )

        if candidate.price_ladder_zone is not None and candidate.gap_to_buy_below_pct is not None:
            # TASK "are these opportunities really worth buying" (30 Aug
            # 2026): a real, live audit found the top-ranked "Accumulate"
            # candidates included stocks trading LKR 5,000-200,000/day —
            # far below §11.1 Gate 1's own LKR 2,000,000 bar, and
            # essentially unbuyable at any meaningful size regardless of
            # how real the valuation discount is. Every ranked candidate
            # now gets this real, position-independent liquidity check
            # before it can rank — a real gap in the value it computed
            # correctly does not make it a real opportunity if nobody can
            # actually trade it.
            snapshot = liquidity_snapshot_for(db, ticker, stamp)
            liquidity_reason = gate1_liquidity_reason(
                snapshot.median_daily_turnover_60d_lkr, snapshot.days_traded_60d,
                days_of_real_history_available=snapshot.days_of_real_history_available,
            )
            if liquidity_reason is not None:
                excluded.append(
                    dataclasses.replace(
                        candidate,
                        warnings=candidate.warnings + (
                            f"Fails §11.1 Gate 1 (liquidity), so not ranked despite a real "
                            f"computable price-ladder zone: {liquidity_reason}.",
                        ),
                    )
                )
            else:
                ranked.append(candidate)
        else:
            excluded.append(candidate)

    # Sorted by decision confidence first (high, then medium, then low —
    # unrecognised grades sort last rather than crashing), gap_to_buy_
    # below_pct only as the tie-breaker WITHIN a confidence tier. Found
    # live in the same audit as the liquidity gate above: sorting by raw
    # discount alone let a handful of single-anchor, "low"-confidence,
    # asset/NAV-only reads dominate the top of the list — real numbers,
    # but the LEAST corroborated ones in the whole ranking, crowding out
    # better-supported multi-anchor "medium"/"high" confidence reads
    # further down. Confidence is not hidden or discarded either way —
    # every candidate still shows its own real `decision_confidence` —
    # this only changes which one a reader sees FIRST.
    _CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}
    ranked.sort(
        key=lambda c: (_CONFIDENCE_RANK.get(c.decision_confidence, 3), c.gap_to_buy_below_pct)
    )
    return OpportunityRankingView(as_of=stamp, ranked=tuple(ranked), excluded=tuple(excluded))
