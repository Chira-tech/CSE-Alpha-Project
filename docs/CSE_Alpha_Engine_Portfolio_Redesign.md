# Portfolio Page Redesign — CSE Alpha Engine

A UX audit of the current screen + a concrete redesign spec. Goal: same dark, calm palette, but organized so you can see "what needs my attention" in 5 seconds instead of reading a table row by row.

---

## 1. What's actually wrong (evidence, not opinion)

Diagnosed straight from your screenshot, mapped to root causes so fixes target the cause, not the symptom.

| # | What you see | Root cause | Why it matters |
|---|---|---|---|
| 1 | JKH.N0000's row is ~3x taller than LWL.N0000's row | Status tags ("Valuation stretched", "ROE falling"...) are stuffed inside the ticker cell and wrap freely | Row height becomes random. Your eye can't scan down a column because the grid keeps breaking. |
| 2 | Zone column shows "Stron accum", "Not y valued" | Fixed-width column, variable-length badge text ("Strong accumulate", "Data unavailable → Not yet valued") | Text is literally cut off — this reads as a bug, not a design choice, and undermines trust in the numbers next to it. |
| 3 | Zone badges look inconsistent (some filled, some outlined, some single word, some two words + an action button underneath) | No standardized badge component — each zone state was styled ad hoc | More visual noise per row than the row's actual information content. |
| 4 | Upload button + a full paragraph of explanation sit side-by-side in one thin row | Instructional copy treated as inline UI instead of a tooltip/help affordance | Wastes the most valuable row on the page (top of viewport) on text you'll read once, ever. |
| 5 | 15D / 30D / 45D returns are three lonely numbers floating under the summary card | Time-series data (returns over time) rendered as text instead of a chart | This is the single most chart-shaped data point on the page and it has no chart. |
| 6 | Every number in "Unrealised P&L" needs to be read individually to know if the portfolio is healthy | No portfolio-level rollups: no chart for allocation, no distribution of how many positions are in each zone | You have 9 positions with computed signals (Exit / Fair / Buy / Strong Accum) but nothing surfaces "3 of 9 positions are flashing Exit" — you have to notice it yourself. |
| 7 | No dividend income, no realized P&L, no sector allocation, no portfolio beta, no concentration risk anywhere on the page | These are explicitly required by your own project spec (§15 Portfolio Management) but not built into this screen yet | The page answers "what do I own and its live P&L" but not "is my portfolio dangerously concentrated" or "what has it actually returned me including dividends." |
| 8 | Data-freshness warnings ("EOD prices 7d ago", "CBSL macro series never run") live only in the left sidebar | Disconnected from the numbers they qualify | Per your own §18 data-integrity principle, a stale-price warning needs to sit next to the price it's warning about, not three panels away. |

---

## 2. Design principles for this redesign

Grounded in how professional financial products (Stripe, Wise, Bloomberg-style terminals) and dedicated investment-dashboard UX research handle this exact problem — dense, numeric, high-stakes data in a calm dark theme.

- **Color means state, nothing else.** Green/red are reserved exclusively for gain/loss and buy/sell zones. No decorative color. This is *already* mostly true in your app — keep it, just standardize it.
- **Numbers are tabular and right-aligned**, always, so digits stack into a readable column instead of a ragged left-aligned mess.
- **One chart per idea, not chart-for-chart's-sake.** You asked for charts "only if relevant" — correct instinct for a data-dense professional tool. Every chart proposed below replaces text that was already trying to describe a trend or a distribution — nothing decorative is added.
- **Lead with capital, not daily noise.** Total value and cost basis stay visually dominant; day-to-day P&L is present but not shouting — this avoids the anxiety-driven, panic-sell UX pattern that dashboards genuinely get flagged for.
- **Progressive disclosure.** Row-level detail (why is this stock flagged?) moves from "always visible and wrapping" to "one click / hover away" — the table becomes scannable, the reasoning is still one click deep, never hidden more than that.
- **Attention-first ordering.** Given you want to act on this fast (leverage over effort, decisions over browsing), the page leads with "what changed / what needs a decision," not with a static table.

---

