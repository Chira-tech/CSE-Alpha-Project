"""
Connects a real uploaded portfolio snapshot (`app.domain.portfolio_
import_view`) to this system's own real valuation engine (`app.domain.
valuation_view.valuation_summary_for`) — for every real held position,
what does THIS system say it's worth right now, not just what the
broker's own snapshot said on the day it was exported.

TWO REAL PRICES, NEVER CONFLATED. `snapshot_*` fields are exactly what
the broker's own file said, unchanged — the user's own real record of
that moment. `live_*` fields are this system's own real, current
`prices_daily` read and the real fair value/price-ladder computed from
it, as of `as_of` (today by default). A position bought when the ticker
traded at a different level than today will show BOTH, never one
silently overwriting the other — the same "never let a real figure get
silently replaced" discipline every other real-data pairing in this
system already applies (see e.g. `app.domain.event_study_view`'s own
real-vs-adjusted return distinction).

ARCHETYPE-UNCLASSIFIED AND UNRECOGNISED TICKERS STILL GET A ROW. A held
position whose archetype hasn't been confirmed yet, or whose ticker
isn't even in this system's own `securities` table (see `app.domain.
portfolio_import_view.unrecognized_tickers`), still appears — with
`live_current_price`/`blended_fair_value_per_share`/etc. all `None` and
a named reason in `warnings`, never silently dropped from the view just
because this system can't value it yet.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.fundamentals_view import ratio_trends_for
from app.domain.liquidity import percentile_rank
from app.domain.liquidity_view import universe_amihud_ratios
from app.domain.macro_engine_view import RegimeView, regime_for
from app.domain.valuation_view import valuation_summary_for
from app.jobs.reconciliation import is_quarantined
from app.models.portfolio import PortfolioPosition, PortfolioSnapshot
from app.models.prices import PriceDaily
from app.models.securities import Security


@dataclass(frozen=True)
class ValuedPosition:
    ticker: str
    quantity: Decimal
    avg_price: Decimal
    total_cost: Decimal

    snapshot_traded_price: Decimal | None
    snapshot_market_value: Decimal | None
    snapshot_unrealized_gain_loss: Decimal | None
    """Exactly what the broker's own file said, as of the snapshot's own
    upload — never recomputed or overwritten."""

    live_current_price: Decimal | None
    live_market_value: Decimal | None
    live_unrealized_gain_loss: Decimal | None
    """This system's own real, current read — `None` together whenever
    no real current price exists for this ticker."""

    blended_fair_value_per_share: Decimal | None
    price_ladder_zone: str | None
    buy_below_price: Decimal | None
    sell_above_price: Decimal | None
    """R1 T4.5.3: `price_ladder.exit_threshold` — the top of the
    valuation range where §26's own zone label already calls the position
    "stretched" (see `compute_price_ladder`'s `zone_meaning` for the exit
    zone). For a HELD position this is the actionable ceiling; buy-below
    is the wrong signal once you already own the name (§1's own framing
    for the brief this closes). Kept ALONGSIDE `buy_below_price`, not in
    place of it — a holder deciding whether to add to a position still
    wants to see it, just not as the headline column."""
    margin_of_safety_pct: Decimal | None
    dispersion_pct: Decimal | None
    """§24's own "how much the methods disagree" figure — a wide
    dispersion on a real position is itself worth seeing, not just the
    blended number it produced."""

    warnings: tuple[str, ...]

    attention_flags: tuple["AttentionFlag", ...]
    """R1 T4.5.4: real, calmly-styled per-position flags — never a
    fabricated "thesis break" (that needs §45's decision record freezing
    state at purchase to compare against, which doesn't exist yet, named
    honestly in this module's own docstring rather than faked here)."""

    # --- TASK 2.2 (product-owner brief): exit plan / overvaluation -------

    trim_above_price: Decimal | None
    """= the blended fair value itself (`price_ladder.trim_threshold`) —
    TASK 2.2's own "trim_above = fair value (start scaling out)". Exposed
    under this name, alongside `buy_below_price`/`sell_above_price`, for
    the same reason `sell_above_price` already is: a HELD position reads
    the ladder as a sell plan, not a buy plan."""

    overvaluation_pct: Decimal | None
    """`(live_current_price / blended_fair_value_per_share) - 1` — TASK
    2.2's own plain-worded number ("14% above fair value" / "22% below
    fair value"). `None` whenever either input is missing, same as every
    other derived field here — never computed from a quarantined or
    sanity-withheld fair value."""

    nearest_trigger_label: str | None
    nearest_trigger_price: Decimal | None
    nearest_trigger_distance_pct: Decimal | None
    """TASK 2.2 asks for "the nearest exit trigger from exit_triggers()
    (§28)... which of the five is closest." §28's own five-trigger
    framework does not exist anywhere in this codebase (verified directly
    — no `exit_triggers` function, no §28 module) and is real, separate,
    unbuilt work, not a display gap over already-computed numbers the way
    the brief's own text assumes. This is the honest, real substitute
    available today: the nearest of the price ladder's own four
    thresholds (strong-accumulate / buy-below / trim-above / exit-above)
    to the current price, signed (positive = price must rise to reach it,
    negative = price must fall). `None` together when no ladder exists."""

    decision_verdict: str | None
    decision_confidence: str | None
    """`app.domain.decision.compute_decision`'s own verdict/confidence —
    computed for every ticker as part of `valuation_summary_for` since
    the system-wide valuation upgrade; threaded through here so a holder
    sees the same call the company file shows, not a second, potentially
    disagreeing read built locally.  `None` when quarantined/withheld,
    same as the other derived fields."""

    thesis_status: str | None
    """`"intact"` (no real attention flags raised) or `"weakening"` (one
    or more raised — see `attention_flags`). NOT §42's own thesis-drift
    monitor, which needs a frozen purchase-time baseline to compare
    against (§45's decision record) and does not exist in this system —
    named honestly rather than faked as a three-state "intact / weakening
    / broken" ladder the brief's own text describes. `None`, not
    "intact", when this system cannot form a real read at all (no
    security record, so no trend data to check)."""


@dataclass(frozen=True)
class AttentionFlag:
    key: str
    label: str
    detail: str


@dataclass(frozen=True)
class ValuedPortfolio:
    snapshot_id: int
    as_of: dt.date
    positions: tuple[ValuedPosition, ...]
    total_cost: Decimal
    total_live_market_value: Decimal | None
    """`None` only when EVERY position lacks a real live price — a
    partial real total (some positions valued, some not) is still
    reported rather than withheld, with `positions_missing_a_live_price`
    naming the gap."""

    positions_missing_a_live_price: tuple[str, ...]


def _latest_price(db: Session, ticker: str, as_of: dt.date) -> Decimal | None:
    return db.scalar(
        select(PriceDaily.close)
        .where(PriceDaily.ticker == ticker, PriceDaily.date <= as_of, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )


def _attention_flags(
    db: Session, ticker: str, as_of: dt.date, price_ladder_zone: str | None,
) -> tuple[AttentionFlag, ...]:
    """Real, derivable-today flags only. `direction` is shown even when
    NOT `significant` (§13's own convention — the sign is informative on
    its own) but the detail names which it is, never collapsing the two."""
    flags: list[AttentionFlag] = []
    if price_ladder_zone in ("trim", "exit"):
        flags.append(AttentionFlag(
            "valuation_stretched", "Valuation stretched",
            f"Price ladder zone: {price_ladder_zone}.",
        ))

    trends = ratio_trends_for(db, ticker, as_of)

    def _trend_flag(key: str, watch_direction: str, flag_key: str, label: str, noun: str) -> None:
        t = trends.get(key)
        if t is None or t.direction.direction.value != watch_direction:
            return
        sig = "statistically significant" if t.direction.significant else "not yet statistically significant"
        flags.append(AttentionFlag(
            flag_key, label,
            f"{noun} {watch_direction} over the last {t.periods_used} periods ({sig}).",
        ))

    _trend_flag("return_on_equity", "decreasing", "roe_falling", "ROE falling", "Return on equity")
    _trend_flag("net_margin", "decreasing", "earnings_deteriorating", "Earnings deteriorating", "Net margin")
    _trend_flag("liabilities_to_equity", "increasing", "leverage_rising", "Leverage rising", "Liabilities/equity")

    return tuple(flags)


def _nearest_trigger(
    current_price: Decimal | None, ladder,
) -> tuple[str | None, Decimal | None, Decimal | None]:
    """See `ValuedPosition.nearest_trigger_label`'s own docstring for why
    this is a real, disclosed substitute for §28's own not-yet-built
    five-trigger framework, built from the four thresholds the price
    ladder already computes."""
    if current_price is None or ladder is None or current_price == 0:
        return None, None, None
    candidates = (
        ("Strong accumulate", ladder.strong_accumulate_threshold),
        ("Buy below", ladder.buy_below_price),
        ("Trim above", ladder.trim_threshold),
        ("Exit above", ladder.exit_threshold),
    )
    label, price = min(candidates, key=lambda c: abs(c[1] - current_price))
    distance_pct = (price - current_price) / current_price
    return label, price, distance_pct


def value_position(
    db: Session,
    position: PortfolioPosition,
    as_of: dt.date,
    *,
    universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
    regime_view: RegimeView | None = None,
) -> ValuedPosition:
    warnings: list[str] = []
    security = db.get(Security, position.ticker)
    archetype = security.archetype if security is not None else None
    if security is None:
        warnings.append(
            f"{position.ticker!r} is not in this system's own securities table — "
            "cannot look up a real archetype or live price for it."
        )

    live_price = _latest_price(db, position.ticker, as_of) if security is not None else None
    if security is not None and live_price is None:
        warnings.append(f"No real live price found for {position.ticker!r} on or before {as_of}.")

    # OI-3 (docs/audits/R1_OPEN_ISSUES.md): same real gap as
    # `opportunity_ranking_view`'s own fix, same reason — a quarantined
    # ticker's adjustment factors failed §7's reconciliation, so its fair
    # value/price-ladder output is not trusted here either. The real
    # price/quantity/cost fields stay visible (directly observed, not
    # model output, and hiding a real held position's price would be
    # worse than a caveated valuation gap) — only the derived valuation
    # fields are withheld, below.
    quarantined = security is not None and is_quarantined(db, position.ticker)
    if quarantined:
        warnings.append(
            f"{position.ticker!r} is quarantined — its stored adjustment factors failed the §7 "
            "reconciliation check, so fair value and the price ladder are withheld until a human "
            "resolves the underlying data-health alert."
        )

    summary = valuation_summary_for(
        db, position.ticker, archetype, live_price, as_of,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
        regime_view=regime_view,
    )

    live_market_value = None
    live_unrealized_gain_loss = None
    if live_price is not None:
        live_market_value = position.quantity * live_price
        live_unrealized_gain_loss = live_market_value - position.total_cost

    # TASK 2.2: every derived exit-plan field below reads through this ONE
    # gate — `effective_ladder` is None whenever quarantined OR withheld
    # by TASK 0.1's plausibility gate, so none of them can ever be
    # computed from a number that failed sanity (the brief's own rule 1).
    effective_ladder = None if quarantined else summary.price_ladder
    effective_fair_value = None if quarantined else summary.triangulation.blended_fair_value_per_share

    overvaluation_pct = None
    if live_price is not None and effective_fair_value not in (None, Decimal(0)):
        overvaluation_pct = (live_price / effective_fair_value) - Decimal(1)

    nearest_label, nearest_price, nearest_distance = _nearest_trigger(live_price, effective_ladder)

    attention_flags_result = (
        _attention_flags(
            db, position.ticker, as_of, effective_ladder.current_zone if effective_ladder else None,
        )
        if security is not None
        else ()
    )
    thesis_status = None
    if security is not None and not quarantined:
        thesis_status = "weakening" if attention_flags_result else "intact"

    return ValuedPosition(
        ticker=position.ticker, quantity=position.quantity, avg_price=position.avg_price,
        total_cost=position.total_cost,
        snapshot_traded_price=position.traded_price, snapshot_market_value=position.market_value,
        snapshot_unrealized_gain_loss=position.unrealized_gain_loss,
        live_current_price=live_price, live_market_value=live_market_value,
        live_unrealized_gain_loss=live_unrealized_gain_loss,
        blended_fair_value_per_share=effective_fair_value,
        price_ladder_zone=effective_ladder.current_zone if effective_ladder is not None else None,
        buy_below_price=effective_ladder.buy_below_price if effective_ladder is not None else None,
        sell_above_price=effective_ladder.exit_threshold if effective_ladder is not None else None,
        trim_above_price=effective_ladder.trim_threshold if effective_ladder is not None else None,
        overvaluation_pct=overvaluation_pct,
        nearest_trigger_label=nearest_label,
        nearest_trigger_price=nearest_price,
        nearest_trigger_distance_pct=nearest_distance,
        decision_verdict=None if quarantined else summary.decision.verdict,
        decision_confidence=None if quarantined else summary.decision.confidence,
        thesis_status=thesis_status,
        margin_of_safety_pct=None if quarantined else summary.margin_of_safety.total_pct,
        dispersion_pct=None if quarantined else summary.triangulation.dispersion_pct,
        warnings=(
            tuple(warnings)
            + summary.triangulation.warnings
            + (effective_ladder.warnings if effective_ladder is not None else ())
            # TASK 0.1/2.2: a blended fair value existed but TASK 0.1's
            # plausibility gate withheld it — `price_ladder` is None for
            # this reason specifically (not "no anchors"), and that
            # reason must reach this position's warnings, since neither
            # `triangulation.warnings` nor (absent) `price_ladder.
            # warnings` say anything about it otherwise. See TASK 2.2's
            # own rule 1: "Never show an exit price derived from a
            # number that failed sanity" — already true here structurally
            # (price_ladder_zone/buy_below_price are both None), this
            # just makes sure the reason is visible too.
            + (
                (f"Exit plan unavailable — fair value withheld: {', '.join(summary.sanity.block_reasons)}",)
                if summary.sanity is not None and summary.sanity.blocked
                else ()
            )
        ),
        attention_flags=attention_flags_result,
    )


def value_portfolio(
    db: Session, snapshot: PortfolioSnapshot, as_of: dt.date | None = None
) -> ValuedPortfolio:
    stamp = as_of or dt.date.today()
    # Computed ONCE for the whole portfolio and threaded through every
    # position — see `app.domain.liquidity_view.liquidity_percentile_
    # for`'s own docstring for why this matters: a real profiling run
    # (18 Aug 2026) found a real 9-position portfolio taking 89 seconds
    # to value because this same market-wide scan was being recomputed
    # from scratch 6 times per position (54 times total) with no
    # sharing at all, even within one position's own valuation.
    universe_ratios = universe_amihud_ratios(db, stamp)
    # A SECOND, independent half of that same cost class, found live
    # later (20 Aug 2026): sharing `universe_ratios` alone still left
    # `percentile_rank` — an O(n²) full universe re-ranking — running
    # fresh on every one of the ~6 per-position calls into `cost_of_
    # equity_for` that `valuation_summary_for` makes. Computed once here
    # instead, exactly the same fix as `universe_ratios` itself — see
    # `app.domain.valuation_view.valuation_summary_for`'s own docstring
    # on `universe_liquidity_percentiles`.
    universe_percentiles = percentile_rank(universe_ratios)
    # Same reasoning applied to the regime read too — see `valuation_
    # summary_for`'s own docstring on `regime_view`. This one was NOT
    # part of the 18 Aug fix above (only the liquidity scan was shared
    # then); each position was still re-running the Markov MLE fit for
    # an identical, market-wide, `as_of`-only answer until now.
    regime_view = regime_for(db, stamp)
    valued = [
        value_position(
            db, p, stamp,
            universe_liquidity_ratios=universe_ratios,
            universe_liquidity_percentiles=universe_percentiles,
            regime_view=regime_view,
        )
        for p in snapshot.positions
    ]

    missing = tuple(v.ticker for v in valued if v.live_current_price is None)
    priced = [v for v in valued if v.live_market_value is not None]
    total_live_market_value = (
        sum((v.live_market_value for v in priced), Decimal(0)) if priced else None
    )
    total_cost = sum((v.total_cost for v in valued), Decimal(0))

    # TASK 2.2's own rule 2: "Sort the portfolio by nearest trigger, not
    # by P&L. What needs attention first is not the same as what has
    # gained most." Ascending by absolute distance to the nearest price-
    # ladder threshold — a position sitting right on a boundary (either
    # direction) surfaces first; a position with no computable trigger
    # (quarantined, withheld, or no ladder at all) sorts last rather than
    # being silently treated as either urgent or safe.
    valued.sort(
        key=lambda v: (
            v.nearest_trigger_distance_pct is None,
            abs(v.nearest_trigger_distance_pct) if v.nearest_trigger_distance_pct is not None else Decimal(0),
        )
    )

    return ValuedPortfolio(
        snapshot_id=snapshot.id, as_of=stamp, positions=tuple(valued),
        total_cost=total_cost, total_live_market_value=total_live_market_value,
        positions_missing_a_live_price=missing,
    )


def portfolio_value_trend(
    db: Session, snapshot: PortfolioSnapshot, as_of: dt.date, calendar_day_windows: tuple[int, ...],
) -> dict[int, Decimal | None]:
    """R1 T4.1.6's `TrendChip` data — real, but under a real, disclosed
    assumption: TODAY's exact holdings (quantity per ticker, from
    `snapshot`) priced at each PAST date's real close. This is not the
    same as "what your portfolio was actually worth then" if you bought,
    sold or resized any position since — it answers "how has the value
    of what I hold RIGHT NOW moved," which is the honest question this
    system can answer without a transaction log (§41, not built — see
    this module's own docstring). Deliberately does NOT call `value_
    portfolio`/`valuation_summary_for` for the historical points: only
    real stored closes are needed here, and the full valuation engine
    read `universe_amihud_ratios` alone measured at 89s for 9 positions
    (see `value_portfolio`'s own docstring) — paying that cost once per
    trend window would make this screen unusable.

    Windows are CALENDAR days, not trading sessions — deliberately
    different from `format.ts`'s own ASPI trend (a single continuous
    session series). A multi-ticker portfolio has no single shared
    session index (each ticker's own real trading gaps differ), so
    `_latest_price`'s existing "most recent close on or before this
    date" point-in-time rule is applied per position instead — the same
    rule every other point-in-time read in this system already uses.

    Returns `{calendar_days_ago: pct_change_or_None}` — `None` for a
    window where at least one held position has no real price that far
    back, never a partial/estimated total silently substituted for a
    missing position's contribution.
    """
    current_value = Decimal(0)
    for p in snapshot.positions:
        price = _latest_price(db, p.ticker, as_of)
        if price is None:
            return {w: None for w in calendar_day_windows}
        current_value += p.quantity * price

    if current_value == 0:
        return {w: None for w in calendar_day_windows}

    results: dict[int, Decimal | None] = {}
    for days_ago in calendar_day_windows:
        then_date = as_of - dt.timedelta(days=days_ago)
        past_value = Decimal(0)
        ok = True
        for p in snapshot.positions:
            past_price = _latest_price(db, p.ticker, then_date)
            if past_price is None:
                ok = False
                break
            past_value += p.quantity * past_price
        if not ok or past_value == 0:
            results[days_ago] = None
            continue
        results[days_ago] = (current_value - past_value) / past_value * Decimal(100)
    return results
