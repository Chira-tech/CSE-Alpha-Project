"""
P0 TASK 0.1's plausibility gate (`docs/CLAUDE_CODE_BRIEF.md`) — defense
in depth on top of, not instead of, the real fix in `app.domain.ttm`.

WHY THIS EXISTS EVEN THOUGH THE ROOT CAUSE IS ALREADY FIXED. The TTM
annualisation bug (`app.domain.ttm`'s own module docstring has the full
story) was ONE specific, now-closed cause of an implausible fair value.
The brief is explicit that a gate belongs here regardless: "a plausibility
gate that runs on every valuation before it is persisted or displayed."
A single root-cause fix closes the bug found on 18 Aug 2026; a gate
catches the NEXT one — a units mismatch on a different company, a bad
share count, a mis-mapped statement line — before it ever reaches a
screen. §1's own law 4 ("never a black box") is exactly this: the system
must be able to say "I don't believe this number and here is why," not
just "here is the number I computed."

PURE, NO DATABASE ACCESS — mirrors `app.domain.price_ladder`'s own split:
the gate is a function of already-resolved inputs (`SanityContext`), not
a thing that goes and fetches its own data. `app.domain.valuation_view`
gathers the context (it already computes every one of these inputs for
other reasons) and `app.domain.valuation_quarantine_view` persists the
result — see that module for why persistence is a separate file rather
than folded in here.

A RULE THAT CANNOT BE EVALUATED IS SKIPPED, NEVER TREATED AS PASSED. If
`ctx.mcap` is `None` (no independently-published market cap on file yet
for this ticker — see `SanityContext.mcap`'s own docstring for why this
is a real independent figure, not a derived one), `share_count_
reconciles` is recorded as `skipped`, not silently counted as a pass.
Silently passing an unevaluated rule would be exactly the "confident
answer built on an absence" failure this whole gate exists to prevent.

THE BLOCK/WARN SEVERITIES ARE THE BRIEF'S OWN, TRANSCRIBED EXACTLY —
`fv_within_5x_price`, `bvps_positive`, `share_count_reconciles`, `roe_
plausible` and `units_consistent` block (no fair value or ladder is
published at all); `fv_within_2x_price` only warns (published, with a
visible caution chip). COMB.N0000's own real numbers, BEFORE the TTM fix
(fair value 93.06 vs price 205.75 — a 0.45x ratio), would have failed
`fv_within_2x_price` (warn) but NOT `fv_within_5x_price` (block) — a
real, disclosed limit of this gate alone: it is a backstop against
egregious implausibility, not a substitute for the real annualisation
fix. The two work together, not either instead of the other.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Callable

_ZERO = Decimal(0)


@dataclass(frozen=True)
class SanityContext:
    """Every input a `SANITY_RULES` predicate might need, gathered ONCE
    by the caller from figures it already computed for other reasons
    (see `app.domain.valuation_view._gather_inputs`) — this module never
    re-derives any of these itself. `None` on any field means "genuinely
    not known for this ticker as of this date," not zero — a rule that
    needs a `None` field is skipped, per this module's own docstring."""

    price: Decimal
    """The current traded price this valuation is being judged against.
    Always present when the gate runs — `valuation_view` only invokes it
    once a `current_price` and a triangulated fair value both exist."""

    bvps: Decimal | None
    """Book value per share — `total_equity ÷ shares_issued`, from
    confirmed fundamentals."""

    roe: Decimal | None
    """Return on equity, TTM-annualised (`app.domain.ttm`) when the
    current period is a quarterly cumulative figure — this IS the fixed
    figure, not the raw pre-fix one, so `roe_plausible` is a genuine
    second check on a number the TTM fix has already corrected, not a
    check on the bug itself."""

    mcap: Decimal | None
    """CSE's OWN independently-published market capitalisation for this
    ticker (`CompanySymbolInfo.marketCap`, `app.ingestion.security_
    enrichment`) — a real, separate figure the exchange computes itself
    from its own current price and share count, fetched in the SAME
    `companyInfoSummery` call as `shares_issued` but, until this fix,
    silently discarded rather than stored (`app.models.float_data.
    FloatData.published_market_cap`, new). Deliberately NOT `price ×
    shares` computed locally — comparing a number against itself would
    catch nothing; this is a genuine second, independently-sourced
    measurement of the same fact, so a mismatch means OUR `shares` or
    OUR `price` has drifted from what the exchange itself is currently
    quoting (a stale `FloatData` snapshot, most likely), not a tautology.
    KNOWN LIMIT, verified against a real captured response (AEL.N0000,
    16 Aug 2026 — see `tests/test_security_enrichment.py`): CSE computes
    `marketCap` from the SAME symbol line's own `quantityIssued` and
    `lastTradedPrice`, so this check will not by itself catch a voting-
    vs-non-voting mixup where our valuation used the WRONG share class's
    count against the RIGHT class's price — both lines would still each
    look internally consistent. It genuinely does catch staleness and
    gross share-count errors, which is what it is built and tested for
    here; it is not a complete defence against every hypothesis TASK 0.1
    named."""

    shares: int | None
    """`shares_issued` as used by THIS valuation (the same figure that
    fed `bvps` and the DCF)."""

    equity: Decimal | None
    """`total_equity`, confirmed, for the period this valuation used."""

    total_assets: Decimal | None
    """`total_assets`, confirmed, for the SAME period as `equity` — both
    fields must come from the identical period or `units_consistent`
    could flag a real, harmless period mismatch as a fabricated units
    error; `app.domain.valuation_view._gather_inputs` sources both from
    the same single-period line-item dict for exactly this reason."""


