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

from app.domain.liquidity_view import universe_amihud_ratios
from app.domain.valuation_view import valuation_summary_for
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
    margin_of_safety_pct: Decimal | None
    dispersion_pct: Decimal | None
    """§24's own "how much the methods disagree" figure — a wide
    dispersion on a real position is itself worth seeing, not just the
    blended number it produced."""

    warnings: tuple[str, ...]


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


def value_position(
    db: Session,
    position: PortfolioPosition,
    as_of: dt.date,
    *,
    universe_liquidity_ratios: dict[str, Decimal] | None = None,
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

    summary = valuation_summary_for(
        db, position.ticker, archetype, live_price, as_of,
        universe_liquidity_ratios=universe_liquidity_ratios,
    )

    live_market_value = None
    live_unrealized_gain_loss = None
    if live_price is not None:
        live_market_value = position.quantity * live_price
        live_unrealized_gain_loss = live_market_value - position.total_cost

    return ValuedPosition(
        ticker=position.ticker, quantity=position.quantity, avg_price=position.avg_price,
        total_cost=position.total_cost,
        snapshot_traded_price=position.traded_price, snapshot_market_value=position.market_value,
        snapshot_unrealized_gain_loss=position.unrealized_gain_loss,
        live_current_price=live_price, live_market_value=live_market_value,
        live_unrealized_gain_loss=live_unrealized_gain_loss,
        blended_fair_value_per_share=summary.triangulation.blended_fair_value_per_share,
        price_ladder_zone=summary.price_ladder.current_zone if summary.price_ladder else None,
        buy_below_price=summary.price_ladder.buy_below_price if summary.price_ladder else None,
        margin_of_safety_pct=summary.margin_of_safety.total_pct,
        dispersion_pct=summary.triangulation.dispersion_pct,
        warnings=(
            tuple(warnings)
            + summary.triangulation.warnings
            + (summary.price_ladder.warnings if summary.price_ladder is not None else ())
        ),
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
    valued = [
        value_position(db, p, stamp, universe_liquidity_ratios=universe_ratios)
        for p in snapshot.positions
    ]

    missing = tuple(v.ticker for v in valued if v.live_current_price is None)
    priced = [v for v in valued if v.live_market_value is not None]
    total_live_market_value = (
        sum((v.live_market_value for v in priced), Decimal(0)) if priced else None
    )
    total_cost = sum((v.total_cost for v in valued), Decimal(0))

    return ValuedPortfolio(
        snapshot_id=snapshot.id, as_of=stamp, positions=tuple(valued),
        total_cost=total_cost, total_live_market_value=total_live_market_value,
        positions_missing_a_live_price=missing,
    )
