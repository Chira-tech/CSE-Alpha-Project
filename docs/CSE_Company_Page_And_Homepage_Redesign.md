# Company Page & Homepage Redesign — Research-Led

Built against one test, applied to every section: **does this help me decide whether today's price is the right price to buy or sell at?** If a section doesn't serve that, it gets demoted or cut — no matter how much work went into it.

Design decisions follow the `ui-ux-mastery` and `dataviz` skills. Chart forms are picked by the data's job, colour tokens are contrast-validated (results in §7), and every chart is checked against the anti-pattern list.

Companion to `aaf-factcheck-and-company-page-redesign.md` and `cse-universe-integrity-rollout.md`. Prepared 2026-08-30.

---

## 1. The caveats aren't twelve gaps — they're two root causes

The page reads as broken because roughly a dozen panels say some version of *"not computed"*, *"no data"*, *"not viable"*. That looks like twelve separate jobs. It isn't. It's one cascade with two sources:

```
UNCONFIRMED STATEMENT LINES ──┬─→ Ratio panels empty (Profitability, Growth,
  (14 pending in the queue)   │    Efficiency, Shareholder returns)
                              │         └─→ Quality & Growth pillars can't score
                              │
                              └─→ Valuation inputs missing ──┐
                                                             ├─→ Most methods "not viable"
COST OF EQUITY NOT COMPUTED ─────────────────────────────────┘        └─→ No credible fair value
  (no CBSL risk-free feed)          └─→ RIM / DDM / justified P/B          └─→ Ladder falls back
                                        all structurally impossible            to something unstated
```

**Fix those two and ~80% of the caveats disappear at once.** Neither is a UI problem.

### 1.1 Cost of equity — build it as a service, not a field

CoE is missing universe-wide, and for financials it isn't one input among many — it's the input the entire correct model family depends on. Build it once, versioned and dated:

```
CoE = risk_free(CBSL 10y or 1y T-bill, dated)
    + beta × equity_risk_premium(Sri Lanka)
    + size/liquidity premium (small, illiquid CSE names)
```

Store every component with its source and timestamp so any fair value can be traced back. Version it — when the risk-free moves, fair values across the whole universe move with it, and you need to be able to explain why.

### 1.2 The composite score is probably wrong in the *other* direction

This one matters more than it looks. AAF shows **29.6/100** while its ratio panels are empty. But the underlying company has ROE 24.3% and PBT up 203%. A genuine quality-and-growth score on those numbers would be strong, not bottom-quartile.

**The likely bug: unmeasured pillars are scoring zero instead of being excluded from the denominator.** Missing data is being silently counted as bad data.

```
WRONG:  score = Σ(pillar_scores) / 100          # unmeasured pillar contributes 0
RIGHT:  score = Σ(measured) / Σ(measured_max)   # unmeasured pillar is excluded
        coverage = Σ(measured_max) / 100        # and reported alongside
```

Display becomes: **`74 / 100 · coverage 45%`** with a note that 3 of 7 pillars are unmeasured. That is honest. `29.6/100` is not — it says "bad company" when the truth is "unmeasured company", and those two need to look completely different to a user making a decision.

Worth auditing across the universe: any name with a low composite *and* low coverage is currently being libelled by your own scoring engine.

### 1.3 The rest of the caveat inventory

| Caveat on screen | Root cause | Fix |
|---|---|---|
| "Cost of equity not computed" | No risk-free feed | §1.1 — CoE service |
| Ratio panels empty (×4) | Statement lines unconfirmed / unmapped | Finish line mapping; bulk-confirm queue |
| "Most methods not viable" | Downstream of both of the above | Resolves itself |
| Fair value shown anyway | No blocking rule | Verdict gate (previous doc, Part 4) |
| Price history chart empty | Query returns nothing, or render bug | Debug — it's rendering axes with no series |
| "More than one listed line" | No security master | Universe rollout, Layer 1 |
| Statement values vs "(LKR M)" header | Units mismatch | Universe rollout, Check 7 |
| Adjustment factor 1.0000000 | Corporate actions not applied | Universe rollout, Layer 3 |

---

## 2. What professional equity research leads with

Institutional research reports converge on the same front page, and it's nothing like the current layout. The cover carries **ticker, rating, price target, current price, market cap, date** — then an **investment thesis in three to five sentences**, which is reported to be the section institutional readers go to first, because it states *why the security is mispriced*. Valuation, catalysts, risks and the financial appendix follow behind it.

Mapped against your current page:

