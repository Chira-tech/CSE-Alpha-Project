from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PriceDaily(Base):
    """Master Spec §9 `prices_daily`.

    `adj_factor` is the cumulative total-return adjustment factor computed
    by app.domain.corporate_actions.build_adjustment_factor_series — never
    hand-edited. Raw OHLCV columns are never overwritten in place; this is
    a Timescale hypertable (see alembic migration) partitioned on `date`.
    """

    __tablename__ = "prices_daily"

    ticker: Mapped[str] = mapped_column(String(20), ForeignKey("securities.ticker"), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)

    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    trades: Mapped[int | None] = mapped_column(Integer, nullable=True)

    adj_factor: Mapped[Decimal] = mapped_column(Numeric(20, 10), default=Decimal("1.0"), nullable=False)

    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="cse.lk")
