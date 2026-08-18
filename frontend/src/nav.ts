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
  | "review";

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
    awaitingPhase: "Phases 2–3",
    willContain:
      "Every investable name ranked by risk-adjusted expected return net of the cost of building the position (§40) — with the composite score, the price ladder zone, the gap to your buy-below price, and the agreement indicator showing how many model layers actually support each case. It needs the fundamental engine (§12), the valuation engine (§16–24) and the price engine (§25–27) to exist first.",
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
    awaitingPhase: "Phase 8",
    willContain:
      "Your holdings with thesis status above P&L (deliberately — P&L is what happened, thesis status is what to do), distance to each of the five exit triggers, portfolio-level factor exposure against target, and the thesis-drift verdict per position (§41–42). It needs the decision record (§45) to have been capturing frozen model state first.",
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
    awaitingPhase: "Phase 4",
    willContain:
      "Every signal, decision and override, logged with the reasoning as written at the time and the full model state frozen alongside — including the override analysis comparing returns where you went against the composite versus with it. The spec calls this the highest-value screen in the product over a three-year horizon, and it ships early (§45) precisely because every decision made without a recorded rationale is a data point that cannot be recovered later.",
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
