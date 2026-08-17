"""
Apply `app.domain.archetype`'s proposals to `securities.archetype`.

Pure database plumbing — the judgement calls (which GICS group means
which archetype, which name patterns signal a conglomerate) all live in
the domain module. This just reads existing securities, proposes,
writes what can be written, and reports what couldn't be.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.archetype import propose_archetype
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.ingestion.archetype")

SOURCE = "app.domain.archetype:proposed"


def apply_archetype_proposals(
    db: Session, *, overwrite_manual: bool = False
) -> dict[str, object]:
    """Propose and write archetypes. Returns a summary including the list
    of tickers that need a human, so the CLI can print something a
    reviewer can act on rather than just a count.

    Same non-clobber rule as `sector_loader`: a row whose `archetype_source`
    is anything other than this module's own SOURCE was set by a human and
    is left alone unless `overwrite_manual` is passed.
    """
    securities = db.scalars(select(Security)).all()

    proposed = skipped_manual = unchanged = 0
    needs_review: list[tuple[str, str]] = []

    for security in securities:
        if security.archetype_source not in (None, SOURCE) and not overwrite_manual:
            skipped_manual += 1
            continue

        result = propose_archetype(security.name, security.cse_sector)
        if result.archetype is None:
            needs_review.append((security.ticker, result.reason))
            continue

        if security.archetype == result.archetype and security.archetype_source == SOURCE:
            unchanged += 1
            continue

        security.archetype = result.archetype
        security.archetype_source = SOURCE
        proposed += 1

    db.commit()

    classified = sum(1 for s in securities if s.archetype)
    summary = {
        "securities": len(securities),
        "classified": classified,
        "proposed": proposed,
        "unchanged": unchanged,
        "skipped_manual": skipped_manual,
        "needs_review": needs_review,
    }
    logger.info(
        "archetype proposals: %d securities, %d classified, %d proposed, "
        "%d unchanged, %d skipped (manual), %d need review",
        len(securities), classified, proposed, unchanged, skipped_manual, len(needs_review),
    )
    return summary
