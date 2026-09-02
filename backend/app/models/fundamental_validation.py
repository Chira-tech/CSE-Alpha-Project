from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FundamentalValidation(Base):
    """One row per `fundamentals` row: the result of the last time the
    data-integrity gate ran against it.

    The model the product owner asked for (3 Sep 2026) is deliberately
    binary — a value either passes every check and is available to the
    valuation engine, or it fails one and goes to the fundamentals queue
    for review. No status ladder, no confidence number. `passed` is that
    flag; `failures` is the list of `{check, detail}` a reviewer sees.

    A `fundamentals` row with NO row here has simply not been swept yet;
    it is treated as not-yet-failed (still usable) until the nightly
    `validate_fundamentals` job gets to it. `method` records which
    version of the check battery produced this verdict so the whole table
    can be re-swept when the checks change.
    """

    __tablename__ = "fundamental_validations"
    __table_args__ = (
        Index("ix_fundamental_validations_passed", "passed"),
    )

    fundamental_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fundamentals.id", ondelete="CASCADE"), primary_key=True
    )
    checked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    method: Mapped[str] = mapped_column(String(60), nullable=False)
    failures_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    """JSON array of `{"check": str, "detail": str}` — empty `[]` when
    `passed` is true."""
