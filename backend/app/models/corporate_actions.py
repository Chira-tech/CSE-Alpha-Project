from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import CorporateActionType


class CorporateAction(Base):
    """Master Spec §9 / §7. This is, per §5, "the highest-consequence data
    in the system" — every row requires `confirmed_by` before it is allowed
    to feed the adjustment-factor build (app.domain.corporate_actions), and
    the ingestion loader must never auto-promote a scraped action to
    confirmed status."""

    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), ForeignKey("securities.ticker"), nullable=False)
    ex_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    type: Mapped[CorporateActionType] = mapped_column(Enum(CorporateActionType), nullable=False)

    # Ratio semantics depend on type: bonus/split "N new per M held" -> ratio
    # stored as Decimal(new_shares_per_held_share); rights issue additionally
    # populates subscription_price and terp.
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    subscription_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    cum_rights_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    terp: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    """Theoretical ex-rights price. Computed by
    app.domain.corporate_actions.compute_terp and stored, not just derived
    on read, so historical adjustment factors are reproducible even if the
    formula changes later."""

    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Free text preserved from ingestion — the announcement's own wording
    plus, for a scraped draft, anything the parser couldn't determine
    (app.ingestion.corporate_actions_loader.build_draft). This is what a
    human reviews before setting confirmed_by; it is never used in any
    calculation."""

    confirmed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_by is not None and self.confirmed_at is not None
