"""
§38's composite investment score, computed for the WHOLE confirmed
universe in one shared pass and ranked — the piece `app.domain.
composite_score_view` names in its own docstring as the universe pass
that "will unblock [Valuation and Growth] next, once built." This module
is that build.

WHAT THIS ADDS OVER THE SINGLE-TICKER VIEW. `composite_score_view.
composite_score_for` deliberately shows Valuation (discount to blended
fair value) and Growth (§34 national-projects revenue adjustment) as
evidence only, never blended, because ranking either one needs every
OTHER ticker's same figure and that universe pass is a real latency
regression on a single interactive request. This module's own pass was
measured at ~70s over the ~280-ticker confirmed universe on the SQLite
dev database (30 Aug 2026) — the same order as `app.domain.
opportunity_ranking_view`'s ~18-25s valuation sweep plus a per-ticker
§33 macro-sector-fit read, §37 timing battery, and §34 register lookup
on top. Here the universe pass IS the request: it runs once, is cached
with the same disclosed TTL `app.domain.opportunity_ranking_view` uses,
and feeds the Valuation pillar into `total_score` through §12's own
generic sector-percentile machinery (`app.domain.sector_percentiles.
sector_percentiles_for_ratio`, reused unmodified — it is explicitly
generic over any `(ratio_key, values_by_ticker)` pair, not just the 13
§12 ratios). The Growth pillar is ranked the same way the moment
`MIN_TICKERS_FOR_GROWTH_RANK` confirmed-universe tickers have a
national-projects revenue impact; until then it is honestly excluded
with that count as the reason, never a fabricated 0 (§1 law 4).

WHAT THIS IS STILL NOT. §40's full target is risk-adjusted expected
return net of the cost of building the position, after §39's sequential
fusion, with §14's automated earnings-integrity veto (Piotroski / Altman
/ Beneish / Sloan) applied. None of §39, §40's cost leg, or §14's
automated veto exist yet. This module ranks by the §38 composite score
alone. Integrity is carried on every row exactly as `composite_score_
view` reports it — `evaluable=False` — and is NEVER applied as a filter
here, because "no red flag found" and "never looked" are different
states (§1 law 4 / §11.1).

UNIVERSE: identical to `app.domain.opportunity_ranking_view` — every
ticker with at least one CONFIRMED (non-draft) fundamental line (§8),
minus anything currently quarantined (§7 / §50), which is surfaced in
`excluded` with its quarantine reason rather than silently dropped. A
confirmed ticker with zero computable pillars is likewise surfaced in
`excluded` with its per-pillar reasons, never a bare absence.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.composite_score import (
    BUSINESS_QUALITY_RATIO_KEYS,
    FINANCIAL_STRENGTH_INVERT,
    FINANCIAL_STRENGTH_RATIO_KEYS,
    PILLAR_SPECS,
    PILLAR_SPECS_BY_KEY,
    ratio_pillar_score,
    renormalize,
)
from app.domain.composite_score_view import (
    UNEVALUABLE_INTEGRITY,
    IntegrityView,
    PillarScore,
    _crash_guard_active,
)
from app.domain.liquidity import percentile_rank
from app.domain.liquidity_view import liquidity_percentile_for, universe_amihud_ratios
from app.domain.macro_engine_view import regime_for
from app.domain.macro_sector_fit_view import macro_sector_fit_for
from app.domain.national_projects_view import (
    confirmed_base_case_revenue_growth_adjustment_for,
)
from app.domain.instrument_type import is_common_equity
from app.domain.opportunity_ranking_view import _confirmed_tickers, _latest_price
from app.domain.sector_percentiles import (
    _percentile_rank_ascending,
    sector_percentiles_for_ratio,
)
from app.domain.sector_percentiles_view import all_sector_percentiles
from app.domain.sector_sensitivity_view import sector_sensitivity_matrix_for
from app.domain.timing_battery_view import timing_battery_for
from app.domain.valuation_view import peer_multiples_for, valuation_summary_for
from app.jobs.reconciliation import is_quarantined
from app.models.securities import Security

#: Growth here is NOT a sector-relative concept (a national-projects
#: revenue tailwind is company-specific, not "vs. your sector"), so its
#: percentile is a plain universe-wide ascending rank rather than §12's
#: sector-grouped one. It still needs a real peer set to mean anything —
#: the same floor `app.domain.sector_percentiles.MIN_CONSTITUENTS_FOR_
#: SECTOR_PERCENTILE` sets for the same reason ("ranking against two
#: peers is technically computable and practically meaningless").
MIN_TICKERS_FOR_GROWTH_RANK = 3

#: The synthetic ratio key the Valuation pillar's discount-to-fair-value
#: figure is ranked under. Not one of §12's real ratios — `sector_
#: percentiles_for_ratio` is generic over the key, so this reuses that
#: machinery (sector grouping, 1%/99% winsorization, ascending rank)
#: without inventing a second percentile scale.
VALUATION_DISCOUNT_KEY = "valuation_discount"


@dataclass(frozen=True)
class RankedComposite:
    ticker: str
    name: str
    archetype: str | None
    cse_sector: str | None
    """The exchange's own CSE sector for this ticker (`Security.cse_sector`)
    — carried on the row so the redesign's sector-average-score heatmap
    (`docs/CSE_Alpha_Engine_Scoreboard_Queue_Redesign.md` §1.2) groups by
    a real classification rather than re-querying per row. `None` when the
    security isn't classified yet."""
    verdict: str
    """The final call from `app.domain.decision.compute_decision`, carried
    through verbatim from the same `valuation_summary_for` pass this view
    already runs per ticker (`summary.decision.verdict`) — Strong Buy /
    Buy / Accumulate / Hold / Trim / Sell / Insufficient data / Withheld.
    This is the real decision-engine verdict, NOT a mapping invented from
    `total_score` (§38 deliberately leaves score→action thresholds open —
    see `app.domain.composite_score`'s module docstring). Populated on
    `excluded` rows too (reads 'Withheld' / 'Insufficient data' there), so
    a screen never has to infer it from an absence."""
    decision_confidence: str
    """`summary.decision.confidence` — 'high' / 'medium' / 'low', the same
    grade `app.domain.opportunity_ranking_view` sorts its board by."""
    total_score: Decimal | None
    """0-100, the weighted mean of whichever pillars are computable for
    this ticker with weights renormalized among them (`app.domain.
    composite_score.renormalize`). `None` — and the ticker lands in
    `excluded`, never `ranked` — when zero pillars are computable."""
    pillars: tuple[PillarScore, ...]
    """All 7 §38 pillars in spec order, each with its own score /
    included flag / reason — same shape the single-ticker `GET
    /composite-score/{ticker}` returns, so a row is self-explaining."""
    pillars_included: int
    """How many of the 7 pillars actually fed `total_score`. A score
    built from 2 thin pillars and one built from all 7 are NOT equally
    trustworthy even at the same number — surfaced (never hidden inside
    `total_score`) so a reader can see the corroboration behind each row,
    the same discipline `app.domain.opportunity_ranking_view`'s own
    confidence-first sort applies for the same reason."""
    weight_covered_pct: Decimal
    """Sum of the §38-specified weights of the pillars that fed the
    score, before renormalization (0-100). 100 means all 7 pillars were
    computable; a low number means the score leans on a small slice of
    §38's intended basis."""
    weight_used_pct: dict[str, Decimal]
    integrity: IntegrityView
    """Always `UNEVALUABLE_INTEGRITY` today — carried, never applied as a
    filter (see module docstring)."""
    blended_fair_value_per_share: Decimal | None
    current_price: Decimal | None
    discount_to_fair_value_pct: Decimal | None
    """`(blended_fair_value - price) / blended_fair_value` — the raw
    quantity the Valuation pillar's percentile is computed from, kept on
    the row as evidence so the pillar score is never one opaque number."""
    valuation_pillar_percentile: Decimal | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CompositeRankingView:
    as_of: dt.date
    ranked: tuple[RankedComposite, ...]
    """Confirmed-universe tickers with a real `total_score`, sorted by it
    descending (ticker as the stable tie-break). This is §38's composite
    score — NOT §40's full risk-adjusted-return-net-of-cost metric and
    NOT §39's fused list; see module docstring."""
    excluded: tuple[RankedComposite, ...]
    """Confirmed-universe tickers this view could not score — quarantined
    (§7), or zero computable pillars — each with a real reason in
    `warnings` and/or its per-pillar `reason`s, never silently dropped."""


