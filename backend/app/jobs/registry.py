"""
TASK 1.1: the fixed catalogue of jobs a human can trigger manually, from
the sidebar's "Run Capture" control, instead of only waiting for
`app.jobs.scheduler`'s own cron schedule.

`est_seconds` is a real, disclosed estimate — 286 tickers at the >=2s
pacing this project already enforces everywhere (`CseClient`'s own
`min_seconds_between_calls`) is genuinely ~10 minutes for a full-universe
per-ticker sweep, not a made-up number, and is shown in the UI so a
human knows what they just started before committing to wait for it.

EVERY RUNNER BELOW WRAPS A REAL, ALREADY-EXISTING INGESTION FUNCTION —
this registry adds NO new data-fetching logic of its own. `capture_all`
is the one exception: a real meta-job that runs the others in sequence,
matching TASK 1.1's own spec ("runs sub-jobs sequentially and reports
which one it is on").
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JobDefinition:
    key: str
    label: str
    est_seconds: int
    sub_jobs: tuple[str, ...] = ()
    """Populated only for `capture_all` — the ordered keys it runs
    sequentially. Empty for every real leaf job."""


JOBS: dict[str, JobDefinition] = {
    "capture_prices": JobDefinition("capture_prices", "EOD prices", 45),
    "capture_market": JobDefinition("capture_market", "Market P/E + ASPI", 20),
    "capture_macro": JobDefinition("capture_macro", "CBSL macro series", 30),
    "capture_filings": JobDefinition("capture_filings", "New financial statement filings", 120),
    "capture_corporate_actions": JobDefinition("capture_corporate_actions", "Corporate actions scan", 600),
    "enrich_securities": JobDefinition("enrich_securities", "Security enrichment (shares, market cap)", 600),
    "recompute": JobDefinition("recompute", "Rebuild valuations", 60),
    # The §38 universe pass (~70s, measured) frozen into a
    # `composite_ranking_snapshots` row so `GET /composite-ranking` reads
    # a finished result instead of triggering the pass on a page load.
    # Pure CPU over already-stored confirmed data — no network, so the
    # estimate is real compute time, not API pacing.
    "recompute_composite_ranking": JobDefinition(
        "recompute_composite_ranking", "Rebuild §38 composite scoreboard", 90
    ),
    # Promotes AI-assisted fundamentals the SERVER can independently
    # verify as corroborated (an independently-sourced REPORTED row
    # already carries the exact same value) — the one case the confirm
    # queue already treats as safe without a human looking at each value,
    # now applied on a schedule instead of waiting for a click.
    "auto_confirm_corroborated_fundamentals": JobDefinition(
        "auto_confirm_corroborated_fundamentals", "Auto-confirm corroborated fundamentals", 60
    ),
    # Pure recomputation from already-stored confirmed corporate actions —
    # no network at all, so the estimate is real CPU time, not API pacing.
    "rebuild_adjustment_factors": JobDefinition(
        "rebuild_adjustment_factors", "Rebuild §7 total-return adjustment factors", 30
    ),
    "rebuild_factor_series": JobDefinition(
        "rebuild_factor_series", "Rebuild §35 weekly factor return series", 180
    ),
    # `est_seconds` for refresh_stale_fundamentals below is a rough,
    # disclosed guess, NOT the same kind of real per-call arithmetic every
    # other estimate here is — runtime depends entirely on how many
    # currently-stored filings fail `check_extraction_quality` right now,
    # which shrinks over time as this job (or its Saturday cron twin,
    # `app.jobs.scheduler._job_refresh_stale_fundamentals`) works through
    # the backlog. A large backlog (e.g. right after a breadth-first
    # `backfill-financials` run) can genuinely take much longer than this;
    # see that job's own docstring.
    "refresh_stale_fundamentals": JobDefinition(
        "refresh_stale_fundamentals", "Repair stale fundamentals (re-check math)", 1800
    ),
    # docs/CSE_Universe_Integrity_Rollout.md Phase 2 — the universe-wide
    # detectors with no nightly job yet (rights-price coherence, nil-paid
    # fingerprint, price discontinuity, rights-line reaping). Pure DB +
    # CPU over already-stored prices and confirmed corporate actions, no
    # network — the estimate is real per-ticker scan time.
    "universe_integrity_checks": JobDefinition(
        "universe_integrity_checks", "Universe integrity checks", 90
    ),
    "capture_all": JobDefinition(
        "capture_all", "Full capture", 900,
        sub_jobs=(
            "capture_prices", "capture_market", "capture_macro",
            "capture_filings", "capture_corporate_actions", "enrich_securities",
        ),
    ),
}
"""NOTE on `capture_orderbook` (in the brief's own pseudocode, est 600s):
NOT included here — verified against `app.ingestion.README_ENDPOINTS.md`
and the CSE API surface this project has actually mapped, there is no
order-book/bid-ask-depth endpoint this system ingests anywhere yet (§52's
own job table lists it as a later-phase placeholder in `app.jobs.
scheduler`'s own module docstring). Listing a job here with no real
runner behind it would be exactly the kind of confident-but-fake control
this whole project's own discipline exists to avoid — omitted rather than
stubbed."""


def job_definition(key: str) -> JobDefinition | None:
    return JOBS.get(key)
