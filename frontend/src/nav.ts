/**
 * UI & Experience Specification §7.1 — the navigation, exactly as
 * specified: six primary destinations, then a rule, then two advanced
 * ones.
 *
 *   TODAY          what needs my attention, and what is the weather
 *   OPPORTUNITIES  the ranked board, the screener, the watchlist
 *   COMPANIES      all ~286 names, searchable — every one has a file
 *   PORTFOLIO      what I own, and whether the reasons still hold
 *   MACRO          the regime, the variables, the project pipeline
 *   JOURNAL        every decision I made and how it turned out
 *   ─────────────
 *   LAB            backtests and strategy variants          (advanced)
 *   DATA HEALTH    freshness, reconciliation, confirm queue (advanced)
 *
 * Destinations whose engines don't exist yet are listed but marked with
 * the phase that builds them, and route to a page that says plainly what
 * will live there. The alternative — hiding them until they work — would
 * misrepresent the shape of the product; the alternative to THAT —
 * showing them with invented content — is the placeholder anti-pattern
 * (§17) that the spec forbids outright.
 */

export type ScreenId =
  | "today"
  | "opportunities"
  | "companies"
  | "portfolio"
  | "macro"
  | "journal"
  | "lab"
  | "data-health"
  | "review"
  | "playbooks";

export interface NavItem {
  id: ScreenId;
  label: string;
  blurb: string;
  /** null when the screen is built and usable today. */
  awaitingPhase: string | null;
  /** What this destination will contain once its engines exist. */
  willContain?: string;
  group: "primary" | "advanced";
}

export const NAV_ITEMS: NavItem[] = [
  {
    id: "today",
    label: "Today",
    blurb: "What needs my attention, and what is the weather",
    awaitingPhase: null,
    group: "primary",
  },
  {
    id: "opportunities",
    label: "Opportunities",
    blurb: "The ranked board, the screener, the watchlist",
    awaitingPhase: null,
    willContain:
      "Built: every confirmed-fundamentals ticker ranked by the §38 composite score (valuation, business quality, growth, financial strength, macro & sector fit, timing & momentum, risk), computed across the whole universe on one cached ~30s pass so the valuation pillar is genuinely ranked — plus a secondary ordering by the gap to each name's buy-below price (§25-26). Still awaiting §39's sequential fusion, the transaction-cost leg of §40's metric, and an automated §14 earnings-integrity veto (carried on every row as unevaluable, never applied) — so this is a genuine but narrower ordering, not risk-adjusted expected return net of transaction cost.",
    group: "primary",
  },
  {
    id: "companies",
    label: "Companies",
    blurb: "All listed names, searchable — every one has a file",
    awaitingPhase: null,
    group: "primary",
  },
  {
    id: "portfolio",
    label: "Portfolio",
    blurb: "What I own, and whether the reasons still hold",
    awaitingPhase: null,
    willContain:
      "Built: upload a real CDS/broker holdings export and see your current positions run through this system's own real valuation engine — live price, fair value, price-ladder zone and buy-below, per holding. Still awaiting Phase 8 (§41–42): thesis status above P&L (deliberately — P&L is what happened, thesis status is what to do), distance to each of the five exit triggers, portfolio-level factor exposure against target, and the thesis-drift verdict per position. Those need the decision record (§45) capturing frozen model state at purchase, which doesn't exist yet.",
    group: "primary",
  },
  {
    id: "macro",
    label: "Macro",
    blurb: "The regime, the variables, the project pipeline",
    awaitingPhase: null,
    willContain:
      "Built: the earnings-yield-minus-364-day-T-bill spread as the hero chart (§29 — the single most powerful macro variable in this market) and the §33 sector sensitivity matrix, both real, live estimates. Still awaiting Phase 5/9: the regime gauge (the classifier exists but hasn't been validated against a real historical Sri Lankan regime yet), a macro variable heatmap, the causality/impulse-response panels, and the national project register.",
    group: "primary",
  },
  {
    id: "journal",
    label: "Journal",
    blurb: "Every decision I made and how it turned out",
    awaitingPhase: null,
    willContain:
      "Built: record a real decision — action, reasoning, conviction, \"what would prove me wrong\" — with this system's own real fair value, price ladder and margin-of-safety breakdown frozen at that exact moment, and record a real exit outcome (gross and net return, after §2.1's real transaction cost) against it. Still awaiting later phases: the override analysis (needs the §38 composite score to compare against), and the automatic thesis-drift evaluation of each falsification condition (§42) — both real, named gaps, not silently omitted.",
    group: "primary",
  },
  {
    id: "lab",
    label: "Lab",
    blurb: "Backtests and strategy variants",
    awaitingPhase: "Phase 8",
    willContain:
      "Strategy variants with an equity curve shaded per regime, gross versus net side by side (net solid, gross dashed — keeping attention on the only number that is real), Deflated Sharpe, the capacity curve and a parameter sensitivity heatmap (§48–49).",
    group: "advanced",
  },
  {
    id: "data-health",
    label: "Data health",
    blurb: "Freshness, reconciliation, confirm queue",
    awaitingPhase: null,
    group: "advanced",
  },
];

/** The review queues are reached from Data health rather than the top
 * level — §7.1's nav has eight destinations and adding a ninth would
 * misrepresent the specified IA. */
export const REVIEW_SCREEN: NavItem = {
  id: "review",
  label: "Confirm queue",
  blurb: "Data awaiting human confirmation",
  awaitingPhase: null,
  group: "advanced",
};

// M5 — Convergence Engine & Playbook System (docs/CLAUDE_CODE_BRIEF_M5.md
// §1.3): the allowlisted frontend nav edit. That brief names
// `frontend/src/config/navigation.ts`, which does not exist in this
// codebase — `NAV_ITEMS` right here IS the real, equivalent "one nav
// array a caller appends to" the brief describes, just at its real
// path. Guarded by `VITE_M5_ENABLED` (unset/false by default — Vite
// env vars are string-typed, so this checks the literal string "true",
// not JS truthiness) so `NAV_ITEMS` is byte-identical to before with
// the flag off, matching the backend's own `m5_enabled` guard exactly.
if (import.meta.env.VITE_M5_ENABLED === "true") {
  NAV_ITEMS.push({
    id: "playbooks",
    label: "Playbooks",
    blurb: "Convergence setups, base rates, and the trial record",
    awaitingPhase: null,
    group: "advanced",
  });
}