# Same disclosed-TTL cache pattern as `app.domain.opportunity_ranking_
# view` (see that module's own long comment for the full rationale): one
# module-level dict shared across every caller in the single real dev-
# server process this exists to speed up, keyed by `as_of`, guarded so a
# test suite's two in-memory DBs on the same date can't share a stale
# entry. 45s — long enough to cover a today-load-then-drilldown window,
# far inside this system's own 12-36 month horizon, so the newest
# confirm/recompute is at most 45s from being reflected.
_CACHE_TTL_SECONDS = 45
_cache_lock = threading.Lock()
_cache: dict[dt.date, tuple[float, CompositeRankingView]] = {}


def clear_cache() -> None:
    """Test-only escape hatch (and an honest 'rebuild now' hook for any
    future admin action) — mirrors `app.domain.opportunity_ranking_view.
    clear_cache`. `conftest.py`'s autouse fixture calls this before and
    after every test for the same reason it does there."""
    with _cache_lock:
        _cache.clear()


def composite_ranking_for(db: Session, as_of: dt.date | None = None) -> CompositeRankingView:
    stamp = as_of or dt.date.today()

    with _cache_lock:
        cached = _cache.get(stamp)
        if cached is not None and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    view = _composite_ranking_for_uncached(db, stamp)

    with _cache_lock:
        _cache[stamp] = (time.monotonic(), view)
        stale = [
            d
            for d in _cache
            if d != stamp and (time.monotonic() - _cache[d][0]) >= _CACHE_TTL_SECONDS
        ]
        for d in stale:
            del _cache[d]

    return view


