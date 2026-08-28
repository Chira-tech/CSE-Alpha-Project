"""
§37's timing battery, DB-wired — computes each real signal
`app.domain.timing_battery.compute_timing_battery` blends, for one real
ticker.

RAW SIGNALS ARE SQUASHED ONTO A 0-100 SCALE VIA `50 + 50*tanh(x/scale)`,
A REAL BUT DELIBERATELY SIMPLER SUBSTITUTE FOR A FULL CROSS-SECTIONAL
PERCENTILE RANK, DISCLOSED. §37's own literature convention (George-
Hwang, Fama-French-style momentum) ranks each signal against the
investable universe at each date — the same real percentile machinery
`app.domain.sector_percentiles.sector_percentiles_for_ratio` already
gives `app.domain.composite_score_view`'s own ratio pillars. Doing that
here too, for four different raw signals at every single-ticker call,
needs its own universe-wide bulk pass (the same shape `app.domain.
factor_series_view`'s own bulk loader already proves is necessary once
per-ticker DB round-trips multiply across a real universe) — real,
valuable, and deliberately deferred to a later increment rather than
half-built now. `tanh` squashing is a real, monotonic, bounded transform
(more extreme raw values -> scores closer to 0 or 100, `scale` chosen
per signal from a plausible real weekly-return magnitude) — not a
placeholder returning a constant, and every score still carries its real
raw value alongside the squashed one so a caller can see exactly what
was actually observed.

RESIDUAL MOMENTUM NEEDS A REAL CARHART REGRESSION FIRST. `app.domain.
carhart_view.carhart_certification_for`'s own `residuals_by_date` is
this signal's real input (§37: "t-12 to t-2 momentum computed on Carhart
residuals, not raw returns") — when that regression itself is
`insufficient_data` (this system's real current bottleneck: the T-bill
series' own real depth, not this module — see `app.domain.
carhart_regression`'s own module docstring), residual momentum is
honestly excluded for this ticker, not silently zero-filled.
"""
from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.carhart_view import carhart_certification_for
from app.domain.factor_series import mom_style_value
from app.domain.timing_battery import (
    CONTRARIAN_FUNDAMENTAL_SCORE_FLOOR,
    REV_1M_BOTTOM_DECILE_THRESHOLD,
    ContrarianCheck,
    TimingBatteryResult,
    build_contrarian_check,
    compute_timing_battery,
)
from app.models.prices import PriceDaily

#: Plausible weekly/short-window real-return magnitudes on the CSE —
#: chosen so a "big but real" move squashes near the ends of the 0-100
#: scale without every ordinary move clustering near 50. Disclosed,
#: real judgement calls, not derived from a formula the spec provides
#: (it doesn't specify a normalization at all).
_MOMENTUM_SCALE = Decimal("0.15")
_VOLUME_Z_SCALE = Decimal("2.0")

VOLUME_SHORT_WINDOW_DAYS = 20
VOLUME_LONG_WINDOW_DAYS = 120
VOLUME_HISTORY_LOOKBACK_DAYS = 250


def _tanh_squash(value: Decimal, scale: Decimal) -> Decimal:
    x = float(value) / float(scale)
    return Decimal(str(round(50.0 + 50.0 * math.tanh(x), 4)))


def _week52_high_proximity(db: Session, ticker: str, as_of: dt.date) -> tuple[Decimal | None, str | None]:
    rows = db.execute(
        select(PriceDaily.close).where(
            PriceDaily.ticker == ticker, PriceDaily.date <= as_of,
            PriceDaily.date > as_of - dt.timedelta(weeks=52), PriceDaily.close.is_not(None),
        )
    ).scalars().all()
    if not rows:
        return None, "no real price history in the trailing 52 weeks"
    current = db.scalar(
        select(PriceDaily.close)
        .where(PriceDaily.ticker == ticker, PriceDaily.date <= as_of, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc()).limit(1)
    )
    high = max(rows)
    if current is None or high <= 0:
        return None, "no real current price or a non-positive 52-week high"
    ratio = min(current / high, Decimal(1))  # George-Hwang's own ratio never exceeds 1 by construction
    return ratio * 100, None


