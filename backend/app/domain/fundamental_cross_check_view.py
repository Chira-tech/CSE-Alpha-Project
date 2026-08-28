"""DB-wired driver for `app.domain.fundamental_cross_check`.

Assembles a `FilingFacts` for every (ticker, period_end, period_type)
that still has an `AI_ASSISTED` row, runs `evaluate_filing`, and yields
the verdicts. The optional re-extraction pass (S2 — mandatory for
auto-confirm) re-downloads each source PDF once and re-runs today's
parser, paced and checkpointed exactly like `scripts/reverify_magnitude_
flagged_fundamentals.py`.

Batching discipline matches `app.api.routes.fundamentals._corroborated_
ids` / `app.domain.fundamentals_view.bulk_latest_line_items`: one load of
every relevant row, then in-Python assembly — never N queries per filing.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.fundamental_cross_check import FilingFacts, RowVerdict, evaluate_filing
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental

#: The exact stamp `app.domain.financial_statement_parsing` /
#: `app.ingestion.financial_pdf_extractor` write onto every draft from a
#: filing whose extracted values fail an accounting identity. Kept as the
#: single literal phrase rather than a looser set — "do not confirm any
#: figure" is only ever a substring of this same stamp, and matching it
#: separately would also catch the OI-4 remediation notes.
_FAILURE_MARKER = "EXTRACTION FAILED ARITHMETIC CHECK"
_FISCAL_YEAR_DAYS = 370  # a little slack past 365 for 52/53-week years


@dataclass(frozen=True)
class FilingGroup:
    ticker: str
    period_end: dt.date
    period_type: str
    ai_rows: tuple[Fundamental, ...]  # the AI_ASSISTED rows on this filing
    source_urls: tuple[str, ...]


def _dual_listing_ticker(ticker: str) -> str | None:
    if ticker.endswith(".N0000"):
        return ticker[: -len(".N0000")] + ".X0000"
    if ticker.endswith(".X0000"):
        return ticker[: -len(".X0000")] + ".N0000"
    return None


def load_rows_by_ticker(db: Session, tickers: set[str] | None = None) -> dict[str, list[Fundamental]]:
    """Every fundamentals row (all tiers) for the given tickers — or the
    whole table when `tickers` is None. One query; grouped in Python."""
    stmt = select(Fundamental)
    if tickers is not None:
        stmt = stmt.where(Fundamental.ticker.in_(tickers))
    by_ticker: dict[str, list[Fundamental]] = defaultdict(list)
    for row in db.scalars(stmt):
        by_ticker[row.ticker].append(row)
    return by_ticker


def _best_values(rows: list[Fundamental]) -> dict[str, Decimal]:
    """One value per canonical line for a set of rows sharing a period —
    the lowest `version` (the original extraction / the row a draft would
    keep), tier-agnostic."""
    best: dict[str, tuple[int, Decimal]] = {}
    for r in rows:
        cur = best.get(r.statement_line)
        if cur is None or r.version < cur[0]:
            best[r.statement_line] = (r.version, Decimal(r.value))
    return {line: v for line, (_ver, v) in best.items()}


def ai_assisted_filing_groups(
    by_ticker: dict[str, list[Fundamental]], only_ticker: str | None = None
) -> list[FilingGroup]:
    groups: list[FilingGroup] = []
    for ticker, rows in by_ticker.items():
        if only_ticker is not None and ticker != only_ticker:
            continue
        by_period: dict[tuple[dt.date, str], list[Fundamental]] = defaultdict(list)
        for r in rows:
            by_period[(r.period_end, r.period_type)].append(r)
        for (period_end, period_type), period_rows in by_period.items():
            ai_rows = [r for r in period_rows if r.provenance_tier == ProvenanceTier.AI_ASSISTED]
            if not ai_rows:
                continue
            groups.append(
                FilingGroup(
                    ticker=ticker,
                    period_end=period_end,
                    period_type=period_type,
                    ai_rows=tuple(ai_rows),
                    source_urls=tuple(sorted({r.source_url for r in ai_rows})),
                )
            )
    groups.sort(key=lambda g: (g.ticker, g.period_end, g.period_type))
    return groups


def gather_filing_facts(
    group: FilingGroup,
    by_ticker: dict[str, list[Fundamental]],
    reextracted_values: dict[str, Decimal] | None,
    reextracted_quality_ok: bool | None = None,
) -> FilingFacts:
    ticker_rows = by_ticker.get(group.ticker, [])
    period_rows = [
        r
        for r in ticker_rows
        if r.period_end == group.period_end and r.period_type == group.period_type
    ]
    values = _best_values(period_rows)

    # S3 — same (ticker, period_end), a DIFFERENT source_url, any tier/type
    this_urls = {r.source_url for r in period_rows}
    cross_source: dict[str, list[Decimal]] = defaultdict(list)
    for r in ticker_rows:
        if r.period_end == group.period_end and r.source_url not in this_urls:
            cross_source[r.statement_line].append(Decimal(r.value))

    # S6 — dual-listing counterpart, same (period_end, period_type)
    dual: dict[str, Decimal] = {}
    counterpart = _dual_listing_ticker(group.ticker)
    if counterpart is not None:
        dual_rows = [
            r
            for r in by_ticker.get(counterpart, [])
            if r.period_end == group.period_end and r.period_type == group.period_type
        ]
        dual = _best_values(dual_rows)

    # S5 — quarterly siblings for an annual filing's fiscal year
    quarterly_values: dict[str, list[Decimal]] = {}
    quarterly_period_count = 0
    if group.period_type == "annual":
        window_start = group.period_end - dt.timedelta(days=_FISCAL_YEAR_DAYS)
        q_by_period: dict[dt.date, list[Fundamental]] = defaultdict(list)
        for r in ticker_rows:
            if r.period_type == "quarterly" and window_start < r.period_end <= group.period_end:
                q_by_period[r.period_end].append(r)
        q_periods = sorted(q_by_period)[-4:]
        quarterly_period_count = len(q_periods)
        per_line: dict[str, list[Decimal]] = defaultdict(list)
        for qp in q_periods:
            for line, val in _best_values(q_by_period[qp]).items():
                per_line[line].append(val)
        quarterly_values = dict(per_line)

    # V3 — the immediately-prior period of the same ticker
    prior_end = max(
        (r.period_end for r in ticker_rows if r.period_end < group.period_end),
        default=None,
    )
    prior_values: dict[str, Decimal] = {}
    if prior_end is not None:
        prior_values = _best_values([r for r in ticker_rows if r.period_end == prior_end])

    # V4 — an extraction-failure marker anywhere on this filing
    has_marker = any(_FAILURE_MARKER in (r.source_snippet or "") for r in period_rows)

    return FilingFacts(
        ticker=group.ticker,
        period_end=group.period_end.isoformat(),
        period_type=group.period_type,
        values=values,
        cross_source_values=dict(cross_source),
        dual_listing_values=dual,
        quarterly_values=quarterly_values,
        quarterly_period_count=quarterly_period_count,
        prior_period_values=prior_values,
        reextracted_values=reextracted_values,
        has_filing_failure_marker=has_marker,
        reextracted_quality_ok=reextracted_quality_ok,
    )


def _reextract_filing(
    group: FilingGroup, *, user_agent: str
) -> tuple[dict[str, Decimal] | None, bool | None]:
    """Re-download every source PDF backing this filing's AI rows and
    re-run today's parser. Returns `({line: value}, quality_ok)` — or
    `(None, None)` if every download/parse failed (S2 then can't be
    earned). `quality_ok` is whether the fresh values pass
    `check_extraction_quality` (identities + magnitude floor); it lets a
    STALE stored failure marker be disregarded."""
    from app.domain.financial_statement_parsing import (
        _IDENTITY_ROUNDING_TOLERANCE,
        _identity_diffs,
        _magnitude_implausible_keys,
    )
    from app.ingestion.financial_pdf_extractor import (
        build_fundamental_drafts,
        download_pdf,
        extract_financial_statement_candidates,
    )

    first_available = min((r.first_available_date for r in group.ai_rows), default=group.period_end)
    fresh: dict[str, Decimal] = {}
    any_ok = False
    for url in group.source_urls:
        try:
            pdf_bytes = download_pdf(url, user_agent=user_agent)
            candidates = extract_financial_statement_candidates(pdf_bytes)
            drafts = build_fundamental_drafts(
                ticker=group.ticker,
                period_end=group.period_end,
                period_type=group.period_type,
                first_available_date=first_available,
                source_url=url,
                candidates=candidates,
            )
        except Exception:  # noqa: BLE001 — a bad filing must not abort the sweep
            continue
        any_ok = True
        for d in drafts:
            fresh.setdefault(d.statement_line, Decimal(d.value))
    if not any_ok:
        return None, None
    quality_ok = not _magnitude_implausible_keys(fresh) and all(
        diff <= _IDENTITY_ROUNDING_TOLERANCE for diff in _identity_diffs(fresh).values()
    )
    return fresh, quality_ok


def cross_check_all(
    db: Session,
    *,
    reextract: bool,
    user_agent: str,
    checkpoint_path: Path | None = None,
    pacing_seconds: float = 2.0,
    min_signals: int = 2,
    only_ticker: str | None = None,
    progress: "callable | None" = None,
) -> Iterator[RowVerdict]:
    """Yield a `RowVerdict` for every AI_ASSISTED row, filing by filing.

    When `reextract` is on, each filing's PDFs are re-fetched once
    (paced) and the result cached to `checkpoint_path` (`.jsonl`) so an
    interrupted run resumes without re-downloading — the exact pattern
    `scripts/reverify_magnitude_flagged_fundamentals.py` established.
    """
    tickers_with_ai = {
        t
        for (t,) in db.execute(
            select(Fundamental.ticker)
            .where(Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED)
            .distinct()
        )
    }
    load_tickers = set(tickers_with_ai)
    for t in list(tickers_with_ai):
        dual = _dual_listing_ticker(t)
        if dual is not None:
            load_tickers.add(dual)
    by_ticker = load_rows_by_ticker(db, load_tickers or None)
    groups = ai_assisted_filing_groups(by_ticker, only_ticker=only_ticker)

    # cache_key -> (fresh values or None, quality_ok or None)
    reextract_cache: dict[str, tuple[dict[str, Decimal] | None, bool | None]] = {}
    checkpoint_f = None
    if reextract and checkpoint_path is not None:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        if checkpoint_path.exists():
            for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                fresh = (
                    {k: Decimal(v) for k, v in rec["_fresh"].items()}
                    if rec["_fresh"] is not None
                    else None
                )
                reextract_cache[rec["_key"]] = (fresh, rec.get("_quality_ok"))
        checkpoint_f = checkpoint_path.open("a", encoding="utf-8")

    try:
        did_network = 0
        for i, group in enumerate(groups):
            if progress is not None:
                progress(i + 1, len(groups), group)
            key = f"{group.ticker}|{group.period_end.isoformat()}|{group.period_type}"
            fresh_values: dict[str, Decimal] | None = None
            quality_ok: bool | None = None
            if reextract:
                if key in reextract_cache:
                    fresh_values, quality_ok = reextract_cache[key]
                else:
                    if did_network > 0:
                        time.sleep(pacing_seconds)
                    fresh_values, quality_ok = _reextract_filing(group, user_agent=user_agent)
                    did_network += 1
                    if checkpoint_f is not None:
                        checkpoint_f.write(
                            json.dumps(
                                {
                                    "_key": key,
                                    "_fresh": (
                                        {k: str(v) for k, v in fresh_values.items()}
                                        if fresh_values is not None
                                        else None
                                    ),
                                    "_quality_ok": quality_ok,
                                }
                            )
                            + "\n"
                        )
                        checkpoint_f.flush()

            facts = gather_filing_facts(group, by_ticker, fresh_values, quality_ok)
            ai_lines = {r.statement_line for r in group.ai_rows}
            for verdict in evaluate_filing(facts, min_signals=min_signals):
                if verdict.statement_line in ai_lines:
                    yield verdict
    finally:
        if checkpoint_f is not None:
            checkpoint_f.close()
