"""The data-health experiment ledger — `docs/CSE_Data_Health_Diagnosis_
And_Protocol.md` §8 / §9.4, "put the experiment log on the page."

A dashboard that runs experiments should show the last changes with the
metric before and after, so the one-variable-per-deploy rule is visible
rather than aspirational. This is that log, kept as version-controlled
data rather than a database table: each entry is a real change that
shipped in this repo's history, and editing it is a code review.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Experiment:
    id: str
    hypothesis: str
    variable: str
    """The single thing that changed."""
    metric: str
    outcome: str
    """What actually happened — confirmed, falsified, or superseded — in
    plain terms, with the before/after where there is one."""
    status: str  # "confirmed" | "falsified" | "shipped" | "pending"
    commit: str = ""


EXPERIMENTS: tuple[Experiment, ...] = (
    Experiment(
        "E0", "Pass rates conflate 'fail' with 'cannot evaluate'.",
        "Metric definition only — the check ledger's three-way split.",
        "pass / fail / not-evaluable + checkable% per check",
        "Shipped. Market-cap identity was 3.4% checkable, not '50% pass'; "
        "corporate-action ratio 91.4% of reviewed, not the reported 15%.",
        "shipped", "dbb8cb6",
    ),
    Experiment(
        "E8", "Freshness is two quantities under one label.",
        "Split into data-date and last-successful-run, counted in trading days.",
        "trading-days-behind, missing_trading_days[], job-last-success",
        "Shipped. Data is 2 trading days behind (Mon+Tue missing); the "
        "price job last succeeded 9 days ago — two different facts.",
        "shipped", "dbb8cb6",
    ),
    Experiment(
        "E3", "The market-cap check is contaminated by price timing.",
        "Compare implied share count (published mcap ÷ published price) "
        "instead of latest close × shares.",
        "share_count_identity pass / fail",
        "Confirmed. On the 10 checkable lines: 10/10 pass at off = 0. The "
        "old check still fails ACME and AEL on price drift alone. AFSL — "
        "predicted a real share-count fault — passes; its 5.95% gap was "
        "also drift.",
        "confirmed", "6347104",
    ),
    Experiment(
        "E2", "A percentage-only tolerance false-positives at low prices.",
        "Second-source tolerance becomes max(5% floor, 2 CSE ticks).",
        "open second_source_mismatch count",
        "Shipped. CITW (1.60→1.70, one legal tick) auto-resolved; RGEM / "
        "SFCL / SHOT / WIND (5–15%) stay flagged.",
        "shipped", "9bb3d04",
    ),
    Experiment(
        "E1", "Stale-vs-live comparison drives the second-source alerts.",
        "(none — investigated only)",
        "sign balance of the residuals",
        "Falsified for this check: the job already refuses non-today "
        "comparisons, and the five alerts were genuine same-date findings "
        "on 2026-08-28. All four survivors are 'stored below external' → a "
        "real systematic bias, per the protocol's own falsifier.",
        "falsified",
    ),
    Experiment(
        "E7", "Non-voting lines fail the sanity gate structurally.",
        "Put the fair value on a non-voting basis (× observed .X/.N ratio) "
        "before the fair-value-vs-price rules; skip them when no ratio is "
        "observable.",
        ".X vs .N block rate on the check ledger",
        "Shipped. Effect lands on the next full recompute; the cohort "
        "split is the falsifier — .X should converge toward .N's ~2.2%.",
        "shipped", "8ebe2db",
    ),
    Experiment(
        "E5", "Discontinuity alerts are a missing CA table, not bad prices.",
        "(none — the table was found already populated)",
        "price_discontinuity checkable%",
        "Falsified. The corporate_actions table holds 1,810 actions; the "
        "check gate was reading job-run history, not the table. Corrected: "
        "0% → 99.3% checkable, 7 real 'no CA near this move' flags remain.",
        "falsified", "a9a7508",
    ),
    Experiment(
        "E6", "The CoE proxy materially distorts fair values.",
        "(none — the real feed was found current)",
        "share of names with a real cost of equity",
        "Falsified. CBSL risk-free data is current to 2026-08-25 and "
        "cost_of_equity_for already returns a real Ke. Only the tile label "
        "implied a proxy; fixed to key off data-date, not job history.",
        "falsified", "a9a7508",
    ),
    Experiment(
        "E4", "Multi-line issuers fail the identity check by construction.",
        "(none — the premise was checked against a real payload)",
        "single-line vs multi-line pass rate",
        "Falsified. The exchange publishes marketCap per line (that line's "
        "own quantityIssued × lastTradedPrice), not per issuer, so the "
        "per-line check is already correct.",
        "falsified", "a9a7508",
    ),
)
