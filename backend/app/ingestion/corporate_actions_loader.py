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

Rights issues and share splits are each announced TWICE by CSE: an
"initial disclosure" (which carries the ratio, and for rights the
subscription price, but no dates) and a follow-up "(DATES)" announcement
(which carries the ex-date but usually not the ratio/price). Both are
verified live — see README_ENDPOINTS.md — for Asia Asset Finance PLC
(rights) and Lanka Tiles / First Capital Holdings (splits). This module
pairs the two announcements for the same event and merges them into one
draft; if only one side exists (e.g. the dates announcement hasn't been
published yet), it still drafts what it can and lists what's missing in
`notes`.

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

from app.domain.announcement_parsing import (
    before_after_to_new_per_held,
    classify_announcement_category,
    parse_before_after_ratio_text,
    parse_share_ratio_text,
)
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

# Action types CSE announces as an (initial disclosure, dates follow-up)
# pair rather than a single self-contained record — verified live for
# both. Everything else in _TYPE_STRING_TO_DB_ENUM is a single-record type.
_PAIRED_TYPES = {"rights_issue", "stock_split"}


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


def _to_decimal_loose(value: str | int | float | None) -> Decimal | None:
    """`votingResultingNumOfShares` is returned by the API as a numeric
    STRING ("405000000") rather than a number — verified live, not a
    typo. Handle both without assuming which one arrives."""
    if value is None:
        return None
    return Decimal(str(value))


def _is_dates_variant(category: str | None) -> bool:
    return bool(category) and "DATES" in category.upper()


def fetch_company_announcements(client: CseClient, symbol: str) -> list[CompanyAnnouncementRow]:
    response = client.post_form(
        "getAnnouncementByCompany", model=CompanyAnnouncementResponse, data={"symbol": symbol}
    )
    assert isinstance(response, CompanyAnnouncementResponse)  # narrows for type checkers
    return response.reqCompanyAnnouncement


