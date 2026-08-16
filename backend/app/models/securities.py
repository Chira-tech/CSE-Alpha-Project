from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.config import settings


class Security(Base):
    """Master Spec §9 `securities` table.

    `reporting_lag_days` defaults from settings but is meant to be
    overridden per company once verified — the spec is explicit that the
    3-month/6-month lag is a conservative *default*, not a fact, and must be
    "verified per company and stored on the security record" (§6).
    """

    __tablename__ = "securities"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    isin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    gics_sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cse_sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    archetype: Mapped[str | None] = mapped_column(String(50), nullable=True)
    """CSE-native archetype (Master Spec §15) — bank, non_bank_finance,
    insurance, diversified_holding, manufacturing, consumer, plantation,
    hotel, telecom, construction_materials, power_energy, property,
    healthcare, logistics, other. Drives the valuation model router (§16)
    and must be manually corrected where GICS misclassifies a CSE
    conglomerate (Appendix P2)."""

    listing_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    delisting_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    board: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fiscal_year_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    """MM-DD, e.g. '03-31'. A large share of CSE companies use 31 March
    (§2.2), which is why the annual factor formation date is fixed at
    30 September market-wide rather than derived per company."""

    reporting_lag_days_quarterly: Mapped[int] = mapped_column(
        Integer, default=settings.default_quarterly_reporting_lag_days, nullable=False
    )
    reporting_lag_days_annual: Mapped[int] = mapped_column(
        Integer, default=settings.default_annual_reporting_lag_days, nullable=False
    )
    currency_exposure_profile: Mapped[str | None] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Security {self.ticker} {self.name!r}>"
