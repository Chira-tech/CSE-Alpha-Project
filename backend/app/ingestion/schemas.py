"""
Pydantic response schemas for cse.lk endpoints — VERIFIED against the live
API on 16 Aug 2026 (see README_ENDPOINTS.md for the full probe trace and
raw captured payloads these are built from). All requests are POST; see
app.ingestion.cse_client for the JSON-vs-form-urlencoded split.

`_Lenient` ignores unknown fields (the API is undocumented and may add
fields harmlessly) but still fails loudly if a field we depend on is
missing or of the wrong type — that failure is exactly the "alert on
shape change" behaviour §5 asks for.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --- no-parameter list/status endpoints (POST with body={}) -----------------


class MarketStatus(_Lenient):
    status: str  # observed: "Market Closed" (probed outside trading hours)


class TradeSummaryRow(_Lenient):
    symbol: str
    name: str | None = None
    price: float | None = None
    previousClose: float | None = None
    change: float | None = None
    percentageChange: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    closingPrice: float | None = None
    sharevolume: int | None = None
    tradevolume: int | None = None
    turnover: float | None = None
    marketCap: float | None = None
    lastTradedTime: int | None = None  # epoch millis


class TradeSummaryResponse(_Lenient):
    reqTradeSummery: list[TradeSummaryRow]


class TodaySharePriceRow(_Lenient):
    id: int | None = None
    symbol: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    lastTradedPrice: float | None = None
    change: float | None = None
    changePercentage: float | None = None
    crossingVolume: int | None = None
    tradesTime: int | None = None  # epoch millis
    quantity: int | None = None


class TopMoverRow(_Lenient):
    """Shared shape for topGainers and topLooses."""

    id: int | None = None
    securityId: int | None = None
    symbol: str
    price: float | None = None
    change: float | None = None
    changePercentage: float | None = None
    tradeDate: int | None = None  # epoch millis


class AspiData(_Lenient):
    id: int | None = None
    value: float
    lowValue: float | None = None
    highValue: float | None = None
    change: float | None = None
    percentage: float | None = None
    timestamp: int | None = None  # epoch millis


class DailyMarketSummaryRow(_Lenient):
    """dailyMarketSummery returns a list of single-element lists, i.e.
    [[row], [row], ...] — one row per trading day, most recent first. The
    field set is large (market-wide turnover, CDS holdings, ASPI/S&P SL20
    close, PER/PBV/DY); only the fields this system currently uses are
    typed, everything else is dropped by `_Lenient`."""

    tradeDate: int  # epoch millis
    marketTurnover: float | None = None
    marketCap: float | None = None
    asi: float | None = None  # ASPI close
    spt: float | None = None  # S&P SL20 close (field name as returned)
    per: float | None = None
    pbv: float | None = None
    dy: float | None = None


# --- parameterised endpoints (POST form-urlencoded) --------------------------


class DetailedTradeRow(_Lenient):
    id: int | None = None
    symbol: str
    name: str | None = None
    price: float | None = None
    qty: int | None = None
    trades: int | None = None
    change: float | None = None
    changePercentage: float | None = None


class DetailedTradesResponse(_Lenient):
    reqDetailTrades: list[DetailedTradeRow]


class CompanySymbolInfo(_Lenient):
    id: int | None = None
    symbol: str
    name: str
    issueDate: str | None = None
    quantityIssued: int | None = None
    parValue: float | None = None
    lastTradedPrice: float | None = None


class CompanyInfoSummary(_Lenient):
    reqSymbolInfo: CompanySymbolInfo


# --- announcements (POST form-urlencoded) ------------------------------------


class CompanyAnnouncementRow(_Lenient):
    """One row from getAnnouncementByCompany. `announcementId` (not `id`)
    is the key to pass to getAnnouncementById /
    getGeneralAnnouncementById. Corporate-action-relevant dates
    (`xr`/`xc`/`xd`, `recordDate`, `paymentDate`, `allotment`) were null on
    every list-row observed live — they only appear on the *detail*
    response, keyed by dType. This row is for classification/routing, not
    for reading dates off directly."""

    id: int | None = None
    createdDate: int | None = None  # epoch millis
    dateOfAnnouncement: str | None = None  # e.g. "31 Jul 2026"
    announcementId: int
    announcementCategory: str | None = None
    company: str | None = None
    remarks: str | None = None


class CompanyAnnouncementResponse(_Lenient):
    reqCompanyAnnouncement: list[CompanyAnnouncementRow]


class AnnouncementDetail(_Lenient):
    """`reqBaseAnnouncement` from either getAnnouncementById (has a
    `dType` discriminator, e.g. "CashDividendWithDates", "RightsIssue") or
    getGeneralAnnouncementById (observed WITHOUT a `dType` field — uses
    `title` instead, e.g. "RIGHTS ISSUE (DATES)"). Deliberately a single
    loose model covering the union of fields seen across both endpoints
    and both dType variants, rather than a strict discriminated union —
    the whole point of this ingestion path is to capture whatever is
    present into a draft row for a human to confirm (§5), not to reject
    anything we haven't seen yet.

    Date fields (`xr`, `xd`, `xc`, `recordDate`, `allotment`,
    `tradingCommencement`, `egm`) are epoch-millisecond ints on the
    "*Dates" detail records and plain "DD Mon YYYY" strings (`xd`,
    `payment`) on the dividend-detail record — both are handled as `str |
    int | None` here and normalised downstream in
    app.ingestion.corporate_actions_loader.
    """

    id: int | None = None
    dType: str | None = None
    title: str | None = None
    dateOfAnnouncement: str | None = None
    remarks: str | None = None
    symbol: str | None = None
    companyName: str | None = None

    # cash dividend
    votingDivPerShare: float | None = None
    nonVotingDivPerShare: float | None = None
    xd: str | int | None = None
    payment: str | int | None = None
    recordDate: int | None = None

    # rights issue (initial disclosure)
    numOfVotingShrsIssued: int | None = None
    votingShrsPropToBeIssued: str | None = None
    votingShareConsideration: float | None = None
    curStatCapOfEntity: float | None = None
    xr: int | None = None

    # rights/subdivision "dates" record (via getGeneralAnnouncementById)
    allotment: int | None = None
    tradingCommencement: int | None = None
    votingProportion: str | None = None
    subDivisionBasedOnShareholdingsAsAt: int | None = None


class AnnouncementDetailResponse(_Lenient):
    # Optional + defaulted: both detail endpoints were observed returning
    # `{}` (HTTP 200, no reqBaseAnnouncement key at all) when queried with
    # an announcementId that belongs to the *other* endpoint's family —
    # see the module docstring. The loader treats that the same as a 204.
    reqBaseAnnouncement: AnnouncementDetail | None = None
