from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DataHealthSnapshot(Base):
    """One row per day: the check ledger frozen so the Data Health screen
    can show a real trend (`docs/CSE_Data_Health_Diagnosis_And_Protocol.md`
    §9.1 — "one sparkline per row") rather than only today's number.

    Written opportunistically by `GET /data-health` when no row exists for
    today yet — one cheap INSERT per calendar day, no separate job. The
    payload is the serialised `check_ledger` list; the reader pulls
    `checkable_pct` / `pass_pct_of_checkable` per check out of it.
    """

    __tablename__ = "data_health_snapshots"
    __table_args__ = (Index("ix_data_health_snapshots_as_of", "as_of", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ledger_json: Mapped[str] = mapped_column(Text, nullable=False)