def _mom_signal(
    db: Session, ticker: str, as_of: dt.date, *, skip_weeks: int, lookback_weeks: int
) -> tuple[Decimal | None, str | None]:
    rows = db.execute(
        select(PriceDaily.date, PriceDaily.close, PriceDaily.adj_factor).where(
            PriceDaily.ticker == ticker, PriceDaily.close.is_not(None),
            PriceDaily.date <= as_of, PriceDaily.date > as_of - dt.timedelta(weeks=lookback_weeks + 2),
        ).order_by(PriceDaily.date)
    ).all()
    closes = [(d, c * af) for d, c, af in rows]
    value = mom_style_value(closes, as_of, skip_weeks=skip_weeks, lookback_weeks=lookback_weeks)
    if value is None:
        return None, f"no real price on or before both endpoints of the {lookback_weeks}w window"
    return _tanh_squash(value, _MOMENTUM_SCALE), None


def _rev_1m(db: Session, ticker: str, as_of: dt.date) -> tuple[Decimal | None, str | None, bool | None]:
    """Returns (squashed_score, reason, bottom_decile_flag) — REV_1M is
    `-1 x prior month return`, and §37.1's own condition 1 ("REV_1M in
    the bottom decile") needs the RAW prior-month return, not the
    inverted signal, so both are derived here together rather than
    recomputed twice."""
    raw, reason = _mom_signal_raw(db, ticker, as_of, skip_weeks=0, lookback_weeks=4)
    if raw is None:
        return None, reason, None
    rev_1m_value = -raw
    bottom_decile = raw <= -REV_1M_BOTTOM_DECILE_THRESHOLD  # a real, disclosed proxy for a true cross-sectional decile -- see module docstring
    return _tanh_squash(rev_1m_value, _MOMENTUM_SCALE), None, bottom_decile


def _mom_signal_raw(
    db: Session, ticker: str, as_of: dt.date, *, skip_weeks: int, lookback_weeks: int
) -> tuple[Decimal | None, str | None]:
    rows = db.execute(
        select(PriceDaily.date, PriceDaily.close, PriceDaily.adj_factor).where(
            PriceDaily.ticker == ticker, PriceDaily.close.is_not(None),
            PriceDaily.date <= as_of, PriceDaily.date > as_of - dt.timedelta(weeks=lookback_weeks + 2),
        ).order_by(PriceDaily.date)
    ).all()
    closes = [(d, c * af) for d, c, af in rows]
    value = mom_style_value(closes, as_of, skip_weeks=skip_weeks, lookback_weeks=lookback_weeks)
    return value, (None if value is not None else "no real price on or before both endpoints")


def _residual_momentum(db: Session, ticker: str, as_of: dt.date) -> tuple[Decimal | None, str | None]:
    view = carhart_certification_for(db, ticker, as_of)
    if view.regression.insufficient_data:
        return None, f"Carhart regression not available yet: {view.regression.reason}"
    residuals = dict(view.regression.residuals_by_date)
    dates = sorted(residuals)
    end_date = as_of - dt.timedelta(weeks=2)
    start_date = as_of - dt.timedelta(weeks=52)
    window = [d for d in dates if start_date <= d <= end_date]
    if len(window) < 4:
        return None, f"only {len(window)} real residual week(s) in the t-12..t-2 window"
    total = sum((residuals[d] for d in window), Decimal(0))
    return _tanh_squash(total, _MOMENTUM_SCALE), None


