"""
Phase 2 — §12's sector-relative ratio percentiles.

CLAUDE_CODE_BRIEF.md's own TASK 3.2 names this step literally:
"`sector_percentiles` — every ratio ranked within [sector], winsorised
1%/99% (§12)." Until now nothing computed it — `app/domain/gics.py`'s own
docstring was written for exactly this feature ("this matters for §12's
sector-relative percentiles") and `RatioTable.tsx`'s evidence-panel text
said outright that sector-relative percentiles "arrive with the rest of
the fundamental engine." This module is that arrival.

GROUPING. Two levels, exactly as `app.domain.gics` describes and
`app.domain.sector_sensitivity` already groups by for the same reason:
`Security.cse_sector` (the exchange's own narrow industry-group name,
e.g. "Banks") first, falling back to the wider `Security.gics_sector`
(e.g. "Financials") when the narrow group has fewer than
`MIN_CONSTITUENTS_FOR_SECTOR_PERCENTILE` tickers with a computable value
for that specific ratio — Sri Lanka has three listed telecoms and one
automobile company, and ranking a company against two peers is
technically computable and practically meaningless (gics.py's own
words). A ticker whose sector is unknown, or whose wider group is STILL
too thin, gets no percentile at all — a named reason, never a guessed
number (§1, law 4).

WINSORIZATION. §12's own spec caps the tails at the 1st/99th percentile
before ranking, so one mis-extracted or genuinely-tiny-denominator
outlier can't distort every other company's rank in the same group.
Nearest-rank, not interpolated — the same choice `app.domain.
portfolio_sort._percentile` already makes, for the same reason (a real
observed value, never one invented between two real ones). Honestly
disclosed limitation: with the small group sizes this exchange actually
has (a "sector" here is a handful to a few dozen names, never hundreds),
the 1st/99th percentile boundary is almost always the group's own
min/max — winsorization only starts doing real work once a group is
large enough to have a genuine tail beyond its extremes, which few CSE
sector groups are. It is still applied uniformly, correctly, and does
real work the moment a group is large enough for one to exist.

RANKING DIRECTION. A ticker's percentile is ALWAYS "where does its raw
ratio value rank, ascending, against its peers" — e.g. the 90th
percentile ROE is one of the highest ROEs in the group. This is
deliberately NOT the same convention as `app.domain.liquidity.
percentile_rank`, whose "higher percentile = more liquid" is a
deliberate inversion specific to the Amihud ratio (where a LOWER raw
value is better) — reusing that function unmodified here would silently
rank a sector's WORST ROE at its 100th percentile. This module's own
`_percentile_rank_ascending` is the same pairwise nearest-rank method,
opposite comparison direction, so no ratio here is silently flipped.
No good/bad qualitative label is attached to any ratio's direction
either — the same restraint `app.domain.sector_sensitivity` already
applies to its own +/− scale ("no real basis... exactly the confident,
precise, entirely fictional symbol §15 warns against"). A reader who
knows lower leverage is usually safer can read that off the number
themselves; this module only ranks.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal

#: Matches `app.domain.gics`'s own "two peers is meaningless" reasoning
#: (see module docstring) — the same threshold `app.domain.
#: sector_sensitivity.MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE` already uses
#: for an identical reason, not a fresh number invented for this module.
MIN_CONSTITUENTS_FOR_SECTOR_PERCENTILE = 3

#: §12's own literal spec — see module docstring.
WINSORIZE_LOW_FRACTION = 0.01
WINSORIZE_HIGH_FRACTION = 0.99


@dataclasses.dataclass(frozen=True)
class SectorPercentileResult:
    ratio_key: str
    percentile: Decimal | None
    """0-100, ascending — see module docstring. `None` when no rank could
    be computed; `reason` then says exactly why."""
    group_label: str | None
    group_size: int
    used_wider_sector: bool
    """True when the narrow `cse_sector` group was too thin and the wider
    `gics_sector` group was used instead."""
    reason: str | None


def _nearest_rank(sorted_values: list[Decimal], fraction: float) -> Decimal:
    """Nearest-rank percentile boundary — see module docstring on why
    this, not interpolation."""
    idx = min(int(len(sorted_values) * fraction), len(sorted_values) - 1)
    return sorted_values[idx]


def winsorize(values_by_ticker: dict[str, Decimal]) -> dict[str, Decimal]:
    """Clamp every value into [1st percentile, 99th percentile] of its
    own group — §12's own stated treatment. A group of 0 or 1 has no
    real tail to clip and is returned unchanged."""
    if len(values_by_ticker) < 2:
        return dict(values_by_ticker)
    ordered = sorted(values_by_ticker.values())
    low = _nearest_rank(ordered, WINSORIZE_LOW_FRACTION)
    high = _nearest_rank(ordered, WINSORIZE_HIGH_FRACTION)
    return {ticker: min(max(value, low), high) for ticker, value in values_by_ticker.items()}


def _percentile_rank_ascending(values_by_ticker: dict[str, Decimal]) -> dict[str, Decimal]:
    """0-100 percentile per ticker, HIGHER RAW VALUE = HIGHER PERCENTILE
    — see module docstring for why this is its own function rather than
    reusing `app.domain.liquidity.percentile_rank`'s inverted Amihud
    convention. A single ticker gets the neutral midpoint, 50, the same
    "no real ranking to compute" treatment `percentile_rank` itself uses.
    """
    tickers = list(values_by_ticker.keys())
    n = len(tickers)
    if n == 0:
        return {}
    if n == 1:
        return {tickers[0]: Decimal(50)}
    result: dict[str, Decimal] = {}
    for ticker in tickers:
        worse_count = sum(
            1 for other in tickers if values_by_ticker[other] < values_by_ticker[ticker]
        )
        result[ticker] = Decimal(100) * Decimal(worse_count) / Decimal(n - 1)
    return result


def _group_by_sector(
    tickers: set[str], sector_by_ticker: dict[str, str | None]
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for ticker in tickers:
        sector = sector_by_ticker.get(ticker)
        if sector is None:
            continue
        groups.setdefault(sector, []).append(ticker)
    return groups


def sector_percentiles_for_ratio(
    ratio_key: str,
    values_by_ticker: dict[str, Decimal],
    narrow_sector_by_ticker: dict[str, str | None],
    wide_sector_by_ticker: dict[str, str | None],
) -> dict[str, SectorPercentileResult]:
    """For one ratio, every ticker's sector-relative percentile — see
    module docstring for grouping, winsorization, and ranking-direction
    rules. Only tickers present in `values_by_ticker` (i.e. this ratio is
    actually computable for them) get a result; a ticker with no ratio
    value has nothing to rank and is the caller's concern, not this
    function's.
    """
    tickers_with_value = set(values_by_ticker)
    narrow_groups = _group_by_sector(tickers_with_value, narrow_sector_by_ticker)
    wide_groups = _group_by_sector(tickers_with_value, wide_sector_by_ticker)

    # One percentile map computed per QUALIFYING group, once — every
    # ticker in that group is ranked against the exact same peer set,
    # rather than recomputing (and risking a subtly different) ranking
    # per ticker.
    narrow_ranks = {
        sector: _percentile_rank_ascending(winsorize({t: values_by_ticker[t] for t in members}))
        for sector, members in narrow_groups.items()
        if len(members) >= MIN_CONSTITUENTS_FOR_SECTOR_PERCENTILE
    }
    wide_ranks = {
        sector: _percentile_rank_ascending(winsorize({t: values_by_ticker[t] for t in members}))
        for sector, members in wide_groups.items()
        if len(members) >= MIN_CONSTITUENTS_FOR_SECTOR_PERCENTILE
    }

    results: dict[str, SectorPercentileResult] = {}
    for ticker in tickers_with_value:
        narrow = narrow_sector_by_ticker.get(ticker)
        if narrow is not None and narrow in narrow_ranks:
            results[ticker] = SectorPercentileResult(
                ratio_key=ratio_key,
                percentile=narrow_ranks[narrow][ticker],
                group_label=narrow,
                group_size=len(narrow_groups[narrow]),
                used_wider_sector=False,
                reason=None,
            )
            continue

        wide = wide_sector_by_ticker.get(ticker)
        if wide is not None and wide in wide_ranks:
            results[ticker] = SectorPercentileResult(
                ratio_key=ratio_key,
                percentile=wide_ranks[wide][ticker],
                group_label=wide,
                group_size=len(wide_groups[wide]),
                used_wider_sector=True,
                reason=None,
            )
            continue

        if narrow is None and wide is None:
            reason = "No sector classification on file for this ticker."
        else:
            best_size = max(
                len(narrow_groups.get(narrow, [])) if narrow else 0,
                len(wide_groups.get(wide, [])) if wide else 0,
            )
            reason = (
                f"Fewer than {MIN_CONSTITUENTS_FOR_SECTOR_PERCENTILE} peers with a computable "
                f"value for this ratio, even in the wider GICS sector (found {best_size}) — "
                "ranking against that few peers is technically possible and practically "
                "meaningless."
            )
        results[ticker] = SectorPercentileResult(
            ratio_key=ratio_key,
            percentile=None,
            group_label=None,
            group_size=0,
            used_wider_sector=False,
            reason=reason,
        )
    return results