@dataclass
class _Work:
    """Per-ticker intermediate state from the first pass — everything
    needed to assemble the final `RankedComposite` once the two
    universe-wide percentile maps (Valuation, Growth) are known."""

    ticker: str
    name: str
    archetype: str | None
    verdict: str
    decision_confidence: str
    bq_score: Decimal | None
    fs_score: Decimal | None
    macro_score: Decimal | None
    macro_reason: str | None
    timing_score: Decimal | None
    risk_score: Decimal | None
    blended_fair_value: Decimal | None
    current_price: Decimal | None
    discount: Decimal | None


def _ratio_pillar(
    key: str, score: Decimal | None, ratio_keys: tuple[str, ...], extra: str = ""
) -> PillarScore:
    spec = PILLAR_SPECS_BY_KEY[key]
    return PillarScore(
        key, spec.label, spec.weight_pct, score, score is not None,
        None if score is not None else (
            f"No sector-relative percentile available for any {spec.label.lower()} ratio "
            f"({', '.join(ratio_keys)}).{extra}"
        ),
    )


def _composite_ranking_for_uncached(db: Session, stamp: dt.date) -> CompositeRankingView:
    # Only common equity is valued (`app.domain.instrument_type`): `.U`
    # closed-end fund units, `.P` preference lines, `.D` debentures, `.R`
    # rights and `.W` warrants are not operating businesses and were only
    # ever landing in the scoreboard as "Insufficient data" rows. Their
    # exclusion is a property of the instrument, not a data gap.
    tickers = [t for t in _confirmed_tickers(db) if is_common_equity(t)]

    # --- Shared universe-wide passes, each computed ONCE and threaded
    # into every per-ticker call — the exact sharing `app.domain.
    # opportunity_ranking_view` already does, for the same measured
    # reason (a real 89s-for-9-positions bug when these were recomputed
    # per ticker).
    universe_ratios = universe_amihud_ratios(db, stamp)
    universe_percentiles = percentile_rank(universe_ratios)
    peer_multiples = peer_multiples_for(db, stamp)
    regime_view = regime_for(db, stamp)
    regime_label = regime_view.result.label if regime_view.result is not None else None
    sector_sensitivity_view = sector_sensitivity_matrix_for(db, stamp)
    crash_guard_active = _crash_guard_active(db, stamp)
    all_percentiles = all_sector_percentiles(db, stamp)

    sector_rows = db.execute(
        select(Security.ticker, Security.cse_sector, Security.gics_sector)
    ).all()
    narrow_sector_by_ticker = {t: cse for t, cse, _ in sector_rows}
    wide_sector_by_ticker = {t: gics for t, _, gics in sector_rows}

    quarantined: list[RankedComposite] = []
    work: list[_Work] = []
    discounts_by_ticker: dict[str, Decimal] = {}
    growth_adj_by_ticker: dict[str, Decimal] = {}

    for ticker in tickers:
        if is_quarantined(db, ticker):
            security = db.get(Security, ticker)
            quarantined.append(
                RankedComposite(
                    ticker=ticker,
                    name=security.name if security is not None else ticker,
                    archetype=security.archetype if security is not None else None,
                    cse_sector=narrow_sector_by_ticker.get(ticker),
                    verdict="Withheld",
                    decision_confidence="low",
                    total_score=None,
                    pillars=(),
                    pillars_included=0,
                    weight_covered_pct=Decimal(0),
                    weight_used_pct={},
                    integrity=UNEVALUABLE_INTEGRITY,
                    blended_fair_value_per_share=None,
                    current_price=None,
                    discount_to_fair_value_pct=None,
                    valuation_pillar_percentile=None,
                    warnings=(
                        f"{ticker!r} is quarantined — an open data-health alert, a failed §7 "
                        "adjustment-factor reconciliation, or a suspended/delisted trading "
                        "status. Its numbers are not trusted for ranking until a human resolves "
                        "it; the specific reason is on the Data Health page.",
                    ),
                )
            )
            continue

        security = db.get(Security, ticker)
        name = security.name if security is not None else ticker
        archetype = security.archetype if security is not None else None
        price = _latest_price(db, ticker, stamp)
        percentiles = all_percentiles.get(ticker, {})

        summary = valuation_summary_for(
            db, ticker, archetype, price, stamp,
            universe_liquidity_ratios=universe_ratios,
            universe_liquidity_percentiles=universe_percentiles,
            universe_peer_multiples=peer_multiples,
            regime_view=regime_view,
        )
        bfv = summary.triangulation.blended_fair_value_per_share
        discount: Decimal | None = None
        if bfv is not None and bfv > 0 and price is not None:
            discount = (bfv - price) / bfv
            discounts_by_ticker[ticker] = discount

        bq_score, _ = ratio_pillar_score(percentiles, BUSINESS_QUALITY_RATIO_KEYS, frozenset())
        fs_score, _ = ratio_pillar_score(
            percentiles, FINANCIAL_STRENGTH_RATIO_KEYS, FINANCIAL_STRENGTH_INVERT
        )
        macro_fit = macro_sector_fit_for(
            db, ticker, stamp,
            sector_sensitivity_view=sector_sensitivity_view,
            regime_label=regime_label,
        )
        timing_result = timing_battery_for(
            db, ticker, stamp,
            business_quality_score=bq_score,
            crash_guard_active=crash_guard_active,
        )
        risk_score = liquidity_percentile_for(
            db, ticker, stamp,
            universe_ratios=universe_ratios,
            universe_percentiles=universe_percentiles,
        )

        growth_adj, _contrib = confirmed_base_case_revenue_growth_adjustment_for(db, ticker, stamp)
        if growth_adj is not None:
            growth_adj_by_ticker[ticker] = growth_adj

        work.append(
            _Work(
                ticker=ticker, name=name, archetype=archetype,
                verdict=summary.decision.verdict,
                decision_confidence=summary.decision.confidence,
                bq_score=bq_score, fs_score=fs_score,
                macro_score=macro_fit.score, macro_reason=macro_fit.reason,
                timing_score=timing_result.composite_score, risk_score=risk_score,
                blended_fair_value=bfv, current_price=price, discount=discount,
            )
        )

    # --- Valuation pillar: rank the discounts through §12's own generic
    # sector-percentile machinery, unmodified. Higher discount (cheaper
    # vs. fair value) -> higher ascending percentile -> higher Valuation
    # score, so no inversion is needed.
    valuation_percentiles = sector_percentiles_for_ratio(
        VALUATION_DISCOUNT_KEY, discounts_by_ticker,
        narrow_sector_by_ticker, wide_sector_by_ticker,
    )

    # --- Growth pillar: a plain universe-wide ascending rank (not
    # sector-relative — see MIN_TICKERS_FOR_GROWTH_RANK's own comment),
    # or honestly excluded for everyone when too few tickers have any
    # confirmed §34 revenue impact to rank against.
    growth_ranks: dict[str, Decimal] = {}
    growth_excluded_reason: str | None = None
    if len(growth_adj_by_ticker) >= MIN_TICKERS_FOR_GROWTH_RANK:
        growth_ranks = _percentile_rank_ascending(growth_adj_by_ticker)
    else:
        growth_excluded_reason = (
            f"Only {len(growth_adj_by_ticker)} confirmed-universe ticker(s) have a §34 "
            f"national-projects revenue impact — fewer than the {MIN_TICKERS_FOR_GROWTH_RANK} "
            "needed to rank a Growth percentile, so this pillar is excluded for every ticker "
            "rather than scored from a fabricated 0."
        )

    ranked: list[RankedComposite] = []
    excluded: list[RankedComposite] = list(quarantined)

    val_spec = PILLAR_SPECS_BY_KEY["valuation"]
    growth_spec = PILLAR_SPECS_BY_KEY["growth"]
    macro_spec = PILLAR_SPECS_BY_KEY["macro_sector_fit"]
    timing_spec = PILLAR_SPECS_BY_KEY["timing_momentum"]
    risk_spec = PILLAR_SPECS_BY_KEY["risk"]

    for w in work:
        val_result = valuation_percentiles.get(w.ticker)
        val_score = val_result.percentile if val_result is not None else None
        if val_score is not None:
            val_pillar = PillarScore("valuation", val_spec.label, val_spec.weight_pct, val_score, True, None)
        elif w.ticker not in discounts_by_ticker:
            val_pillar = PillarScore(
                "valuation", val_spec.label, val_spec.weight_pct, None, False,
                "No positive blended fair value from confirmed data, so no discount-to-fair-"
                "value to rank.",
            )
        else:
            val_pillar = PillarScore(
                "valuation", val_spec.label, val_spec.weight_pct, None, False,
                (val_result.reason if val_result is not None and val_result.reason else
                 "Fewer than 3 sector peers have a computable discount to fair value — too "
                 "few to rank this ticker's own."),
            )

        growth_score = growth_ranks.get(w.ticker)
        growth_pillar = PillarScore(
            "growth", growth_spec.label, growth_spec.weight_pct, growth_score,
            growth_score is not None,
            None if growth_score is not None else (
                growth_excluded_reason
                if growth_excluded_reason is not None
                else "No confirmed §34 national-projects revenue impact for this ticker."
            ),
        )

        bq_pillar = _ratio_pillar(
            "business_quality", w.bq_score, BUSINESS_QUALITY_RATIO_KEYS,
            extra=" Needs confirmed fundamentals for this ticker and at least 3 sector peers "
            "with the same ratio computable.",
        )
        fs_pillar = _ratio_pillar("financial_strength", w.fs_score, FINANCIAL_STRENGTH_RATIO_KEYS)
        macro_pillar = PillarScore(
            "macro_sector_fit", macro_spec.label, macro_spec.weight_pct,
            w.macro_score, w.macro_score is not None, w.macro_reason,
        )
        timing_pillar = PillarScore(
            "timing_momentum", timing_spec.label, timing_spec.weight_pct,
            w.timing_score, w.timing_score is not None,
            None if w.timing_score is not None else (
                "None of the timing battery's 6 signals were computable for this ticker yet."
            ),
        )
        risk_pillar = PillarScore(
            "risk", risk_spec.label, risk_spec.weight_pct, w.risk_score, w.risk_score is not None,
            None if w.risk_score is not None else (
                "Not enough real price/turnover history to compute an Amihud illiquidity ratio "
                "for this ticker yet."
            ),
        )

        by_key = {
            "valuation": val_pillar, "business_quality": bq_pillar, "growth": growth_pillar,
            "financial_strength": fs_pillar, "macro_sector_fit": macro_pillar,
            "timing_momentum": timing_pillar, "risk": risk_pillar,
        }
        pillars = tuple(by_key[spec.key] for spec in PILLAR_SPECS)
        pillar_scores = {p.key: p.score for p in pillars if p.included}
        total_score, weight_used = renormalize(pillar_scores)
        weight_covered = sum(
            (PILLAR_SPECS_BY_KEY[k].weight_pct for k in pillar_scores), Decimal(0)
        )

        row = RankedComposite(
            ticker=w.ticker,
            name=w.name,
            archetype=w.archetype,
            cse_sector=narrow_sector_by_ticker.get(w.ticker),
            verdict=w.verdict,
            decision_confidence=w.decision_confidence,
            total_score=total_score,
            pillars=pillars,
            pillars_included=len(pillar_scores),
            weight_covered_pct=weight_covered,
            weight_used_pct=weight_used,
            integrity=UNEVALUABLE_INTEGRITY,
            blended_fair_value_per_share=w.blended_fair_value,
            current_price=w.current_price,
            discount_to_fair_value_pct=w.discount,
            valuation_pillar_percentile=val_score,
            warnings=() if total_score is not None else (
                "No §38 pillar was computable for this ticker from confirmed data yet — see "
                "each pillar's own reason.",
            ),
        )
        (ranked if total_score is not None else excluded).append(row)

    ranked.sort(key=lambda r: (-r.total_score, r.ticker))  # type: ignore[operator]
    excluded.sort(key=lambda r: r.ticker)
    return CompositeRankingView(as_of=stamp, ranked=tuple(ranked), excluded=tuple(excluded))
