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
    """One of the 11 GICS sectors, derived from the industry-group code's
    first two digits (`app.domain.gics`). The exchange publishes only the
    industry group; the level above follows from the standard."""

    gics_industry_group_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    """e.g. "4010" for Banks. Kept so the sector above stays derivable."""

    cse_sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    """The industry-group NAME as the exchange publishes it, e.g. "Banks",
    "Diversified Financials". This is the CSE's own sector taxonomy."""

    sector_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    """Where the classification came from. Populated by the loader so a
    hand-corrected value is distinguishable from a fetched one and is
    never silently overwritten by a later run."""
    archetype: Mapped[str | None] = mapped_column(String(50), nullable=True)
    """CSE-native archetype (Master Spec §15) — bank, non_bank_finance,
    insurance, diversified_holding, manufacturing, consumer, plantation,
    hotel, telecom, construction_materials, power_energy, property,
    healthcare, logistics, other. Drives the valuation model router (§16)
    and must be manually corrected where GICS misclassifies a CSE
    conglomerate (Appendix P2)."""

    archetype_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    """Where `archetype` came from: `app.domain.archetype`'s proposal
    engine, or a human. Mirrors `sector_source` — a re-run of the proposal
    loader must never silently overwrite a hand-set value."""

    instrument_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    """What the line actually is — see `app.domain.instrument_type`.
    `tradeSummary` returns non-voting lines, fund units and rights
    alongside ordinary shares, and only ordinary/non-voting are common
    equity a valuation model may be pointed at."""

    issuer_code: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    """The stem shared by every line of one company: COMB.N0000 and
    COMB.X0000 both carry `COMB`. Fundamentals belong to the issuer, and
    the §27.1 concentration caps must count one bank once."""

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
