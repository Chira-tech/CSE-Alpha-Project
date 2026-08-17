"""
Ingest the exchange's issuer registry from `cntSecurity`.

See `app.models.registry.IssuerRegistry` for what this is and how far it
goes. The short version: it is the only source found that names companies
which no longer trade, which is what §7's survivorship requirement needs.

`cntSecurity` is a GET — one of very few on this API — and takes no
parameters.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.instrument_type import issuer_code as issuer_code_of
from app.ingestion.cse_client import CseClient
from app.models.registry import IssuerRegistry
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.ingestion.issuer_registry")


class RegistryShapeError(RuntimeError):
    """The registry did not come back in the shape we verified."""


def fetch_registry(client: CseClient) -> list[dict]:
    payload = client.get_json("cntSecurity")
    rows = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RegistryShapeError(
            f"cntSecurity returned no usable `content` list (got {type(payload).__name__})"
        )
    return rows


def upsert_registry(
    db: Session, rows: list[dict], *, observed_on: dt.date | None = None
) -> dict[str, int]:
    """Insert or refresh the registry. Returns a small summary.

    `first_seen` is never moved once set: it is the earliest date we can
    prove the issuer existed, and the only lower bound on a delisting date
    this exchange will give us.
    """
    observed_on = observed_on or dt.date.today()

    # Which issuers currently have a tradeable line? Derived here rather
    # than trusted from the registry, which has no such flag.
    trading = {
        code
        for (code,) in db.execute(
            select(Security.issuer_code).where(Security.issuer_code.is_not(None)).distinct()
        ).all()
    }

    existing = {row.issuer_code: row for row in db.scalars(select(IssuerRegistry)).all()}

    inserted = updated = 0
    newly_delisted: list[str] = []

    for raw in rows:
        symbol = str(raw.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        # Defensive: the registry publishes bare issuer codes, but strip a
        # line suffix if one ever appears so the join key stays consistent.
        code = issuer_code_of(symbol)
        delisted = bool(raw.get("deleted"))

        record = existing.get(code)
        if record is None:
            db.add(
                IssuerRegistry(
                    issuer_code=code,
                    name=str(raw.get("name") or code).strip(),
                    security_id=raw.get("securityId"),
                    board_id=raw.get("boardId"),
                    delisted=delisted,
                    currently_trading=code in trading,
                    first_seen=observed_on,
                    last_seen=observed_on,
                )
            )
            inserted += 1
            continue

        if delisted and not record.delisted:
            newly_delisted.append(code)
        record.name = str(raw.get("name") or record.name).strip()
        record.board_id = raw.get("boardId")
        record.delisted = delisted
        record.currently_trading = code in trading
        record.last_seen = observed_on
        updated += 1

    db.commit()

    for code in newly_delisted:
        logger.warning("issuer %s is now flagged delisted by the exchange", code)

    summary = {
        "registry_issuers": len(rows),
        "inserted": inserted,
        "updated": updated,
        "delisted": sum(1 for r in rows if r.get("deleted")),
        "trading": len(trading),
        "newly_delisted": len(newly_delisted),
    }
    logger.info("issuer registry: %s", summary)
    return summary


def ingest_issuer_registry(
    client: CseClient, db: Session, *, observed_on: dt.date | None = None
) -> dict[str, int]:
    return upsert_registry(db, fetch_registry(client), observed_on=observed_on)
