# Mobile Responsive Layer — Implementation Spec

**For:** Claude Code, working directly in the CSE platform repo
**Goal:** Add a fully responsive mobile/tablet experience **without changing the existing desktop UI in any way.** Desktop stays pixel-for-pixel identical above the breakpoint. Everything below is additive.

Companion to the existing redesign specs in this project (`CSE_Company_Page_And_Homepage_Redesign.md`, `CSE_Alpha_Engine_Portfolio_Redesign.md`, `CSE_Alpha_Engine_Scoreboard_Queue_Redesign.md`, `macro-page-redesign-spec_1.md`) — same design tokens, same component-state model, same dark "quiet institutional terminal" theme. This doc only adds the responsive layer on top.

---

## Corrections after checking against the real codebase (2026-09-05)

This section supersedes the parts of the doc below that assumed things not actually built. Read this first.

- **Stack:** plain React 18 + Vite + hand-written CSS (`frontend/src/index.css`, `frontend/design-tokens.css`). No Tailwind, no CSS-in-JS, no table or chart library, no router (screens switch via local `useState`, not URL routes) — so "page" below means a screen component, not a route.
- **Nav — do not build a bottom tab bar.** `index.css` already collapses the 240px sidebar into a horizontal, scrollable top bar below 1024px (`.rail` becomes `flex-direction: row; overflow-x: auto`), showing all 8 destinations. `frontend/src/nav.ts` states an explicit product principle: every destination stays visible, even unbuilt ones — hiding items behind a hamburger/"more" menu would violate that. Per this doc's own ground rule ("extend, don't replace"), the mobile work here **extends that existing top bar** (bigger touch targets, scroll edge-fade, no items removed) instead of replacing it with the 4-5-item bottom bar §2 originally sketched.
- **Company page has no tab strip yet.** The Overview/Valuation/Financials/Price & actions/Data quality tabs, football-field chart, peer scatter and score-emphasis bars in §5's table are only proposed in the redesign doc — `CompanyScreen.tsx` is still one long scroll, and none of those charts exist in code (real ones: `PriceLadder`, `CompositeScoreBar`, `PriceHistoryChart`, `FairValueRange`, `TornadoChart`). Build order item 3 (§8) needs that desktop redesign to land first; until then, treat the company page as single-column reflow only, no tab-strip work.
- **Badge labels are wrong.** §4b says "keep the Actual/Calculated/Estimated/Forecast badges" — the real provenance tiers (`ProvenanceChip.tsx`) are **R=Reported, D=Derived, N=Normalised, E=Estimated, F=Forecast, A=AI-assisted, -=Unavailable**. Card transforms must keep these tiers, not the invented labels.
- **No "Screener" page.** It's merged into `OpportunitiesScreen.tsx` (Opportunities), which has no filter sidebar at all today — so §8 step 4's "collapse filters into a bottom sheet" is new UI, not a mobile transform of anything existing. Same file also covers "Scoreboard."
- **Charts are already fluid, mostly.** Every chart is hand-written inline SVG (`viewBox` + `width: 100%`), so container-width overflow (§5's stated "single most common cause") isn't the real risk. The real risk: internal font-size/stroke-width is fixed inside the `viewBox` (e.g. 10px chart labels), so on a narrow phone the whole chart scales down together and labels can render nearly illegible. Fixing that needs a per-chart responsive font/stroke variant (real component work, screen by screen) — flagged here as a known follow-up, not done in this pass to avoid touching desktop rendering of the same SVG.
- **Page file names for the real build order:** Homepage → `TodayScreen.tsx`, Company → `CompanyScreen.tsx`, Opportunities/Scoreboard/Screener → `OpportunitiesScreen.tsx`, Portfolio → `PortfolioScreen.tsx`, Macro → `MacroScreen.tsx`.

---

## 0. Ground rule, read first

**Mobile is not a shrunk desktop. It's a different context, done additively.**

- Never write logic that removes or alters desktop behavior. Every change here is scoped behind a breakpoint (media query) or a mobile-only component variant that renders in parallel to the existing desktop one.
- Before touching any file, check whether it already has responsive rules. If it does, extend them — don't replace.
- After every change, verify the desktop view (≥1024px) is byte-for-byte the same as before. If a diff shows a change to a desktop-scoped rule, that's a bug, not a refactor.
- Ship page by page, not as one giant PR. Order is in §8.

---

## 1. Breakpoints

Use content-driven breakpoints, not device names. These four cover this app's actual density cliffs (dense tables, multi-column charts, sticky headers):

```css
/* Mobile portrait   : 320–480px  — default, no media query needed */
/* Mobile landscape / small tablet : 481–767px */
@media (min-width: 481px) { }

/* Tablet portrait   : 768–1023px — where 2-column layouts become viable */
@media (min-width: 768px) { }

/* Desktop           : 1024px+    — existing layout, UNCHANGED */
@media (min-width: 1024px) { }
```

Author mobile-first: base styles = mobile (320–767px), then layer up with `min-width` media queries. This means the *existing* desktop CSS should end up wrapped in `@media (min-width: 1024px)` (or gated behind an equivalent class/container query) rather than being the default — but the computed result at ≥1024px must match today's rendering exactly. If the codebase currently isn't mobile-first, do this as a mechanical wrap, not a rewrite: move each desktop rule under the 1024px query verbatim, then build the new small-screen rules underneath as the new default.

Reasoning: BrowserStack's 2025/2026 guidance and current device-usage data show breakpoints should trigger "whenever the content becomes harder to read," and the most common real widths in the wild are 360, 390, 393, 412px (phones) and 768–1024px (tablets) — so those are the widths to actually test at, not just the breakpoint edges.

---

## 2. Navigation

Desktop keeps its existing sidebar/topnav exactly as-is.

Mobile (< 768px):
- Replace the sidebar with a **fixed bottom tab bar**, 4–5 destinations max: Home, Screener, Portfolio, Macro, (Alerts if it exists as top-level today). Icon + label, 44×44pt minimum touch target, current tab visually distinct via the existing `--accent` token, never color alone (also underline or fill).
- Anything not in the bottom bar (settings, data-quality tools, less-used pages) moves behind a hamburger/menu icon in the header, not the tab bar.
- Page-level sub-navigation (e.g. the company page's tab strip: Overview / Valuation / Financials / Price & actions / Data quality) becomes a horizontally-scrollable pill/tab row directly under the sticky header — same tabs as desktop, just scrollable instead of all-visible, with a subtle edge-fade to signal there's more.

## 3. Sticky headers

Desktop's sticky header pattern (ticker, price, verdict chip, key dates) is good UX and should carry to mobile, just condensed:

- Keep on one line if possible: ticker + price + verdict badge. If the verdict chip or date info doesn't fit, it drops to a second sticky line rather than disappearing — never hide the verdict/blocker state, that's the whole point of the "trust bar" pattern already in the spec.
- Height budget: sticky header + tab strip should stay under ~112px combined on mobile so it doesn't eat the viewport.

## 4. Tables (statement lines, OHLCV, screener, ranking tables, peer comparison)

This is the highest-risk area — most financial dashboards get this wrong by just adding horizontal scroll and calling it done. Two different table types in this app need two different treatments:

### 4a. Comparison/ranking tables (Screener, Opportunity Ranking, Scoreboard) — **sticky-column scroll, not cards**

Rows here are meant to be scanned and compared against each other (rank, score, upside %). Turning them into stacked cards breaks exactly the comparison the table exists for. Instead:

- Freeze the leftmost column (ticker/company name) with `position: sticky; left: 0`, same background as the row so scrolled columns pass underneath cleanly.
- Sticky header row stays fixed vertically (`position: sticky; top: <header height>`) so column labels never scroll away.
- Everything else scrolls horizontally. Add `-webkit-overflow-scrolling: touch` and `scroll-snap-type: x proximity` so it doesn't feel janky, and a soft right-edge shadow/fade while there's more content to scroll.
- Let the user pick which 2–3 secondary columns show (a simple column-picker), defaulting to the columns this app's own spec already calls "decision" columns: Score, Fair Value, Upside, Verdict. Reference data columns (sector, ISIN) default off on mobile.
- Row density: use the app's existing table row height, or drop one step (e.g. 48px → 40px) — never smaller than a 44px tap target for the whole row if rows are tappable.

### 4b. Single-record detail tables (one company's statement lines, corporate actions, notes) — **card transformation**

These are read top-to-bottom for one entity, not compared row-to-row, so cards work well here:

- Each row becomes a small card: label left, value right (still `tabular-nums`, right-aligned), one card per line item, grouped under the same section headers the desktop table uses.
- Keep the existing Actual/Calculated/Estimated/Forecast source-and-timestamp badges — don't drop them to save space; that's a core trust feature of this platform (§18 of the project spec) and must survive the mobile transform.

### General table rules (both types)
- Never truncate a number or a verdict word to save width. Truncate labels with an ellipsis + full text on tap, never truncate values.
- Loading/empty/blocked/provisional/error states (already defined in the desktop spec) render identically in the mobile card/scroll versions — same amber-for-blocked rule, same icons, not color alone.

## 5. Charts

The existing chart set (football field, price-with-zone-bands, score emphasis bars, peer scatter, ratio small multiples, diverging upside/downside bar) all need mobile variants. General rule: **simplify the chart's chrome, never the data it's making a point about.**

| Chart | Desktop | Mobile treatment |
|---|---|---|
| **Football field** (valuation ranges) | Horizontal bars, method labels left | Keep horizontal bars (this form scales down well); drop method sub-labels to abbreviations with a tap-to-expand legend; keep the current-price vertical rule — it's the entire point of the chart |
| **Price + zone bands** | Line + shaded bands + separate volume panel | Keep both panels stacked (never merge into dual-axis to save space — that's an explicit anti-pattern in your own spec). Reduce to 2 timeframe presets visible (e.g. 1Y, Max) with the rest behind a dropdown instead of 4 always-visible buttons |
| **Score emphasis bars** | Weakest pillar in accent, rest gray | Same treatment, stack labels above bars instead of beside them if width is tight |
| **Peer scatter** | ROE(x) vs P/B(y), company highlighted | Keep as scatter (don't convert to a table) but shrink axis label font and use the tap-for-tooltip pattern from §7 instead of hover |
| **Ratio small multiples** | 4 tiny line charts in a row | Stack 2×2 or 1-per-row depending on width; each stays a full-width sparkline rather than shrinking below legibility |
| **Diverging upside/downside bar** | Centered bar | Unchanged, this form is already narrow-screen-friendly |

Chart library notes:
- If charts are SVG/canvas-rendered, make them respond to container width (`ResizeObserver` or a responsive wrapper), not a fixed pixel width — this is the single most common cause of charts overflowing or getting cut off on phones.
- Every chart keeps its table-view fallback (already speced) — on mobile, make that fallback more prominent, since it's also the accessible/no-JS path and a legitimate way to inspect dense data on a small screen without pinch-zooming a chart.
- Respect `prefers-reduced-motion` on chart transitions, same as desktop.

## 6. Cards, spacing, typography

- Keep the existing 4/8px spacing scale and single type family/scale. On mobile, card padding can step down one notch (e.g. 24px → 16px) but never below 12px.
- Body/label text stays ≥16px minimum (prevents iOS Safari's automatic zoom-on-focus for inputs, and keeps the platform's own accessibility bar). Numerals may go to 14px as already speced, given tabular alignment — this rule is unchanged on mobile.
- Card stacks go single-column below 768px, 2-column at 768–1023px (tablet), matching the existing desktop multi-column grid unchanged at ≥1024px.

## 7. Interaction: hover → tap

Nothing in the desktop design should depend on `:hover` alone for information that's needed to use the product:

- Any hover-only tooltip (chart points, badge explanations, "why is this blocked" popovers) needs a tap-to-open equivalent on touch devices — detect via `(hover: none)` media feature, not user-agent sniffing.
- Buttons/icons at 44×44pt minimum touch target (Apple/Material both converge here); 48px where there's room, per current mobile HIG guidance.
- Disabled/loading button states must stay visually distinct on mobile too — no relying on a hover-cursor change as the only "this isn't clickable" signal.

## 8. Build order (page by page)

Ship and verify one page at a time; each should be checkable in isolation before moving to the next.

1. **Global shell** — breakpoint scaffolding, bottom tab bar, sticky header condensing, design-token pass (confirm all existing dark-theme tokens read correctly at small width — no contrast regressions).
2. **Homepage** — trust bar (1 line, unchanged), "decisions today" hero (already card-shaped, should stack naturally), 3 stat tiles → 1 column, universe histogram + sector bars → full width stacked, ranking tables → §4a sticky-column pattern.
3. **Company page** — sticky header condense, tab strip → scrollable pills, football field + price chart stacked full-width, score panel, peer scatter, then tabs (Financials/Data quality/Price&actions) using §4b card pattern for statement lines.
4. **Screener** — this is the highest-value mobile page to get right (filtering + scanning is inherently mobile-friendly if done as §4a). Filters collapse into a bottom sheet or expandable panel rather than a permanent sidebar.
5. **Portfolio** — holdings table → §4a sticky-column, alerts/attention list stacks naturally as cards already.
6. **Macro dashboard** — indicator tiles stack, sourced per the macro-page-redesign-spec.md, unchanged content just reflowed to 1–2 columns.

## 9. Verification checklist (do this before calling any page done)

Test at real widths, not just breakpoint edges: **360, 390, 412, 428px** (phones), **768, 1024px** (tablet/edge). For each page:

- [ ] No horizontal scroll on the page body itself (only inside explicitly scrollable table/chart containers)
- [ ] Desktop view at ≥1024px is unchanged — diff against the pre-change screenshot
- [ ] Every number stays fully visible, right-aligned, tabular-nums — nothing truncated
- [ ] Every loading/empty/blocked/provisional/error state still renders with its correct color/icon (amber for blocked, never red)
- [ ] All interactive elements ≥44×44pt
- [ ] Sticky header + tab strip together stay under ~112px
- [ ] Tap-based tooltip/detail equivalents exist wherever desktop uses hover-only
- [ ] `prefers-reduced-motion` respected
- [ ] Contrast ratios re-checked at the actual rendered mobile font sizes (WCAG AA, same bar as desktop)

---

## Sources

- [Data table UI design reference guide for 2026 — Setproduct](https://www.setproduct.com/blog/data-table-ui-design)
- [Data Table Design UX Patterns & Best Practices — Pencil & Paper](https://www.pencilandpaper.io/articles/ux-pattern-analysis-enterprise-data-tables)
- [The Best Mobile Layout for Complex Data Tables — UX Movement](https://uxmovement.medium.com/the-best-mobile-layout-for-complex-data-tables-e3ced21ce425)
- [Designing an Intuitive Mobile Dashboard UI: 4 Best Practices — Toptal](https://www.toptal.com/designers/dashboard-design/mobile-dashboard-ui)
- [Data-Dense Dashboard — DESIGN.md](https://designmd.app/library/data-dense-dashboard)
- [Fintech UI/UX Design: Best Practices for Financial Apps in 2026 — The Skins Factory](https://www.theskinsfactory.com/uiux-design-blog/fintech-ui-ux-design)
- [Breakpoint: Responsive Design Breakpoints in 2025/2026 — BrowserStack](https://www.browserstack.com/guide/responsive-design-breakpoints)
- [How Bloomberg Terminal UX designers conceal complexity — Bloomberg LP](https://www.bloomberg.com/company/stories/how-bloomberg-terminal-ux-designers-conceal-complexity/)
- Internal: `company-page-and-homepage-redesign.md`, `portfolio-page-redesign-spec.md`, `scoreboard-queue-redesign-spec.md`, `macro-page-redesign-spec.md` (design tokens, component states, chart set this doc extends)
