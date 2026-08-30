# Opportunities / Composite Scoreboard — Redesign, Speed Fix, and Confirm-Queue Plan

Three problems in one doc because they're actually one problem: the scoreboard is slow *and* unreadable for the same underlying reason — it's rendering everything, for everyone, every time, instead of showing you the 5 things you actually need to decide something today.

---

## 0. Do this first (highest leverage, lowest effort)

1. **Stop rendering the full AI-reasoning paragraph for every row on page load.** This alone is almost certainly your biggest load-time and readability win — see §2.
2. **Precompute scores on a schedule, not on request.** The dashboard should read finished numbers, never trigger a live DCF/technical/macro recompute when you open the page — see §2.
3. **Paginate or virtualize the table.** Nothing renders all ~300 CSE names as full DOM rows at once — see §2.
4. **Add a Top Insights strip.** 4-5 sentences, auto-generated from the data, above the table — see §1.

Everything else below is detail on *how*.

---

## 1. Composite Scoreboard — UI/UX redesign

### 1.1 What the current page is doing

From what you shared: the page is a long, single-column scroll of dozens of stocks, each followed by its own paragraph of AI-generated reasoning, stacked one after another. That's the "explainability" requirement from your own project spec working correctly *in principle* (every score has a "why"), but wired up in a way that turns a ranking tool into a document you'd have to read top to bottom to use. A scoreboard's entire job is comparison at a glance — a wall of paragraphs is the opposite of that.

### 1.2 The fix: table is primary, reasoning is on-demand

```
┌───────────────────────────────────────────────────────────────────┐
│ Opportunities                                    Last run: 06:00  │
│ Which CSE stocks offer the best risk-adjusted opportunity today.  │
├───────────────────────────────────────────────────────────────────┤
│ TOP INSIGHTS                                                       │
│ • Banking sector avg score +6 pts this week — rate-cut tailwind    │
│ • 3 new Strong Buy signals since yesterday: LWL, CBNK, KZOO        │
│ • JKH dropped Buy → Exit — valuation stretched, ROE falling        │
├───────────────────────────────────────────────────────────────────┤
│ Score distribution        │ Verdict mix          │ Sector heatmap  │
│  ▁▂▅▇▇▅▂▁ (histogram)      │ ▓▓▓░░░ SB·B·A·H·R·S  │ Bank ██ Cons ▓▓ │
├───────────────────────────────────────────────────────────────────┤
│ Rank Stock    Score        FairVal Price  Upside  Verdict  Sector │
│  1   LWL.N   ▓▓▓▓▓▓▓░░ 91  69.99   44.00  +59%   StrongBuy Bank   │
│  2   CBNK.N  ▓▓▓▓▓▓░░░ 88  10.04    7.40  +36%   Buy       Bank   │
│  3   KZOO.N  ▓▓▓▓▓░░░░ 84  14.50    8.60  +69%   Accumulate Cons  │
│  ...  [50 rows on screen, virtualized, sort/filter in header]      │
│  Row click → expands inline: score breakdown + AI reasoning        │
└───────────────────────────────────────────────────────────────────┘
```

**Score column:** replace the bare number with a small horizontal bar (0-100 fill) so relative strength is visible without reading digits — this is a "part of a whole vs. threshold" use of a chart, so it earns its place (unlike a gauge/speedometer, which would just be decoration for a single number).

**Row expansion, not row explosion:** clicking a row expands it in place (or opens a side panel) to show the score breakdown (Quality 23/25, Valuation 22/25, Growth 13/15...) as small horizontal bars, plus the AI reasoning paragraph, plus buy/sell zone. This is your existing per-stock explainability content — just moved from "always on, for all 300 stocks" to "on demand, for the one you clicked." Same information, one click away, page loads in a fraction of the time.

**Top Insights strip:** 3-5 auto-generated sentences above the table, computed from the score delta week-over-week, verdict changes, and sector averages. This directly answers your project's own questions #1 ("what's worth investing in") and #9 ("best risk-adjusted opportunity") without you having to scan the table yourself — the table is there for when you want to verify or go deeper, not as the only entry point.

**Score distribution histogram + sector heatmap:** these two charts answer "which sectors are becoming attractive" (project question) at a glance — a heatmap of average score by sector is the correct chart for "compare a metric across categories," and it's the one chart on this page doing work a table genuinely can't do as fast.

**Verdict badges:** same standardized, fixed-width badge component from the Portfolio redesign (Strong Buy/Buy/Accumulate/Hold/Reduce/Sell/Avoid) — reuse it here so the whole app reads as one system, not per-page ad hoc styling.

### 1.3 Table mechanics

- Default sort: Score descending (best opportunity first — outcome-first ordering).
- Filter bar: sector, verdict, market cap band, upside % threshold — matches your project's Stock Screener requirements (§17) and can double as that screen if it isn't separate.
- Tabular numerals, right-aligned, everywhere — same rule as the Portfolio redesign.
- Sparkline of score-over-4-weeks per row (optional, add after the core rebuild) — shows whether a stock is a *newly* attractive opportunity or has quietly been top-ranked for months.

---

## 2. Why the scoreboard "takes forever to load," and the actual fix

