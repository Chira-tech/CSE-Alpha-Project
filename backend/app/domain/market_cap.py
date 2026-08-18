"""
Real market capitalisation per ticker — `shares_issued × price`, the
size dimension §35's own SMB size split, MOM's size dimension, and every
book-to-market factor's own denominator all need (`app.domain.
portfolio_sort`'s `size_value`/the B/M `style_value`'s own scale).

A DISCLOSED FULL-SHARES-ISSUED PROXY FOR FREE-FLOAT MARKET CAP, NOT THE
REAL THING §35.1 ASKS FOR. §35.1's own text: "Size split at universe
median FREE-FLOAT market cap." This system has real `FloatData.shares_
issued` per company but not real `public_float_pct` for any of them —
checked live, 18 Aug 2026: 0 of the real `FloatData` rows on file have
it, and the quarterly shareholding disclosures that would carry it
aren't ingested anywhere in this system (see `FloatData`'s own model
docstring, which already names this exact gap). Using TOTAL shares
issued as if it were free float OVERSTATES the true free-float market
cap for any company with a large controlling stake — likely most CSE
conglomerates, per this project's own Edge Thesis (§3: "Family-
controlled conglomerates; opaque related-party flows") — so a size sort
built on this proxy will systematically read some genuinely small-float,
large-headline-cap names as "big" when the spec's own free-float basis
would call them "small." Disclosed here and at every real consumer of
this module, never silently presented as the real free-float figure.
"""
from __future__ import annotations

from decimal import Decimal


def market_cap(shares_issued: int, price: Decimal) -> Decimal:
    """`shares_issued × price` — see module docstring for why this is a
    full-shares-issued proxy, not free-float market cap."""
    return Decimal(shares_issued) * price
