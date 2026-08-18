"""
§P1's own formula reference: "Amihud illiquidity = mean(|return| ÷
turnover)." Real Amihud (2002) illiquidity ratio + percentile ranking —
the input `app.domain.margin_of_safety.liquidity_component`'s own
docstring and `app.domain.cost_of_equity`'s own module docstring have
both named as "confirmed blocked... needs real turnover history" since
early in this project. Real and closeable now: real per-company daily
turnover exists via `app.ingestion.company_price_history_loader`'s
~1-year backfill.

TURNOVER IN LKR VALUE, COMPUTED AS CLOSE × VOLUME, NOT READ FROM
`PriceDaily.turnover` DIRECTLY. Amihud's own formula divides by rupee
(dollar, in the original) volume, not share count, so a large-priced
illiquid stock and a small-priced illiquid stock are comparable on the
same scale. Checked live (18 Aug 2026): `PriceDaily.turnover` itself is
populated for only 284 of 66,516 real rows in this system's own dev
database — it's set only by the live `capture-market`/`bootstrap`
snapshot path, never by `company_price_history_loader`'s own ~1-year
daily-bar backfill (which returns `close`/`volume` but no separate
turnover figure). This module computes turnover as `close × volume`
throughout instead — a standard, disclosed proxy (the day's closing
price times its share volume, not an intraday VWAP-weighted figure a
real `turnover` field would carry more precisely), the real figure this
system's actual real data depth supports, not a workaround dressed up as
the exact thing.

HIGHER PERCENTILE = MORE LIQUID — the opposite direction from the raw
Amihud ratio itself (a LOWER ratio, less price impact per rupee traded,
is MORE liquid). `percentile_rank` computes this directly: a value's
percentile is the fraction of the universe with a STRICTLY WORSE
(higher-Amihud / less-liquid) reading, so the least liquid name in the
universe reads near 0 and the most liquid reads near 100 — matching
`app.domain.margin_of_safety.liquidity_component`'s own already-stated
convention exactly, not a fresh convention invented for this module.

ONE INTERPOLATION RULE, SHARED, NOT REINVENTED FOR A SECOND CONSUMER.
`liquidity_percentile_band` is `app.domain.margin_of_safety.liquidity_
component`'s own interpolation formula (top quartile of the liquidity
ranking → 0, bottom quartile → the stated cap, linear between the 25th/
75th percentile boundaries, flat outside — an explicit choice that
module's own docstring already justifies, §25 itself only gives the two
anchor points) — generalised to an arbitrary cap so `app.domain.cost_
of_equity`'s own illiquidity_premium (§17.2: "0 to ~3.0%, mapped from
the Amihud percentile") can reuse the exact same shape with its own 3%
cap rather than a second, independently-invented interpolation rule.
`margin_of_safety.liquidity_component` itself now calls this function
with its own 10% cap instead of carrying a private copy of the formula.
"""
from __future__ import annotations

from decimal import Decimal

#: A real, disclosed floor — lower than most other statistical modules'
#: minimums (this is a simple mean, not a model fit), but still enough
#: real non-zero-turnover trading days for the average to mean something
#: rather than being dominated by one or two extreme days.
MIN_OBSERVATIONS = 20

LIQUIDITY_TOP_QUARTILE = Decimal(75)
LIQUIDITY_BOTTOM_QUARTILE = Decimal(25)

#: §17.2's own stated range for the Ke illiquidity premium.
ILLIQUIDITY_PREMIUM_CAP = Decimal("0.03")


def amihud_illiquidity_ratio(returns: list[Decimal], turnovers_lkr: list[Decimal]) -> Decimal | None:
    """`mean(|return| ÷ turnover)`, excluding any day with zero or
    missing (non-positive) turnover — a genuinely untraded day carries
    no real price-impact information to average in, the standard
    treatment for this ratio, not a hand-rolled shortcut.

    `None` — never a ratio computed from too little real data — when
    fewer than `MIN_OBSERVATIONS` real (positive-turnover) days remain
    after that filter."""
    if len(returns) != len(turnovers_lkr):
        raise ValueError("returns and turnovers must be the same length")
    ratios = [abs(r) / t for r, t in zip(returns, turnovers_lkr) if t > 0]
    if len(ratios) < MIN_OBSERVATIONS:
        return None
    return sum(ratios) / len(ratios)


def percentile_rank(amihud_by_key: dict[str, Decimal]) -> dict[str, Decimal]:
    """0-100 liquidity percentile per key, HIGHER = MORE liquid (see
    module docstring). A key's percentile is `100 × (count of strictly
    worse — higher-Amihud — keys) ÷ (n − 1)` for `n > 1`; with a single
    key there is no real ranking to compute, so it gets the neutral
    midpoint, 50, rather than an arbitrary extreme."""
    keys = list(amihud_by_key.keys())
    n = len(keys)
    if n == 0:
        return {}
    if n == 1:
        return {keys[0]: Decimal(50)}
    result: dict[str, Decimal] = {}
    for key in keys:
        worse_count = sum(1 for other in keys if amihud_by_key[other] > amihud_by_key[key])
        result[key] = Decimal(100) * Decimal(worse_count) / Decimal(n - 1)
    return result


def liquidity_percentile_band(liquidity_percentile: Decimal | None, cap: Decimal) -> Decimal | None:
    """The shared top-quartile/bottom-quartile linear interpolation rule
    — see module docstring. `None` propagates rather than defaulting to
    either end of the range."""
    if liquidity_percentile is None:
        return None
    if liquidity_percentile >= LIQUIDITY_TOP_QUARTILE:
        return Decimal(0)
    if liquidity_percentile <= LIQUIDITY_BOTTOM_QUARTILE:
        return cap
    span = LIQUIDITY_TOP_QUARTILE - LIQUIDITY_BOTTOM_QUARTILE
    fraction_toward_illiquid = (LIQUIDITY_TOP_QUARTILE - liquidity_percentile) / span
    return fraction_toward_illiquid * cap


def illiquidity_premium_from_percentile(liquidity_percentile: Decimal | None) -> Decimal | None:
    """§17.2's own Ke component: "illiquidity_premium: 0 to ~3.0%,
    mapped from the Amihud percentile." Reuses `liquidity_percentile_
    band` with §17.2's own stated 3% cap rather than a fresh formula."""
    return liquidity_percentile_band(liquidity_percentile, ILLIQUIDITY_PREMIUM_CAP)
