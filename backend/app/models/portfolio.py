"""
Master Spec §41's own "Position level" data (holdings, average cost,
current price, market value, unrealised P&L) — sourced here from a real
CDS/broker portfolio export the user uploads themselves, not yet the
full §41 portfolio engine (no transaction log, no realised P&L history,
no thesis-drift tracking — Phase 8, still genuinely unbuilt; this is the
narrower, real, immediately useful slice: "what do I currently own,
according to my own broker").

EVERY UPLOAD IS A NEW, PERMANENT SNAPSHOT — NEVER AN OVERWRITE. The same
Design Law 2 this whole system already applies everywhere else ("Point-
in-time or nothing... restated statements are inserted as new versions,
never overwritten") applies here too: a user's broker export changes
every time they trade, and overwriting the prior snapshot in place would
throw away the only real history of what they held and when — exactly
the kind of information §42's own future thesis-drift monitor and §41's
own future P&L history would need. `PortfolioSnapshot.uploaded_at` is
the real timestamp that orders snapshots; `latest` is a query concern
(see `app.domain.portfolio_import_view`), not a column.

NO ACCOUNT/NIC IDENTIFIER IS STORED. The real file's own title row
carries the account holder's real NIC number and CDS account code —
genuine personal data with no bearing on "which stocks does this system
know about." The parser (`app.domain.portfolio_import_parsing`)
deliberately never extracts it, and nothing in this schema has a column
for it.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    stated_total_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    """The file's own "Total" row cost figure — kept alongside the
    parsed positions' own summed total as a real, independent
    cross-check (see `app.domain.portfolio_import_parsing`'s own
    identity check), not because this system needs the figure itself."""

    stated_total_market_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    identity_check_passed: Mapped[bool] = mapped_column(nullable=False)
    identity_check_note: Mapped[str] = mapped_column(String(500), nullable=False)

    positions: Mapped[list["PortfolioPosition"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("portfolio_snapshots.id"), nullable=False)

    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    """Deliberately NOT a foreign key to `securities.ticker` — a real
    held position must never be silently dropped just because this
    system's own `securities` table doesn't (yet) carry that ticker
    (a delisted name, a board-suffix mismatch, a security type this
    system's own registry hasn't classified). `app.domain.portfolio_
    import_view` names any ticker it can't cross-reference rather than
    refusing to store the real holding."""

    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    avg_price: Mapped[Decimal] = mapped_column(Numeric(18, 5), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)

    traded_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    """The file's OWN price as of its own export time — never treated as
    a live quote by any caller. See `app.domain.market_view`/`app.
    domain.company_price_history` for this system's own real live price
    sources."""

    market_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    unrealized_gain_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)

    snapshot: Mapped["PortfolioSnapshot"] = relationship(back_populates="positions")
