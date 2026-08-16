from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Boolean, Date, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ProvenanceTier


class Fundamental(Base):
    """Master Spec §9 `fundamentals` / §6 point-in-time discipline.

    THE non-negotiable rule of the whole data layer: every model must query
    on `first_available_date <= t`, never `period_end <= t`. Restatements
    are inserted as a new `version`, the old row is never updated in place.
    See app.domain.point_in_time for the query helper that enforces this
    so callers can't accidentally bypass it.
    """

    __tablename__ = "fundamentals"

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
