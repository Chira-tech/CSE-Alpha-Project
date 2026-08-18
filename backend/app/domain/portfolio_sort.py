"""
§35.1's real construction method: "SMB / HML: 2×3 Fama–French sort...
Size split at universe median... book-to-market split at 30th/70th
percentiles." This module builds that sort as a reusable, general
mechanism — six portfolios (Small/Big × Low/Medium/High), the SMB-style
size-factor return and the HML-style value-factor return computed from
them — shared by every §35 factor that needs a size-crossed style split
(SMB, HML, HML_hard, MOM all specify the same 2×3 shape), rather than
reimplemented per factor.

THE REAL FAMA-FRENCH FORMULAS, NOT AN APPROXIMATION.
    size_factor  = mean(S/L, S/M, S/H) − mean(B/L, B/M, B/H)
    style_factor = mean(S/H, B/H) − mean(S/L, B/L)
The size factor averages across all three style buckets on each side
(so it isn't contaminated by the style split); the style factor averages
across both size buckets on each side (so it isn't contaminated by the
size split) — this cross-averaging is the actual point of a 2×3 sort
over a simpler independent single-variable sort, and is exactly what
makes SMB and HML "cleaner" reads of size and style than a naive top-
minus-bottom-decile spread would be.

VALIDATED AGAINST A KNOWN, INJECTED DOUBLE PREMIUM, NOT JUST THAT IT
RUNS. A synthetic universe with a real, known +2% size premium AND a
real, known 3% high-minus-low style premium baked into each stock's own
return recovers both — size_factor_return ≈ 0.02, style_factor_return ≈
0.03 — the same "check against a known ground truth" discipline every
other statistical module this project applies.

EQUAL-WEIGHTED WITHIN EACH PORTFOLIO, A DISCLOSED SIMPLIFICATION, NOT
FAMA-FRENCH'S OWN VALUE-WEIGHTED CONVENTION. The original methodology
value-weights each of the six portfolios by market cap; this system's
own market-cap figures are already a disclosed full-shares-issued proxy
for free float (see `app.domain.market_cap`), so value-weighting on top
of an already-approximate cap would compound one approximation with
another for a precision this system's real inputs don't support. Equal-
weighting within each portfolio matches this project's own already-
established simplification for §33's sector returns (`app.domain.
sector_sensitivity_view`'s own module docstring draws the identical
line for the identical reason).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: A real, disclosed floor. Fama-French's own six-portfolio construction
#: needs every bucket non-empty for the cross-averaging to mean anything;
#: 12 is the minimum that guarantees an average of 2 per bucket if
#: perfectly balanced, itself a thin but real floor for this system's own
#: real, currently-small universe depth (see the module-level caller's
#: own further disclosure of how thin real coverage actually is today).
MIN_TICKERS = 12


@dataclass(frozen=True)
class SortConstituent:
    key: str
    """Ticker or other identifier — carried through only for the
    per-portfolio membership breakdown, not used in the sort math."""

    size_value: Decimal
    style_value: Decimal
    period_return: Decimal


@dataclass(frozen=True)
class TwoByThreeSortResult:
    portfolio_returns: dict[str, Decimal]
    """Keyed `"S/L"`, `"S/M"`, `"S/H"`, `"B/L"`, `"B/M"`, `"B/H"` —
    absent (not zero) for any bucket with no real constituents."""

    portfolio_counts: dict[str, int]
    size_factor_return: Decimal
    style_factor_return: Decimal
    size_median: Decimal
    style_p30: Decimal
    style_p70: Decimal
    constituent_count: int
    note: str


def _percentile(sorted_values: list[Decimal], fraction: float) -> Decimal:
    """Nearest-rank percentile — matches `app.domain.sector_sensitivity`
    -adjacent modules' own preference for a real observed value over an
    interpolated one that might not correspond to any real constituent."""
    idx = min(int(len(sorted_values) * fraction), len(sorted_values) - 1)
    return sorted_values[idx]


def two_by_three_sort(constituents: list[SortConstituent]) -> TwoByThreeSortResult | None:
    """§35.1's real 2×3 sort, applied to one real period's worth of real
    constituent data — size split at the universe median, style split at
    the 30th/70th percentiles, six portfolios, both factor returns.

    `None` — never a number computed from too little real data — below
    `MIN_TICKERS`, or when any of the six portfolios ends up with zero
    real constituents (a real, possible outcome on a thin universe, not
    a bug — reported rather than silently working around it by merging
    buckets)."""
    if len(constituents) < MIN_TICKERS:
        return None

    sizes = sorted(c.size_value for c in constituents)
    styles = sorted(c.style_value for c in constituents)
    size_median = _percentile(sizes, 0.5)
    style_p30 = _percentile(styles, 0.3)
    style_p70 = _percentile(styles, 0.7)

    buckets: dict[str, list[Decimal]] = {k: [] for k in ("S/L", "S/M", "S/H", "B/L", "B/M", "B/H")}
    for c in constituents:
        size_label = "S" if c.size_value <= size_median else "B"
        if c.style_value <= style_p30:
            style_label = "L"
        elif c.style_value > style_p70:
            style_label = "H"
        else:
            style_label = "M"
        buckets[f"{size_label}/{style_label}"].append(c.period_return)

    if any(not returns for returns in buckets.values()):
        # At least one of the six portfolios has zero real constituents —
        # the cross-averaging formulas would silently treat a missing
        # bucket as absent from the average, changing what the factor
        # return actually measures. Refused outright rather than guessed
        # at by merging buckets or dropping a term from the average.
        return None

    portfolio_returns = {k: sum(v) / len(v) for k, v in buckets.items()}
    portfolio_counts = {k: len(v) for k, v in buckets.items()}

    small_avg = (portfolio_returns["S/L"] + portfolio_returns["S/M"] + portfolio_returns["S/H"]) / 3
    big_avg = (portfolio_returns["B/L"] + portfolio_returns["B/M"] + portfolio_returns["B/H"]) / 3
    size_factor = small_avg - big_avg

    high_avg = (portfolio_returns["S/H"] + portfolio_returns["B/H"]) / 2
    low_avg = (portfolio_returns["S/L"] + portfolio_returns["B/L"]) / 2
    style_factor = high_avg - low_avg

    note = (
        f"2x3 sort on {len(constituents)} real constituents: size factor "
        f"{size_factor:.4f}, style factor {style_factor:.4f}. Portfolio counts: "
        + ", ".join(f"{k}={v}" for k, v in portfolio_counts.items())
    )

    return TwoByThreeSortResult(
        portfolio_returns=portfolio_returns, portfolio_counts=portfolio_counts,
        size_factor_return=size_factor, style_factor_return=style_factor,
        size_median=size_median, style_p30=style_p30, style_p70=style_p70,
        constituent_count=len(constituents), note=note,
    )
