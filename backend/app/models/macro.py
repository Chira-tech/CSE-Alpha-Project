from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MacroSeries(Base):
    """Master Spec §9 `macro_series`. Point-in-time discipline applies here
    too — `first_available_date` is the release date, not the observation
    date (e.g. June CCPI is typically released weeks into July)."""

    __tablename__ = "macro_series"

    series_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    obs_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    first_available_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
