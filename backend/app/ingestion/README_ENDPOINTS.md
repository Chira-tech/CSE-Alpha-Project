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

### Full endpoint inventory (from the site's own `apiService` calls)

Extracted by grepping the production JS bundle for `apiService.*("...")`,
which is the authoritative list of what the frontend actually uses:

```
allSectors            allSecurityCode       announcementById
approvedAnnouncement  aspi/year             chartData
cntSecurity           corporateAnnouncementCategory
circularAnnouncement  directiveAnnouncement events  events/top
getAnnouncementByCompany  getAnnouncementById
getBuyInBoardAnnouncements  getCOVIDAnnouncements
getFinancialAnnouncement  getGeneralAnnouncementById
getNewListingsRelatedNoticesAnnouncements
getNonComplianceAnnouncements  marketStatus  news/web
notifications  notifications/corporate  notifications/directors
notifications/financial  returnAspiSnp  smd  smd/categories
(plus auth/subscription endpoints: signIn*, signUp*, verifyOtp,
 calculateAmount, editSubscription, paymentConfirm, ... — not relevant)
```

### `allSecurityCode` — GET (one of the few genuine GETs)
```json
[{"id":204,"name":"ABANS ELECTRICALS PLC","symbol":"ABAN.N0000","active":1}]
```
Every security with an `active` flag. Relevant to §7's survivorship
requirement ("delisted, suspended and defaulted companies remain in the
database"): this is the only endpoint found that distinguishes inactive
listings, though it gives no delisting date. Not yet used by any loader.

### `chartData` — POST form, `chartId=<N>&period=<1-5>`
**Index history only — not per company.** `chartId=1` is the ASPI;
`chartId` values 2-4 and every security id tried returned `[]`. Verified
depth:

| period | points | range |
|---|---|---|
| 1 | intraday | 1-minute bars for the session |
| 3 | 20 | ~1 month daily |
| 4 | 60 | ~3 months daily |
| 5 | 240 | ~1 year daily |

```json
[{"d":1784256360000,"v":21420.8,"pc":-0.1248}]
```
(`d` epoch millis, `v` index value, `pc` percent change.) Useful for the
Phase 5 macro engine; does **not** solve per-company price backfill.

### `aspi/year` — POST, no params
Year-to-date returns only, not a series:
`{"triAspiValue":-1.09,"snpValueForYear":-1.49,"aspiValueForYear":-4.43,"triSnpValue":2.34}`

### `companyInfoSummery` — POST form, `symbol=<TICKER>`
```json
{"reqSymbolBetaInfo": {"securityId":1108,"triASIBetaValue":1.42,
   "betaValueSPSL":1.52,"triASIBetaPeriod":"2026","quarter":1},
 "reqLogo": {...},
 "reqSymbolInfo": {"id":2025,"symbol":"AAF.N0000","name":"ASIA ASSET FINANCE PLC",
   "isin":"LK0406N00005","issueDate":"12/JAN/2012","quantityIssued":124195533,
   "parValue":1.0,"lastTradedPrice":49.1,"marketCap":...,
   "foreignHoldings":...,"foreignPercentage":...,
   "...": "plus wtd/mtd/ytd/p12 hi-lo-volume-turnover aggregates"}}
```
Consumed by `app.ingestion.security_enrichment` for ISIN, listing date
(`issueDate`, format "12/JAN/2012") and shares issued. Three deliberate
non-uses:

- **`foreignPercentage` is not free float.** A family-controlled
  conglomerate can be 95% domestically held and still have a 10% public
  float. `float_data.public_float_pct` therefore stays NULL until
  quarterly shareholding disclosures (§5) are ingested, and Gate 2 treats
  NULL as "cannot evaluate", never as a pass.
- **`betaValueSPSL` / `triASIBetaValue` are captured but not used as the
  system's beta.** §35.2 requires the Dimson (1979) aggregated-coefficient
  correction because CSE stocks routinely go days without trading, and
  calls skipping it "the single most common technical error in
  frontier-market factor work". CSE's published beta is a comparison
  point for our own estimate, not a substitute.
- **The `hi/lo` aggregates (`wtdHiPrice`, `ytdLowPrice`, `p12HiPrice`…)
  are not a price series.** They're summary statistics; they cannot
  reconstruct the daily history the factor library needs.

### No sector or archetype anywhere
Searched every endpoint above. `allSectors` gives sector *index levels*
but no company→sector membership, and `companyInfoSummery` has no sector
field. So `securities.cse_sector` and `securities.archetype` cannot be
populated from the API at all — which matches Appendix P2's own
instruction that the archetype mapping is "maintained as a
version-controlled file with manual overrides", since "several CSE
conglomerates are misclassified by standard GICS and must be corrected by
hand." Enrichment deliberately leaves both NULL rather than guessing:
archetype drives the valuation model router, where a wrong value silently
routes a bank through an industrial DCF (Part N #7).

### `detailedTrades` — POST form, `symbol=<TICKER>`
```json
{"reqDetailTrades": [{"id":204,"securityId":null,"name":"ABANS ELECTRICALS PLC",
  "symbol":"ABAN.N0000","price":1099.0,"qty":4,"trades":1,"change":4.75,
  "changePercentage":0.43}]}
```
Individual trade prints for the day, most recent first.

### `getFinancialAnnouncement` — POST form (any body, params ignored)
Master Spec §5's "Company financials ... PDF table extraction" path.
Confirmed by comparing responses for two different `symbol` values byte-
for-byte identical — **the `symbol` parameter is silently ignored**. This
is a GLOBAL feed of the ~180 most recent financial-statement filings
platform-wide, not a per-company query; there is no visible pagination
parameter, so it's unclear how far back "recent" goes (empirically, it
captured filings clustered around a single day — plausibly a rolling
window rather than a fixed count). Fine for event-driven "a new filing
just landed" ingestion; **not usable for historical backfill** (Part O #2)
without finding a different, per-company endpoint.
```json
{"reqFinancialAnnouncemnets": [{"id":52726,
  "path":"cmt/upload_report_file/3399_1786715988377.pdf",
  "manualDate":1774895400000,
  "uploadedDate":"14 Aug 2026 07:29:48 PM",
  "authorizedDate":"14 Aug 2026 08:16:24 PM",
  "fileText":"Annual Report as at 31st March 2026",
  "name":"JF PACKAGING PLC","symbol":"JFP"}]}
```
(Note the misspelling `reqFinancialAnnouncemnets` — that's the live API's
actual key, not a typo introduced here.) Field semantics, verified by
downloading the linked PDF and cross-checking its own printed dates:
- `symbol` is the BARE ticker without the CSE board suffix ("JFP", not
  "JFP.N0000") — client-side filtering must account for this.
- `path` is relative to CDN base `https://cdn.cse.lk/`. The PDF is the
  real, full filing (the annual report example was 18.6MB, 160 pages).
- `manualDate` is the statement's period-end ("as at"/"for the year
  ended" date) — confirmed against the PDF's own "As at 31st March 2026"
  heading.
- `authorizedDate` is when CSE actually published the filing — this is
  the correct point-in-time `first_available_date` (§6), NOT
  `manualDate`, which is exactly the period-end-as-availability-date
  mistake §6 warns against. `uploadedDate` is an earlier internal staging
  timestamp; used as a fallback when `authorizedDate` is absent (observed
  null on at least one interim filing in the same batch).
- `fileText` distinguishes annual reports from quarterly interims via
  simple substring matching ("Annual Report" / "Interim ... Quarter") —
  see `classify_period_type`; wording not matching either is skipped, not
  guessed.

### Extracting line items from the PDF
`app.domain.financial_statement_parsing` + `app.ingestion.financial_pdf_extractor`
implement a deterministic (not LLM-based — see their docstrings for why)
extractor, verified against the real J.F. Packaging PLC filing above.
Two findings worth knowing before extending it:
1. `pdfplumber`'s `extract_tables()` is useless on these documents — no
   ruled lines/borders, so it collapses each statement page into one text
   blob plus a column of numbers disconnected from their labels.
   `extract_text()`'s line-by-line output works far better.
2. Statement lines sometimes carry a note-reference number between the
   label and the values ("Revenue 5 4,504,801 ...") and sometimes don't
   ("Total Assets 3,807,110 ..."), and a bare note ref ("5", "13.2") is
   indistinguishable from a genuine small/decimal value by shape alone.
   The reliable signal turned out to be the statement's own declared
   column count (Sri Lankan comparative statements consistently print
   exactly 4 value columns — Group/Company × this-year/last-year, stated
   in their own "Notes Rs.000 Rs.000 Rs.000 Rs.000" header): one extra
   leading numeric token beyond that count is the note reference.

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
the ex-date but no subscription price**.

### Share splits / sub-divisions — same two-announcement pattern, verified
Confirmed on Lanka Tiles (TILE.N0000, Feb 2021) and First Capital Holdings
(CFVF.N0000, Feb–Apr 2022): `getAnnouncementById` on the initial
`SUB-DIVISION OF SHARES` announcement returns `dType: "ShareSplits"` with
**exact share counts** — the most reliable ratio source of anything this
loader handles:
```json
{"reqBaseAnnouncement": {"id":13681,"dType":"ShareSplits","symbol":"CFVF",
  "votingExistingNumOfShares":101250000,"votingResultingNumOfShares":"405000000",
  "votingProportion":"1 : 4","tradingCommencement":null}}
```
(`votingResultingNumOfShares` is a **string** in the API response even
though it's numeric — not a typo, handled as `str | int` in the schema.)
The follow-up `SUB-DIVISION OF SHARES (DATES)` announcement (via
`getGeneralAnnouncementById`, same 204-then-fallback pattern as rights
issues) carries the actual effective date as **`tradingCommencement`, not
`xr`** — `xr` was null on every split example seen, unlike rights issues
where it's the primary date field:
```json
{"reqBaseAnnouncement": {"id":14032,"title":"SUB-DIVISION OF SHARES (DATES)",
  "symbol":"CFVF","xr":null,"tradingCommencement":1650565800000,
  "tradingSuspended":1649615400000,"votingProportion":null}}
```
**The ratio convention is different from rights issues and this is the
easiest mistake to make if you write this loader from memory rather than
from a live example**: a rights issue's "N:M" means *N new shares per M
held* (additive), verified via `parse_share_ratio_text`. A split's "1:4"
means *1 old share becomes 4 total* (multiplicative), verified via
`parse_before_after_ratio_text` — same textual shape, opposite arithmetic.
`app.domain.announcement_parsing.before_after_to_new_per_held` converts
the latter into this system's "new shares per held share" convention
before it's stored, so downstream code (the adjustment-factor build) never
has to know two conventions exist.

`app.ingestion.corporate_actions_loader` now pairs the initial and dates
announcements for the same event (rights issues and splits both) rather
than drafting each independently — see the module's own docstring for the
pairing heuristic and its limits.

## Known gaps — confirm before relying on these in production

1. **Bonus issue** (a plain bonus/scrip issue with no share-count fields,
   as opposed to the sub-division cases above which turned out to be well
   covered): no live example was captured this session. The loader's
   handling for it is the same generic ratio-text path used before splits
   were verified, and is explicitly labelled `UNVERIFIED MAPPING` in the
   notes it writes.
2. **Consolidation**: same caveat as bonus issue. `CONSOLIDATION OF SHARES
   AND RIGHTS ISSUE` was seen in one company's announcement list but its
   detail payload wasn't successfully retrieved during probing (an
   announcementId lookup returned an unrelated AGM notice instead —
   plausible cause: `id` vs `announcementId` confusion in the source list,
   worth re-checking). Given splits and consolidations are economically
   opposite (share count up vs down), do not assume consolidation reuses
   the split convention without verifying — check whether `before > after`
   changes sign conventions anywhere before trusting a consolidation draft.
3. **Rights-issue / split pairing heuristic**: `_pair_rows` in
   `corporate_actions_loader.py` sorts each company's initial and dates
   announcements chronologically and zips them index-wise. This matched
   every live example this session (each company had exactly one event of
   each type in the sampled window) but was not tested against a company
   with two overlapping rights issues or splits in flight at once.
4. **`notifications`, `notifications/corporate`, `notifications/financial`,
   `notifications/directors`**: these exist in the frontend's service
   layer as `apiService.get(...)` calls (i.e. GET, unlike everything
   else), but `GET /api/notifications/corporate` etc. returned `400
   "Could not find the GET method for URL"` live. Only bare `GET
   /api/notifications` worked. Possible explanations: a frontend/backend
   version mismatch, or these routes require a header/param not yet
   identified. Not used by any loader in this codebase; re-verify before
   building against them.
5. **Rate limiting behaviour under sustained load** was not tested (this
   session made ~80 requests total across three verification passes, well
   under any plausible limit, spaced by manual probing rather than the
   client's actual pacing). `CseClient`'s conservative defaults (§5: ≥2s
   between calls) should be kept until there's a reason to believe
   otherwise.
6. **Financial-statement extraction covers a specific, verified subset**
   (see CANONICAL_LABELS in `app.domain.financial_statement_parsing`):
   the totals/subtotals typical of a Statement of Financial Position and
   a Statement of Profit or Loss — total assets/equity/liabilities and
   their current/non-current splits, revenue, gross/operating profit,
   profit before tax, net income. It does NOT extract: cash flow
   statement lines, balance-sheet line items below the totals (PPE,
   receivables, etc. — deliberately, since those are usually
   note-referenced and less load-bearing for a first pass), segment data,
   or anything from a statement laid out with a different column count
   than the 4-column Group/Company comparative format (see
   `DEFAULT_EXPECTED_VALUE_COLUMNS`'s docstring). Verified against exactly
   one real filing (J.F. Packaging PLC's FY2025/26 annual report) — label
   wording that varies across other companies' statements (e.g. "Total
   Shareholders' Funds" instead of "Total Equity" — one synonym for this
   is already in CANONICAL_LABELS, but there will be others) will simply
   fail to match rather than extract something wrong, which is the safe
   failure mode but means real coverage across all ~286 companies is
   unknown until more filings are processed.
7. **No LLM-assisted extraction is wired in.** The deterministic extractor
   above is a genuine, tested Phase-1 capability, but it is not what
   Master Spec §5 ultimately describes. Actually calling an LLM to map
   arbitrary statement line items needs an API key, a model/cost
   decision, and a place to put that decision — none of which belongs in
   this file being decided unilaterally. Track it as an open item
   (PARAMETERS.md) rather than assuming it's "coming later" without a
   decision behind it.
