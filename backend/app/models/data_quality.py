from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DataAlert(Base):
    """Not named explicitly as a schema block in §9 but required by the
    behaviour specified in §7 (reconciliation), §8 (freshness) and §50
    (kill switches): a ticker whose adjusted-vs-raw total return mismatches
    by more than the threshold is quarantined from every model until a
    human resolves it. This table is that quarantine record."""

    __tablename__ = "data_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'reconciliation_mismatch' | 'stale_source' | 'schema_change' | 'fetch_failure'
    detail: Mapped[str] = mapped_column(String(1000), nullable=False)
    mismatch_pct: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    raised_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    @property
    def is_quarantined(self) -> bool:
        return not self.resolved
