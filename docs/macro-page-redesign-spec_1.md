# Macro Page Redesign — CSE Alpha Engine

A UX audit of the current Macro screen + a concrete redesign spec. Same goal as the rest of this series: same dark, calm palette, but organized so the regime call, the one number that actually moves your allocation, and the caveats that qualify it are all visible in the first five seconds — not somewhere in three screens of prose.

Design decisions follow the `ui-ux-mastery` and `dataviz` skills, and reuse the contrast-validated dark tokens from `company-page-and-homepage-redesign.md` rather than inventing a new palette for this page.

Companion to `portfolio-page-redesign-spec.md`, `scoreboard-queue-redesign-spec.md`, `company-page-and-homepage-redesign.md`, and `data-health-diagnosis-and-experiment-protocol.md` — sixth in the series, same design system throughout.

---

## 1. What's actually wrong (evidence, not opinion)

Diagnosed straight from your screenshot, mapped to root causes so fixes target the cause, not the symptom.

| # | What you see | Root cause | Why it matters |
|---|---|---|---|
| 1 | A full paragraph of methodology ("What's real on this screen, and what's still missing") is the *first* thing on the page, before a single live number appears | Explanatory copy is treated as primary content instead of a footnote/tooltip | This is the exact "answer at the bottom, working at the top" problem found on the Company page. The one thing you open this page to learn — what regime are we in, and can I trust it — is pushed a full screen down by prose. |
| 2 | Section titles carry a bare number in parentheses — "Regime gauge (531)", "The hero spread (529)", "Sector sensitivity matrix (333)" | A sample size / observation count, rendered inline with no label | Reads like a footnote marker or a rendering bug, not a stated sample size. A number with no unit next to it erodes trust instead of building it — the opposite of what disclosing your N is supposed to do. |
| 3 | The regime probability is shown as three lines of text — "Risk-On 69.7%", "Transition 10.2%", "Risk-Off 20.0%" | A three-way probability distribution — the textbook case for a single segmented bar — has no chart at all | This is the single highest-value number on the page (*how confident is "Risk-On," really?*) and it currently takes reading three label:value pairs to absorb, instead of one glance at a bar. |
| 4 | The sector sensitivity matrix is a grid of roughly 60 sector-by-shock cells, and almost all of them read "N/A" in the same plain gray text as ordinary secondary labels | Statistically-insignificant, not-yet-tested, and genuinely-no-data are all rendered identically as "N/A" | Violates your own project's data-integrity principle (§18): the system must distinguish calculated, estimated, and unavailable data, never collapse them into one label. Visually, a matrix that's ~97% "N/A" reads as broken, not as rigorous — the opposite of the intended signal. |
| 5 | "Still missing from this gauge" — a genuinely important disclosure — sits mid-page, after the regime call, the momentum explainer, the consequence table, and the confidence section | Caveats are appended where they were written, not ordered by how much they should change your trust in the number above them | Same fix as the Portfolio and Company pages: a blocker needs to be seen *before* the number it qualifies, not three panels later, or you act on the number before you've read the caveat. |
| 6 | The hero spread's supporting line chart is small, cramped under a large bold number, with dense small-print caption text | Chart sized as an afterthought under the headline number, rather than built as a first-class chart for a "spread" shape (signed, has a meaningful zero, moves over time) | The chart form that this data calls for — a diverging area around a zero line — is exactly the one your `dataviz` skill would pick first, and it's currently the least-developed element in that card. |
| 7 | Sector indices render as a 21-row plain-text table with small arrow glyphs | This is a "compare a signed metric across ~20 categories" job — the definitional bar-chart case — kept as a table anyway | Finding the 3–4 sectors that actually moved today means reading all 21 rows. A sorted diverging bar makes the outliers visible without reading a single number. |
| 8 | The ASPI 12-month chart and the regime call above it are built as two unrelated sections | The chart and the regime analysis are separate widgets instead of one connected story, even though the system already knows the regime for every period it has classified | You have to mentally overlay "we're in Risk-On" onto the price chart yourself. The system could shade the regime history directly behind the price line. |
| 9 | The left sidebar repeats ASPI price, market P/E, and CBSL rate with no link back to the Macro content those numbers actually explain | Global stats and page content built as disconnected surfaces | Same issue flagged on the Portfolio page: a number and the thing it qualifies need to be near each other, not three panels apart. |

