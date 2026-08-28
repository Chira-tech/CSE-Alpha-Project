"""
R1 T4.6.4 — "the highest-value new feature in this release": clicking a
sector on the Macro screen's sensitivity matrix opens a panel with a
market-share treemap, a ranked table, and the sector's macro
sensitivities carried through from the matrix already on screen.

WHY COMPOSITE SCORE ISN'T IN THE RANKED TABLE, MEASURED NOT ASSUMED:
the brief's own mockup lists composite score as a ranked-table column.
`composite_score_for()` is a genuinely expensive per-ticker computation
— timed live against this system's own real data at ~11s for ONE
ticker (JKH.N0000, 23 Aug 2026) — the same real cost `app.domain.
composite_score_view`'s own module docstring already discloses for the
Opportunities screen's Valuation/Growth pillars. A sector with 10-15
constituents would mean 2-3 minutes of synchronous computation on a
single click. Rather than silently drop the column or fake a number,
it is omitted here with this same real, measured reason attached to
the response, and each row links to the company file, which computes
and shows the real score for that one ticker in ~11s.

Fair value gap DOES appear, reusing `opportunity_ranking_for` — a real,
already-accepted ~18s whole-universe cost this same system already
pays on every Opportunities screen load — filtered down to this
sector's own tickers rather than re-deriving valuation logic here.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.market_cap_view import bulk_market_cap_for
from app.domain.opportunity_ranking_view import opportunity_ranking_for
from app.models.securities import Security


@dataclass(frozen=True)
class SectorCompany:
    ticker: str
    name: str
    market_cap: Decimal | None
    market_cap_reason: str | None
    """Set whenever `market_cap` is `None` — missing shares-issued or
    missing price, named rather than silently blank."""

    pct_of_sector: Decimal | None
    """Share of `market_cap` among constituents that have a real,
    computable market cap. `None` whenever this ticker's own cap is
    `None` — never computed against a denominator this ticker itself
    isn't part of."""

    fair_value_gap_pct: Decimal | None
    """(current_price - fair_value) / fair_value, from the same real
    triangulated blend the company file's own Fair value section shows
    — positive means trading above fair value. `None` with `gap_reason`
    set whenever this ticker has no confirmed fundamentals, no
    computable fair value, or no live price."""

    gap_reason: str | None


@dataclass(frozen=True)
class SectorDrilldown:
    sector: str
    as_of: dt.date
    companies: tuple[SectorCompany, ...]
    total_market_cap: Decimal | None
    """Sum of every constituent's real market cap where computable;
    `None` only when the sector has zero constituents with one."""

    excluded_from_market_cap_pct: int
    """Count of constituents with `market_cap is None` — real gaps in
    the free-float/shares-issued data this system has today, not
    treated as zero."""

    composite_score_omitted_reason: str


def sector_drilldown_for(db: Session, sector: str, as_of: dt.date | None = None) -> SectorDrilldown | None:
    stamp = as_of or dt.date.today()

    tickers_and_names = db.execute(
        select(Security.ticker, Security.name)
        .where(Security.cse_sector == sector, Security.delisting_date.is_(None))
        .order_by(Security.ticker)
    ).all()
    if not tickers_and_names:
        return None

    tickers = tuple(t for t, _ in tickers_and_names)
    caps = bulk_market_cap_for(db, tickers, stamp)

    # Real cost, already paid once per click, not per constituent — see
    # this module's own docstring for why this is the accepted tradeoff
    # (real §18-26 fair value per ticker) over a fabricated shortcut.
    ranking = opportunity_ranking_for(db, stamp)
    gap_by_ticker: dict[str, tuple[Decimal | None, str | None]] = {}
    for c in ranking.ranked:
        if c.blended_fair_value_per_share and c.current_price and c.blended_fair_value_per_share != 0:
            gap = (c.current_price - c.blended_fair_value_per_share) / c.blended_fair_value_per_share
            gap_by_ticker[c.ticker] = (gap, None)
        else:
            gap_by_ticker[c.ticker] = (None, "No computable fair value or live price.")
    for c in ranking.excluded:
        gap_by_ticker[c.ticker] = (None, c.warnings[0] if c.warnings else "Excluded from the confirmed-fundamentals set.")

    total_cap = sum((v for v in caps.values() if v is not None), Decimal(0))
    excluded_count = sum(1 for v in caps.values() if v is None)

    companies = []
    for ticker, name in tickers_and_names:
        cap = caps.get(ticker)
        gap, gap_reason = gap_by_ticker.get(ticker, (None, "No confirmed fundamentals for this ticker."))
        companies.append(
            SectorCompany(
                ticker=ticker,
                name=name,
                market_cap=cap,
                market_cap_reason=None if cap is not None else "Missing real shares-issued or a real recent close.",
                pct_of_sector=(cap / total_cap if cap is not None and total_cap > 0 else None),
                fair_value_gap_pct=gap,
                gap_reason=gap_reason,
            )
        )
    # Largest first — a treemap and a "market share" table both read
    # naturally biggest-to-smallest; unknown caps sort last, not first,
    # so a real gap in the data doesn't visually claim the top slot.
    companies.sort(key=lambda c: (c.market_cap is None, -(c.market_cap or Decimal(0))))

    return SectorDrilldown(
        sector=sector,
        as_of=stamp,
        companies=tuple(companies),
        total_market_cap=total_cap if total_cap > 0 else None,
        excluded_from_market_cap_pct=excluded_count,
        composite_score_omitted_reason=(
            "Composite score is a real, per-ticker computation measured at ~11s each (JKH.N0000, 23 "
            "Aug 2026) — computing it for every constituent synchronously on a single click would be "
            "minutes, not seconds, so it is left out of this table rather than faked or silently "
            "slowed down. Open any company below for its own real score."
        ),
    )
