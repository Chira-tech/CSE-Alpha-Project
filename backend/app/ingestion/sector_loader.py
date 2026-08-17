"""
Sector classification from the exchange's own GICS publication.

Two endpoints, both POST form, found by watching what the CSE's "GICS
Classification" page actually requests (they are not in the endpoint
inventory this project built earlier, which is why sector membership was
wrongly recorded as unavailable):

    sector_list                    -> the 20 industry groups (+ 2 indices)
    listBySector  sectorId=<id>    -> that group's constituent symbols

Constituents come back as full line symbols (`LGL.N0000`), so this maps
per LINE, not per issuer — which is right: a company's voting and
non-voting lines belong to the same industry group, and mapping by line
keeps the join trivial without assuming that.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.gics import is_industry_group, sector_for_industry_group
from app.ingestion.cse_client import CseClient
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.ingestion.sectors")

SOURCE = "cse.lk:listBySector"


class SectorFetchError(RuntimeError):
    """The classification could not be read in the shape we verified."""


def fetch_sector_map(client: CseClient) -> dict[str, tuple[str, str]]:
    """Return `{symbol: (industry_group_name, industry_group_code)}`.

    One request per industry group, paced by the client's own rate limit
    (§5). Twenty requests is a small, infrequent job.
    """
    payload = client.post_form("sector_list", data={})
    groups = payload.get("indicesList") if isinstance(payload, dict) else None
    if not isinstance(groups, list) or not groups:
        raise SectorFetchError("sector_list returned no `indicesList`")

    mapping: dict[str, tuple[str, str]] = {}
    classified_groups = 0

    for group in groups:
        code = group.get("indexCode")
        # The list mixes in the ASPI and S&P SL20, which have no code.
        # Filing every listed company under "All Share Price Index" is
        # exactly the failure this check exists to prevent.
        if not is_industry_group(code):
            logger.debug("skipping non-industry-group entry %r", group.get("name"))
            continue

        body = client.post_form("listBySector", data={"sectorId": group["id"]})
        rows = body.get("reqIndustryBySectors") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            logger.warning("listBySector returned no list for %s", group.get("name"))
            continue

        classified_groups += 1
        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol:
                mapping[symbol] = (str(group["name"]).strip(), str(code))

    if classified_groups == 0:
        raise SectorFetchError("no industry groups could be read from sector_list")

    logger.info(
        "sector map: %d symbols across %d industry groups", len(mapping), classified_groups
    )
    return mapping


def apply_sector_map(
    db: Session, mapping: dict[str, tuple[str, str]], *, overwrite_manual: bool = False
) -> dict[str, int]:
    """Write the classification onto `securities`.

    A row whose `sector_source` is set to anything other than this
    loader's own source was put there by a human and is left alone unless
    `overwrite_manual` is passed. Appendix P2 treats the classification as
    hand-correctable, and a scheduled refresh that silently reverted those
    corrections would make the correction pointless.
    """
    updated = skipped_manual = unchanged = 0
    securities = db.scalars(select(Security)).all()

    for security in securities:
        entry = mapping.get(security.ticker.upper())
        if entry is None:
            continue
        name, code = entry

        if security.sector_source not in (None, SOURCE) and not overwrite_manual:
            skipped_manual += 1
            continue

        gics_sector = sector_for_industry_group(code)
        if (
            security.cse_sector == name
            and security.gics_industry_group_code == code
            and security.gics_sector == gics_sector
        ):
            unchanged += 1
            continue

        security.cse_sector = name
        security.gics_industry_group_code = code
        security.gics_sector = gics_sector
        security.sector_source = SOURCE
        updated += 1

    db.commit()

    classified = sum(1 for s in securities if s.cse_sector)
    summary = {
        "securities": len(securities),
        "classified": classified,
        "unclassified": len(securities) - classified,
        "updated": updated,
        "unchanged": unchanged,
        "skipped_manual": skipped_manual,
    }
    logger.info("sector classification: %s", summary)
    return summary


def ingest_sectors(
    client: CseClient, db: Session, *, overwrite_manual: bool = False
) -> dict[str, int]:
    return apply_sector_map(
        db, fetch_sector_map(client), overwrite_manual=overwrite_manual
    )
