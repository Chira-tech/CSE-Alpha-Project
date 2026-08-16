from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FloatData(Base):
    """Master Spec §9 `float_data`. Feeds Gate 2 (§11.1: free float >= 15%)."""

    __tablename__ = "float_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), ForeignKey("securities.ticker"), nullable=False)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    shares_issued: Mapped[int] = mapped_column(Integer, nullable=False)

    public_float_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    """Nullable because the source that carries it (quarterly shareholding
    disclosures, §5) isn't wired up yet, while shares_issued IS available
    from companyInfoSummery. Recording the real figure and leaving this
    genuinely-unknown one NULL is what Design Law 3 requires; Gate 2's
    free-float test treats NULL as "cannot evaluate", never as a pass."""
    top20_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    controlling_holder: Mapped[str | None] = mapped_column(String(200), nullable=True)
