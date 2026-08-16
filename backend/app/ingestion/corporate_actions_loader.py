"""
Corporate-actions ingestion, Master Spec §5 ("Scrape + mandatory human
confirm queue — this is the highest-consequence data in the system").

Pipeline: getAnnouncementByCompany(symbol) -> classify each row's category
-> for matches, fetch detail via getAnnouncementById, falling back to
getGeneralAnnouncementById on an empty response (both are real, verified
behaviours — see cse_client.py and README_ENDPOINTS.md) -> build a DRAFT
CorporateAction row (confirmed_by=None, confirmed_at=None, always) ->
upsert, skipping rows that already exist for the same (ticker, ex_date,
type) so re-running ingestion doesn't spam duplicate drafts.

No row this module writes is ever confirmed. That happens in a human
workflow this phase doesn't build yet (ROADMAP.md) — this module's job
ends at "here is a plausible draft, with the source text preserved."
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.announcement_parsing import classify_announcement_category, parse_share_ratio_text
from app.ingestion.cse_client import CseClient, ShapeChangedError
from app.ingestion.schemas import (
    AnnouncementDetail,
    AnnouncementDetailResponse,
    CompanyAnnouncementResponse,
    CompanyAnnouncementRow,
)
from app.models.corporate_actions import CorporateAction
from app.models.corporate_actions import CorporateActionType as DbActionType

logger = logging.getLogger("cse_alpha.ingestion.corporate_actions_loader")

_SRI_LANKA_TZ = ZoneInfo("Asia/Colombo")

_TYPE_STRING_TO_DB_ENUM = {
    "dividend_cash": DbActionType.DIVIDEND_CASH,
    "bonus_issue": DbActionType.BONUS_ISSUE,
    "rights_issue": DbActionType.RIGHTS_ISSUE,
    "stock_split": DbActionType.STOCK_SPLIT,
    "consolidation": DbActionType.CONSOLIDATION,
    "suspension": DbActionType.SUSPENSION,
}


def _epoch_ms_to_date(ms: int | None) -> dt.date | None:
    if ms is None:
        return None
    return dt.datetime.fromtimestamp(ms / 1000, tz=_SRI_LANKA_TZ).date()


def _parse_dmy(text: str | int | None) -> dt.date | None:
    """CSE renders some dates as epoch millis (int) and others as "24 Jul
    2026" strings (str), inconsistently, even within the same detail
    payload family — see AnnouncementDetail's docstring. Handle both."""
    if text is None:
        return None
    if isinstance(text, int):
        return _epoch_ms_to_date(text)
    try:
        return dt.datetime.strptime(text.strip(), "%d %b %Y").date()
    except ValueError:
        logger.warning("could not parse date string %r", text)
        return None


def fetch_company_announcements(client: CseClient, symbol: str) -> list[CompanyAnnouncementRow]:
    response = client.post_form(
        "getAnnouncementByCompany", model=CompanyAnnouncementResponse, data={"symbol": symbol}
    )
    assert isinstance(response, CompanyAnnouncementResponse)  # narrows for type checkers
    return response.reqCompanyAnnouncement


def fetch_announcement_detail(client: CseClient, announcement_id: int) -> AnnouncementDetail | None:
    """Tries getAnnouncementById first (covers dType-discriminated
    records: dividends, initial rights disclosures); falls back to
    getGeneralAnnouncementById (covers "(DATES)" follow-ups, AGM/EGM
    notices) when the first returns empty — both are real, observed
    behaviours, not a guess."""
    primary = client.post_form(
        "getAnnouncementById",
        model=AnnouncementDetailResponse,
        data={"announcementId": announcement_id},
        allow_empty=True,
    )
    if primary is not None:
        assert isinstance(primary, AnnouncementDetailResponse)
        if primary.reqBaseAnnouncement is not None:
            return primary.reqBaseAnnouncement

    fallback = client.post_form(
        "getGeneralAnnouncementById",
        model=AnnouncementDetailResponse,
        data={"announcementId": announcement_id},
        allow_empty=True,
    )
    if fallback is not None:
        assert isinstance(fallback, AnnouncementDetailResponse)
        return fallback.reqBaseAnnouncement
    return None


@dataclass(frozen=True)
class DraftCorporateAction:
    """What this module can determine before any human involvement. `notes`
    always carries enough of the source text that a human confirming the
    row doesn't have to re-fetch the announcement to sanity-check it."""

    ticker: str
    ex_date: dt.date
    type: DbActionType
    ratio: Decimal | None
    cash_amount: Decimal | None
    subscription_price: Decimal | None
    cum_rights_price: Decimal | None
    source_announcement_id: int
    notes: str


