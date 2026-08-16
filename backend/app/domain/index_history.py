"""
Recovering the official ASPI close series from cse.lk's `chartData`.

`chartData` (chartId=1, period=5) is the only historical series the public
CSE API exposes — about 240 daily points, roughly one year. It is the only
route to ASPI history we have, so it is worth reading correctly.

THE TRAP. Each point carries `d` (epoch millis), `v` (an index level) and
`pc` (a percentage change). The obvious reading — "`v` is the close for
day `d`" — is wrong on roughly 38% of days, and wrong by amounts (up to
0.55%, 20-50 index points) that look entirely plausible on a chart.

What the timestamps actually say, measured over a full year of real data:

  - Points stamped AFTER the 14:30 Colombo close carry the official close.
    For 69 consecutive pairs where both points are post-close stamped,
    `v[i]/v[i-1] - 1` equals the published `pc[i]` to 0.00000 percentage
    points. Not approximately — exactly.
  - Points stamped BEFORE the open (08:16 Colombo is the common one) carry
    a provisional or carried-over level, not the close. For those, the
    same identity is off by a median of 0.08pp.

But `pc` is trustworthy in BOTH cases: it is always measured against the
prior day's official close. That gives an exact recovery for every day
that has a successor in the series:

    close[i-1] = v[i] / (1 + pc[i]/100)

VERIFIED AGAINST AN INDEPENDENT SOURCE. This is not an internal-consistency
argument. The Central Bank publishes the ASPI in its Daily Economic
Indicators PDF, which is a different institution and a different pipeline.
On every early-stamped date whose CBSL edition could be fetched
(2026-08-05, 2026-08-04, 2026-07-28), CBSL's ASPI matched the
reconstruction to 0.00 index points while disagreeing with the raw `v` by
48.90, 19.79 and 20.70 points respectively.

So: reconstruct from `pc`, and treat a directly-usable post-close `v` as a
free integrity check rather than the primary reading.

The final point in the series has no successor, so it can only be used
when it is itself post-close stamped. Pulling the feed before the close
therefore yields no observation for that day, which is correct — the
close does not exist yet.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("Asia/Colombo")

# The CSE closing auction ends at 14:30 Colombo. Observed post-close stamps
# cluster at 14:47-14:55 and pre-open stamps at 08:16, so this threshold
# separates the two populations with a wide margin either side.
MARKET_CLOSE = dt.time(14, 30)

# A daily move beyond this is not something the ASPI does; it means the
# feed changed units, a decimal moved, or `pc` was misread. The largest
# single-day ASPI moves on record are well inside 20%.
_MAX_DAILY_MOVE = Decimal("0.20")

SOURCE_DIRECT = "cse.lk:chartData"
SOURCE_RECOVERED = "cse.lk:chartData(pc)"


class IndexHistoryError(ValueError):
    """Raised when the feed cannot be read without guessing."""


@dataclass(frozen=True)
class ChartPoint:
    """One raw `chartData` point, already converted to Colombo time."""

    stamped_at: dt.datetime
    value: Decimal
    pct_change: Decimal

    @property
    def session_date(self) -> dt.date:
        return self.stamped_at.date()

    @property
    def is_post_close(self) -> bool:
        return self.stamped_at.timetz().replace(tzinfo=None) >= MARKET_CLOSE


@dataclass(frozen=True)
class IndexClose:
    """An official closing level for one session."""

    obs_date: dt.date
    value: Decimal
    source: str

    @property
    def first_available_date(self) -> dt.date:
        """The close is public the same day it is struck. True for this
        series; deliberately not a shared default, because CBSL series
        publish days or weeks after their observation date."""
        return self.obs_date


def parse_points(payload: object) -> list[ChartPoint]:
    """Convert the raw JSON list into typed points, in date order.

    Rejects duplicate session dates rather than picking one: two points
    for the same day means the feed's shape changed and the assumption
    this module rests on needs re-verifying, not working around.
    """
    if not isinstance(payload, list):
        raise IndexHistoryError(f"chartData returned {type(payload).__name__}, expected a list")

    points: list[ChartPoint] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise IndexHistoryError(f"chartData entry is {type(raw).__name__}, expected an object")
        try:
            stamped_at = dt.datetime.fromtimestamp(raw["d"] / 1000, tz=dt.timezone.utc).astimezone(
                MARKET_TZ
            )
            value = Decimal(str(raw["v"]))
            pct_change = Decimal(str(raw["pc"]))
        except (KeyError, TypeError, ValueError, OSError, InvalidOperation) as exc:
            raise IndexHistoryError(f"unreadable chartData point {raw!r}: {exc}") from exc
        if value <= 0:
            raise IndexHistoryError(f"non-positive index level {value} at {stamped_at:%Y-%m-%d}")
        points.append(ChartPoint(stamped_at=stamped_at, value=value, pct_change=pct_change))

    points.sort(key=lambda p: p.stamped_at)
    dates = [p.session_date for p in points]
    if len(set(dates)) != len(dates):
        dupes = sorted({d for d in dates if dates.count(d) > 1})
        raise IndexHistoryError(f"chartData returned duplicate session dates: {dupes}")
    return points


def reconstruct_closes(points: list[ChartPoint]) -> tuple[list[IndexClose], list[str]]:
    """Recover the official close for every session the feed can support.

    Returns the closes plus a list of human-readable integrity warnings.
    Warnings do not stop the ingest: one anomalous day should be visible,
    not fatal to the other 239.
    """
    closes: list[IndexClose] = []
    warnings: list[str] = []

    for previous, current in zip(points, points[1:]):
        factor = 1 + current.pct_change / 100
        if factor <= 0:
            warnings.append(
                f"{previous.session_date}: pc={current.pct_change} implies a "
                f"non-positive prior close; skipped"
            )
            continue
        recovered = current.value / factor
        move = abs(recovered / previous.value - 1) if previous.value else Decimal(0)

        # A post-close `v` is independently the official close, so it is a
        # real cross-check on the recovery — not a tautology.
        if previous.is_post_close:
            drift = abs(recovered - previous.value) / previous.value
            if drift > Decimal("0.0001"):
                warnings.append(
                    f"{previous.session_date}: post-close level {previous.value} disagrees "
                    f"with the level recovered from the next day's pc ({recovered:.2f}) "
                    f"by {drift * 100:.4f}%"
                )
            closes.append(
                IndexClose(previous.session_date, previous.value, SOURCE_DIRECT)
            )
            continue

        if move > _MAX_DAILY_MOVE:
            warnings.append(
                f"{previous.session_date}: recovered close {recovered:.2f} implies a "
                f"{move * 100:.1f}% move from the stamped level; skipped as implausible"
            )
            continue
        closes.append(
            IndexClose(previous.session_date, recovered.quantize(Decimal("0.01")), SOURCE_RECOVERED)
        )

    # The newest point has no successor to recover it, so it is usable only
    # if it is itself post-close. Before 14:30 there simply is no close.
    if points:
        last = points[-1]
        if last.is_post_close:
            closes.append(IndexClose(last.session_date, last.value, SOURCE_DIRECT))
        else:
            warnings.append(
                f"{last.session_date}: newest point is stamped {last.stamped_at:%H:%M} "
                f"(pre-close) and has no successor, so its close is not yet knowable"
            )

    return closes, warnings
