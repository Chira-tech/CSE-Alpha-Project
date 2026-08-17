"""
Per-company daily price history from `companyChartDataByStock`.

This is the endpoint the earlier survey missed. That survey tested
`chartData` (param `chartId`) against every security id and got `[]` for
all of them, and concluded — reasonably, from that evidence — that no
per-company historical series exists on the public API at all. It was
looking at the wrong endpoint. `companyChartDataByStock` takes a
DIFFERENT id space (`stockId`, from `allSecurityCode`'s `id`, not the
chart ids `chartData` uses) and returns a genuine one-year daily series
per line: high, low, a daily price, and volume.

VERIFIED, not assumed. For COMB.N0000 on 2026-08-14 the endpoint returned
h=205.0, l=203.0, p=204.5, q=190303 — which match `companyInfoSummery`'s
independently-fetched hiTrade, lowTrade, closingPrice and tdyShareVolume
for that ticker EXACTLY. Across a full year of COMB.N0000 history: `p` is
never outside `[l, h]` (0 violations in 241 rows), only weekdays appear,
and the one >4-day gap lines up with the Sinhala/Tamil New Year holiday
already seen in the ASPI series.

WHY THIS IS NOT THE SAME TRAP AS THE ASPI's `chartData`. That endpoint's
points mixed "whatever index level was last cached" with "the actual
close", distinguished only by a timestamp's time-of-day, and reading it
naively was wrong 38% of the time. This endpoint has no equivalent
ambiguity: it returns one aggregated bar per calendar day built from that
day's completed trades, not a cached snapshot. There is no `pc` field to
reconcile against here (`c`/`pc` are populated only in the intraday
period, a different shape not used by this module) — `p`/`h`/`l` are the
day's actual figures, not something that needs recovering.

A CLOSE-OUTSIDE-RANGE WARNING IS COMMON, NOT RARE — characterised across
the full 283-ticker backfill (17 Aug 2026), not just the one JKH row
above. 2,058 such warnings landed across 115 of 283 tickers. They are not
concentrated in one instrument type — ordinary, non-voting and fund-unit
lines are all represented (e.g. NEH.N0000, NTB.X0000, CALC.U0000) — but
they are heavily concentrated in thinly-traded small caps, consistent
with the exchange's own day-bar computation occasionally carrying a stale
reference low/high forward on a session with very few trades, rather than
with anything wrong in this parser. The guard above already handles it
safely: only the contradicted bound is dropped, the close (the figure
every downstream calculation actually needs) is always kept, and nothing
is silently fabricated. Re-check this characterisation if the warning
rate changes materially on a future backfill — that would suggest the
exchange's own data quality shifted, not that this comment is wrong.

WHAT THIS DOES NOT SOLVE. It comes from cse.lk, the same institution as
every other price figure in this system. It does not satisfy
PARAMETERS.md #5's independent second-source requirement — that still
needs a source outside the exchange's own systems, e.g. a broker EOD
file. What it DOES solve: the momentum, Dimson beta and Amihud liquidity
inputs that Phase 2/6 needed and that a prior survey concluded were
simply unavailable.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("Asia/Colombo")

# Verified live: values other than 1-5 fall back to a short recent window
# rather than erroring, so passing anything else would silently return
# far less history than intended. 5 is the deepest available, matching
# the index-level chartData endpoint's own maximum.
PERIOD_ONE_YEAR = 5


class CompanyPriceHistoryError(ValueError):
    """Raised when the feed cannot be read without guessing."""


@dataclass(frozen=True)
class DailyBar:
    date: dt.date
    close: Decimal
    volume: int
    high: Decimal | None = None
    low: Decimal | None = None


def parse_bars(payload: object) -> tuple[list[DailyBar], list[str]]:
    """Convert the raw `chartData` array into typed, date-sorted bars.

    Returns `(bars, warnings)`. A structurally broken PAYLOAD (not a dict,
    no `chartData` list, an unparseable date) raises — that means the
    endpoint's shape changed and nothing in the response can be trusted.
    A problem confined to ONE bar — an unreadable row, a missing `l`/`h`,
    a close outside its own day's range — instead drops just that field
    or that bar and is reported as a warning, matching
    `app.domain.index_history`'s reconstruct_closes. Verified live: one
    real day (JKH.N0000, 2025-10-23) has `l: null` with `h` and `p` both
    present, out of 241 bars checked. Raising on that would discard a
    company's entire year over one missing field on one day; the day's
    real close and volume are not in doubt and are worth keeping.

    `open` is always null on this endpoint (verified across every symbol
    probed) so it is not modelled here — `PriceDaily.open` simply stays
    unfilled for backfilled rows rather than being invented from `close`.
    """
    if not isinstance(payload, dict):
        raise CompanyPriceHistoryError(
            f"companyChartDataByStock returned {type(payload).__name__}, expected an object"
        )
    rows = payload.get("chartData")
    if not isinstance(rows, list):
        raise CompanyPriceHistoryError("companyChartDataByStock response has no `chartData` list")

    bars: list[DailyBar] = []
    warnings: list[str] = []

    for raw in rows:
        if not isinstance(raw, dict):
            raise CompanyPriceHistoryError(f"unreadable bar {raw!r}")
        try:
            date = dt.datetime.fromtimestamp(raw["t"] / 1000, tz=dt.timezone.utc).astimezone(
                MARKET_TZ
            ).date()
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise CompanyPriceHistoryError(f"unreadable timestamp in {raw!r}: {exc}") from exc

        try:
            close = Decimal(str(raw["p"]))
            volume = int(raw["q"])
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            warnings.append(f"{date}: unreadable close/volume, bar dropped ({exc})")
            continue
        if volume < 0:
            warnings.append(f"{date}: negative volume {volume}, bar dropped")
            continue

        high = _optional_decimal(raw.get("h"))
        low = _optional_decimal(raw.get("l"))
        if raw.get("h") is not None and high is None:
            warnings.append(f"{date}: unreadable high {raw.get('h')!r}, field dropped")
        if raw.get("l") is not None and low is None:
            warnings.append(f"{date}: unreadable low {raw.get('l')!r}, field dropped")

        if high is not None and low is not None and low > high:
            warnings.append(f"{date}: low {low} exceeds high {high}, both dropped")
            high = low = None
        elif high is not None and close > high:
            warnings.append(f"{date}: close {close} exceeds high {high}, high dropped")
            high = None
        elif low is not None and close < low:
            warnings.append(f"{date}: close {close} below low {low}, low dropped")
            low = None

        bars.append(DailyBar(date=date, high=high, low=low, close=close, volume=volume))

    bars.sort(key=lambda b: b.date)
    dates = [b.date for b in bars]
    if len(set(dates)) != len(dates):
        dupes = sorted({d for d in dates if dates.count(d) > 1})
        raise CompanyPriceHistoryError(f"duplicate dates in response: {dupes}")
    return bars, warnings


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