@dataclass(frozen=True)
class SanityRule:
    name: str
    requires: tuple[str, ...]
    """`SanityContext` field names this rule needs non-`None` to run."""

    predicate: Callable[[Decimal, "SanityContext"], bool]
    """`(fair_value, ctx) -> True` if plausible. Never called when any
    `requires` field is `None` — see `run_sanity_checks`."""

    severity: str
    """`"block"` — withhold; `"warn"` — publish with a visible caution."""

    message: str
    """Shown to the user verbatim when this rule fails — must stand on
    its own without the rule name, per §1 law 4 ("never a black box")."""


SANITY_RULES: tuple[SanityRule, ...] = (
    SanityRule(
        "fv_within_5x_price",
        ("price",),
        lambda v, ctx: Decimal("0.2") <= v / ctx.price <= Decimal("5.0"),
        "block",
        "Fair value is more than 5x, or less than a fifth of, the current price — "
        "outside any range a going-concern valuation should plausibly produce.",
    ),
    SanityRule(
        "bvps_positive",
        ("bvps",),
        lambda v, ctx: ctx.bvps > _ZERO,
        "block",
        "Book value per share is zero or negative — check total_equity and "
        "shares_issued for this period.",
    ),
    SanityRule(
        "share_count_reconciles",
        ("mcap", "shares"),
        lambda v, ctx: abs(ctx.mcap / (ctx.price * Decimal(ctx.shares)) - 1) < Decimal("0.02"),
        "block",
        "Market cap does not reconcile against price x shares outstanding, within 2%, "
        "against the exchange's own published figure. Check: voting vs non-voting share "
        "classes, or a stale share count.",
    ),
    SanityRule(
        "roe_plausible",
        ("roe",),
        lambda v, ctx: Decimal("-0.5") < ctx.roe < Decimal("0.6"),
        "block",
        "Return on equity is outside a plausible range (-50% to 60%) — check for an "
        "unannualised interim figure or a units mismatch between statement lines.",
    ),
    SanityRule(
        "units_consistent",
        ("equity", "total_assets"),
        lambda v, ctx: ctx.equity / ctx.total_assets < Decimal("1.0"),
        "block",
        "Total equity exceeds total assets — an accounting impossibility, almost "
        "always a units mismatch between statement lines (e.g. LKR '000 vs LKR mn).",
    ),
    SanityRule(
        "fv_within_2x_price",
        ("price",),
        lambda v, ctx: Decimal("0.5") <= v / ctx.price <= Decimal("2.0"),
        "warn",
        "Fair value is more than double, or less than half, the current price.",
    ),
)


@dataclass(frozen=True)
class SanityCheckResult:
    fair_value: Decimal
    blocked: bool
    blocked_by: tuple[str, ...]
    block_reasons: tuple[str, ...]
    warned_by: tuple[str, ...]
    warn_reasons: tuple[str, ...]
    skipped: tuple[str, ...]
    """Rules that could not be evaluated because a required input was
    `None` — named so a caller (and, eventually, the UI) can distinguish
    "checked and passed" from "not checked" rather than conflating them."""


def run_sanity_checks(fair_value: Decimal, ctx: SanityContext) -> SanityCheckResult:
    """§1's own plausibility gate, run on one already-triangulated fair
    value before it is allowed to become a price ladder. Never mutates,
    never touches the database — see this module's own docstring for why."""
    blocked_by: list[str] = []
    block_reasons: list[str] = []
    warned_by: list[str] = []
    warn_reasons: list[str] = []
    skipped: list[str] = []

    for rule in SANITY_RULES:
        if any(getattr(ctx, field_name) is None for field_name in rule.requires):
            skipped.append(rule.name)
            continue
        try:
            passed = rule.predicate(fair_value, ctx)
        except (DivisionByZero, InvalidOperation, ZeroDivisionError):
            # A required field WAS present but produced an undefined
            # comparison (e.g. price == 0) — genuinely unevaluable, same
            # as a missing field, not a silent pass.
            skipped.append(rule.name)
            continue
        if passed:
            continue
        if rule.severity == "block":
            blocked_by.append(rule.name)
            block_reasons.append(rule.message)
        else:
            warned_by.append(rule.name)
            warn_reasons.append(rule.message)

    return SanityCheckResult(
        fair_value=fair_value,
        blocked=bool(blocked_by),
        blocked_by=tuple(blocked_by),
        block_reasons=tuple(block_reasons),
        warned_by=tuple(warned_by),
        warn_reasons=tuple(warn_reasons),
        skipped=tuple(skipped),
    )