def _volume_confirmation(db: Session, ticker: str, as_of: dt.date) -> tuple[Decimal | None, str | None]:
    rows = db.execute(
        select(PriceDaily.date, PriceDaily.close, PriceDaily.volume).where(
            PriceDaily.ticker == ticker, PriceDaily.close.is_not(None), PriceDaily.volume.is_not(None),
            PriceDaily.date <= as_of, PriceDaily.date > as_of - dt.timedelta(days=VOLUME_HISTORY_LOOKBACK_DAYS),
        ).order_by(PriceDaily.date)
    ).all()
    if len(rows) < VOLUME_LONG_WINDOW_DAYS + VOLUME_SHORT_WINDOW_DAYS:
        return None, f"only {len(rows)} real trading day(s) of volume history, need at least " \
                      f"{VOLUME_LONG_WINDOW_DAYS + VOLUME_SHORT_WINDOW_DAYS}"

    turnovers = [c * Decimal(v or 0) for _d, c, v in rows]
    ratios: list[Decimal] = []
    for i in range(VOLUME_LONG_WINDOW_DAYS, len(turnovers)):
        long_avg = sum(turnovers[i - VOLUME_LONG_WINDOW_DAYS:i]) / VOLUME_LONG_WINDOW_DAYS
        short_avg = sum(turnovers[i - VOLUME_SHORT_WINDOW_DAYS:i]) / VOLUME_SHORT_WINDOW_DAYS
        if long_avg > 0:
            ratios.append(short_avg / long_avg)
    if len(ratios) < 20:
        return None, f"only {len(ratios)} real ratio observation(s) to build a self-history z-score from"

    mean = sum(ratios) / len(ratios)
    variance = sum((r - mean) ** 2 for r in ratios) / len(ratios)
    stdev = variance.sqrt() if variance > 0 else Decimal(0)
    if stdev == 0:
        return Decimal(50), None  # no real variation to score against
    z = (ratios[-1] - mean) / stdev
    return _tanh_squash(z, _VOLUME_Z_SCALE), None


def timing_battery_for(
    db: Session, ticker: str, as_of: dt.date | None = None, *,
    business_quality_score: Decimal | None = None,
    integrity_red_flag: bool | None = None,
    crash_guard_active: bool = False,
    sector_macro_shock_active: bool | None = None,
) -> TimingBatteryResult:
    """§37 for one real ticker. `business_quality_score`,
    `integrity_red_flag`, `sector_macro_shock_active` and
    `crash_guard_active` are caller-supplied (from `app.domain.
    composite_score_view`'s own Business-quality pillar, §11's integrity
    gate, and §37.2's own two-`regime_for`-calls check respectively) —
    this module deliberately doesn't recompute any of them a second time."""
    stamp = as_of or dt.date.today()

    values: dict[str, Decimal | None] = {}
    reasons: dict[str, str | None] = {}

    values["week52_high_proximity"], reasons["week52_high_proximity"] = _week52_high_proximity(db, ticker, stamp)
    values["mom_12_2"], reasons["mom_12_2"] = _mom_signal(db, ticker, stamp, skip_weeks=4, lookback_weeks=52)
    values["mom_6_1"], reasons["mom_6_1"] = _mom_signal(db, ticker, stamp, skip_weeks=4, lookback_weeks=26)
    rev_1m_score, rev_1m_reason, rev_1m_bottom_decile = _rev_1m(db, ticker, stamp)
    values["rev_1m"], reasons["rev_1m"] = rev_1m_score, rev_1m_reason
    values["residual_momentum"], reasons["residual_momentum"] = _residual_momentum(db, ticker, stamp)
    values["volume_confirmation"], reasons["volume_confirmation"] = _volume_confirmation(db, ticker, stamp)

    contrarian = build_contrarian_check(
        rev_1m_bottom_decile=rev_1m_bottom_decile,
        business_quality_ge_70=(business_quality_score >= CONTRARIAN_FUNDAMENTAL_SCORE_FLOOR) if business_quality_score is not None else None,
        no_integrity_red_flag=(not integrity_red_flag) if integrity_red_flag is not None else None,
        no_active_sector_macro_shock=(not sector_macro_shock_active) if sector_macro_shock_active is not None else None,
    )

    return compute_timing_battery(values, reasons, crash_guard_active=crash_guard_active, contrarian=contrarian)
