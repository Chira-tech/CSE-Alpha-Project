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

    published_market_cap: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    """CSE's own independently-published market capitalisation
    (`companyInfoSummery.reqSymbolInfo.marketCap`) — fetched in the SAME
    call as `shares_issued` (`app.ingestion.security_enrichment.
    enrich_security`) but, until TASK 0.1's plausibility gate needed a
    genuinely independent cross-check, silently discarded rather than
    stored. See `app.domain.sanity.SanityContext.mcap`'s own docstring
    for exactly what this does and does not catch, and why it must be
    this exchange-published figure rather than `price x shares` computed
    locally — comparing a number against itself would be a tautology,
    not a check."""
