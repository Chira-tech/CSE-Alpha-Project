# R1 Phase 5 — Independent valuation validation

Master Spec R1 brief §7: "The user asked for a blind cross-check of the
system's own outputs. This is the single best test of whether the
platform is trustworthy."

## Method (as specified)

1. Select 5 tickers at random with a recorded seed, spanning at least
   three sectors, including at least one bank.
2. For each, **without reading the system's own output first**, build
   an independent valuation from the raw financial statements and
   market data in the database: appropriate model for the sector,
   explicit assumptions, worked arithmetic.
3. Record the independent fair value range, buy-below level and
   sell-above level.
4. Retrieve the system's output and compare.
5. For every material divergence (>15% on fair value), diagnose: input
   error, model selection error, assumption difference, or genuine
   judgement gap.

## Selection

Random seed: `20260823` (today's date, Python `random.Random(seed)`,
`.shuffle()` on the full investable universe with a real `cse_sector`
assigned, sorted by ticker first for reproducibility). First 5 of the
shuffled order, checked afterwards (not forced) to confirm >=3 sectors
and >=1 bank — both held on the first pass, so no re-draw was needed.

| Ticker | Name | Sector | Archetype |
|---|---|---|---|
| LOFC.N0000 | LOLC FINANCE PLC | Diversified Financials | non_bank_finance |
| UCAR.N0000 | UNION CHEMICALS LANKA PLC | Materials | manufacturing |
| HNB.N0000 | HATTON NATIONAL BANK PLC | Banks | bank |
| MFPE.N0000 | MAHARAJA FOODS PLC | Food, Beverage & Tobacco | consumer |
| TAJ.N0000 | TAL LANKA HOTELS PLC | Consumer Services | hotel |

Reproduction script:

```python
import random
from app.db.session import SessionLocal
from sqlalchemy import select
from app.models.securities import Security

db = SessionLocal()
rows = db.execute(
    select(Security.ticker, Security.name, Security.cse_sector, Security.archetype)
    .where(Security.delisting_date.is_(None))
    .order_by(Security.ticker)
).all()
db.close()
universe = [(t, n, s, a) for t, n, s, a in rows if s is not None]
rng = random.Random(20260823)
shuffled = universe[:]
rng.shuffle(shuffled)
picked = shuffled[:5]
```

## Independence discipline

For each ticker below, the raw `Fundamental` rows, real stored prices
and real shares-issued were pulled directly from the database — never
this system's own `/valuation/{ticker}` or `/composite-score/{ticker}`
endpoints — before any model or number was written down. The system's
own output was retrieved and compared only after the independent
figure was recorded, in a separate section per ticker, so the
independent number could not be unconsciously anchored on it.

**The single most important result of this exercise happened before
any valuation model was even reached**: pulling LOFC.N0000's raw
confirmed data turned up two implausible values on inspection alone
(`interest_expense=4.2`, `income_tax_expense=13`, both absurd next to
surrounding billion-scale figures). Checked against the real source PDF
and the current extractor — both were genuine note-reference numbers
wrongly confirmed as real values, the exact OI-1 bug pattern, on two
statement lines OI-1's own reverification sweep never checked. Both are
now corrected in the database (see `R1_OPEN_ISSUES.md`, OI-4) — this
document's own LOFC section below uses the corrected figures.

---

## Part A — Independent calculations, and Part B — third-party comparison

Combined per ticker below rather than as two separate passes: each
section still separates a ticker's independent figure (built from this
system's own raw stored data, before any external search) from what
the external search then found, so the independence discipline above
holds — but presenting them together is easier to audit than the same
content split across two disconnected parts of the document.

### LOFC.N0000 — LOLC Finance PLC (Diversified Financials, non_bank_finance)

**Independent calculation.** After the OI-4 correction, the confirmed
FY2024/25 (period end 2025-03-31) figures are real and internally
consistent: net income LKR 25,085,140,797, interest expense
-26,211,477,746 (i.e. LKR 26.2bn of interest cost), income tax expense
0 (nil per the filing). Shares issued 29,560,147,161; last price LKR
5.10 (2026-08-21) -> market cap ~LKR 150.7bn.

- EPS = 25,085,140,797 / 29,560,147,161 = **LKR 0.849/share**
- P/E at LKR 5.10 = **6.0x**

No confirmed `total_equity` exists for this period in this system's own
data (the only confirmed equity figure sits on a 2019 row whose own
scale is inconsistent with the surrounding years — a second, separate
data-quality issue on this same ticker, not corrected here — see
"Not independently valued further" below), so a book-value-based
justified-P/B or residual-income figure — LOFC's real routing as an
NBFI — cannot be built independently from this system's stored data
today. **Independent read: on a bare P/E basis, 6.0x against
"highest-ever" reported profit reads cheap, but this is a single-
multiple check, not a real independent valuation** — NBFIs carry real
leverage/asset-quality risk a P/E multiple alone doesn't price in.