def build_draft(ticker: str, action_type: str, detail: AnnouncementDetail) -> DraftCorporateAction | None:
    """Returns None (rather than a low-confidence guess) whenever an
    ex_date can't be pinned down — Master Spec §7 requires the ex_date to
    drive the adjustment-factor build, so a corporate action without one
    is not yet actionable and shouldn't become a draft at all.
    """
    db_type = _TYPE_STRING_TO_DB_ENUM[action_type]
    source_text = detail.remarks or detail.title or detail.votingShrsPropToBeIssued or detail.votingProportion or ""

    if action_type == "dividend_cash":
        ex_date = _parse_dmy(detail.xd)
        if ex_date is None:
            return None
        cash_amount = detail.votingDivPerShare or detail.nonVotingDivPerShare
        cash_decimal = Decimal(str(cash_amount)) if cash_amount else None
        return DraftCorporateAction(
            ticker=ticker,
            ex_date=ex_date,
            type=db_type,
            ratio=None,
            cash_amount=cash_decimal,
            subscription_price=None,
            cum_rights_price=None,
            source_announcement_id=detail.id or 0,
            notes=(
                f"Cash dividend, source: {source_text!r}. "
                + ("" if cash_decimal else "Per-share amount not machine-readable from the API response "
                                            "(observed null on preference-share dividends) — confirm from the "
                                            "linked announcement PDF before approving.")
            ),
        )

    if action_type == "rights_issue":
        ex_date = _parse_dmy(detail.xr) or _parse_dmy(detail.xd)
        if ex_date is None:
            return None
        parsed = parse_share_ratio_text(detail.votingProportion or detail.votingShrsPropToBeIssued)
        ratio = (parsed[0] / parsed[1]) if parsed else None
        subscription_price = (
            Decimal(str(detail.votingShareConsideration)) if detail.votingShareConsideration else None
        )
        missing = []
        if ratio is None:
            missing.append("ratio (couldn't parse proportion text)")
        if subscription_price is None:
            missing.append("subscription price (only present on the initial disclosure, not the dates record)")
        return DraftCorporateAction(
            ticker=ticker,
            ex_date=ex_date,
            type=db_type,
            ratio=ratio,
            cash_amount=None,
            subscription_price=subscription_price,
            cum_rights_price=None,  # always resolved from our own price series, never from the announcement
            source_announcement_id=detail.id or 0,
            notes=(
                f"Rights issue, source: {source_text!r}."
                + (f" MISSING before this can be confirmed: {', '.join(missing)}." if missing else "")
            ),
        )

    # bonus_issue / stock_split / consolidation: no verified live example
    # was captured this session (see README_ENDPOINTS.md). Best-effort
    # generic handling only — always produces a draft that needs full
    # manual review, never assumed correct.
    if action_type in ("bonus_issue", "stock_split", "consolidation"):
        ex_date = _parse_dmy(detail.xr) or _parse_dmy(detail.xd) or _parse_dmy(detail.tradingCommencement)
        if ex_date is None:
            return None
        parsed = parse_share_ratio_text(detail.votingProportion or detail.votingShrsPropToBeIssued)
        ratio = (parsed[0] / parsed[1]) if parsed else None
        return DraftCorporateAction(
            ticker=ticker,
            ex_date=ex_date,
            type=db_type,
            ratio=ratio,
            cash_amount=None,
            subscription_price=None,
            cum_rights_price=None,
            source_announcement_id=detail.id or 0,
            notes=(
                f"UNVERIFIED MAPPING ({action_type}) — this category's detail shape was not confirmed "
                f"against a live example during Phase 1 build. Source: {source_text!r}. "
                "Review the linked PDF in full before confirming."
            ),
        )

    if action_type == "suspension":
        ex_date = _parse_dmy(detail.dateOfAnnouncement)
        if ex_date is None:
            return None
        return DraftCorporateAction(
            ticker=ticker,
            ex_date=ex_date,
            type=db_type,
            ratio=None,
            cash_amount=None,
            subscription_price=None,
            cum_rights_price=None,
            source_announcement_id=detail.id or 0,
            notes=f"Trading suspension notice. Source: {source_text!r}.",
        )

    raise AssertionError(f"unhandled action_type: {action_type!r}")  # pragma: no cover


def _already_drafted(db: Session, draft: DraftCorporateAction) -> bool:
    existing = db.scalar(
        select(CorporateAction).where(
            CorporateAction.ticker == draft.ticker,
            CorporateAction.ex_date == draft.ex_date,
            CorporateAction.type == draft.type,
        )
    )
    return existing is not None


def ingest_corporate_actions_for_ticker(client: CseClient, db: Session, ticker: str) -> int:
    """Returns the number of new draft rows inserted. Never touches an
    existing row — confirmed or not — so a human's in-progress review is
    never clobbered by a re-run."""
    rows = fetch_company_announcements(client, ticker)
    inserted = 0

    for row in rows:
        action_type = classify_announcement_category(row.announcementCategory)
        if action_type is None:
            continue

        try:
            detail = fetch_announcement_detail(client, row.announcementId)
        except ShapeChangedError:
            logger.warning(
                "shape change fetching detail for %s announcementId=%s, skipping", ticker, row.announcementId
            )
            continue

        if detail is None:
            logger.info(
                "no detail available for %s announcementId=%s (category=%r) via either detail endpoint",
                ticker,
                row.announcementId,
                row.announcementCategory,
            )
            continue

        draft = build_draft(ticker, action_type, detail)
        if draft is None:
            continue

        if _already_drafted(db, draft):
            continue

        db.add(
            CorporateAction(
                ticker=draft.ticker,
                ex_date=draft.ex_date,
                type=draft.type,
                ratio=draft.ratio,
                cash_amount=draft.cash_amount,
                subscription_price=draft.subscription_price,
                cum_rights_price=draft.cum_rights_price,
                source_url=f"https://www.cse.lk/api/getAnnouncementById?announcementId={draft.source_announcement_id}",
                notes=draft.notes,
                confirmed_by=None,
                confirmed_at=None,
            )
        )
        inserted += 1

    if inserted:
        db.commit()
    return inserted
