"""
R1 Phase 3 — export and backup. See `app.domain.export`'s own docstring
for the disaster-recovery reasoning behind `/export/backup`.

`/export/workbook` is the analyst-facing sibling (T3.1): one real .xlsx
with a sheet per domain, meant for opening in Excel, not for restoring
the system. Both are plain synchronous downloads rather than routed
through the SSE Run Capture job system (`app.jobs.runner`) — a real,
disclosed scope decision, not an oversight: that system exists for
long-running scans paced against cse.lk's own courtesy-access limits
(minutes, sometimes ~10), where a human genuinely benefits from live
progress. An export reads only this system's OWN already-stored data —
no external pacing, no multi-minute wait — and start-to-finish is
seconds at this project's real data volume (a few hundred securities,
~100k fundamentals rows). Wiring a job/SSE/progress-bar path around a
sub-10-second synchronous response would be the "confident, precise, but
pointless" complexity this project avoids everywhere else.
"""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.export import build_backup_zip
from app.domain.fundamentals_view import bulk_raw_latest_line_items, compute_all_correctly_scoped, ttm_adjusted_copy
from app.domain.opportunity_ranking_view import opportunity_ranking_for
from app.domain.ratios import DEFINITIONS
from app.models.corporate_actions import CorporateAction
from app.models.fundamentals import Fundamental
from app.models.macro import MacroSeries
from app.models.portfolio import PortfolioPosition, PortfolioSnapshot
from app.models.prices import PriceDaily
from app.models.securities import Security

router = APIRouter(prefix="/export", tags=["export"])

_ALL_RATIO_LINE_ITEMS = tuple(sorted({field for d in DEFINITIONS for field in d.required}))


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _write_sheet(writer: "pd.ExcelWriter", name: str, df: pd.DataFrame) -> None:
    """Frozen header row, sensible column widths, no merged cells — T3.1's
    own formatting requirements. `name` is truncated to Excel's real
    31-character sheet-name limit rather than raising."""
    sheet_name = name[:31]
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    ws = writer.sheets[sheet_name]
    ws.freeze_panes = "A2"
    for i, col in enumerate(df.columns):
        content_width = int(df[col].astype(str).fillna("").str.len().max()) if len(df) else 10
        width = max(10, min(40, max(content_width, len(str(col))) + 2))
        ws.column_dimensions[get_column_letter(i + 1)].width = width


def _companies_sheet(db: Session) -> pd.DataFrame:
    rows = db.execute(select(Security)).scalars().all()
    return _df([
        {
            "ticker": s.ticker, "name": s.name, "cse_sector": s.cse_sector, "gics_sector": s.gics_sector,
            "archetype": s.archetype, "isin": s.isin, "instrument_type": s.instrument_type,
            "issuer_code": s.issuer_code, "listing_date": s.listing_date, "delisting_date": s.delisting_date,
        }
        for s in rows
    ])


def _prices_sheet(db: Session) -> pd.DataFrame:
    rows = db.execute(select(PriceDaily).order_by(PriceDaily.ticker, PriceDaily.date)).scalars().all()
    return _df([
        {
            "ticker": p.ticker, "date": p.date, "open": p.open, "high": p.high, "low": p.low,
            "close": p.close, "volume": p.volume, "turnover": p.turnover, "adj_factor": p.adj_factor,
        }
        for p in rows
    ])


def _financials_sheet(db: Session, period_type: str) -> pd.DataFrame:
    rows = db.execute(
        select(Fundamental).where(Fundamental.period_type == period_type)
        .order_by(Fundamental.ticker, Fundamental.period_end, Fundamental.statement_line)
    ).scalars().all()
    return _df([
        {
            "ticker": f.ticker, "period_end": f.period_end, "statement_line": f.statement_line,
            "value": f.value, "currency": f.currency, "provenance_tier": f.provenance_tier.value,
            "confirmed": f.confirmed_by is not None, "source_url": f.source_url,
        }
        for f in rows
    ])


def _corporate_actions_sheet(db: Session) -> pd.DataFrame:
    rows = db.execute(select(CorporateAction).order_by(CorporateAction.ticker, CorporateAction.ex_date)).scalars().all()
    return _df([
        {
            "ticker": a.ticker, "ex_date": a.ex_date, "type": a.type.value, "ratio": a.ratio,
            "cash_amount": a.cash_amount, "confirmed": a.is_confirmed, "source_url": a.source_url,
        }
        for a in rows
    ])