| Research convention | Your page today |
|---|---|
| Rating + target + current price, together, at the top | Price at top; verdict ~600px down; fair value ~3,000px down |
| Thesis in 3–5 sentences, first thing after the header | A narrative block ("What this tells you") at position 13 of 15 |
| Valuation range across methods, one chart | Split across three sections (ladder, fair value, scenarios) |
| Catalysts & risks as named sections | Absent |
| Peer comparison | Absent |
| Financial detail in an appendix | Mid-page, full-length, with action buttons |

The single biggest structural error: **the answer is at the bottom and the working is at the top.** Professional research inverts that, and so should this page.

---

## 3. Company page — add, remove, merge

| Section | Decision | Why |
|---|---|---|
| Multi-line warning paragraph | **Compress** → one chip + popover | It's a blocker, not an essay. Chip in the header, detail on click. |
| Identity metadata card | **Compress** → one line under the header | Sector, ISIN, listing date, free float — reference data, not decision data. |
| Price ladder (§26) | **Merge** into the price chart | A ladder disconnected from price history is half a chart. Draw the zones *behind* the price line. |
| Composite score, 7 panels | **Merge** → one emphasis bar + coverage badge | Seven small-text panels answer "which pillar is dragging?" worse than one chart. |
| Price history chart | **Fix + keep, promote** | Broken today. Once fixed with zone bands it becomes the page's primary chart. |
| OHLCV table | **Move** → Price & actions tab | Reference data. Nobody makes a decision from row 4 of an OHLCV table. |
| Corporate actions | **Keep, move** → Price & actions tab | Important, not primary. Surface *upcoming* ex-dates in the header instead. |
| Ratio accordions (×5) | **Merge** → sector KPI strip + trend small-multiples | Empty accordions are worse than absent ones. Show what exists; count what doesn't. |
| Cost of equity (§31) | **Move** → Valuation tab, as a model input | It's an input, not a finding. Its absence belongs in the blocker chip. |
| Valuation routing table | **Demote** → collapsed "show all methods" | Mostly "not viable" rows. The *chosen* method and its inputs are what matter. |
| Fair value (§16–26) | **Merge** into the football field chart | See §4. |
| Scenarios (§21) | **Merge** into the football field chart | Bear/base/bull *is* a range — draw it as one. |
| "What this tells you" | **Promote to the top**, rewrite as thesis | Research says this is what gets read first. It's currently 13th. |
| Statement lines + Confirm | **Move** → Data quality tab | Data operations don't belong interleaved with analysis. |
| "What this system cannot tell you" | **Move** → footer link | Important, read once. |
| **Investment thesis (3–5 sentences)** | **ADD** | The single most-read section in professional research. Currently absent. |
| **Peer comparison** | **ADD** | Relative valuation is half of "is this the right price". Required by spec §5, absent from the page. |
| **Catalysts & thesis-breakers** | **ADD** | Spec §12. Without thesis-breakers there's no sell discipline. |
| **Quality × Value quadrant** | **ADD** | Spec §1 requires distinguishing "weak company + cheap price". A 2×2 does it instantly. |
| **Sector KPI strip** | **ADD** | Spec §7. For an LFC: NIM, NPL, CAR, cost-to-income, provision cover. Generic ratios miss the business. |
| **Liquidity & free float** | **ADD** | On the CSE this decides whether you can actually build or exit a position. Currently invisible. |

**Net: 15 stacked sections → 6 above-the-fold blocks + 5 tabs.**

---

