"""
Phase 1 of `docs/CSE_Universe_Integrity_Rollout.md` — the report-only
triage sweep the spec calls "the actual deliverable of the rollout":
run every universe-integrity detector across the whole listed universe,
change nothing, and produce the bucket table that says whether this is a
20-name problem or a 200-name problem.

Reusable and re-runnable, exactly like `scripts.audit_data_integrity`:

    python -m scripts.audit_universe_integrity            # from backend/

writes `docs/audits/UNIVERSE_INTEGRITY_TRIAGE.md` and prints the summary.
Every number comes from a query in this file — nothing is hand-typed, so
re-running after data changes reproduces the report. NO WRITES: this
raises no `DataAlert` and quarantines nothing. Enforcement is a separate
step (`app.jobs.runner._run_universe_integrity_checks`), running the same
detectors from `app.domain.universe_integrity`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.domain import universe_integrity as ui  # noqa: E402
from app.domain.instrument_type import issuer_code  # noqa: E402
from app.models.corporate_actions import CorporateAction, CorporateActionType  # noqa: E402
from app.models.data_quality import DataAlert  # noqa: E402
from app.models.float_data import FloatData  # noqa: E402
from app.models.prices import PriceDaily  # noqa: E402
from app.models.securities import Security  # noqa: E402

TODAY = dt.date.today()
RIGHTS_OPEN_WINDOW_DAYS = 90
FINANCIAL_ARCHETYPES = {"bank", "non_bank_finance", "insurance"}


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _latest_close(db: Session, ticker: str) -> tuple[Decimal | None, dt.date | None]:
    row = db.scalar(
        select(PriceDaily)
        .where(PriceDaily.ticker == ticker, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )
    return (row.close, row.date) if row is not None else (None, None)


def _published_market_cap(db: Session, ticker: str) -> Decimal | None:
    return db.scalar(
        select(FloatData.published_market_cap)
        .where(FloatData.ticker == ticker, FloatData.published_market_cap.is_not(None))
        .order_by(FloatData.as_of.desc())
        .limit(1)
    )


def _latest_shares(db: Session, ticker: str) -> int | None:
    return db.scalar(
        select(FloatData.shares_issued)
        .where(FloatData.ticker == ticker)
        .order_by(FloatData.as_of.desc())
        .limit(1)
    )


def _recent_rights_action(db: Session, ticker: str) -> CorporateAction | None:
    """A confirmed rights issue whose ex-date is within the open-offer
    window of today — the closest this data supports to "an offer is
    currently open"."""
    return db.scalar(
        select(CorporateAction)
        .where(
            CorporateAction.ticker == ticker,
            CorporateAction.type == CorporateActionType.RIGHTS_ISSUE,
            CorporateAction.ex_date >= TODAY - dt.timedelta(days=RIGHTS_OPEN_WINDOW_DAYS),
        )
        .order_by(CorporateAction.ex_date.desc())
        .limit(1)
    )


def _corporate_action_dates(db: Session, ticker: str) -> set[dt.date]:
    return {
        d
        for (d,) in db.execute(
            select(CorporateAction.ex_date).where(CorporateAction.ticker == ticker)
        ).all()
    }


def _one_day_returns(db: Session, ticker: str) -> list[tuple[dt.date, Decimal]]:
    rows = list(
        db.execute(
            select(PriceDaily.date, PriceDaily.close)
            .where(PriceDaily.ticker == ticker, PriceDaily.close.is_not(None), PriceDaily.close > 0)
            .order_by(PriceDaily.date)
        ).all()
    )
    out: list[tuple[dt.date, Decimal]] = []
    for (d0, c0), (d1, c1) in zip(rows, rows[1:]):
        out.append((d1, (c1 - c0) / c0))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "docs" / "audits" / "UNIVERSE_INTEGRITY_TRIAGE.md"
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        _run(db, args.out)
    finally:
        db.close()


