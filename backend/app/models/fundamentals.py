from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ProvenanceTier


class Fundamental(Base):
    """Master Spec §9 `fundamentals` / §6 point-in-time discipline.

    THE non-negotiable rule of the whole data layer: every model must query
    on `first_available_date <= t`, never `period_end <= t`. Restatements
    (the COMPANY issuing a different number for a period it already
    reported) are inserted as a new `version`, the old row is never
    updated in place. See app.domain.point_in_time for the query helper
    that enforces this so callers can't accidentally bypass it.

    Promoting an AI-assisted extraction to Reported after human review is
    a DIFFERENT operation from a restatement and does NOT bump `version`:
    the company's number hasn't changed, only our confidence in having
    captured it correctly has. `confirmed_by`/`confirmed_at` and
    `provenance_tier` are updated in place by
    app.api.routes.fundamentals.confirm_extraction;
    `first_available_date` is never touched by confirmation either — it
    must always reflect when the market could see the filing, never when
    this system got around to reviewing it.
    """

    __tablename__ = "fundamentals"
    __table_args__ = (
        Index("ix_fundamentals_ticker", "ticker"),
        # (ticker, first_available_date): the point-in-time query shape
        # every caller is supposed to use (§6 — always filter on
        # first_available_date <= t, never period_end <= t).
        Index("ix_fundamentals_ticker_first_available", "ticker", "first_available_date"),
        Index("ix_fundamentals_ticker_source_url", "ticker", "source_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), ForeignKey("securities.ticker"), nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)  # 'quarterly' | 'annual'
    first_available_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    statement_line: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="LKR")
    provenance_tier: Mapped[ProvenanceTier] = mapped_column(Enum(ProvenanceTier), nullable=False)
    restated_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Master Spec §8: an AI-assisted figure "must show the source
    snippet" in the UI. Populated by the PDF extractor with the text
    surrounding the matched value so a reviewer can sanity-check it
    without re-opening the source PDF."""

    confirmed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