## 3. New page structure (top to bottom)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Portfolio                                    [Upload holdings ⓘ]    │
│ What I own, and whether the reasons still hold.                     │
├─────────────────────────────────────────────────────────────────────┤
│  NEEDS ATTENTION (2)                                                 │
│  ⚠ WLTH.N0000 — Exit zone, down 34.4% from cost, thesis broken →    │
│  ⚠ EAST.N0000 — Exit zone, up 52.8% but valuation stretched →       │
├───────────────────────────────────┬───────────────────────────────┤
│ PORTFOLIO VALUE                    │ ALLOCATION                    │
│ 76,122.80  ▲ +1.3% (+991.67)       │   [donut: by holding | sector]│
│ ┌─────────────────────────────┐   │        ╭───╮                  │
│ │      ╱╲      ╱╲╱‾╲           │   │       │ • │  JKH  26%        │
│ │  ╱╲╱╲╱  ╲╱╲╱╲╱    ╲          │   │        ╰───╯  NTB  33%        │
│ │╱               ‾‾‾╲╱‾╲       │   │               CBNK 10%        │
│ └─────────────────────────────┘   │               +5 more         │
│ [15D] [30D] [45D] [YTD] [1Y]       │                                │
├───────────────────────────────────┴───────────────────────────────┤
│  COST        76,122.80  |  REALIZED P&L   +0.00  |  DIVIDEND YTD  0 │
│  BETA          1.08     |  TOP-3 CONCENTRATION   58%  ⚠ high        │
├─────────────────────────────────────────────────────────────────────┤
│ POSITIONS (9)                    [Sort: Nearest exit ▾] [Filter ▾] │
│ ─────────────────────────────────────────────────────────────────  │
│ Ticker      Qty   Avg    Live   Value      P&L         Trend  Zone │
│ JKH.N0000  1,000  20.22  19.80  19,800  ▬▬▬▬░ -2.1%    ⌐⌐⌐    Exit │
│            ⓘ 4 signals: valuation stretched, ROE falling...        │
│ ─────────────────────────────────────────────────────────────────  │
│ NTB.N0000     80  303.36 313.00 25,040  ░▬▬▬▬ +3.2%    ⌐⌐⌐    Fair │
│ ─────────────────────────────────────────────────────────────────  │
│ ... (consistent row height throughout, no wrapping)                │
├─────────────────────────────────────────────────────────────────────┤
│ As of 2026-08-30 · Fair value from §16–26 engine · blank = no data │
│ Prices 7d stale ⚠  ·  Macro series not yet run ⚠                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Every chart, and why it's earned its place

| Chart | Replaces | Why it's relevant here (not decorative) |
|---|---|---|
| **Portfolio value area chart** (with a faint cost-basis reference line, period toggle 15D/30D/45D/YTD/1Y) | The current lonely "15D −0.8% / 30D +1.8% / 45D −0.4%" text row | Those three numbers *are* a time series someone already computed. A line/area chart shows the shape of the journey (was it a steady climb or one volatile spike?) — the text can't. |
| **Allocation donut** (toggle: by holding ↔ by sector) | Nothing today — concentration is invisible | Directly answers your own spec's "concentration risk" requirement. A donut is the correct chart for "parts of a whole," and at 9 holdings it stays readable (a donut with 30+ slices would *not* be relevant — this is exactly the "only if relevant" judgment call). |
| **Inline diverging bar inside the P&L cell** (small horizontal bar, red left / green right of center, next to the % text) | The current plain colored +/− percentage text | Turns a column you have to *read* into one you can *scan* — outliers (WLTH at −34.4%) visually jump out without reading every row. |
| **12-week price sparkline per row** | Nothing today | Small, axis-less, "wordless" trend line. Cheapest chart to add, highest scan-value per pixel — this is the single best leverage-to-effort chart on this whole page. |
| **Zone-distribution strip** (thin horizontal stacked bar: how many positions are Exit / Fair / Buy / Strong Accum) | Nothing today | One glance answer to "is my book mostly healthy or mostly flashing exit," which today requires reading all 9 zone badges individually. |

Deliberately **not** adding: pie charts with many thin slices, 3D charts, gauges/speedometers for beta (a single number with a small colored threshold marker is clearer than a gauge), or a candlestick chart on this page (that belongs on the per-stock analysis page, not the portfolio overview) — these would be chart-for-chart's-sake and would violate the "only if relevant" instruction.

---

## 5. Positions table — the actual fix

The table is your highest-traffic surface, so this is where most of the redesign value is.

**Column grouping** (subtle vertical spacing, not hard borders, between groups so the eye parses in chunks):

1. **Identity** — Ticker (link) · a single small info icon that opens signals in a popover/drawer instead of inline chips
2. **Position** — Quantity · Avg price · Live price (right-aligned, tabular figures)
3. **Performance** — Live value · P&L (text + inline diverging bar) · 12-week sparkline
4. **Valuation** — Fair value · Zone (standardized badge, fixed width, never wraps)

**Fixing the specific bugs you're seeing:**