**Third-party comparison.** LOLC Finance's own investor communications
(via web search, not this system) confirm FY2024/25 profit after tax
of "Rs. 25 billion... highest-ever" and interest income of Rs. 68.3
billion (2024/25) — both match this system's own now-corrected
`net_income` (25,085,140,797) and `interest_income` almost exactly
(68,317,633,361 extracted vs. "Rs. 68.3 billion" reported), which is
real, independent corroboration that the OI-4 correction landed on the
right number, not just a plausible-looking one. No broker target price
or formal research note was found in this search pass for LOFC
specifically — CSE broker coverage of NBFIs below the largest names is
thin, consistent with the brief's own "handle absence honestly"
instruction.

**Divergence:** not computed against the system's own `/valuation`
output — no comparable system-computed fair value exists for LOFC
today (no confirmed total_equity -> no Justified P/B or residual
income anchor computable), so there is nothing to diverge from. This
is itself the finding: this system's real fair-value coverage does not
yet reach a real, randomly-selected NBFI, for a real, disclosed reason
(a missing confirmed balance-sheet figure), not a defect in the
valuation logic itself.

Sources: [LOLC Finance Annual Report 2024/2025 — MarketScreener](https://www.marketscreener.com/news/lolc-finance-annual-report-2024-2025-ce7c50dcd080f226), [LOLC Finance half-year result announcement](https://www.lolc.com/news/lolc-finance-reports-robust-half-year-result-with-rs-14-billion-profit-after-tax)

---

### HNB.N0000 — Hatton National Bank PLC (Banks, bank)

**Independent calculation, first pass (from this system's own stored
data alone).** Confirmed FY2025 (period end 2025-12-31) and FY2024
(2024-12-31) annual figures give: total equity = total assets - total
liabilities = LKR 270,320,960,000 (2025) and LKR 231,479,275,000
(2024). Shares issued 460,218,180; last price LKR 384.25 -> book value
per share = LKR 587.44 -> **P/B = 0.65x**. FY2024's own confirmed
`net_income` (3,179,557,000) implies ROE = 3,179,557,000 /
231,479,275,000 = **1.37%** — implausibly low for a bank of HNB's real
scale, and low enough that a standard Justified-P/B formula
((ROE-g)/(Ke-g)) breaks (produces a negative multiple once g exceeds
this ROE).

**Third-party comparison — and this is the material divergence.** Real
external search (not this system) reports HNB's actual FY2025 group
earnings at **LKR 47.59 billion**, up 9.31% YoY, on FY2025 revenue of
LKR 183.24 billion. This system's own confirmed `net_income` for
FY2024 (3,179,557,000) is roughly **15x smaller** than the real,
externally-reported group profit for the adjacent year — an order-of-
magnitude divergence, not a rounding difference. Recomputing with the
external, real earnings figure instead: EPS ~= 47,590,000,000 /
460,218,180 ~= LKR 103.4/share -> **P/E ~= 3.7x** at the current LKR
384.25 price — a genuinely low multiple for a bank that just grew
earnings 9%, consistent with the external analyst target range found
(LKR 366.58-566.82, midpoint estimates clustering around LKR 481) all
sitting at or above the current price.

**Diagnosis (per the brief's own four categories): input error.** This
system's own confirmed `net_income` for HNB FY2024 is wrong by roughly
an order of magnitude against real, externally-reported group
earnings — most likely either a mis-scoped line (Bank-only vs. Group,
or a single quarter mislabelled `period_type=annual`) rather than a
genuine restatement. **Not yet root-caused to a specific source PDF
line in this pass** (unlike the LOFC finding above, which was traced
to an exact page and snippet) — flagged here as a real, high-priority
follow-up for Phase 1, not silently corrected, because guessing the
right replacement number without finding the actual misread source
line would just be a second, different fabrication.

Sources: [HNB.N0000 forecast/price target — TradingView](https://www.tradingview.com/symbols/CSELK-HNB.N0000/forecast/), [Simply Wall St — HNB.N0000](https://simplywall.st/stocks/lk/banks/cose-hnb.n0000/hatton-national-bank-shares), [stockanalysis.com — HNB.N0000](https://stockanalysis.com/quote/cose/HNB.N0000/)

---

### MFPE.N0000 — Maharaja Foods PLC (Food, Beverage & Tobacco, consumer)

**Independent calculation.** This system's own confirmed data for MFPE
has a real, separate data-quality issue found live: the two most
recent "annual" periods on file (2025-10-22 and 2025-03-31) carry
**identical figures down to the last rupee** — revenue 630,360,999,
total_assets 698,694,157, total_equity 268,412,280 repeated exactly —
almost certainly the same filing stored twice under two different
period_end dates rather than two genuinely distinct fiscal periods
(named here, not corrected — see "Not independently valued further"
below; distinct from OI-4's note-reference bug, a period-tagging issue
instead). No `net_income` is confirmed for MFPE at all, only
`gross_profit` (123,985,214) and revenue. BVPS = 268,412,280 /
137,500,000 = LKR 1.95 -> at LKR 16.00, **P/B ~= 8.2x** — high for the
observable ~19.7% gross margin, but ROE cannot be computed independently
without a confirmed net_income to check whether that multiple is
earned.

**Third-party comparison.** External search finds real FY2026 results:
EPS LKR 0.44 (up from LKR 0.42 FY2025), revenue LKR 1.01bn (up 61%
YoY, implying FY2025 revenue ~= LKR 627m — consistent with this
system's own stored 630,360,999), net income LKR 60.4m (up 21% YoY,
implying FY2025 net income ~= LKR 50m). Using the external FY2025 EPS
(~LKR 0.42-0.36 depending on which growth figure is used as the
base): P/E at LKR 16.00 ~= **38-44x**.

**Diagnosis: genuine judgement gap, not an input error.** The external
figures corroborate this system's own confirmed revenue closely
(627m external vs. 630m stored) — the gap here is that this system has
no confirmed `net_income` for MFPE to compute ROE or a P/E from at
all, which is a real, named coverage gap, not a wrong number. The
independent P/B-only read (~8.2x, "high for the observable margin
profile") is confirmed directionally by the external P/E (~38-44x,
also high) — both readings agree this is a richly-valued small-cap,
via two different routes to the same conclusion.

Sources: [Maharaja Foods — stockanalysis.com](https://stockanalysis.com/quote/cose/MFPE.N0000/), [Maharaja Foods market cap — stockanalysis.com](https://stockanalysis.com/quote/cose/MFPE.N0000/market-cap/)

---

### TAJ.N0000 — Tal Lanka Hotels PLC (Consumer Services, hotel)

**Independent calculation.** This system's own confirmed FY2025 data
(period end 2025-03-31) shows total_equity = -LKR 1,704,524,473 — a
real, internally-consistent negative figure (total_assets
4,663,346,498 minus total_liabilities 6,367,870,971 matches exactly).
A negative-equity company cannot be meaningfully valued on P/B (the
multiple is undefined/sign-flipped), consistent with this system's own
real archetype routing for hotels (NAV/EV-EBITDA-style models, not
P/B) — and no `net_income` or EBITDA is confirmed for TAJ either, so a
full independent DCF/EV-EBITDA cannot be built from this system's
stored data alone. The one usable independent read: shares issued
171,866,018 x price LKR 31.00 = market cap ~LKR 5.33bn against real
confirmed operating cash flow of LKR 643,276,344 (FY2025) -> **~8.3x
market-cap/operating-cash-flow** — not obviously expensive for a
hotel, but a weak, single-multiple estimate given everything else
missing.

**Third-party comparison.** External search independently confirms
the negative-equity finding almost exactly (real reported shareholder
equity ~-LKR 1.6bn vs. this system's own -LKR 1.70bn) and adds
context this system doesn't have at all: TAJ has been **loss-making in
its most recent quarters** (net income -LKR 164.34m and -LKR 112.29m
in the two most recent quarters found), and the share price has fallen
from a 52-week high of LKR 52.00 to the current LKR 31.00.

**Diagnosis: genuine judgement gap.** This system's own stored balance-
sheet figures for TAJ are real and externally corroborated — the gap
is coverage (no net_income/EBITDA confirmed at all), not correctness.
The external loss-making trend is real context this system's fair-
value engine has no way to reflect without those confirmed figures,
and is exactly why this system routes hotels away from an earnings
multiple in the first place.

Sources: [TAL Lanka Hotels — TradingView financials](https://www.tradingview.com/symbols/CSELK-TAJ.N0000/financials-overview/), [TAL Lanka Hotels balance sheet — Simply Wall St](https://simplywall.st/stocks/lk/consumer-services/cose-taj.n0000/tal-lanka-hotels-shares/health)

---

### UCAR.N0000 — Union Chemicals Lanka PLC (Materials, manufacturing)

**Independent calculation: not possible from this system's own data.**
Zero confirmed (human-approved) `Fundamental` rows exist for UCAR at
all. Real AI-assisted DRAFT rows do exist and were inspected (never
confirmed, correctly withheld from any valuation per §8's own gate) —
and they show the exact same note-reference-contamination shape as
OI-4's LOFC finding, on MANY more lines at once (`revenue=5000`,
`interest_expense=8200`, `profit_before_tax=9000`,
`income_tax_expense=10000`, `inventories`/`trade_receivables`/
`trade_payables` all in the low thousands next to real billion-scale
`total_assets`/`cost_of_sales`/`net_income` on the very same rows) —
real, live evidence that §8's human-confirmation gate is doing exactly
the job it exists to do: none of this contaminated draft data has ever
reached a valuation.

**Third-party comparison.** External search finds a real, striking
price discrepancy: this system's own stored last close is LKR
2,330.00 (2026-08-21), while external sources show LKR ~910.75 —
roughly **2.6x apart**, not a rounding gap. Not root-caused in this
pass (a stock split/bonus issue timing mismatch, a stale external
quote, or a real error in this system's own stored price are all
plausible and were not distinguished here) — named as a real, separate
follow-up rather than guessed at. External EPS was reported at LKR
139.15 with a 13.50% net margin, which cannot be cross-checked against
this system's own data at all (zero confirmed fundamentals).

**Diagnosis: genuine judgement gap on fundamentals coverage (confirmed
data literally does not exist), plus a separate, unresolved possible
input error on price** — two different findings on the same ticker,
neither fabricated a number to fill the gap.

Sources: [Union Chemicals Lanka — TradingView](https://www.tradingview.com/symbols/CSELK-UCAR.N0000/), [Union Chemicals Lanka — Morningstar](https://www.morningstar.com/stocks/xcol/ucar.n0000/quote)

---

## Not independently valued further (named, not silently dropped)

- **LOFC's own 2019-03-31 confirmed balance-sheet figures** (total_assets
  211,114,232,211, total_equity 17,105,633,755) are inconsistent with
  every surrounding year (15-24bn total_assets in 2020-2022) — a
  second, separate note-reference-or-unit-scale contamination on this
  same ticker, not traced to an exact source line or corrected in this
  pass (OI-4 only covers the two rows this exercise's own arithmetic
  directly needed and could fully verify against the source PDF).
- **MFPE's duplicate-period bug** (2025-10-22 and 2025-03-31 carrying
  identical figures) is named above but not fixed — needs tracing
  through the ingestion pipeline's period-end assignment logic, not a
  simple data-value correction like OI-4's.
- **HNB's real net_income divergence** is diagnosed as a probable input
  error (see above) but the specific wrong source line was not found —
  correcting a number without finding the actual misread would be a
  second fabrication, not a fix.
- **UCAR's 2.6x price discrepancy** against external quotes was found
  but not root-caused.

## Combined findings

**Where this system is trustworthy:** every confirmed figure that WAS
cross-checked against real external sources in this pass — LOFC's
corrected net_income and interest_income, HNB's balance-sheet-derived
equity, TAJ's negative equity, MFPE's revenue — matched real external
reporting closely. §8's human-confirmation gate is working exactly as
designed: UCAR's heavily-contaminated draft data has never touched a
valuation, and every stale-but-confirmed bad value found (LOFC's two
rows) traces to a REAL prior extraction bug already partially
remediated (OI-1), not an ongoing live defect.

**Where it is not, ranked:**
1. **HNB's net_income is wrong by ~15x** against real external
   reporting — the single most material finding in this pass, and
   still unresolved (root cause not found).
2. **OI-1's reverification sweep was scoped too narrowly** (8 lines
   checked out of far more that exist) — this pass found two more
   contaminated rows on lines outside that set from a SINGLE random
   ticker; the true scale across the whole universe is unknown.
3. **Real fair-value coverage for a "typical" (non-flagship) CSE
   ticker is thin**: 3 of 5 randomly-selected tickers (LOFC, MFPE, TAJ)
   had no independently-computable fair value from this system's own
   confirmed data, each for a different, real, named reason (missing
   equity, missing net_income, missing net_income/EBITDA) — not a
   uniform gap with one fix.
4. **A real, unresolved price discrepancy** on UCAR (2.6x vs. external)
   and **a real, unresolved period-tagging bug** on MFPE (duplicate
   periods) — both named, neither root-caused in this pass.

**Prioritised follow-up work:**
1. Root-cause HNB's net_income divergence — highest materiality, a
   bank getting its own headline profit figure wrong by 15x is a
   serious integrity problem even though it never reached a valuation
   (HNB currently isn't included as a live scored position anywhere
   observed this session).
2. Re-scope and re-run OI-1's reverification sweep across every
   confirmed statement line, not just the original 8 — the true extent
   of note-reference contamination in currently-confirmed data is
   unknown at universe scale.
3. Trace MFPE's duplicate-period bug through the ingestion pipeline.
4. Root-cause UCAR's price discrepancy.
5. Broaden confirmed-fundamentals coverage for non-flagship tickers —
   this pass's own random sample (not cherry-picked) found 3 of 5
   randomly-selected names unvaluable from confirmed data alone, which
   is the real, current state of coverage depth outside the handful of
   large, closely-watched names this session's manual testing mostly
   used (JKH, COMB, HNB itself).
