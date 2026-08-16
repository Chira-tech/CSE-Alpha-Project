"""
Master Spec §7 — "where CSE backtests silently die" — and Appendix P1.

Pure, deterministic functions only. No I/O, no ORM objects in the public
signatures, so this module is trivially unit-testable and directly
reflects the formulas quoted in the spec:

    TERP = (N * cum-rights price + S * subscription price) / (N + S)

and the requirement to build "a total-return adjustment factor series per
ticker, applied cumulatively backwards across the entire price history."

Every corporate action is converted to a single `price_ratio`: the factor
by which the *raw* price is expected to change on the ex-date purely
because of the action, isolated from any genuine return. The cumulative
adjustment factor for a date is the product of every price_ratio for
actions whose ex_date is strictly after that date. Adjusted price at date t
is then `raw_price(t) * adj_factor(t)`, and adjusted total return between
two dates is computed entirely from adjusted prices — no separate dividend
add-back is needed downstream because the ratio already grosses it up.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from enum import Enum


class ActionKind(str, Enum):
    DIVIDEND_CASH = "dividend_cash"
    BONUS_ISSUE = "bonus_issue"
    STOCK_SPLIT = "stock_split"
    CONSOLIDATION = "consolidation"
    RIGHTS_ISSUE = "rights_issue"


@dataclasses.dataclass(frozen=True)
class CorporateActionEvent:
    """Minimal, source-agnostic representation of one action, enough to
    compute its price ratio. `ex_date` is the date the action takes effect;
    by convention prices *on or after* ex_date are unaffected by the ratio,
    prices *before* ex_date get multiplied by it.
    """

    ex_date: dt.date
    kind: ActionKind
    # Cash dividend:
    cash_amount: Decimal | None = None
    close_price_day_before_ex: Decimal | None = None
    # Bonus issue / stock split: new shares received per share already held
    # (a 1:1 bonus -> 1.0; a 1-for-5 split -> 4.0 new per held, i.e. 5x total)
    new_shares_per_held_share: Decimal | None = None
    # Consolidation: old shares required per one new share (5:1 -> 5.0)
    old_shares_per_new_share: Decimal | None = None
    # Rights issue:
    shares_held_n: Decimal | None = None
    shares_subscribed_s: Decimal | None = None
    subscription_price: Decimal | None = None
    cum_rights_price: Decimal | None = None


def compute_terp(
    shares_held_n: Decimal,
    shares_subscribed_s: Decimal,
    cum_rights_price: Decimal,
    subscription_price: Decimal,
) -> Decimal:
    """Theoretical ex-rights price, Master Spec Appendix P1:

        TERP = (N * cum-rights price + S * subscription price) / (N + S)
    """
    if shares_held_n < 0 or shares_subscribed_s < 0:
        raise ValueError("share counts must be non-negative")
    denominator = shares_held_n + shares_subscribed_s
    if denominator == 0:
        raise ValueError("N + S must be greater than zero")
    numerator = shares_held_n * cum_rights_price + shares_subscribed_s * subscription_price
    return numerator / denominator


def price_ratio_for_event(event: CorporateActionEvent) -> Decimal:
    """The multiplier applied to every raw price *strictly before*
    `event.ex_date` so that it becomes comparable, on a total-return basis,
    to prices on or after the ex-date. Always > 0.

    Sign convention check for each branch is documented inline because this
    is exactly the kind of formula that is silently backwards half the time
    it's implemented from memory.
    """
    if event.kind is ActionKind.DIVIDEND_CASH:
        if event.cash_amount is None or event.close_price_day_before_ex is None:
            raise ValueError("dividend event requires cash_amount and close_price_day_before_ex")
        if event.close_price_day_before_ex <= 0:
            raise ValueError("close_price_day_before_ex must be positive")
        # Price is expected to fall by roughly the dividend amount on
        # ex-date. To gross up historical (pre-ex) prices onto a
        # total-return basis, scale them DOWN by (1 - div/price) — i.e. the
        # ratio is < 1, which when multiplied into the cumulative factor
        # for earlier dates shrinks them relative to today, exactly
        # cancelling the fact that a dividend was extracted from the price
        # series without the holder losing that value.
        ratio = 1 - (event.cash_amount / event.close_price_day_before_ex)
        if ratio <= 0:
            raise ValueError(
                "computed dividend ratio <= 0 — cash_amount implausibly large "
                "relative to price; check inputs before trusting this event"
            )
        return ratio

    if event.kind in (ActionKind.BONUS_ISSUE, ActionKind.STOCK_SPLIT):
        if event.new_shares_per_held_share is None:
            raise ValueError("bonus/split event requires new_shares_per_held_share")
        n = event.new_shares_per_held_share
        if n < 0:
            raise ValueError("new_shares_per_held_share must be >= 0")
        # A 1:1 bonus doubles shares outstanding -> price roughly halves.
        # Historical prices must be scaled DOWN to be comparable to the
        # post-bonus, more-numerous, cheaper shares.
        return Decimal(1) / (Decimal(1) + n)

    if event.kind is ActionKind.CONSOLIDATION:
        if event.old_shares_per_new_share is None:
            raise ValueError("consolidation event requires old_shares_per_new_share")
        m = event.old_shares_per_new_share
        if m <= 0:
            raise ValueError("old_shares_per_new_share must be > 0")
        # A 5:1 consolidation reduces shares outstanding 5x -> price
        # roughly quintuples. Historical (pre-consolidation) prices must be
        # scaled UP by that same factor to be comparable.
        return m

    if event.kind is ActionKind.RIGHTS_ISSUE:
        if event.shares_held_n is None or event.shares_subscribed_s is None:
            raise ValueError("rights event requires shares_held_n and shares_subscribed_s")
        if event.cum_rights_price is None or event.subscription_price is None:
            raise ValueError("rights event requires cum_rights_price and subscription_price")
        if event.cum_rights_price <= 0:
            raise ValueError("cum_rights_price must be positive")
        terp = compute_terp(
            event.shares_held_n, event.shares_subscribed_s, event.cum_rights_price, event.subscription_price
        )
        # Price is expected to drop from cum-rights price to TERP.
        return terp / event.cum_rights_price

    raise AssertionError(f"unhandled action kind: {event.kind!r}")  # pragma: no cover


def build_adjustment_factor_series(
    dates: list[dt.date],
    events: list[CorporateActionEvent],
) -> dict[dt.date, Decimal]:
    """Master Spec §7: "A total-return adjustment factor series per ticker,
    applied cumulatively backwards across the entire price history."

    Returns {date: cumulative_factor}, one entry per input date, such that
    `adjusted_price(t) = raw_price(t) * factor[t]`. The most recent date(s)
    — those on/after every event's ex_date — carry factor 1.0 by
    construction; every action multiplies the factor for all strictly
    earlier dates by that action's price_ratio.
    """
    factors = {d: Decimal(1) for d in dates}
    # Process events oldest-first isn't required for correctness (each
    # event only affects dates before its own ex_date, independent of
    # order), but sorting makes the accumulation easy to reason about and
    # keeps behaviour deterministic regardless of input order.
    for event in sorted(events, key=lambda e: e.ex_date):
        ratio = price_ratio_for_event(event)
        for d in dates:
            if d < event.ex_date:
                factors[d] *= ratio
    return factors


def total_return_from_adjusted_prices(
    price_start: Decimal, price_end: Decimal, adj_factor_start: Decimal, adj_factor_end: Decimal
) -> Decimal:
    """Total return over a window, computed purely from adjusted prices —
    this is what the nightly reconciliation test (§7) cross-checks against
    the independent raw-price-plus-declared-actions computation."""
    if price_start <= 0 or adj_factor_start <= 0:
        raise ValueError("start price and adjustment factor must be positive")
    adjusted_start = price_start * adj_factor_start
    adjusted_end = price_end * adj_factor_end
    return (adjusted_end / adjusted_start) - 1