---

## 2. Design principles for this redesign

- **The answer comes before the working.** Regime call and hero spread lead the page; the methodology paragraph that currently opens it becomes a collapsible "How this is computed" drawer, one click away, not the first thing read.
- **Three distinct "no value" states, not one "N/A."** *Not significant* (tested, coefficient not distinguishable from zero), *not yet computed* (backend hasn't run this check), and *no data to test* (too few constituents) are three different facts and need three different visual treatments — never the same gray text. This is the same fix as `E0` in the data-health work, applied here instead of to the confirm queue.
- **Blocked is amber, not red — and it comes first.** The "still missing" disclosures move into one blocker strip at the top of the page, using the same `--blocked` amber token as every other page in this series. Missing validation is unfinished work, not a failure, and it must never visually read as a sell signal.
- **Every number that's shaped like a chart gets one.** A 3-way probability, a signed spread over time, a sector-by-shock matrix, and a 21-row ranked list are four of the most chart-shaped data types there are — each gets exactly one chart, chosen by the job the data is doing, per §4.
- **N-counts get a label, not a set of bare parentheses.** "(531)" becomes "based on 531 names" in a small caption, or moves into the methodology drawer entirely.
- **Same tokens, same components, one product.** Nothing new is invented here — the amber/muted-grey/pos/neg tokens, the tabular-numeral rule, and the badge components are pulled from `company-page-and-homepage-redesign.md` so this page reads as the same system as Portfolio, Opportunities, and Company.

---

## 3. New page structure (top to bottom)

```
┌────────────────────────────────────────────────────────────────────────┐
│ Macro                                              06:00 · 531 names ⓘ │ sticky
│ The regime, the variables, and what still isn't proven.                │
├────────────────────────────────────────────────────────────────────────┤
│ ⚠ 3 NOT YET VALIDATED                                                  │
│  Historical regime backtest not run · ARDL bounds test not performed ·  │
│  Gross exposure sizing not calculated                          [detail]│
├─────────────────────────────────┬──────────────────────────────────────┤
│ CURRENT REGIME                  │ THE HERO SPREAD                      │
│                                  │ Equity earnings yield − 364d T-bill  │
│  RISK-ON                        │                                       │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░  69.7%   │        −1.04pp                       │
│  ── Risk-On ── Transition ── Risk-Off ──                                │
│                                  │  ┌───────────────────────────────┐   │
│  Blended 50/50 of a Markov       │  │ · · · · · · zero · · · · · · │   │
│  switching model (2-state, daily│  │ ╱╲    ╱╲___          ╱╲      │   │
│  returns) and a 14-signal macro │  │╱  ╲__╱    ╲___    __╱  ╲___  │   │
│  composite.        [Details ›]  │  └───────────────────────────────┘   │
│                                  │  Market earnings yield      8.77%    │
│                                  │  364-day T-bill yield        9.81%   │
│                                  │  Bonds are paying more than stocks   │
│                                  │  earn — valuations tend to compress. │
├─────────────────────────────────┴──────────────────────────────────────┤
│ WHAT THIS REGIME IS DOING TO YOUR NUMBERS RIGHT NOW                     │
│  Margin of safety widened .......... +0.0%  (not yet applied)           │
│  Added to equity risk premium ...... +0.0%  (not yet applied)           │
├────────────────────────────────────────────────────────────────────────┤
│ SECTOR SENSITIVITY — where the regime actually bites          [ⓘ read] │
│                     Policy rate   T-bill yield   CCPI YoY   USD/LKR    │
│  Consumer Services      ·             ·             ·      ▓▓ −0.03p  │
│  Health Eq. & Services  ·             ·             ·      ▓▓ −0.04p  │
│  Banks                  ·             ·             ·          ·      │
│  ...11 more rows, hollow · = tested, not significant at p<0.05         │
│  4 sectors excluded — too few live constituents for a return series    │
├────────────────────────────────┬───────────────────────────────────────┤
│ SECTOR PERFORMANCE TODAY        │ ASPI, LAST 12 MONTHS                  │
│  Retailing        ▓▓▓▓▓▓ +1.7%  │  Risk-On ░░░░░░░░░░░  Risk-Off ▓▓▓▓  │
│  Real Estate      ▓▓▓▓▓ +1.1%   │        ╱╲___╱╲                       │
│  Materials        ▓▓▓▓  +1.0%   │       ╱      ╲___╱‾╲___              │
│  ...                            │                                       │
│  Software & Svcs  ▓▓  −2.1%     │  shaded bands = classified regime     │
├────────────────────────────────┴───────────────────────────────────────┤
│ [ How this page is computed ▾ ]   (methodology + confidence, collapsed) │
└────────────────────────────────────────────────────────────────────────┘
```

Reading order, top to bottom: *what regime are we in and how sure are we → what does that mean for pricing right now (the spread) → is that trust warranted, or are there gaps (blocker strip, above both) → where does it actually show up (sector sensitivity, sector performance) → the underlying chart, in context (ASPI with regime shading) → how was any of this computed, for the one time you want to check.*

---

## 4. Every chart, and the job it's doing

| # | Chart | Replaces | Job | Form | Anti-pattern avoided |
|---|---|---|---|---|---|
| 1 | **Regime segmented bar** | Three text lines: "Risk-On 69.7% / Transition 10.2% / Risk-Off 20.0%" | Show composition of a fixed 3-state distribution | One horizontal stacked bar, fixed state order, status hues (positive/amber/negative) | Not a donut (three states rendered as a strip reads faster and stacks cleanly with the "hero" number above it); not a gauge/speedometer, which would dress up a single percentage as more precise than it is. |
| 2 | **Hero spread — diverging area chart** | The current small cramped line chart | Show the sign, magnitude, and trend of a quantity with a meaningful zero | Area chart, zero baseline, shaded warm above / cool below (or vice versa, matched to "equities cheap vs. rich"), 2px line | Not a bare number with a decorative sparkline; not dual-axis — the two component yields (earnings yield, T-bill yield) feed one computed spread series, they don't get two y-axes. |
| 3 | **Sector sensitivity — sparse heatmap** | The current mostly-blank table of "N/A" cells | Compare a coefficient's sign and magnitude across two categories (sector × shock) while staying honest about what's untested | Colored cells only where p<0.05 (diverging hue by direction: hurt/help, opacity by magnitude); non-significant cells shown as a small hollow gray dot; excluded sectors shown as a separate muted row with a tooltip reason | Not a rainbow heatmap; critically, does **not** conflate "tested, not significant" with "not tested" with "no data" — three visually distinct marks, matching the E0 fix from the data-health work. |
| 4 | **Sector performance — diverging horizontal bar** | The 21-row plain table with small arrows | Compare a signed % change across ~20 categories | Bars, warm/cool by sign, sorted by magnitude, turnover shown via bar opacity | Not a 21-row table for data whose shape is a textbook sorted bar chart; not color-only — every bar still carries its signed % label. |
| 5 | **ASPI, 12 months, with regime shading** | The current unshaded line chart | Show price trend in the context of the regime call made above it | Existing line kept as-is; add a low-opacity background band per classified regime period, sharing the same status hues as chart #1 | Volume/turnover, if added later, gets its own panel on a shared x-axis — never a second y-axis on this chart. |

Deliberately **not** built: a gauge for the regime probability, a donut for sector performance (20 slices is well past the point a donut stays readable), or a rainbow-scale heatmap for sensitivity — all on the anti-pattern list, and all would cost comprehension on a page this numeric.

Every chart ships with a hover tooltip and a "view as table" toggle, per the interaction rules in the `dataviz` skill — the raw numbers stay one click away for anyone who wants to audit them, which matters more on this page than almost any other, since its entire job is to be checkable.

---

## 5. Section-by-section: keep, compress, merge, promote

| Section | Decision | Why |
|---|---|---|
| "What's real on this screen, and what's still missing" (opening paragraph) | **Compress** → collapsible "How this is computed" drawer at the bottom | It's good, honest writing — it just doesn't belong as the page's first read. Move it where the Company page moved its statement-line detail: one click deep, not blocking the header. |
| "Regime gauge (531)" title | **Relabel** → "Current regime · based on 531 names" as a small caption, not a bare parenthetical | A number with no unit reads as a bug. A labeled caption reads as a disclosed sample size, which is the actual intent. |
| Regime probability list | **Merge** into the segmented bar (chart #1) | Same information, one glance instead of three lines. |
| "The two momentum regimes explained" | **Compress** → "Details ›" link under the regime card, opening the same methodology drawer | Useful once, not on every visit — matches how the Portfolio redesign treated the upload instructions. |
| "What this regime is already doing to every allocation" | **Keep**, restyle as a compact before/after stat row directly under the regime card | This is the one place the page currently states a real consequence (even if it's 0.0% today) — keep it visible, just smaller and closer to the number that drives it. |
| "Where confidence has and has not been established" | **Merge** into the methodology drawer | Important, read once — same treatment as "What this system cannot tell you" on the Company page. |
| "Sector fact-check (531)" | **Merge** into the sensitivity heatmap (chart #3) as its significant cells, with the p-values available on hover | Currently a separate two-row table repeating information the matrix below it is trying to show — one chart instead of a table plus a matrix telling two halves of the same story. |
| "Still missing from this gauge" | **Promote** → blocker strip at the very top of the page, next to the header | Same fix as Portfolio's "Needs Attention" and Company's blocker chip: caveats that change how much you should trust the page need to be seen before the numbers, not after. |
| "The hero spread (529)" | **Keep and promote** — paired with the regime card as the two above-the-fold hero blocks | This is arguably the single most decision-relevant number on the page (bonds vs. stocks) and currently gets no more visual weight than the paragraph next to it. |
| "Sector sensitivity matrix (333)" | **Rebuild** as the sparse heatmap in §4 | See row above; also relabel the title the same way as the regime gauge. |
| "Read this matrix carefully" | **Keep**, shortened to a one-line caption + ⓘ that expands the full explanation | The caution is legitimate and important; it doesn't need to be a full paragraph sitting permanently on the page. |
| "ASPI last year" | **Keep, enhance** with regime shading (chart #5) | Turns an isolated price chart into the one place price and regime are shown together. |
| "Sector indices" table | **Rebuild** as the diverging bar chart in §4, with a "view as table" toggle | See §1 row 7 and §4 row 4. |
| Sidebar ASPI / P/E / CBSL rate | **Keep**, add deep-links from each stat into the matching section on this page | Closes the gap flagged in §1 row 9 without removing anything that's already useful. |

---

## 6. Design tokens (reused, not reinvented)

Same contrast-validated dark palette as the rest of the app, carried over verbatim from `company-page-and-homepage-redesign.md` §7:

```css
:root {
  --surface-0: #0d0f10;   /* page */
  --surface-1: #14171a;   /* card */
  --surface-2: #1b1f23;   /* raised: table header, popover */
  --border:    #262b30;

  --text-1:    #e8eaed;   /* primary, all numerals */
  --text-2:    #9aa3ab;   /* labels, secondary */
  --text-3:    #7d858c;   /* muted, still AA */

  --pos:       #3fae7a;   /* Risk-On, gains, "help" shocks */
  --neg:       #e0664a;   /* Risk-Off, losses, "hurt" shocks */
  --blocked:   #d9a441;   /* Transition regime, not-yet-validated — AMBER, NOT RED */
  --accent:    #3987e5;   /* emphasis, links, focus ring */
}
```

**One addition specific to this page**, though it belongs everywhere the same conflation exists — the `--not-evaluated` token first named in the data-health work:

```css
  --not-evaluated: #4a4f55;  /* tested-not-significant AND not-yet-tested — hollow marks only */
```

This is what makes chart #3's three "no value" states (not significant, not yet computed, no data) render distinctly instead of collapsing back into the same gray "N/A" this redesign exists to fix. Not significant and not yet computed still need visually distinct marks from each other at the component level (§7) — the token just guarantees neither one is ever mistaken for `--neg`.

Carried-over rules: `font-variant-numeric: tabular-nums` and right-alignment on every numeric cell; color means state and nothing else; never color alone — every signed value keeps its `▲`/`▼` glyph or explicit sign.

---

## 7. Component states

| Component | State | Treatment |
|---|---|---|
| Regime segmented bar | Loading | Skeleton bar at final width, no spinner |
| | Populated | As designed in §4 |
| Hero spread chart | Loading | Skeleton chart frame, axis pre-drawn |
| | No history available | Muted empty frame: "Spread history not yet computed" — not a blank chart with no explanation |
| Sensitivity matrix cell | Significant (p<0.05) | Colored, filled, hover shows coefficient + p-value |
| | Tested, not significant | Small hollow `--not-evaluated` dot |
| | Not yet computed | Same hollow dot, distinct hover text: "Not yet tested" |
| | Excluded (too few constituents) | Entire row muted, hover explains why |
| Blocker strip | Any items open | Amber `--blocked`, expandable detail per item |
| | Nothing outstanding | Strip collapses to a single quiet green confirmation line, not just disappears — "0 open validations" is itself a useful, calm signal |
| Sector performance bars | Loading | Skeleton bars, final row count and heights reserved |
| | Data stale | Amber hairline on the whole panel + timestamp, same treatment as staleness elsewhere in the app |

---

## 8. Build order

**Now (cheap, high impact):**
1. Blocker strip at the top, pulling directly from the existing "still missing" and "confidence" copy — no new analysis, just relocation.
2. Regime segmented bar replacing the three text lines.
3. Relabel every bare `(N)` title into a captioned "based on N names/observations."
4. Collapse the opening methodology paragraph and the momentum-regime explainer into one "How this is computed" drawer.

**Next (moderate effort):**
5. Sensitivity matrix rebuilt as the sparse heatmap with three distinct no-value marks.
6. Hero spread chart upgraded to a proper diverging area chart with a real zero baseline.
7. Sector indices table rebuilt as the sorted diverging bar chart, with a table-view toggle.

**Later (needs new data plumbing, not just UI):**
8. Regime-shaded bands behind the ASPI chart — needs historical regime classifications stored per period, not just the current read.
9. Sidebar deep-links from ASPI/P/E/CBSL rate into their matching sections on this page.
10. Roll the `--not-evaluated` token and its three-state convention back onto the Data Health and Confirm Queue pages, so "not significant" vs "not yet tested" vs "no data" reads the same everywhere in the app, not just here.

---

## 9. Before / After summary

| | Before | After |
|---|---|---|
| First thing read | A paragraph of methodology | The regime call and the hero spread, side by side |
| Regime probability | Three text lines | One segmented bar |
| "Still missing" caveats | Mid-page, after ~2 screens of other content | A single blocker strip at the very top |
| Sensitivity matrix | ~97% "N/A" in plain gray text | A heatmap where every cell's state — significant, not significant, untested, excluded — looks different |
| Sector indices | 21-row plain table | Sorted diverging bar chart, table view one click away |
| Hero spread chart | Small, cramped, dense caption | A first-class diverging area chart with a real zero line |
| ASPI chart | Unrelated to the regime call above it | Regime-shaded, telling one continuous story |
| Section titles | Bare parentheses — "(531)", "(529)", "(333)" | Captioned sample sizes |
| "No value" cells | One gray label for three different facts | Three distinct marks: not significant, not yet tested, no data |

---

*Sixth in the series with `portfolio-page-redesign-spec.md`, `scoreboard-queue-redesign-spec.md`, `company-page-and-homepage-redesign.md`, `aaf-factcheck-and-company-page-redesign.md`, `cse-universe-integrity-rollout.md`, and `data-health-diagnosis-and-experiment-protocol.md`. Same design system, same principles — answer before working, blocked is amber not red, "not evaluable" is its own state, tabular numbers, one chart per idea. Prepared 2026-09-04.*
