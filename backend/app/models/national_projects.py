from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    NationalProjectFinancingSource,
    NationalProjectImpactMetric,
    NationalProjectStatus,
    NationalProjectTransmissionChannel,
    ProvenanceTier,
)


class NationalProject(Base):
    """Master Spec §34: "A structured register of confirmed Sri Lankan
    projects and policy programmes, each mapped to affected tickers,
    because for a 12–36 month horizon these are the concrete catalysts."

    Confirmation is at the PROJECT level, not per-ticker-impact — §34's
    own text says "human confirmation required before it can affect any
    valuation" about the register entry as a whole, not each affected-
    ticker row separately, so a project and every one of its `impacts`
    are confirmed together as one coherent, complete unit, mirroring
    `CorporateAction`'s own confirmed_by/confirmed_at gate (§7/§8) —
    "the highest-consequence data in the system" pattern, applied here to
    a genuinely different table for a genuinely different reason: a
    corporate action changes a price series; a national project changes
    a forecast assumption (§18.2 names this register explicitly as an
    input to DCF Y1-2 revenue growth)."""

    __tablename__ = "national_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    sponsor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    """§34: "developer" — kept as a free-text field, not a foreign key to
    `securities`/`issuer_registry`, because a project sponsor is
    routinely a state ministry, a foreign government or an unlisted
    contractor, not a CSE-listed entity."""

    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    financing_source: Mapped[NationalProjectFinancingSource | None] = mapped_column(
        Enum(NationalProjectFinancingSource), nullable=True
    )

    capex_lkr: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    capex_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    """§34: "Value in LKR and USD" — both kept, never one derived from the
    other via a spot rate at entry time, because the exchange rate at
    financial close and the rate whenever someone later reads this row
    are different numbers, and silently repricing a stated USD capex
    figure into LKR (or vice versa) would misrepresent what was actually
    announced."""

    phase_start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    phase_expected_completion_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[NationalProjectStatus] = mapped_column(
        Enum(NationalProjectStatus), nullable=False, default=NationalProjectStatus.ANNOUNCED
    )

    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    confirmed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rejected_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Deliberately separate columns from confirmed_by/confirmed_at,
    never a shared "reviewed_by" with a status flag — the exact same
    reasoning `CorporateAction`'s own docstring gives: every query that
    decides whether a row may affect a valuation must be able to keep
    meaning exactly "a human approved this" without also having to
    remember to exclude a rejected row some other way."""

    impacts: Mapped[list["NationalProjectTickerImpact"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_by is not None and self.confirmed_at is not None

    @property
    def is_rejected(self) -> bool:
        return self.rejected_by is not None and self.rejected_at is not None


class NationalProjectTickerImpact(Base):
    """One row per (project, affected ticker) — §34: "Explicit mapping
    with the transmission channel... Estimated revenue or margin effect,
    with the assumption stated and provenance-tagged E or F." The
    provenance tag reuses `ProvenanceTier` directly (its `ESTIMATED`/
    `FORECAST` members are literally "E"/"F") rather than a second,
    parallel two-value enum — the DB column still accepts any
    `ProvenanceTier` value structurally, but `app.domain.national_
    projects` enforces the E-or-F restriction §34 actually states, the
    same "the model is permissive, the domain layer is the real gate"
    split `CorporateAction`'s ratio/ex_date fields already use."""

    __tablename__ = "national_project_ticker_impacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("national_projects.id"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(20), ForeignKey("securities.ticker"), nullable=False)
    transmission_channel: Mapped[NationalProjectTransmissionChannel] = mapped_column(
        Enum(NationalProjectTransmissionChannel), nullable=False
    )
    impact_metric: Mapped[NationalProjectImpactMetric] = mapped_column(
        Enum(NationalProjectImpactMetric), nullable=False
    )
    quantified_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    """A fraction (0.02 = 2%), matching every other percentage in this
    codebase — §34: "Estimated revenue or margin effect". `None` is a
    real, valid state: a project can be logged with a stated transmission
    channel before anyone has quantified its effect, same as this
    project's other "the fact is real, the number isn't ready yet"
    fields elsewhere."""

    impact_description: Mapped[str] = mapped_column(Text, nullable=False)
    """§34: "with the assumption stated" — never optional. A quantified
    percentage with no stated assumption behind it is exactly the
    "confident, precise, entirely fictional number" §15 warns against;
    this field exists so the assumption is always visible next to the
    number, not implied."""

    provenance_tag: Mapped[ProvenanceTier] = mapped_column(Enum(ProvenanceTier), nullable=False)

    project: Mapped[NationalProject] = relationship(back_populates="impacts")