A composite score in your architecture (per your own project doc, §20) is the output of five separate engines — Fundamental, Valuation, Technical, Macro/Sector, Risk — feeding a Scoring/Ranking engine. That is expensive work: DCF runs, multiple-based valuations, technical indicator calculations across timeframes, macro overlays, for every company in the ranking.

**The likely root causes, in order of probable impact:**

1. **Scores are being computed live, on request.** If opening this page triggers those five engines to run in real time for every listed company, that's the dominant cost by far — this work does not belong on the request path of a page view.
2. **AI reasoning text is generated (or re-fetched) per row, per page load**, matching the "wall of paragraphs" symptom in §1 — LLM generation/retrieval for 80+ stocks on every visit is slow and largely redundant, since a company's thesis doesn't change minute to minute.
3. **No pagination/virtualization** — the DOM is holding every row's full markup (including full-length reasoning text) at once, which slows both the initial render and any scrolling/interaction afterward.
4. **No caching layer** between engine output and the page — even if computation isn't literally live, if there's no read-optimized store in front of the engines, every page load may still be doing more work than a simple row fetch.

**The fix, matched to those causes:**

| Cause | Fix |
|---|---|
| Live computation on request | Run the Scoring & Ranking engine on a **schedule** (e.g., nightly after market close, plus an event trigger on new financials/price data) and write results to a `scores` table/materialized view. The dashboard **only ever reads** from that table — never triggers a recompute itself. |
| AI text regenerated per load | Generate the reasoning paragraph **once per score run**, store it alongside the score, and only regenerate when the underlying inputs actually changed (new financials, new price zone, thesis-breaking event) — not on every page view. |
| Full DOM render | Paginate (50 rows/page) or virtualize (render only the ~15-20 rows in viewport, per §1.3) — this is a pure front-end fix, independent of the backend work above, and is the fastest one to ship. |
| No caching layer | Even with scheduled computation, put a lightweight cache (in-memory or a fast KV store) in front of the `scores` table read, since this is your most-visited page and the data changes at most once a day. |

**One more thing to surface, not hide:** show a **"Last computed: <timestamp>"** badge at the top of the page (as sketched in §1.2). Once scores are precomputed rather than live, staleness becomes a real property of the page — and per your own data-integrity principle (§18 of your project spec), that should be visible, not silent. This also removes any temptation to "fix slowness" by quietly serving half-stale data without telling you.

---

## 3. Confirm queue — a plan to actually clear it, not just display it better

You mentioned the queue backlog separately, and I don't have a clean screenshot of that specific screen to critique pixel-by-pixel the way I did for Portfolio — so this section is a general backend plan based on how a data-confirmation queue works in a pipeline like yours (Data Validation & Normalisation, per §20 of your project spec). Treat field names below as illustrative; send me a screenshot of that page and I'll make this exact.

**Why queues like this grow forever if you only work them by hand:** every item requires a human decision, but most items in a queue like this are the *same* decision repeated hundreds of times (e.g., "this is a duplicate, skip it" or "the new figure matches the old one, auto-confirm"). If every item — trivial or not — waits for a person to click it, the queue grows faster than one person can clear it, forever. The fix is upstream automation plus smarter triage, not a nicer list view.

**Concrete plan:**

1. **Auto-resolve the obvious cases.** If an incoming record is byte-identical (or within a defined tolerance) to what's already stored, auto-confirm it — never show it to you at all. This is very likely the single biggest volume reducer.
2. **Classify what's left by type, not FIFO.** Group into buckets like *duplicate job runs*, *conflicting values needing a source-of-truth decision*, *missing linkage keys* — and surface counts per bucket so you can see where the backlog actually is, not just its total size.
3. **Bulk actions.** If 40 items are all "duplicate company job run, same source, same value" — let one click confirm all 40, not 40 individual clicks. This is usually the fastest way to burn down an existing backlog without writing new resolution logic.
4. **Fix it at the source.** For each recurring bucket, trace it back to the pipeline stage generating it (a scraper re-running on the same file, a join key that's ambiguous between two data sources) and fix that stage so the item never reaches the queue in the first place. A queue that regenerates itself every night is a symptom, not the disease.
5. **Age-based visibility, not silent accumulation.** Flag anything sitting unconfirmed past a threshold (e.g., 7 days) distinctly — old unconfirmed items are exactly the kind of "silently stale" data your own §18 principle says should never be hidden.
6. **A burn-down number on the page itself.** "Queue: 340 → 12 this week" is the kind of measurable-progress signal you specifically value — put it at the top of that screen so clearing the backlog is visibly working, not just theoretically working.

---

## 4. Summary — what ties all three together

The scoreboard is slow because it computes and renders everything live, for everyone, on every visit. The scoreboard is hard to read for the identical reason — it shows everything, for every stock, all the time, instead of leading with the 3-5 things that actually changed. And the confirm queue keeps growing for the same underlying shape of problem — every item gets full manual attention instead of the 90% that are the same trivial decision being auto-resolved. The fix in all three cases is the same move: **decide once, upfront, what's routine — and show the human only what's actually a decision.**

---

*Companion to the Portfolio page redesign (`portfolio-page-redesign-spec.md`) — same design system, same principles (color = state, tabular numbers, progressive disclosure, attention-first ordering), applied to the Opportunities/Scoreboard screen and the confirm-queue backlog. Prepared 2026-08-30.*
