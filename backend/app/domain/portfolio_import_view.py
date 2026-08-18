"""
Bridges a parsed real portfolio export (`app.domain.portfolio_import_
parsing.ParsedPortfolio`) to stored `portfolio_snapshots`/`portfolio_
positions` rows — and the read side, latest-snapshot lookup and cross-
referencing every real held ticker against this system's own `securities`
table.

EVERY UPLOAD CREATES A NEW SNAPSHOT ROW; NONE ARE EVER UPDATED IN PLACE.
See `app/models/portfolio.py`'s own module docstring for the full
reasoning — this mirrors Design Law 2 ("point-in-time or nothing")
already applied everywhere else in this system.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.portfolio_import_parsing import ParsedPortfolio
from app.models.portfolio import PortfolioPosition, PortfolioSnapshot
from app.models.securities import Security


def store_portfolio_snapshot(
    db: Session,
    parsed: ParsedPortfolio,
    *,
    source_filename: str,
    uploaded_at: dt.datetime | None = None,
) -> PortfolioSnapshot:
    """Persists `parsed` as one new, permanent snapshot — never mutates
    or replaces an earlier one."""
    snapshot = PortfolioSnapshot(
        uploaded_at=uploaded_at or dt.datetime.now(dt.timezone.utc),
        source_filename=source_filename,
        stated_total_cost=parsed.stated_total_cost,
        stated_total_market_value=parsed.stated_total_market_value,
        identity_check_passed=parsed.identity_check_passed,
        identity_check_note=parsed.identity_check_note,
    )
    db.add(snapshot)
    db.flush()

    db.add_all(
        PortfolioPosition(
            snapshot_id=snapshot.id,
            ticker=p.ticker,
            quantity=p.quantity,
            avg_price=p.avg_price,
            total_cost=p.total_cost,
            traded_price=p.traded_price,
            market_value=p.market_value,
            unrealized_gain_loss=p.unrealized_gain_loss,
        )
        for p in parsed.positions
    )
    db.commit()
    db.refresh(snapshot)
    return snapshot


def latest_snapshot(db: Session) -> PortfolioSnapshot | None:
    """The most recently uploaded real snapshot — "what do I currently
    hold, according to my own broker" is always this, never an inferred
    or diffed state."""
    return db.scalar(
        select(PortfolioSnapshot).order_by(PortfolioSnapshot.uploaded_at.desc()).limit(1)
    )


def list_snapshots(db: Session) -> list[PortfolioSnapshot]:
    """Every real snapshot ever uploaded, most recent first — the real
    history Design Law 2 exists to preserve."""
    return list(db.scalars(select(PortfolioSnapshot).order_by(PortfolioSnapshot.uploaded_at.desc())))


def unrecognized_tickers(db: Session, snapshot: PortfolioSnapshot) -> list[str]:
    """Real held tickers in this snapshot that this system's own
    `securities` table doesn't currently carry — a delisted name, a
    board-suffix mismatch, or a real gap in this system's own universe
    coverage. Named, not silently ignored — `app.models.portfolio.
    PortfolioPosition.ticker` is deliberately not a foreign key for
    exactly this reason."""
    known = set(db.scalars(select(Security.ticker)).all())
    return sorted({p.ticker for p in snapshot.positions if p.ticker not in known})
