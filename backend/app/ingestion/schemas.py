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


class SectorIndexRow(_Lenient):
    """One row from `allSectors` — verified live. These are the S&P/CSE
    GICS industry-group indices (Energy, Materials, Capital Goods, ...),
    not the CSE's own sector classification of individual companies."""

    sectorId: int | None = None
    symbol: str | None = None
    name: str
    indexName: str | None = None
    indexValue: float | None = None
    change: float | None = None
    percentage: float | None = None
    sectorTurnoverToday: float | None = None
    sectorVolumeToday: int | None = None
    transactionTime: int | None = None


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
    tradingSuspended: int | None = None
    votingProportion: str | None = None
    subDivisionBasedOnShareholdingsAsAt: int | None = None

    # share split / sub-division (dType "ShareSplits", initial disclosure).
    # Verified live (Lanka Tiles TILE.N0000, First Capital Holdings
    # CFVF.N0000): `votingProportion` here is a bare "1 : 4" before:after
    # ratio — a DIFFERENT convention from the rights issue's "N new every
    # M held" prose above. `votingResultingNumOfShares` is returned as a
    # STRING by the API even though it's numeric ("405000000"), hence
    # `str | int` rather than `int`.
    votingExistingNumOfShares: int | None = None
    votingResultingNumOfShares: str | int | None = None


class FinancialAnnouncementRow(_Lenient):
    """One filing from `getFinancialAnnouncement` — verified live 16 Aug
    2026 (see README_ENDPOINTS.md). This endpoint returns a GLOBAL feed of
    recent financial-statement filings across every listed company; the
    `symbol` parameter passed in the request appears to be ignored (the
    same global list came back regardless), so per-company filtering must
    be done client-side on the returned `symbol` field, which is the BARE
    ticker without the CSE board suffix (e.g. "JFP", not "JFP.N0000").
    `path` is relative to the CDN base `https://cdn.cse.lk/`.
    """

    id: int
    symbol: str
    name: str | None = None
    path: str
    manualDate: int | None = None  # epoch millis — the statement's "as at" / period-end date
    uploadedDate: str | None = None  # "14 Aug 2026 07:29:48 PM"
    authorizedDate: str | None = None  # "14 Aug 2026 08:16:24 PM" — when CSE published it; use as first_available_date
    fileText: str | None = None  # e.g. "Annual Report as at 31st March 2026"


class FinancialAnnouncementResponse(_Lenient):
    reqFinancialAnnouncemnets: list[FinancialAnnouncementRow]  # sic — typo is in the live API response key


class AnnouncementDetailResponse(_Lenient):
    # Optional + defaulted: both detail endpoints were observed returning
    # `{}` (HTTP 200, no reqBaseAnnouncement key at all) when queried with
    # an announcementId that belongs to the *other* endpoint's family —
    # see the module docstring. The loader treats that the same as a 204.
    reqBaseAnnouncement: AnnouncementDetail | None = None