def fetch_announcement_detail(client: CseClient, announcement_id: int) -> AnnouncementDetail | None:
    """Tries getAnnouncementById first (covers dType-discriminated
    records: dividends, initial rights/split disclosures); falls back to
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


def build_single_record_draft(
    ticker: str, action_type: str, detail: AnnouncementDetail
) -> DraftCorporateAction | None:
    """Handles the action types CSE announces as one self-contained
    record: dividends (verified) and suspensions. Bonus issues have no
    verified live example — see README_ENDPOINTS.md — and are handled
    with the same best-effort generic path as a fallback, clearly flagged.
    """
    db_type = _TYPE_STRING_TO_DB_ENUM[action_type]
    source_text = detail.remarks or detail.title or ""

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

    if action_type in ("bonus_issue", "consolidation"):
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

    raise AssertionError(f"unhandled single-record action_type: {action_type!r}")  # pragma: no cover


def build_rights_issue_draft(
    ticker: str,
    initial: AnnouncementDetail | None,
    dates: AnnouncementDetail | None,
) -> DraftCorporateAction | None:
    """Verified live (Asia Asset Finance PLC, June-July 2026): the initial
    "RightsIssue" disclosure carries `votingShrsPropToBeIssued` (ratio
    prose) and `votingShareConsideration` (subscription price); the
    "(DATES)" follow-up carries `xr` (ex-rights date) and, in this
    example, ALSO repeated the ratio prose in `votingProportion` — so
    ratio can come from either side, but subscription price only from the
    initial disclosure. `cum_rights_price` is deliberately never populated
    here: Master Spec §7's TERP formula requires the market's own closing
    price the day before ex-date, which belongs to the reconciliation/
    adjustment-factor build (app.jobs.reconciliation), not to anything the
    announcement itself states.
    """
    source = initial or dates
    if source is None:
        return None
    source_text = (
        (initial.votingShrsPropToBeIssued if initial else None)
        or (dates.votingProportion if dates else None)
        or (source.remarks or "")
    )

    ex_date = _parse_dmy(dates.xr) if dates else None
    if ex_date is None and initial is not None:
        ex_date = _parse_dmy(initial.xr)
    if ex_date is None:
        return None

    ratio_text = (initial.votingShrsPropToBeIssued if initial else None) or (
        dates.votingProportion if dates else None
    )
    parsed = parse_share_ratio_text(ratio_text)
    ratio = (parsed[0] / parsed[1]) if parsed else None

    subscription_price = (
        Decimal(str(initial.votingShareConsideration))
        if initial is not None and initial.votingShareConsideration
        else None
    )

    missing = []
    if ratio is None:
        missing.append("ratio (couldn't parse proportion text)")
    if subscription_price is None:
        missing.append(
            "subscription price ("
            + ("initial disclosure not found/matched" if initial is None else "field was empty")
            + ")"
        )

    return DraftCorporateAction(
        ticker=ticker,
        ex_date=ex_date,
        type=DbActionType.RIGHTS_ISSUE,
        ratio=ratio,
        cash_amount=None,
        subscription_price=subscription_price,
        cum_rights_price=None,
        source_announcement_id=(dates or initial).id or 0,
        notes=(
            f"Rights issue, source: {source_text!r}."
            + (f" MISSING before this can be confirmed: {', '.join(missing)}." if missing else "")
        ),
    )


def build_stock_split_draft(
    ticker: str,
    initial: AnnouncementDetail | None,
    dates: AnnouncementDetail | None,
) -> DraftCorporateAction | None:
    """Verified live (Lanka Tiles TILE.N0000, First Capital Holdings
    CFVF.N0000): the initial "ShareSplits" disclosure carries the ratio —
    ideally as exact share counts (`votingExistingNumOfShares` /
    `votingResultingNumOfShares`, most reliable), else as before:after
    text ("1 : 4") in `votingProportion` or "X into Y" prose in `remarks`.
    The ex-date is NOT `xr` (that field was null on both live examples) —
    it's `tradingCommencement`, the date the sub-divided shares actually
    begin trading, which lives on the "(DATES)" follow-up.
    """
    source = initial or dates
    if source is None:
        return None
    source_text = (initial.remarks if initial and initial.remarks else None) or (source.remarks or "")

    ex_date = None
    if dates is not None:
        ex_date = _parse_dmy(dates.tradingCommencement) or _parse_dmy(dates.xr) or _parse_dmy(dates.xd)
    if ex_date is None and initial is not None:
        ex_date = _parse_dmy(initial.tradingCommencement)
    if ex_date is None:
        return None

    ratio = None
    ratio_source_note = "not determined"
    if initial is not None:
        existing = initial.votingExistingNumOfShares
        resulting = _to_decimal_loose(initial.votingResultingNumOfShares)
        if existing and resulting and existing > 0:
            ratio = before_after_to_new_per_held(Decimal(existing), resulting)
            ratio_source_note = f"exact share counts ({existing:,} -> {resulting:,.0f})"
        else:
            parsed = parse_before_after_ratio_text(initial.votingProportion) or parse_before_after_ratio_text(
                initial.remarks
            )
            if parsed:
                ratio = before_after_to_new_per_held(*parsed)
                ratio_source_note = f"parsed text ratio {parsed[0]}:{parsed[1]}"

    missing = []
    if ratio is None:
        missing.append("ratio (no share-count fields or parseable proportion text on the initial disclosure)")
        ratio_source_note = "MISSING"
    if initial is None:
        missing.append("initial disclosure not found/matched — ratio cannot be confirmed from the dates record alone")

    return DraftCorporateAction(
        ticker=ticker,
        ex_date=ex_date,
        type=DbActionType.STOCK_SPLIT,
        ratio=ratio,
        cash_amount=None,
        subscription_price=None,
        cum_rights_price=None,
        source_announcement_id=(initial or dates).id or 0,
        notes=(
            f"Share split/sub-division, source: {source_text!r}. Ratio derived from {ratio_source_note}."
            + (f" MISSING before this can be confirmed: {', '.join(missing)}." if missing else "")
        ),
    )


_PAIRED_BUILDERS = {
    "rights_issue": build_rights_issue_draft,
    "stock_split": build_stock_split_draft,
}


def _sort_key(row: CompanyAnnouncementRow) -> tuple[int, int]:
    parsed = _parse_dmy(row.dateOfAnnouncement)
    ordinal = parsed.toordinal() if parsed else 0
    return (ordinal, row.createdDate or 0)


def _pair_rows(rows: list[CompanyAnnouncementRow]) -> list[tuple[CompanyAnnouncementRow | None, CompanyAnnouncementRow | None]]:
    """Splits a same-action-type group of announcement rows into initial
    vs "(DATES)" rows, sorts each chronologically, and pairs them
    index-wise. This is a heuristic (Phase 1, see ROADMAP.md): it assumes
    CSE publishes at most one initial+dates pair per event and that the
    Nth initial disclosure corresponds to the Nth dates follow-up in
    chronological order, which held for every live example captured this
    session but has not been stress-tested against a company with
    multiple overlapping events of the same type.
    """
    initials = sorted((r for r in rows if not _is_dates_variant(r.announcementCategory)), key=_sort_key)
    dates_rows = sorted((r for r in rows if _is_dates_variant(r.announcementCategory)), key=_sort_key)

    pairs: list[tuple[CompanyAnnouncementRow | None, CompanyAnnouncementRow | None]] = []
    for i in range(max(len(initials), len(dates_rows))):
        initial = initials[i] if i < len(initials) else None
        dates = dates_rows[i] if i < len(dates_rows) else None
        pairs.append((initial, dates))
    return pairs


def _already_drafted(db: Session, draft: DraftCorporateAction) -> bool:
    existing = db.scalar(
        select(CorporateAction).where(
            CorporateAction.ticker == draft.ticker,
            CorporateAction.ex_date == draft.ex_date,
            CorporateAction.type == draft.type,
        )
    )
    return existing is not None


def _insert_draft(db: Session, draft: DraftCorporateAction) -> bool:
    """Returns True if a new row was added (False if a row already exists
    for this ticker/ex_date/type and was skipped, confirmed or not)."""
    if _already_drafted(db, draft):
        return False
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
    return True


def ingest_corporate_actions_for_ticker(client: CseClient, db: Session, ticker: str) -> int:
    """Returns the number of new draft rows inserted. Never touches an
    existing row — confirmed or not — so a human's in-progress review is
    never clobbered by a re-run."""
    rows = fetch_company_announcements(client, ticker)

    grouped: dict[str, list[CompanyAnnouncementRow]] = {}
    singles: list[tuple[CompanyAnnouncementRow, str]] = []
    for row in rows:
        action_type = classify_announcement_category(row.announcementCategory)
        if action_type is None:
            continue
        if action_type in _PAIRED_TYPES:
            grouped.setdefault(action_type, []).append(row)
        else:
            singles.append((row, action_type))

    def _fetch(row: CompanyAnnouncementRow) -> AnnouncementDetail | None:
        try:
            return fetch_announcement_detail(client, row.announcementId)
        except ShapeChangedError:
            logger.warning(
                "shape change fetching detail for %s announcementId=%s, skipping", ticker, row.announcementId
            )
            return None

    inserted = 0

    for action_type, group_rows in grouped.items():
        builder = _PAIRED_BUILDERS[action_type]
        for initial_row, dates_row in _pair_rows(group_rows):
            initial_detail = _fetch(initial_row) if initial_row else None
            dates_detail = _fetch(dates_row) if dates_row else None
            draft = builder(ticker, initial_detail, dates_detail)
            if draft is not None and _insert_draft(db, draft):
                inserted += 1

    for row, action_type in singles:
        detail = _fetch(row)
        if detail is None:
            logger.info(
                "no detail available for %s announcementId=%s (category=%r) via either detail endpoint",
                ticker,
                row.announcementId,
                row.announcementCategory,
            )
            continue
        draft = build_single_record_draft(ticker, action_type, detail)
        if draft is not None and _insert_draft(db, draft):
            inserted += 1

    if inserted:
        db.commit()
    return inserted
