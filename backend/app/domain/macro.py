"""
Master Spec §29 — the hero variable.

    "CSE equity is priced as a substitute for Treasury bills. When the
    364-day yield falls, domestic money rotates into equities and the
    market re-rates regardless of earnings. The equity earnings yield
    minus 364-day T-bill yield spread is therefore the single most
    powerful macro variable in the system... put it on the home screen as
    the hero chart."

Two inputs, from two different places:

  * Market earnings yield — derived as 1 ÷ market P/E, which the CSE's
    own `dailyMarketSummery` publishes daily. Real, automatic.
  * 364-day T-bill yield — from CBSL. Their published pages are
    JavaScript-rendered, so scraping them is a genuine integration rather
    than a quick fetch (§5 lists it as "API + scrape, release-calendar
    driven"). Until that exists the rate is recorded manually, stored in
    the same point-in-time series table with `source='manual'`, and every
    figure derived from it inherits that provenance. A manually-recorded
    number with a date and a source note is honest; a hard-coded constant
    pretending to be live data would not be.

Series IDs are namespaced by origin so a later CBSL scraper can write
`cbsl.tbill_364d` alongside the manual entries without ambiguity about
which is which.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal

#: CSE-derived, ingested automatically from dailyMarketSummery.
SERIES_MARKET_PER = "cse.market_per"
SERIES_MARKET_PBV = "cse.market_pbv"
SERIES_MARKET_DY = "cse.market_dy"
SERIES_ASPI = "cse.aspi"
SERIES_SP_SL20 = "cse.sp_sl20"
SERIES_MARKET_TURNOVER = "cse.market_turnover"
SERIES_MARKET_CAP = "cse.market_cap"
SERIES_FOREIGN_NET = "cse.foreign_net_flow"

#: CBSL-sourced. Written manually today (source='manual'), by a scraper later.
SERIES_TBILL_364D = "cbsl.tbill_364d"
SERIES_TBILL_91D = "cbsl.tbill_91d"
SERIES_POLICY_RATE = "cbsl.policy_rate"

#: Series the risk-free rate may be taken from, in order of preference.
#: §17.1 Route A: "Rf_LKR = 364-day T-bill yield ... Domestic rupee
#: government paper has not been restructured and is the relevant
#: opportunity cost for a domestic rupee investor."
RISK_FREE_PREFERENCE = (SERIES_TBILL_364D,)


def earnings_yield_from_per(per: Decimal) -> Decimal | None:
    """Earnings yield = 1 ÷ P/E, as a decimal fraction (0.0877 = 8.77%).

    Returns None for a non-positive P/E rather than a number: a negative
    market P/E means aggregate losses, where the reciprocal is not an
    earnings yield in any useful sense, and a zero P/E is a data error.
    """
    if per is None or per <= 0:
        return None
    return Decimal(1) / per


@dataclasses.dataclass(frozen=True)
class EquityTbillSpread:
    """§29's hero number, with everything needed to audit it."""

    obs_date: dt.date
    market_per: Decimal
    earnings_yield: Decimal
    tbill_yield: Decimal
    tbill_obs_date: dt.date
    tbill_source: str
    spread: Decimal

    @property
    def equities_cheap_versus_bills(self) -> bool:
        """A positive spread means equities out-yield the risk-free
        alternative. Deliberately NOT called anything like 'buy signal' —
        §4 Law 6 and §17 of the UI spec forbid a verdict; this is one
        input to a regime read, not a conclusion."""
        return self.spread > 0


def compute_spread(
    *,
    obs_date: dt.date,
    market_per: Decimal,
    tbill_yield: Decimal,
    tbill_obs_date: dt.date,
    tbill_source: str,
) -> EquityTbillSpread | None:
    """`tbill_yield` is a decimal fraction (0.102 for 10.2%), matching the
    earnings yield's units. Storing one as a percentage and the other as a
    fraction would produce a spread wrong by two orders of magnitude while
    still looking like a plausible number — so both are fractions
    everywhere, and the ingestion layer converts once, at the edge."""
    earnings_yield = earnings_yield_from_per(market_per)
    if earnings_yield is None:
        return None
    return EquityTbillSpread(
        obs_date=obs_date,
        market_per=market_per,
        earnings_yield=earnings_yield,
        tbill_yield=tbill_yield,
        tbill_obs_date=tbill_obs_date,
        tbill_source=tbill_source,
        spread=earnings_yield - tbill_yield,
    )
