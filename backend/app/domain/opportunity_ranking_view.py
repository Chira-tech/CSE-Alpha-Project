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

import datetime as dt
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.liquidity import percentile_rank
from app.domain.liquidity_view import universe_amihud_ratios
from app.domain.macro_engine_view import regime_for
from app.domain.provenance import can_enter_valuation
from app.domain.valuation_view import valuation_summary_for
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
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityRankingView:
    as_of: dt.date
    ranked: tuple[OpportunityCandidate, ...]
    """Every candidate with a real, computable price-ladder zone —
    sorted by `gap_to_buy_below_pct` ascending (most below your
    buy-below price first)."""

    excluded: tuple[OpportunityCandidate, ...]
    """Confirmed-data tickers this view could NOT rank, each with its
    own real `warnings` explaining why — never silently dropped."""


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


def opportunity_ranking_for(db: Session, as_of: dt.date | None = None) -> OpportunityRankingView:
    stamp = as_of or dt.date.today()

    with _cache_lock:
        cached = _cache.get(stamp)
        if cached is not None and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    view = _opportunity_ranking_for_uncached(db, stamp)

    with _cache_lock:
        _cache[stamp] = (time.monotonic(), view)
        # Never let this grow across days of dev-server uptime — a
        # correctness non-issue (each entry is real for its own `as_of`
        # forever) but a real, if slow, memory leak otherwise.
        stale_days = [d for d in _cache if d != stamp and (time.monotonic() - _cache[d][0]) >= _CACHE_TTL_SECONDS]
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
                dispersion_pct=None,
                warnings=(
                    f"{ticker!r} is quarantined — its stored adjustment factors failed the §7 "
                    "reconciliation check against real corporate actions, so its numbers are not "
                    "trusted for ranking until a human resolves the underlying data-health alert.",
                ),
            ))
            continue

        summary = valuation_summary_for(
            db, ticker, archetype, price, stamp,
            universe_liquidity_ratios=universe_ratios,
            universe_liquidity_percentiles=universe_percentiles,
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
            warnings=tuple(warnings),
        )

        if candidate.price_ladder_zone is not None and candidate.gap_to_buy_below_pct is not None:
            ranked.append(candidate)
        else:
            excluded.append(candidate)

    ranked.sort(key=lambda c: c.gap_to_buy_below_pct)  # most below buy-below first
    return OpportunityRankingView(as_of=stamp, ranked=tuple(ranked), excluded=tuple(excluded))