def _run(db: Session, out_path: Path) -> None:
    securities = list(db.scalars(select(Security).order_by(Security.ticker)))
    lines_by_issuer: dict[str, list[Security]] = defaultdict(list)
    for s in securities:
        lines_by_issuer[s.issuer_code or issuer_code(s.ticker)].append(s)

    # bucket -> list of (ticker, detail)
    buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def record(finding: ui.IntegrityFinding | None) -> None:
        if finding is not None:
            buckets[finding.bucket].append((finding.detail.split(":")[0].split()[0], finding.detail))

    for s in securities:
        close, close_date = _latest_close(db, s.ticker)
        days_stale = (TODAY - close_date).days if close_date is not None else None

        record(ui.check_instrument_type_known(s.ticker, s.instrument_type))
        record(ui.check_rights_line_expired(s.ticker, s.instrument_type, close_date, TODAY))
        record(
            ui.check_market_cap_identity(
                s.ticker, close, _latest_shares(db, s.ticker), _published_market_cap(db, s.ticker)
            )
        )
        record(ui.check_price_staleness(s.ticker, days_stale))
        record(
            ui.check_sector_model_routed(
                s.ticker, s.archetype, s.archetype  # archetype IS the routing key today
            )
        )

        rights = _recent_rights_action(db, s.ticker)
        if rights is not None and s.instrument_type in ("ordinary", "non_voting"):
            record(ui.check_rights_price_coherence(s.ticker, close, rights.subscription_price))
            record(
                ui.check_nil_paid_fingerprint(
                    s.ticker, close, rights.subscription_price, rights.terp
                )
            )

        ca_dates = _corporate_action_dates(db, s.ticker)
        for d, ret in _one_day_returns(db, s.ticker):
            f = ui.check_price_discontinuity(s.ticker, ret, d, d in ca_dates)
            if f is not None:
                record(f)
                break  # one example per ticker is enough for a triage count

    # --- Financial-sector lines with no independent beta on file: a cheap,
    # honestly-partial proxy for "CoE may be unavailable". A real per-name
    # CoE availability count needs the valuation pass (Phase 3).
    fin_no_beta = db.scalar(
        select(func.count())
        .select_from(Security)
        .where(
            Security.archetype.in_(FINANCIAL_ARCHETYPES),
            Security.published_beta_asi.is_(None),
            Security.published_beta_sp_sl20.is_(None),
        )
    ) or 0

    open_alerts = db.execute(
        select(DataAlert.alert_type, func.count())
        .where(DataAlert.resolved.is_(False))
        .group_by(DataAlert.alert_type)
        .order_by(func.count().desc())
    ).all()

    issuers_no_primary = [
        code
        for code, lines in lines_by_issuer.items()
        if not any(l.instrument_type in ("ordinary", "non_voting") for l in lines)
    ]

    # --- assemble report
    lines: list[str] = [
        "# Universe Integrity — Phase 1 Triage",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}Z"
        f" · DB: `{settings.database_url}`",
        "",
        "Report-only. Every number below is reproducible by re-running "
        "`python -m scripts.audit_universe_integrity` from `backend/`. Nothing was written; no "
        "ticker was quarantined. This is the measurement the rollout's Phase 2 acts on.",
        "",
        f"- Listed lines scanned: **{len(securities)}**",
        f"- Distinct issuers: **{len(lines_by_issuer)}**",
        f"- Issuers with no ordinary/non-voting line at all: **{len(issuers_no_primary)}**"
        + (f" — {', '.join(sorted(issuers_no_primary))}" if issuers_no_primary else ""),
        "",
        "## Triage buckets",
        "",
    ]

    bucket_order = [
        "Unresolved / unknown line type",
        "Wrong line bound (nil-paid rights fingerprint)",
        "Rights-price incoherent (wrong line suspected)",
        "Market-cap identity fail",
        "Implausible implied multiple",
        "Unexplained price discontinuity",
        "Rights line not reaped",
        "Stale price",
        "Sector model routing gap",
    ]
    table_rows: list[list[str]] = []
    for b in bucket_order:
        hits = buckets.get(b, [])
        example = hits[0][0] if hits else "—"
        table_rows.append([b, str(len(hits)), example])
    table_rows.append(["Cost of equity unavailable (proxy: financial line, no beta)", str(fin_no_beta), "—"])
    lines.append(_md_table(["Bucket", "Lines", "Example"], table_rows))
    lines.append("")

    lines.append("## Detail, per bucket")
    lines.append("")
    for b in bucket_order:
        hits = buckets.get(b, [])
        lines.append(f"### {b} — {len(hits)}")
        lines.append("")
        if not hits:
            lines.append("_None._")
        else:
            for _, detail in hits[:40]:
                lines.append(f"- {detail}")
            if len(hits) > 40:
                lines.append(f"- … and {len(hits) - 40} more")
        lines.append("")

    lines.append("## Currently-open DataAlerts (the enforcing side, already live)")
    lines.append("")
    lines.append(
        _md_table(
            ["alert_type", "open"],
            [[t, str(c)] for t, c in open_alerts] or [["(none)", "0"]],
        )
    )
    lines.append("")
    lines.append(
        "The buckets above that map to a `DataAlert.alert_type` "
        "(`market_cap_mismatch`, `rights_price_incoherent`, `wrong_line_fingerprint`, "
        "`implausible_multiple`, `price_discontinuity`) become blocking quarantine rows once "
        "`app.jobs.scheduler`'s `universe_integrity_checks` job runs; the rest are report-only "
        "signals for a human worklist."
    )
    lines.append("")

    report = "\n".join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Wrote {out_path}", file=sys.stderr)
    print("\n" + "\n".join(report.splitlines()[:24]), file=sys.stderr)


if __name__ == "__main__":
    main()