## 4. The new company page

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ← Companies   ASIA ASSET FINANCE PLC   AAF.N0000 ▾   LFC · Fitch A+(lka) │ sticky
│ LKR 49.10 ▼2.6%   ⛔ NO VERDICT · 2 blockers   Ex-rights 12 Sep   06:00   │
├──────────────────────────────────────────────────────────────────────────┤
│ THESIS                                                                    │
│ Muthoot's Sri Lankan arm. Gold-loan led, PBT +203%, ROE 10→24% in three   │
│ years. Trades ~1.3× pro-forma book. The question is not quality — it's    │
│ whether a 24% ROE survives the LKR 1.5bn equity raise now diluting it.    │
│ ⛔ No fair value: cost of equity unavailable, 14 statement lines pending.  │
├────────────────────────────────┬─────────────────────────────────────────┤
│ WHAT IT'S WORTH                │ QUALITY × VALUE                          │
│  ┌── football field ─────────┐ │      cheap │  ● AAF                      │
│  │ Justified P/B  ├───┤      │ │            │      (good & fairly priced) │
│  │ Residual inc.  ⛔ blocked  │ │  ──────────┼──────────                   │
│  │ P/E multiple     ├──┤     │ │            │                             │
│  │ Peer P/B       ├────┤     │ │       weak │ strong  →  quality          │
│  │ 52-week range ├──────┤    │ │                                          │
│  │           ▲ price 49.10   │ ├─────────────────────────────────────────┤
│  └───────────────────────────┘ │ SCORE  74/100 · coverage 45% ⚠           │
│  Range 37–56 · 2 of 6 methods  │ Quality ▓▓▓▓▓▓▓░ 21/25                   │
│  blocked                       │ Valuation ▓▓▓▓░░░░ 13/25                 │
│                                │ Growth ▓▓▓▓▓▓▓▓ 15/15                    │
│                                │ Financial ░░░░░░░░ unmeasured            │
├────────────────────────────────┴─────────────────────────────────────────┤
│ PRICE & ZONES                                        [1Y] [3Y] [5Y] [Max] │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │ ░░░ expensive ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░╱‾‾╲░░░░░░░░░░░░ │    │
│  │ ▒▒▒ fair ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒╱‾‾╲╱‾‾‾    ‾╲▒▒●49.10   │    │
│  │ ███ buy ██████████████████╱‾╲╱‾‾‾‾╲╱‾‾‾                          │    │
│  │ ███ strong buy ███╱‾‾╲╱‾‾‾                                       │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│  ▁▁▃▁▂▅▁▁▂▁ volume (own panel, shared x-axis — never a second y-axis)     │
├──────────────────────────────────────────────────────────────────────────┤
│ [Overview] [Valuation] [Financials] [Price & actions] [Data quality ⚠3]   │
└──────────────────────────────────────────────────────────────────────────┘
```

Above the fold, in reading order: **what is it → what's it worth → is it good → is now the price.** Everything else is a tab.

---

## 5. The chart set

Form chosen by the data's job, per the `dataviz` heuristic — then checked against the anti-patterns.

| # | Chart | Job | Form | Anti-pattern avoided |
|---|---|---|---|---|
| 1 | **Football field** — one horizontal range bar per valuation method, current price as a vertical rule | Compare ranges across methods; show *disagreement* | Range bars, one hue, blocked methods shown as struck-through rows | Replaces a single false-precision number. Blocked methods stay visible — absence is information. |
| 2 | **Price with zone bands** | Trend over time against thresholds | Line + shaded bands behind it | Volume gets its **own panel** sharing the x-axis — never a dual y-axis (the #1 chart mistake). |
| 3 | **Score breakdown** | "Which pillar drags the score?" | **Emphasis** bars — weakest pillar in accent, rest gray, unmeasured as an empty track | Not 7 categorical hues; not a gauge; not a donut. The story is one pillar, so emphasis. |
| 4 | **Peer scatter — ROE (x) vs P/B (y)** with fitted line, this company highlighted | "Does it deserve its premium/discount?" | Scatter, emphasis colouring (accent + gray) | The definitive relative-valuation chart for lenders. Emphasis keeps it inside the 3-series all-pairs cap. |
| 5 | **Ratio trends — small multiples** | Direction of travel on ROE, NIM, NPL, BVPS | 4 tiny one-hue line charts, shared time axis | Different scales → small multiples, never dual-axis. Spec §3: trends beat point ratios. |
| 6 | **Upside/downside** | Distance to fair value, signed | Diverging bar centred on fair value | Polarity → diverging, warm/cool poles, neutral midpoint. |

**Explicitly not built:** gauges or speedometers for the score, donuts for anything, a rainbow heatmap, a number on every data point, dashed gridlines, dual-axis price+volume. Each is on the anti-pattern list, and on a page this numeric they cost comprehension.

Every chart ships with a hover tooltip and a table view — an HTML chart is interactive by default, and the table view is what makes the numbers auditable, which is the whole premise of the product.

---

## 6. Homepage — what an investor sees in one glance

The homepage's job is **not** "what's happening in the market." It's *"where is price wrong today, and can I trust that answer."*

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Today                                        Friday 30 Aug · run 06:00 ✓ │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░  248 clean · 41 provisional · 23 quarantined     │
├──────────────────────────────────────────────────────────────────────────┤
│ 3 DECISIONS TODAY                                                         │
│ ▲ LWL.N  entered Strong Buy — 41% below fair value, score 88     [open →] │
│ ▼ JKH.N  left Buy → Exit — valuation stretched, ROE falling      [open →] │
│ ⚠ WLTH.N thesis breaker fired — leverage rising 3 quarters       [open →] │
├──────────────────┬──────────────────────┬────────────────────────────────┤
│ PORTFOLIO        │ MARKET VALUATION     │ MACRO → VALUATIONS             │
│ 76,122           │ ASPI 14,208 ▲0.4%    │ Policy rate 7.50% ▼50bp        │
│ ▲ +1.3%          │ Mkt P/E 11.8×        │ → CoE falls ~40bp              │
│ 2 need attention │ ▓▓▓▓▓▓░░░░ 62nd pctl │ → fair values ↑ on 14 rate-    │
│                  │ vs own 10y history   │   sensitive names       [see →] │
├──────────────────┴──────────────────────┴────────────────────────────────┤
│ IS THE MARKET CHEAP?              │ WHERE IS VALUE BY SECTOR?            │
│  price ÷ fair value, 248 names    │  median discount to fair value       │
│    ▁▂▅█▇▄▂▁                       │  Banks      ████████ -22%            │
│   0.5  1.0  1.5                   │  LFC        ██████ -17%              │
│   ▲ median 1.06  ● your holdings  │  Plantation ███ -8%                  │
│                                   │  Hotels     ▌+4%  (premium)          │
├───────────────────────────────────┼──────────────────────────────────────┤
│ BEST RISK-ADJUSTED (clean only)   │ POSITIONS NEEDING ATTENTION          │
│ 1 LWL.N   88  FV 70.0  +59% ▓▓▓▓  │ WLTH.N  Exit    -34%  thesis broken  │
│ 2 CBNK.N  84  FV 10.0  +36% ▓▓▓   │ EAST.N  Exit    +53%  take profit?   │
│ 3 KZOO.N  81  FV 14.5  +69% ▓▓▓▓  │ JKH.N   Exit     -2%  ROE falling    │
├──────────────────────────────────────────────────────────────────────────┤
│ CHANGED SINCE YESTERDAY   4 verdict changes · 2 filings · 1 ex-date ▸     │
└──────────────────────────────────────────────────────────────────────────┘
```

