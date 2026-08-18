"""
TASK 0.1's "Persist a `valuation_quarantine` row with the failed rule and
the offending input values" — implemented by REUSING `app.models.data_
quality.DataAlert` rather than adding a new, parallel table.

WHY REUSE RATHER THAN A NEW `valuation_quarantine` TABLE, AS THE BRIEF'S
OWN SPEC PSEUDOCODE SUGGESTS. This system already has a real, tested
quarantine mechanism — `DataAlert` plus `app.jobs.reconciliation.
is_quarantined` — built for exactly this shape of problem: "a ticker
this system currently does not trust, with a named reason, until a human
resolves it" (§7/§50). `app.jobs.second_source_reconciliation` already
reuses the same table for a second, unrelated failure mode
(`alert_type="second_source_mismatch"`) rather than inventing its own.
A third table for a third failure mode would fragment "why is this
ticker not trusted right now" across three places a Data Health screen
(TASK 1.2) would then have to query separately, for no real benefit —
`alert_type="valuation_sanity_block"` is the whole difference this needs.

WHY THIS IS A SEPARATE MODULE FROM `app.domain.sanity`, NOT FOLDED IN.
`sanity.py` is deliberately pure — no `Session`, no I/O, mirroring
`app.domain.price_ladder`'s own split (see that module's docstring).
Persistence is a genuinely separate concern with its own real design
question (below) that a pure predicate module has no business deciding.

WHY RECORDING IS IDEMPOTENT RATHER THAN "INSERT ON EVERY BLOCKED CALL".
`valuation_summary_for` is a live, on-demand read — called every time a
company file, portfolio row or opportunity ranking is viewed, not once a
night like `app.jobs.reconciliation`. Inserting a new `DataAlert` on
every single blocked call would flood the table with duplicates for a
company a user simply keeps looking at. `record_sanity_result` instead
checks for an already-open, unresolved alert of this `alert_type` for
this ticker first: a still-blocked result leaves an existing open alert
untouched (no new row); a NOW-passing result auto-resolves an existing
open alert (the underlying data changed — e.g. a later confirmation
fixed the offending line — so the quarantine record should reflect that
without waiting for a human to notice and close it by hand, the same
self-healing `app.jobs.reconciliation.is_quarantined` does NOT currently
do for its own alert type, a real, narrower gap outside TASK 0.1's scope
to fix here).

WHERE THIS IS CALLED FROM. `app.api.routes.valuation.get_valuation` —
the single-company detail route a human actually looks at — calls this
once per request, after building the summary. `app.domain.portfolio_
valuation_view` and `app.domain.opportunity_ranking_view` deliberately do
NOT also call it: both already read `summary.price_ladder is None`/
`summary.sanity.blocked` directly to withhold an exit price or a ranking
(the real safety behaviour §1 requires), and calling this from every
row of a multi-ticker screen would multiply writes for the same
information the single-company route already records. The quarantine
record that surfaces on the Data Health screen (TASK 1.2) is therefore
populated by real usage of the company file, not a background sweep —
a real, disclosed scope boundary, not an oversight.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.sanity import SanityCheckResult
from app.models.data_quality import DataAlert

ALERT_TYPE = "valuation_sanity_block"


def record_sanity_result(db: Session, ticker: str, result: SanityCheckResult) -> DataAlert | None:
    """Returns the `DataAlert` row now representing this ticker's sanity
    state (newly created, already-open, or the one just auto-resolved),
    or `None` when the result passed clean and no alert existed to
    resolve. Commits — same convention as `app.jobs.reconciliation.
    reconcile_ticker`, the pattern this mirrors."""
    existing = db.scalar(
        select(DataAlert)
        .where(
            DataAlert.ticker == ticker,
            DataAlert.alert_type == ALERT_TYPE,
            DataAlert.resolved.is_(False),
        )
        .order_by(DataAlert.raised_at.desc())
        .limit(1)
    )

    if not result.blocked:
        if existing is not None:
            existing.resolved = True
            existing.resolved_at = dt.datetime.now(dt.timezone.utc)
            existing.resolved_by = "system:sanity_recheck_passed"
            db.commit()
            return existing
        return None

    if existing is not None:
        return existing  # already open — don't spam a new row for the same ongoing failure

    alert = DataAlert(
        ticker=ticker,
        alert_type=ALERT_TYPE,
        detail=(
            f"Fair value withheld — failed: {', '.join(result.blocked_by)}. "
            + " ".join(result.block_reasons)
        ),
        mismatch_pct=None,
        raised_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(alert)
    db.commit()
    return alert
