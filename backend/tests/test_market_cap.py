"""app.domain.market_cap — trivial arithmetic, tested for the same
reason every other pure module in this system is: a real regression here
would silently corrupt every §35 factor sort built on top of it."""
from __future__ import annotations

from decimal import Decimal

from app.domain.market_cap import market_cap


def test_hand_worked_market_cap():
    assert market_cap(1_000_000, Decimal("50.25")) == Decimal("50250000.00")


def test_zero_shares_gives_zero():
    assert market_cap(0, Decimal("100")) == Decimal(0)
