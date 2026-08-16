# cse.lk API — verified endpoint trace

Probed live on 16 Aug 2026 (outside trading hours — market was closed
during this session, so price fields reflect the last completed session).
Base URL: `https://www.cse.lk/api`. Confirmed by downloading and grepping
the site's Next.js JS chunks for the `apiService` client (`axios.create({
baseURL: "https://www.cse.lk/api" })`), which is the authoritative source
for method/path — more reliable than guessing from the rendered UI.

**The single biggest correction to the original Phase-1 assumption:**
every endpoint is **POST**, never GET. `curl -X GET` returns `405/400
"Could not find the GET method for URL ..."` on all of them. This wasn't
obvious from the master spec (which never states the HTTP method) and
would have silently produced zero data forever if left unverified.

## Request shape — two distinct conventions, and they are not interchangeable

| Endpoint class | Content-Type | Example |
|---|---|---|
| No-parameter list/status endpoints | `application/json`, body `{}` | `marketStatus`, `tradeSummary`, `todaySharePrice`, `topGainers`, `topLooses`, `aspiData`, `dailyMarketSummery` |
| Parameterised endpoints | `application/x-www-form-urlencoded` | `companyInfoSummery` (symbol), `detailedTrades` (symbol), `getAnnouncementByCompany` (symbol), `getAnnouncementById` / `getGeneralAnnouncementById` (announcementId) |

Sending a parameterised endpoint a JSON body (even with the right field
name) returns `400 {"apierror":{"message":"symbol parameter is
missing"}}` — the server reads form fields, not the JSON body, for these.
`app.ingestion.cse_client.CseClient` exposes `post_json` and `post_form`
as separate methods specifically so a loader can't accidentally use the
wrong one and get a confusing 400.

## Verified endpoints and shapes

### `marketStatus` — POST `{}`
```json
{"status": "Market Closed"}
```

### `tradeSummary` — POST `{}`
```json
{"reqTradeSummery": [{
  "id": 204, "name": "ABANS ELECTRICALS PLC", "symbol": "ABAN.N0000",
  "quantity": 1, "percentageChange": -3.107, "change": -34.0,
  "price": 1060.25, "previousClose": 1094.25, "high": 1099.0, "low": 1060.0,
  "lastTradedTime": 1786691785346, "turnover": 127387.75,
  "sharevolume": 120, "tradevolume": 10, "marketCap": 5.41847124E9,
  "open": 1099.0, "closingPrice": 1060.25, "crossingVolume": 120,
  "crossingTradeVol": 10, "status": 0
}]}
```
`sharevolume` = shares traded, `tradevolume` appears to be trade count
(not fully confirmed — no separate `trades` field was observed).

### `todaySharePrice` — POST `{}`
```json
[{"id":204,"symbol":"ABAN.N0000","open":1099.0,"high":1099.0,"low":1060.0,
  "lastTradedPrice":1060.25,"change":-34.0,"changePercentage":-3.107151,
  "crossingVolume":120,"tradesTime":1786691785346,"quantity":1}]
```
Returns a bare JSON array, not wrapped in an object key.

### `topGainers` / `topLooses` — POST `{}`
```json
[{"id":57581725,"securityId":3244,"symbol":"AINS.N0000","price":27.7,
  "change":2.8,"changePercentage":11.24,"tradeDate":1786697798000}]
```

### `aspiData` — POST `{}`
```json
{"id":36972259,"value":21623.17,"lowValue":21539.0,"highValue":21675.45,
 "change":84.17,"percentage":0.39,"sectorId":1.0,"timestamp":1786699620393}
```

### `dailyMarketSummery` — POST `{}`
Returns `[[{row}], [{row}], ...]` — a list of **single-element lists**,
one per trading day, most recent first. Each row carries ~30 market-wide
fields (turnover, CDS holdings domestic/foreign, ASI/SPT close, PER, PBV,
DY, etc.) — see `app.ingestion.schemas.DailyMarketSummaryRow` for the
subset this system types; everything else is dropped by the lenient model.

### `companyInfoSummery` — POST form, `symbol=<TICKER>`
```json
{"reqSymbolBetaInfo": {...}, "reqLogo": {...},
 "reqSymbolInfo": {"id":2025,"symbol":"AAF.N0000","name":"ASIA ASSET FINANCE PLC",
   "issueDate":"12/JAN/2012","quantityIssued":124195533,"parValue":1.0,
   "lastTradedPrice":49.1, "...": "many more hi/lo/volume fields"}}
```

### `detailedTrades` — POST form, `symbol=<TICKER>`
```json
{"reqDetailTrades": [{"id":204,"securityId":null,"name":"ABANS ELECTRICALS PLC",
  "symbol":"ABAN.N0000","price":1099.0,"qty":4,"trades":1,"change":4.75,
  "changePercentage":0.43}]}
```
Individual trade prints for the day, most recent first.

## Announcements / corporate actions — the Phase-1-critical path

### `getAnnouncementByCompany` — POST form, `symbol=<TICKER>`
List of every announcement for a company, newest first. **Corporate-action
dates (`xr`/`xc`/`xd`, `recordDate`, `paymentDate`, `allotment`) are
always `null` on this list endpoint** — they only appear on the detail
lookup. Use `announcementId` (not `id`) to fetch detail.

```json
{"reqCompanyAnnouncement": [{"id":31879,"createdDate":1784132908000,
  "dateOfAnnouncement":"15 Jul 2026","announcementId":38054,
  "announcementCategory":"CASH DIVIDEND","company":"ASIA ASSET FINANCE PLC",
  "type":"new","symbol":null,"recordDate":null,"xr":null,"xd":null, "...": null}]}
```

Categories observed live (Asia Asset Finance PLC, ~2021-2026 history):
`CASH DIVIDEND`, `CASH DIVIDEND (DATES TO BE NOTIFIED)`, `RIGHTS ISSUE`,
`RIGHTS ISSUE (DATES)`, `RIGHTS ISSUE DATES`, `RIGHTS ISSUE / CHANGE OF
DATE OF ACCEPTANCE AND PAYMENT`, `CONSOLIDATION OF SHARES AND RIGHTS
ISSUE`, plus a long tail of non-corporate-action categories (AGM/EGM
notices, director dealings, disclosures, auditor/chairman changes...).
`SUBDIVISION, PRIVATE PLACEMENT AND REDUCTION OF STATED CAPITAL` was seen
on DIST.N0000 but its detail payload was **not** successfully captured
(see Known Gaps below). No plain `BONUS ISSUE` or `STOCK SPLIT` example
was found on the tickers sampled this session.

### `getAnnouncementById` — POST form, `announcementId=<ID>`
Detail for "base" announcements (dividends, initial rights disclosures).
Discriminated by `dType`. **Returns HTTP 204 (no body) for an
announcementId that belongs to the "general announcement" family
instead** — this is real, observed behaviour, not an error to work
around; the loader falls back to `getGeneralAnnouncementById`.

Cash dividend example (`dType: "CashDividendWithDates"`):
```json
{"reqBaseAnnouncement": {"id":38054,"dType":"CashDividendWithDates",
  "symbol":"AAF","companyName":"ASIA ASSET FINANCE PLC",
  "financialYear":"2025/2026","xd":"24 Jul 2026","payment":"13 Aug 2026",
  "recordDate":1785090600000,"votingDivPerShare":0,"nonVotingDivPerShare":0,
  "remarks":"...Fixed - Non Cumulative Dividend of Cents .70..."}}
```
Note `votingDivPerShare`/`nonVotingDivPerShare` were both `0` here even
though the dividend amount ("Cents .70") is stated in `remarks` — observed
on a **preference-share** dividend specifically; the loader does not
attempt to parse the amount out of `remarks` (too fragile for a figure
that feeds arithmetic) and instead flags the row for manual entry.

Rights issue example (`dType: "RightsIssue"`, the *initial* disclosure —
no dates yet):
```json
{"reqBaseAnnouncement": {"id":37489,"dType":"RightsIssue","symbol":"AAF",
  "numOfVotingShrsIssued":45162012,
  "votingShrsPropToBeIssued":"04 (Four) new Ordinary Voting Shares will be provisionally allotted to every 11 (Eleven) Ordinary Voting Shares",
  "votingShareConsideration":33.3,"curStatCapOfEntity":2205463801,"xr":null}}
```

### `getGeneralAnnouncementById` — POST form, `announcementId=<ID>`
Detail for "general" announcements: AGM/EGM notices, and — critically —
the **rights-issue "(DATES)" follow-up**, which is where the actual
ex-rights date lives:
```json
{"reqBaseAnnouncement": {"id":37897,"title":"RIGHTS ISSUE (DATES)",
  "symbol":"AAF","recordDate":1785695400000,"allotment":1786300200000,
  "xr":1785436200000,"tradingCommencement":1786645800000,
  "votingProportion":"04 (Four) new Ordinary Voting Shares will be provisionally allotted to every 11 (Eleven) Ordinary Voting Shares",
  "egm":1785349800000}}
```
No `dType` key on this family — use `title` instead. Note the **initial
disclosure has the subscription price but no dates; the dates record has
the ex-date but no subscription price**. A fully-populated rights-issue
draft (ratio + subscription price + ex-date, everything TERP needs except
the market's own cum-rights price) requires correlating both
announcements for the same company issued close together in time — not
implemented this session; `corporate_actions_loader.build_draft` produces
a partial draft from whichever record it's given and lists what's missing
in `notes` for the human reviewer.

## Known gaps — confirm before relying on these in production

1. **Bonus issue / plain stock split**: no live example captured. The
   loader's handling for these (`app.ingestion.corporate_actions_loader`,
   the `bonus_issue`/`stock_split` branch) is generic and explicitly
   labelled `UNVERIFIED MAPPING` in the notes it writes — treat every such
   draft as needing full manual reconstruction from the source PDF.
2. **Consolidation**: same caveat. `CONSOLIDATION OF SHARES AND RIGHTS
   ISSUE` was seen in a list but its detail payload wasn't successfully
   retrieved (an announcementId mismatch during probing pulled up an
   unrelated AGM notice instead — plausible cause: `id` vs
   `announcementId` confusion in the source list, worth re-checking).
3. **`notifications`, `notifications/corporate`, `notifications/financial`,
   `notifications/directors`**: these exist in the frontend's service
   layer as `apiService.get(...)` calls (i.e. GET, unlike everything
   else), but `GET /api/notifications/corporate` etc. returned `400
   "Could not find the GET method for URL"` live. Only bare `GET
   /api/notifications` worked. Possible explanations: a frontend/backend
   version mismatch, or these routes require a header/param not yet
   identified. Not used by any loader in this codebase; re-verify before
   building against them.
4. **Rate limiting behaviour under sustained load** was not tested (this
   session made ~40 requests total, well under any plausible limit,
   spaced by manual probing rather than the client's actual pacing).
   `CseClient`'s conservative defaults (§5: ≥2s between calls) should be
   kept until there's a reason to believe otherwise.