def _ratios_sheet(db: Session, as_of: dt.date) -> pd.DataFrame:
    """One row per (ticker, ratio) — reuses the exact bulk, two-view
    (raw + TTM) computation `app.domain.sector_percentiles_view.
    all_sector_percentiles` already established, so this sheet can never
    silently disagree with what the company file itself shows."""
    raw_by_ticker = bulk_raw_latest_line_items(db, as_of, _ALL_RATIO_LINE_ITEMS)
    out: list[dict] = []
    for ticker, (period_end, raw_items, period_type_by_line) in raw_by_ticker.items():
        ttm_items = ttm_adjusted_copy(db, ticker, as_of, period_end, raw_items, period_type_by_line)
        for r in compute_all_correctly_scoped(raw_items, ttm_items):
            if r.value is None:
                continue
            out.append({
                "ticker": ticker, "period_end": period_end, "ratio": r.key,
                "value": r.value, "provenance": r.provenance.value if r.provenance else None,
            })
    return _df(out)


def _valuations_sheet(db: Session, as_of: dt.date) -> pd.DataFrame:
    """Reuses `opportunity_ranking_for` directly — the same full-universe
    valuation pass the Opportunities screen itself runs — rather than a
    second, independently-maintained loop that could silently disagree."""
    view = opportunity_ranking_for(db, as_of)
    out: list[dict] = []
    for c in list(view.ranked) + list(view.excluded):
        out.append({
            "ticker": c.ticker, "name": c.name, "archetype": c.archetype,
            "current_price": c.current_price, "blended_fair_value_per_share": c.blended_fair_value_per_share,
            "margin_of_safety_pct": c.margin_of_safety_pct, "price_ladder_zone": c.price_ladder_zone,
            "buy_below_price": c.buy_below_price, "gap_to_buy_below_pct": c.gap_to_buy_below_pct,
            "dispersion_pct": c.dispersion_pct, "as_of": view.as_of,
            "warnings": "; ".join(c.warnings),
        })
    return _df(out)


def _macro_sheet(db: Session) -> pd.DataFrame:
    rows = db.execute(select(MacroSeries).order_by(MacroSeries.series_id, MacroSeries.obs_date)).scalars().all()
    return _df([
        {"series_id": m.series_id, "obs_date": m.obs_date, "value": m.value, "source": m.source}
        for m in rows
    ])


def _portfolio_sheet(db: Session) -> pd.DataFrame:
    latest = db.scalar(select(PortfolioSnapshot).order_by(PortfolioSnapshot.uploaded_at.desc()))
    if latest is None:
        return _df([])
    positions = db.scalars(
        select(PortfolioPosition).where(PortfolioPosition.snapshot_id == latest.id)
    ).all()
    return _df([
        {
            "snapshot_uploaded_at": latest.uploaded_at, "ticker": p.ticker, "quantity": p.quantity,
            "avg_price": p.avg_price, "total_cost": p.total_cost, "traded_price": p.traded_price,
            "market_value": p.market_value,
        }
        for p in positions
    ])


@router.get("/workbook")
def export_workbook(db: Session = Depends(get_db)) -> Response:
    as_of = dt.date.today()
    generated_at = dt.datetime.now(dt.timezone.utc)

    sheets: dict[str, pd.DataFrame] = {
        "Companies": _companies_sheet(db),
        "Prices": _prices_sheet(db),
        "Financials_Annual": _financials_sheet(db, "annual"),
        "Financials_Interim": _financials_sheet(db, "quarterly"),
        "CorporateActions": _corporate_actions_sheet(db),
        "Ratios": _ratios_sheet(db, as_of),
        "Valuations": _valuations_sheet(db, as_of),
        "Macro": _macro_sheet(db),
        "Portfolio": _portfolio_sheet(db),
    }

    readme_rows = [
        {"field": "generated_at", "value": generated_at.isoformat()},
        {"field": "schema_version", "value": "1"},
        {"field": "provenance_legend", "value": "R=Reported, D=Derived, N=Normalised, E=Estimated, F=Forecast, A=AI-assisted (cannot enter a valuation until confirmed), -=Unavailable"},
    ] + [{"field": f"{name}_row_count", "value": str(len(df))} for name, df in sheets.items()]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        _write_sheet(writer, "README", _df(readme_rows))
        for name, df in sheets.items():
            _write_sheet(writer, name, df)

    filename = f"cse-alpha-workbook-{as_of.isoformat()}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/backup")
def export_backup(db: Session = Depends(get_db)) -> Response:
    content, _manifest = build_backup_zip(db)
    filename = f"cse-alpha-backup-{dt.date.today().isoformat()}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