### What's deliberately different

**The trust bar comes first.** A thin strip, not a card. Everything below it is worthless if it's red, so it's the first thing on the page — but it's one line, because on a good day it deserves one line.

**"3 decisions today" is the hero, not a market summary.** The product exists to tell you when price is wrong. That belongs above everything else. Most days it will be empty — *"Nothing needs a decision today"* is a legitimate and valuable answer, and it should feel calm rather than broken.

**Market P/E as a percentile of its own history, not a level.** "11.8×" means nothing on its own. "62nd percentile of its own 10-year range" tells you whether the whole market is expensive — the macro question a value investor actually has, and nothing else on the site currently answers it.

**Macro is expressed as its effect on fair value, not as a rate.** "Policy rate 7.50%" is trivia. "→ CoE falls 40bp → fair values rise on 14 rate-sensitive names" is the mechanism, and it's exactly the macro-to-company translation spec §6 asks for.

**Universe valuation histogram.** Distribution of price ÷ fair value across the clean universe, with your holdings marked. One picture answering "is the market cheap, and where do I sit in it."

### One deliberate deviation from your spec

**Top gainers / top losers / most active are cut from the homepage** (spec §17 lists them). They're trading widgets: they reward momentum and volatility, which is the opposite of what this system is for, and they compete for attention with the decisions list. They belong on a Market tab for the days you want them.

Flagging it explicitly so you can overrule me — but I'd argue a value platform that opens on "biggest movers" is quietly training you to chase.

---

## 7. Design tokens — dark, validated

Direction, in four words: **quiet institutional terminal.** Near-black, one accent, colour reserved for state.

```css
:root {
  /* surfaces — three levels, no more */
  --surface-0: #0d0f10;   /* page */
  --surface-1: #14171a;   /* card */
  --surface-2: #1b1f23;   /* raised: table header, popover */
  --border:    #262b30;   /* hairline, 1px, never dashed */

  /* ink */
  --text-1:    #e8eaed;   /* 14.93:1 — primary, all numerals */
  --text-2:    #9aa3ab;   /*  7.03:1 — labels, secondary */
  --text-3:    #7d858c;   /*  4.80:1 — muted, still AA */

  /* state — never decorative, never anything else */
  --pos:       #3fae7a;   /*  6.47:1 — gain, buy zone */
  --neg:       #e0664a;   /*  5.29:1 — loss, exit zone */
  --blocked:   #d9a441;   /*  8.00:1 — data blocked. AMBER, NOT RED. */
  --accent:    #3987e5;   /*  4.94:1 — emphasis, links, focus ring */
}
```

