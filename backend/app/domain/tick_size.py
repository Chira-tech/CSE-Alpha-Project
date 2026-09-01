"""CSE minimum price increment (tick size), by price band.

`docs/CSE_Data_Health_Diagnosis_And_Protocol.md` §2 / E2: a
percentage-only tolerance is meaningless at the bottom of the price range
(on a stock at LKR 1.60 the smallest legal price change is already ~6% of
the price) and far too loose at the top. Every cross-source price check
should allow at least a couple of ticks before calling a disagreement.

Per the Colombo Stock Exchange Automated Trading Rules amendment of
2021-01-07: **LKR 0.10** for a traded price **at or below LKR 100**,
**LKR 0.25 above LKR 100**. Verified against the doc's own worked
example — CITW at 1.60, one tick = 0.10 = 6.25% of price — and against
the CSE ATS rule book.
"""
from __future__ import annotations

from decimal import Decimal

_TICK_AT_OR_BELOW_100 = Decimal("0.10")
_TICK_ABOVE_100 = Decimal("0.25")
_BAND_EDGE = Decimal("100")


def tick_size(price: Decimal) -> Decimal:
    """The minimum legal price increment for a CSE line trading at
    `price`. Undefined for a non-positive price — callers should not be
    checking one."""
    return _TICK_ABOVE_100 if price > _BAND_EDGE else _TICK_AT_OR_BELOW_100


def price_tolerance_fraction(price: Decimal, *, pct_floor: Decimal, n_ticks: int = 2) -> Decimal:
    """`max(pct_floor, n_ticks × tick_size ÷ price)` — the fraction of
    `price` a cross-source disagreement may reach before it counts. The
    percentage floor covers genuine same-date cross-source noise on a
    thin market; the tick floor stops the smallest legal price move being
    read as an error on a low-priced stock (§2)."""
    if price <= 0:
        return pct_floor
    tick_fraction = (Decimal(n_ticks) * tick_size(price)) / price
    return max(pct_floor, tick_fraction)
