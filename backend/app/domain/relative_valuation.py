"""
§20: Relative valuation — done properly.

§20.2's four justified multiples, each answering "what multiple does this
company's own fundamentals justify, and is it trading below that?" rather
than the naive "is this P/E lower than the sector median?" comparison
§20 opens by criticising:

    Justified P/E      = payout × (1 + g) ÷ (Ke - g)
    Justified P/B       = (ROE - g) ÷ (Ke - g)
    Justified EV/EBIT   = (1 - tax) × (1 - g ÷ ROIC) ÷ (WACC - g)
    Justified P/S       = net margin × payout × (1 + g) ÷ (Ke - g)

Pure functions, same discipline as `app.domain.ratios`: every input is
named, every guard is stated, a `None` result always carries a reason
rather than being silently omitted.

THREE PARTS OF §20 THIS MODULE DELIBERATELY DOES NOT ATTEMPT, AND WHY.
§20.1's "three comparison frames" (own 5/10-year history, sector peers,
whole-market) and §20.2's cross-sectional regression
(`P/B_i = a + b·ROE_i + c·growth_i + d·leverage_i + e·payout_i + ε_i`,
re-estimated monthly across the whole exchange) are both corpus-level
computations — they need every security's multiple history or every
security's current fundamentals in one dataset, not one company's. That
is exactly the split this project already draws elsewhere between a pure
domain module and its `_view.py` companion (see `cost_of_equity_view.py`,
which queries prices/macro series and calls into the pure
`app.domain.cost_of_equity`) — except here the view layer would need to
query the WHOLE universe, not one ticker, and hasn't been built yet.
`justified_price_to_book` and friends are the pure arithmetic that
corpus-level layer would call once per company; building that layer is
tracked in ROADMAP.md rather than attempted here.

Justified EV/EBIT needs ROIC, which `app.domain.ratios.NOT_YET_COMPUTABLE`
already lists as unavailable (needs NOPAT, total debt, cash — none
extracted). `justified_ev_to_ebit` is built and tested regardless — a
caller who does have a ROIC estimate (or ROIC becomes computable later)
gets a correct answer immediately — but it will return `None` with a
named reason from any caller passing `roic=None`, same as every other
NOT_YET_COMPUTABLE guard in this codebase.

`justified_price_to_book` is the SAME formula §19.3 uses for its own
justified P/B — deliberately defined once, here, rather than duplicated
in `app.domain.dividend_residual_income`, because it is unambiguously a
relative-valuation multiple (§20.2's own table) that §19.3 happens to
reference, not the reverse.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class JustifiedMultipleResult:
    multiple_name: str
    value: Decimal | None
    formula: str
    note: str | None = None


def justified_price_to_earnings(
    payout_ratio: Decimal, growth_rate: Decimal, cost_of_equity: Decimal
) -> JustifiedMultipleResult:
    """Justified P/E = payout × (1 + g) ÷ (Ke - g) (§20.2)."""
    formula = "payout × (1 + g) ÷ (Ke - g)"
    if cost_of_equity <= growth_rate:
        return JustifiedMultipleResult(
            "justified_pe", None, formula, f"Ke ({cost_of_equity}) <= growth ({growth_rate})."
        )
    value = payout_ratio * (Decimal(1) + growth_rate) / (cost_of_equity - growth_rate)
    return JustifiedMultipleResult("justified_pe", value, formula)


def justified_price_to_book(
    roe: Decimal, growth_rate: Decimal, cost_of_equity: Decimal
) -> JustifiedMultipleResult:
    """Justified P/B = (ROE - g) ÷ (Ke - g) (§19.3 and §20.2 — the same
    formula both sections use)."""
    formula = "(ROE - g) ÷ (Ke - g)"
    if cost_of_equity <= growth_rate:
        return JustifiedMultipleResult(
            "justified_pb", None, formula, f"Ke ({cost_of_equity}) <= growth ({growth_rate})."
        )
    value = (roe - growth_rate) / (cost_of_equity - growth_rate)
    return JustifiedMultipleResult("justified_pb", value, formula)


def justified_ev_to_ebit(
    tax_rate: Decimal,
    growth_rate: Decimal,
    roic: Decimal | None,
    wacc: Decimal,
) -> JustifiedMultipleResult:
    """Justified EV/EBIT = (1 - tax) × (1 - g ÷ ROIC) ÷ (WACC - g) (§20.2).

    `roic` is `None` by default across this codebase — see module
    docstring — so a `None` result here is expected until ROIC is
    computable, not a bug in this function.
    """
    formula = "(1 - tax) × (1 - g ÷ ROIC) ÷ (WACC - g)"
    if roic is None:
        return JustifiedMultipleResult(
            "justified_ev_ebit", None, formula,
            "roic not supplied — app.domain.ratios.NOT_YET_COMPUTABLE (needs NOPAT, "
            "total debt, cash, none of which are extracted).",
        )
    if roic == 0:
        return JustifiedMultipleResult("justified_ev_ebit", None, formula, "roic is zero.")
    if wacc <= growth_rate:
        return JustifiedMultipleResult(
            "justified_ev_ebit", None, formula, f"WACC ({wacc}) <= growth ({growth_rate})."
        )
    value = (Decimal(1) - tax_rate) * (Decimal(1) - growth_rate / roic) / (wacc - growth_rate)
    return JustifiedMultipleResult("justified_ev_ebit", value, formula)


def justified_price_to_sales(
    net_margin: Decimal, payout_ratio: Decimal, growth_rate: Decimal, cost_of_equity: Decimal
) -> JustifiedMultipleResult:
    """Justified P/S = net margin × payout × (1 + g) ÷ (Ke - g) (§20.2)."""
    formula = "net margin × payout × (1 + g) ÷ (Ke - g)"
    if cost_of_equity <= growth_rate:
        return JustifiedMultipleResult(
            "justified_ps", None, formula, f"Ke ({cost_of_equity}) <= growth ({growth_rate})."
        )
    value = net_margin * payout_ratio * (Decimal(1) + growth_rate) / (cost_of_equity - growth_rate)
    return JustifiedMultipleResult("justified_ps", value, formula)


@dataclass(frozen=True)
class TradingMultiples:
    """The current, observed multiples for one company — what the four
    justified figures above are compared against. Any field left `None`
    means that multiple isn't displayable (§20.3's own normalisation
    rules — e.g. P/E "not meaningful" for a loss-making company)."""

    price_to_earnings: Decimal | None = None
    price_to_book: Decimal | None = None
    ev_to_ebit: Decimal | None = None
    price_to_sales: Decimal | None = None


@dataclass(frozen=True)
class JustifiedVsTradingComparison:
    multiple_name: str
    justified: Decimal | None
    trading: Decimal | None
    discount_to_justified_pct: Decimal | None
    """(justified - trading) ÷ justified — positive means trading BELOW
    what fundamentals justify (cheap by this measure); negative means
    trading above it. `None` when either side is unavailable."""

    read_as_cheap: bool | None


def compare_to_justified(
    justified: JustifiedMultipleResult, trading_value: Decimal | None
) -> JustifiedVsTradingComparison:
    """§20.2: "is it trading below that [justified multiple]?" — this is
    that single comparison, for one multiple. A screener assembling all
    four would call this once per multiple, per company."""
    if justified.value is None or trading_value is None or justified.value == 0:
        return JustifiedVsTradingComparison(justified.multiple_name, justified.value, trading_value, None, None)
    discount = (justified.value - trading_value) / justified.value
    return JustifiedVsTradingComparison(
        justified.multiple_name, justified.value, trading_value, discount, discount > 0
    )