- **Row height:** move the status tags ("Valuation stretched," "ROE falling," etc.) out of the visible row entirely. Replace with a single `ⓘ 4 signals` affordance that expands inline or opens a side panel on click. Every row becomes the same height.
- **Zone badge:** one component, fixed width (e.g. 110px), text truncates to an abbreviation with the full label on hover rather than wrapping ("Strong Accum" not "Stron accum"). Severity conveyed by fill weight: filled = actionable now (Exit, Strong Accum), outlined = informational (Fair, Buy).
- **"Not yet valued" (PAP.N0000):** keep this exactly as-is philosophically — it's your data-integrity principle in action (§18, never silently invent a number) — just give it its own clearly muted, non-alarming badge style so it reads as "pending data" rather than an error state.
- **Sorting/filtering:** add a sort control defaulting to "nearest to exit zone" (soonest-action-needed first) rather than upload order — this is the outcome-first ordering: the position that needs a decision today should be at the top, not wherever it happened to load in the CDS export.

---

## 6. Color & type system (keep the palette, standardize the usage)

Your existing near-black background with muted green/red accents is already the right choice for a "psychologically non-triggering" financial tool — dark, low-saturation, no alarm-red flashing. Formalize it:

| Token | Use | Note |
|---|---|---|
| `--bg` near-black (`#0b0f10`-ish, as today) | Page background | Unchanged |
| `--pos` muted green | Gains, Buy/Strong Accum badges | Never used decoratively elsewhere |
| `--neg` muted red/orange | Losses, Exit badges | Pair with a ▲/▼ arrow glyph, not color alone (colorblind-safe) |
| `--neutral` gray | Fair/Hold badges, secondary text | |
| `--muted` low-contrast gray | "Data unavailable," stale-data warnings | Signals "pending," not "error" |
| Numeric font-feature: `font-variant-numeric: tabular-nums` | Every price/quantity/percent cell | This one CSS property fixes most of the ragged-column feeling you're seeing today |

---

## 7. Spacing/grid fix

- 8px baseline spacing scale for all card padding and gaps (16/24/32px multiples) — the current page mixes tighter and looser spacing between the summary card, the 15D/30D/45D row, and the table, which is what reads as "alignment doesn't look right."
- Cards get consistent internal padding (24px) and consistent gaps between cards (16px) across Summary, Allocation, Composition, and Positions sections.
- Table cell padding standardized vertically (12px) so — combined with the row-height fix in §5 — every row is visually identical in height.

---

## 8. What this closes from your own project spec

Straight from your project's §15 Portfolio Management requirements that this screen wasn't yet surfacing:

- Realized P&L → new stat tile
- Dividend income → new stat tile
- Sector allocation → donut toggle
- Portfolio beta → new stat tile
- Concentration risk → Top-3 concentration stat + allocation donut
- "Has the thesis changed" monitoring → the new **Needs Attention** strip at the top, generated from the same signal tags (Valuation stretched / ROE falling / Earnings deteriorating / Leverage rising) you're already computing per row but not yet rolling up

---

## 9. Build order (leverage-first — do these in order, not all at once)

**Now (cheap, high impact, ~an afternoon each):**
1. `tabular-nums` + right-align every numeric column
2. Standardize the Zone badge component (fixed width, no wrap)
3. Move status tags out of the row into an `ⓘ` popover — fixes row-height chaos immediately
4. Move the upload instructions into a tooltip/help icon, not inline text

**Next (moderate effort, high value):**
5. Portfolio value area chart replacing the 15D/30D/45D text
6. Sparkline column in the positions table
7. Needs Attention strip at the top (you already compute the underlying signals — this is a rollup view, not new analysis)

**Later (needs new data plumbing, not just UI):**
8. Allocation donut (by holding / sector)
9. Realized P&L, dividend income, beta, concentration stat tiles
10. Zone-distribution strip

---

## 10. Before / After summary

| | Before | After |
|---|---|---|
| Row height | Random, driven by tag wrapping | Fixed, identical across all rows |
| Zone label | Truncated ("Stron accum") | Fixed-width badge, never wraps |
| Returns (15D/30D/45D) | Three text numbers | One area chart with period toggle |
| "What needs action" | You read all 9 rows | Top-of-page attention strip, 2 items |
| Concentration risk | Invisible | Donut chart + Top-3 concentration stat |
| Dividend / realized P&L | Missing entirely | Two new stat tiles |
| Row-level reasoning | Inline chips (breaks layout) | One-click popover (layout stays intact) |
| Numeric alignment | Inconsistent | Tabular, right-aligned throughout |

---

*Prepared for the CSE Alpha Engine Portfolio screen, 2026-08-30. Sources consulted: [Investment Dashboard UX Design Guide — Lollypop](https://lollypop.design/blog/2026/may/investment-dashboard-ux-design-guide/), [Fintech Dashboard Design: 9 Real Products, Analyzed — AdminLTE](https://adminlte.io/blog/fintech-dashboard-design-examples/).*