All ratios measured against `--surface-1` with the contrast checker, not eyeballed. Every one clears WCAG AA for normal text.

**Rules that carry across every screen in the app:**

- `font-variant-numeric: tabular-nums` on every numeric cell, right-aligned. Cheapest legibility win available.
- Colour means state, nothing else. Gain/loss and zone only — never decoration, never series identity.
- Never colour alone: `▲`/`▼` beside every gain/loss, an icon on every status badge.
- **Blocked is amber, not red.** Missing data is not bad news, and it must never look like a sell signal. This distinction is the difference between a user trusting the system and second-guessing it.
- 4/8px spacing scale. Cards 24px padding, 16px gaps, tables 12px cell padding. Nothing hand-tuned.
- One type scale, one family, weight and size for hierarchy. Body ≥ 16px; numerals may go to 14px given tabular alignment.
- Motion 150–250ms with easing, on state change only. Respect `prefers-reduced-motion`.

---

## 8. Component states

The gap between a demo and a product is that the demo only draws the happy path. Every data-bearing component needs five:

| State | Treatment |
|---|---|
| **Loading** | Skeleton at the final layout's dimensions — never a spinner over a collapsing card, never a blank flash |
| **Empty** | Say what to do about it, not "no data". *"No peers mapped for this sector — assign peers →"* |
| **Blocked** | Amber, names the blocker, links to the fix. *"Fair value unavailable — cost of equity not computed."* |
| **Provisional** | Renders normally with an amber hairline border + tooltip. Numbers shown, conviction capped. |
| **Error** | Distinct from empty and blocked. Something broke; say so and offer a retry. |

Plus the basics that are easy to skip: visible focus rings on everything keyboard-reachable, 44px touch targets, semantic `<button>`/`<a>`/`<th>`, and every table with a real header row so a screen reader can navigate it.

---

## 9. Build order

**Backend first — the UI can't fix missing numbers**

1. Cost of equity service (unblocks the entire correct model family, universe-wide)
2. Fix the scoring denominator — exclude unmeasured pillars, publish coverage
3. Finish statement-line mapping; bulk-confirm the queue
4. Debug the empty price history chart

**Then the company page**

5. Sticky header + thesis block promoted to the top
6. Football field replacing ladder + fair value + scenarios (three sections → one chart)
7. Price chart with zone bands; volume as its own panel
8. Tabs; move OHLCV, statement lines, routing table off the main page
9. Score emphasis chart + coverage badge
10. Peer scatter, quality×value quadrant, sector KPI strip

**Then the homepage**

11. Trust bar + decisions hero
12. Three stat tiles with the macro→valuation translation
13. Universe valuation histogram + sector discount bars
14. Opportunities / attention tables

**Then the system**

15. Roll the token set and component states across Portfolio, Opportunities and Company so the app reads as one product

---

## 10. The one-line test

Before shipping any section, ask: *if I deleted this, would I be worse at deciding whether today's price is the right price?*

If no, it belongs in a tab. If it's still no, it belongs in the appendix. Almost nothing genuinely belongs above the fold — which is exactly why the things that do should be unmissable.

## Sources

- [Equity Research Report: Samples, Tutorials, and Explanations — Mergers & Inquisitions](https://mergersandinquisitions.com/equity-research-report/)
- [What Is an Equity Research Report? Format, Sections, and How to Write One — Valuation Master Class](https://valuationmasterclass.com/equity-research-report/)
- [Football Field Analysis — Financial Edge Training](https://www.fe.training/free-resources/valuation/football-field-analysis/)
- [The Football Field Chart: How Bankers Synthesize Valuation](https://ibinterviewquestions.com/guides/valuation-investment-banking/football-field-chart-how-bankers-synthesize-valuation)
- [Investment Dashboard UX Design — Lollypop](https://lollypop.design/blog/2026/may/investment-dashboard-ux-design-guide/)
- [Fintech Dashboard Design: 9 Real Products, Analyzed — AdminLTE](https://adminlte.io/blog/fintech-dashboard-design-examples/)
- Internal: `ui-ux-mastery` and `dataviz` skills (form heuristic, anti-patterns, contrast validation)

*Fourth in the series with `portfolio-page-redesign-spec.md`, `scoreboard-queue-redesign-spec.md`, `aaf-factcheck-and-company-page-redesign.md`, and `cse-universe-integrity-rollout.md`.*
