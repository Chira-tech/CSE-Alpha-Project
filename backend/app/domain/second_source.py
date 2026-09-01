"""
Comparing our own captured close against an independent second source.

Part II §5.2: "nightly cross-check against a second source... discrepancy
>0.5% quarantines the ticker." PARAMETERS.md #5 has recorded this as
entirely unmet since the project began — every price figure in this
system came from one unofficial cse.lk endpoint, with nothing outside
that single institution ever checking it.

TradingView carries a live quote for every CSE line under the `CSELK:`
exchange prefix (its own symbols match cse.lk's exactly, e.g.
`CSELK:COMB.N0000`), reachable through its `/global/scan` screener API —
the one path its scanner subdomain's robots.txt explicitly allows,
unlike the per-symbol quote page endpoint, which is disallowed.

WHAT THIS DOES AND DOES NOT CLOSE. It gives §5.2's nightly cross-check
exactly what it asks for: comparing TODAY's own captured close against an
independently-pipelined reading of today's price, from a company with no
relationship to cse.lk. It does NOT give independent HISTORICAL depth —
TradingView's own chart for CSE symbols renders no candles at any
timeframe, live quote only — so it cannot backfill or verify anything
before today, and PARAMETERS.md #5's price-history-second-source gap
stays open for that purpose.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.tick_size import price_tolerance_fraction


@dataclass(frozen=True)
class SecondSourceQuote:
    close: Decimal
    high: Decimal
    low: Decimal
    open: Decimal
    volume: int
    currency: str
    exchange: str


class SecondSourceShapeError(ValueError):
    """The quote isn't the CSE line it claims to be — never compare
    against it."""


@dataclass(frozen=True)
class CrossCheckResult:
    ticker: str
    our_close: Decimal
    their_close: Decimal
    mismatch_pct: Decimal
    tolerance_pct: Decimal
    """The `max(pct_floor, 2 ticks)` band actually applied — carried so an
    alert can quote it and the Data Health ledger can re-derive the same
    verdict without re-fetching a quote."""
    within_tolerance: bool


def validate_quote(ticker: str, quote: SecondSourceQuote) -> None:
    """A quote whose currency or exchange doesn't match what a CSE line
    must carry is not evidence about that line — comparing against it
    would be comparing against noise, or worse, a different company that
    happens to share a symbol on another exchange."""
    if quote.currency != "LKR":
        raise SecondSourceShapeError(
            f"{ticker}: second-source quote is in {quote.currency}, not LKR — refusing to compare"
        )
    if quote.exchange != "CSELK":
        raise SecondSourceShapeError(
            f"{ticker}: second-source quote reports exchange {quote.exchange!r}, not CSELK"
        )
    if quote.close <= 0:
        raise SecondSourceShapeError(f"{ticker}: non-positive second-source close {quote.close}")


def cross_check(
    ticker: str, our_close: Decimal, quote: SecondSourceQuote, *, pct_floor: Decimal
) -> CrossCheckResult:
    """Pure comparison — no I/O. `docs/CSE_Data_Health_Diagnosis_And_
    Protocol.md` §2 / E2: the tolerance is `max(pct_floor, 2 × tick_size ÷
    price)`, not a bare percentage. `pct_floor` (1% by default,
    `settings.second_source_mismatch_pct_floor`) covers genuine same-date
    cross-source noise on a thin market; the two-tick term stops the
    smallest legal CSE price move being read as an error on a low-priced
    line."""
    validate_quote(ticker, quote)
    if our_close <= 0:
        raise SecondSourceShapeError(f"{ticker}: non-positive stored close {our_close}")

    mismatch = abs(quote.close - our_close) / our_close
    tolerance = price_tolerance_fraction(our_close, pct_floor=pct_floor)
    return CrossCheckResult(
        ticker=ticker,
        our_close=our_close,
        their_close=quote.close,
        mismatch_pct=mismatch,
        tolerance_pct=tolerance,
        within_tolerance=mismatch <= tolerance,
    )
