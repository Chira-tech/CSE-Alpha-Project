from __future__ import annotations

import datetime as dt

from sqlalchemy import Index, Boolean, Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IssuerRegistry(Base):
    """The exchange's own list of every issuer it knows about.

    Master Spec §7 requires that "delisted, suspended and defaulted
    companies remain in the database" — without them a backtest only ever
    sees survivors, and Part N #1 lists survivorship as a headline failure
    mode. Our `securities` table is built from `tradeSummary`, which by
    construction contains only what traded, so on its own it can never
    satisfy that.

    `cntSecurity` does better: 369 issuers against the 264 that traded,
    and it carries a `deleted` flag. It is kept in its own table rather
    than folded into `securities` for a deliberate reason — it is
    ISSUER-level (symbol `COMB`, not `COMB.N0000`), so writing these rows
    into a line-level table would mean inventing line suffixes the
    exchange never published. `securities.issuer_code` joins to it.

    HOW FAR THIS GOES, honestly: 11 issuers are flagged deleted, and a
    further 94 are in the registry without trading and without a flag —
    debt-only issuers like Bank of Ceylon, suspended companies, and names
    that simply did not trade that session, indistinguishable from each
    other here. Eleven delistings across the exchange's whole history is
    implausibly few, so this is a partial record. It moves the universe
    from survivors-only to survivors-plus-eleven; it does not close §7.
    """

    __tablename__ = "issuer_registry"
    __table_args__ = (
    # Declared here to match what the migrations actually created. These
    # indexes existed in the database but not on the model, so
    # `alembic revision --autogenerate` would have emitted a migration
    # DROPPING them (found in the 29 Aug audit via `alembic check`).
        Index("ix_issuer_registry_delisted", "delisted"),
    )

    issuer_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    security_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """The exchange's own internal id, kept for cross-referencing."""

    board_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Stored raw and UNINTERPRETED. Six distinct values appear (0-5) with
    an uneven spread (181/38/94/26/25/5) that matches neither the CSE's
    three published boards nor any sector taxonomy, and no endpoint
    explains it. Naming it "Main Board" or similar on that evidence would
    be a guess recorded as a fact, so it stays a number until a source
    says what it means."""

    delisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """The exchange's `deleted` flag. True means genuinely gone —
    verifiable by name (DFCC Vardhana Bank merged into DFCC Bank;
    Commercial Leasing Company became Commercial Leasing & Finance).
    False does NOT mean actively trading, only "not flagged"."""

    currently_trading: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Whether any line of this issuer appeared in the latest
    `tradeSummary`. Derived by us, not published by the exchange —
    which is why it is a separate column from `delisted` rather than
    collapsed into one status."""

    first_seen: Mapped[dt.date] = mapped_column(Date, nullable=False)
    last_seen: Mapped[dt.date] = mapped_column(Date, nullable=False)
    """When we first and last observed this issuer in the registry. A
    delisting date the exchange never publishes can at least be bounded
    from below once this has been running for a while."""

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IssuerRegistry {self.issuer_code} delisted={self.delisted}>"
