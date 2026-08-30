"""
The universe-wide data-integrity detectors from `docs/CSE_Universe_
Integrity_Rollout.md` that were not already built — pure predicates in the
exact mould of `app.domain.sanity` (no `Session`, no I/O; they operate on
inputs a caller has already resolved).

WHY PURE, AND WHY SHARED. Two callers run these: `scripts.audit_universe_
integrity` in REPORT-ONLY mode (the spec's Phase 1 "actual deliverable" —
count the problem before fixing it) and `app.jobs.runner._run_universe_
integrity_checks` in ENFORCING mode (raise a `DataAlert`, quarantine).
The spec is explicit that these must be the same checks in both modes
("turn the checks from report-only into blocking"), so the logic lives
here once and neither caller reimplements it.

WHAT IS DELIBERATELY NOT HERE. The AAF-class failure (a company bound to
its rights line) is already structurally prevented by `app.domain.
instrument_type` (`AAF.N0000` classifies `ordinary`, `AAF.R0000`
`rights`, and `is_common_equity` gates what a valuation model may be
pointed at). The market-cap identity check already runs live
(`app.domain.sanity.share_count_reconciles`) and nightly
(`app.jobs.market_cap_reconciliation`). The adjustment-factor
reconciliation already runs nightly (`app.jobs.reconciliation`). This
module adds the checks that had NO detector yet: rights-price coherence,
the nil-paid-rights price fingerprint, the cheap-and-profitable multiple
band, a raw 1-day price discontinuity, and rights-line reaping.

A CHECK THAT CANNOT BE EVALUATED RETURNS ``None``, NEVER A FINDING —
same discipline as `app.domain.sanity`: a missing input is "not
checked", never a silent pass and never a fabricated failure.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, DivisionByZero, InvalidOperation

# --- DataAlert.alert_type values this module's enforcing caller raises.
# `alert_type` is a free-text column (`app.models.data_quality.DataAlert`),
# so these are just agreed strings, not a schema change.
ALERT_RIGHTS_PRICE_INCOHERENT = "rights_price_incoherent"
ALERT_WRONG_LINE_FINGERPRINT = "wrong_line_fingerprint"
ALERT_IMPLAUSIBLE_MULTIPLE = "implausible_multiple"
ALERT_PRICE_DISCONTINUITY = "price_discontinuity"
ALERT_RIGHTS_LINE_EXPIRED = "rights_line_expired"

#: Alert types that mean "this ticker's numbers are not trusted at all" —
#: a hard failure. Consumed by `app.domain.security_status_view` to decide
#: QUARANTINED, and already the effective behaviour of `app.jobs.
#: reconciliation.is_quarantined` (any unresolved alert). The existing
#: four are listed alongside the five this rollout adds so the whole set
#: lives in one place.
HARD_ALERT_TYPES: frozenset[str] = frozenset(
    {
        "reconciliation_mismatch",
        "second_source_mismatch",
        "valuation_sanity_block",
        "market_cap_mismatch",
        ALERT_RIGHTS_PRICE_INCOHERENT,
        ALERT_WRONG_LINE_FINGERPRINT,
        ALERT_IMPLAUSIBLE_MULTIPLE,
        ALERT_PRICE_DISCONTINUITY,
    }
)

#: Alert types that mean "publish, but marked provisional — no maximum-
#: conviction verdict" (spec Part 4's PROVISIONAL state).
SOFT_ALERT_TYPES: frozenset[str] = frozenset(
    {
        "stale_source",
        ALERT_RIGHTS_LINE_EXPIRED,
    }
)

#: A rights line that has not traded for this many calendar days after its
#: issue is treated as expired and reaped. Nil-paid rights trade for a
#: short window (typically two–three weeks on the CSE) and then vanish;
#: 21 days with no trade is comfortably past any real trading window
#: without risking a live line during a slow offer.
RIGHTS_LINE_STALE_DAYS = 21

#: A 1-day return larger than this with no corporate action on the date is
#: not a price move, it is a data error (a split not applied, a decimal
#: shift, a wrong-line swap). Spec §Check 6.
PRICE_DISCONTINUITY_RETURN = Decimal("0.30")

#: How close the nil-paid-rights implied cum-price must land to a real
#: computed TERP before it is called a fingerprint match rather than a
#: coincidence. Spec §Check 3 matched AAF within 0.6%.
NIL_PAID_FINGERPRINT_TOLERANCE = Decimal("0.03")

#: Market-cap identity band — the same 2% `app.domain.sanity` and
#: `app.jobs.market_cap_reconciliation` already use, referenced here so a
#: report-only sweep and the live checks cannot silently diverge.
MARKET_CAP_IDENTITY_TOLERANCE = Decimal("0.02")


@dataclass(frozen=True)
class IntegrityFinding:
    check: str
    """Machine name — one of the ``ALERT_*`` constants for an enforcing
    check, or a descriptive slug for a report-only-only one."""
    severity: str
    """``"hard"`` — quarantine; ``"soft"`` — provisional; ``"info"`` —
    surfaced in the triage report only."""
    bucket: str
    """The Phase-1 triage-table row this finding counts toward."""
    detail: str
    """A sentence that stands on its own without the check name (§1 law 4)."""
    evidence: dict[str, str] = field(default_factory=dict)


def _ratio(a: Decimal, b: Decimal) -> Decimal | None:
    try:
        return a / b
    except (DivisionByZero, InvalidOperation, ZeroDivisionError):
        return None


# --------------------------------------------------------------------------
# Line identity
# --------------------------------------------------------------------------
def check_instrument_type_known(symbol: str, instrument_type: str | None) -> IntegrityFinding | None:
    """`instrument_type` is `UNKNOWN` / unset — the line cannot be
    classified, so nothing downstream should treat it as investable
    equity. A blocking state, never a default-to-ordinary."""
    if instrument_type in (None, "unknown"):
        return IntegrityFinding(
            check="instrument_type_unknown",
            severity="hard",
            bucket="Unresolved / unknown line type",
            detail=(
                f"{symbol} has no confirmed instrument type — it cannot be classified as "
                "ordinary, non-voting, preference, debenture, rights, unit or warrant, so it "
                "must not enter the investable universe until a human resolves it."
            ),
            evidence={"instrument_type": str(instrument_type)},
        )
    return None


def check_rights_line_expired(
    symbol: str,
    instrument_type: str | None,
    last_trade_date: dt.date | None,
    as_of: dt.date,
    *,
    stale_days: int = RIGHTS_LINE_STALE_DAYS,
) -> IntegrityFinding | None:
    """A `.R` rights line still carried as active well after it has stopped
    trading. Rights lines expire; left un-reaped they get re-picked next
    quarter (spec §1.3 rule 2)."""
    if instrument_type != "rights":
        return None
    if last_trade_date is None:
        return None
    age = (as_of - last_trade_date).days
    if age <= stale_days:
        return None
    return IntegrityFinding(
        check=ALERT_RIGHTS_LINE_EXPIRED,
        severity="soft",
        bucket="Rights line not reaped",
        detail=(
            f"{symbol} is a rights line whose last trade was {age} days ago "
            f"({last_trade_date}). Rights expire; it should be marked delisted so it is not "
            "re-picked as a company next quarter."
        ),
        evidence={"last_trade_date": str(last_trade_date), "age_days": str(age)},
    )


# --------------------------------------------------------------------------
# Price ↔ fundamentals identity
# --------------------------------------------------------------------------
def check_market_cap_identity(
    symbol: str,
    price: Decimal | None,
    shares_in_issue: int | None,
    exchange_published_market_cap: Decimal | None,
    *,
    tolerance: Decimal = MARKET_CAP_IDENTITY_TOLERANCE,
) -> IntegrityFinding | None:
    """`|price × shares − exchange_market_cap| / exchange_market_cap ≤ 2%`
    (spec §Check 1). Skipped, never failed, on any missing input."""
    if price is None or not shares_in_issue or exchange_published_market_cap is None:
        return None
    local = price * Decimal(shares_in_issue)
    off = _ratio(abs(exchange_published_market_cap - local), exchange_published_market_cap)
    if off is None or off <= tolerance:
        return None
    return IntegrityFinding(
        check="market_cap_mismatch",
        severity="hard",
        bucket="Market-cap identity fail",
        detail=(
            f"{symbol}: price × shares ({local:,.0f}) disagrees with the exchange's own "
            f"published market cap ({exchange_published_market_cap:,.0f}) by {off:.1%} — outside "
            "the 2% band. Usually a wrong share class, a stale share count, or a units error."
        ),
        evidence={
            "price_x_shares": f"{local:,.0f}",
            "exchange_market_cap": f"{exchange_published_market_cap:,.0f}",
            "off_by": f"{off:.2%}",
        },
    )


def check_rights_price_coherence(
    symbol: str,
    underlying_price: Decimal | None,
    subscription_price: Decimal | None,
) -> IntegrityFinding | None:
    """During an open rights issue the underlying's market price must
    exceed the subscription price — rights are always priced at a
    discount, so a market price at or below the subscription price is
    arithmetically near-impossible in a live offer (spec §Check 2). If it
    holds, the "price" series is very likely the nil-paid rights line, not
    the ordinary."""
    if underlying_price is None or subscription_price is None:
        return None
    if underlying_price > subscription_price:
        return None
    return IntegrityFinding(
        check=ALERT_RIGHTS_PRICE_INCOHERENT,
        severity="hard",
        bucket="Rights-price incoherent (wrong line suspected)",
        detail=(
            f"{symbol} has an open rights issue at a subscription price of {subscription_price}, "
            f"but the bound price series reads {underlying_price} — at or below the subscription "
            "price, which cannot happen for the underlying in a live offer. The series is almost "
            "certainly the nil-paid rights line."
        ),
        evidence={"bound_price": str(underlying_price), "subscription_price": str(subscription_price)},
    )


def check_nil_paid_fingerprint(
    symbol: str,
    bound_price: Decimal | None,
    subscription_price: Decimal | None,
    terp_from_confirmed_action: Decimal | None,
    *,
    tolerance: Decimal = NIL_PAID_FINGERPRINT_TOLERANCE,
) -> IntegrityFinding | None:
    """If `bound_price + subscription_price` (the implied cum-price for a
    nil-paid right) lands within tolerance of the TERP computed
    independently from the confirmed rights action, the bound series
    behaves like a nil-paid right — so it is one (spec §Check 3). This is
    the detector that pinpoints *which* wrong line was grabbed."""
    if bound_price is None or subscription_price is None or terp_from_confirmed_action is None:
        return None
    implied_cum = bound_price + subscription_price
    off = _ratio(abs(implied_cum - terp_from_confirmed_action), terp_from_confirmed_action)
    if off is None or off > tolerance:
        return None
    return IntegrityFinding(
        check=ALERT_WRONG_LINE_FINGERPRINT,
        severity="hard",
        bucket="Wrong line bound (nil-paid rights fingerprint)",
        detail=(
            f"{symbol}: treating the bound price {bound_price} as a nil-paid right implies a "
            f"cum-price of {implied_cum} (bound + subscription {subscription_price}), which "
            f"matches the TERP computed from the confirmed rights action ({terp_from_confirmed_action}) "
            f"within {off:.1%}. The bound series is the rights line, not the ordinary equity."
        ),
        evidence={
            "bound_price": str(bound_price),
            "implied_cum_price": str(implied_cum),
            "terp_from_action": str(terp_from_confirmed_action),
            "off_by": f"{off:.2%}",
        },
    )


def check_implied_multiple_band(
    symbol: str,
    price_to_book: Decimal | None,
    price_to_earnings: Decimal | None,
    roe: Decimal | None,
    net_profit: Decimal | None,
) -> IntegrityFinding | None:
    """Valuations that have never existed for a solvent company (spec
    §Check 4). Universal bands for now — sector-specific calibration is a
    later step once the universe has clean data."""
    reasons: list[str] = []
    if price_to_book is not None and roe is not None and price_to_book < Decimal("0.40") and roe > Decimal("0.15"):
        reasons.append(
            f"P/B {price_to_book:.2f} with ROE {roe:.1%} — a deep discount to book AND high "
            "returns is a data error, not an opportunity"
        )
    if (
        price_to_earnings is not None
        and net_profit is not None
        and price_to_earnings < Decimal("2.0")
        and net_profit > 0
    ):
        reasons.append(f"P/E {price_to_earnings:.2f} on a profitable company")
    if price_to_book is not None and price_to_book > Decimal("15"):
        reasons.append(f"P/B {price_to_book:.1f}")
    if price_to_earnings is not None and price_to_earnings > Decimal("200"):
        reasons.append(f"P/E {price_to_earnings:.0f}")
    if not reasons:
        return None
    return IntegrityFinding(
        check=ALERT_IMPLAUSIBLE_MULTIPLE,
        severity="hard",
        bucket="Implausible implied multiple",
        detail=f"{symbol}: implied multiples outside any plausible band — " + "; ".join(reasons) + ".",
        evidence={
            "pb": str(price_to_book),
            "pe": str(price_to_earnings),
            "roe": str(roe),
        },
    )


def check_price_discontinuity(
    symbol: str,
    return_1d: Decimal | None,
    on_date: dt.date | None,
    has_corporate_action_on_date: bool,
    *,
    threshold: Decimal = PRICE_DISCONTINUITY_RETURN,
) -> IntegrityFinding | None:
    """A single-day return past ±30% with no corporate action on that date
    (spec §Check 6, line 1). The companion "corporate action on the date
    but adjustment factor still 1.0" is already caught for the whole
    universe by `app.jobs.reconciliation`."""
    if return_1d is None:
        return None
    if abs(return_1d) <= threshold or has_corporate_action_on_date:
        return None
    return IntegrityFinding(
        check=ALERT_PRICE_DISCONTINUITY,
        severity="hard",
        bucket="Unexplained price discontinuity",
        detail=(
            f"{symbol} moved {return_1d:+.0%} in one session"
            + (f" on {on_date}" if on_date is not None else "")
            + " with no corporate action recorded for that date — a split not applied, a decimal "
            "shift, or a wrong-line swap rather than a real move."
        ),
        evidence={"return_1d": f"{return_1d:+.2%}", "on_date": str(on_date)},
    )


# --------------------------------------------------------------------------
# Model / routing / freshness (report-only in Phase 1)
# --------------------------------------------------------------------------
def check_cost_of_equity_available(
    symbol: str, needs_cost_of_equity: bool, cost_of_equity: Decimal | None
) -> IntegrityFinding | None:
    """A CoE-dependent model (every financial-sector valuation) with no
    cost of equity available — the engine would otherwise fall back
    silently (spec §Check/class 5)."""
    if not needs_cost_of_equity or cost_of_equity is not None:
        return None
    return IntegrityFinding(
        check="cost_of_equity_unavailable",
        severity="soft",
        bucket="Cost of equity unavailable",
        detail=(
            f"{symbol} needs a cost of equity for its valuation model and none is available — "
            "any CoE-dependent number for this name is unsupported until the CoE service can "
            "produce one."
        ),
    )


def check_sector_model_routed(symbol: str, archetype: str | None, routed_family: str | None) -> IntegrityFinding | None:
    """No archetype, or the router produced no model family — the valuation
    would run on the wrong model family for the sector (spec §class 6)."""
    if archetype is not None and routed_family is not None:
        return None
    return IntegrityFinding(
        check="sector_model_unrouted",
        severity="soft",
        bucket="Sector model routing gap",
        detail=(
            f"{symbol} has "
            + ("no archetype" if archetype is None else f"archetype {archetype!r} but no routed model family")
            + " — its valuation cannot be routed to the correct model family for its sector."
        ),
        evidence={"archetype": str(archetype), "routed_family": str(routed_family)},
    )


def check_price_staleness(
    symbol: str, calendar_days_since_last_trade: int | None, *, threshold_days: int = 10
) -> IntegrityFinding | None:
    """Last trade older than the threshold — treated as live otherwise
    (spec §class 10). ~10 calendar days ≈ 7 trading days plus a weekend."""
    if calendar_days_since_last_trade is None:
        return None
    if calendar_days_since_last_trade <= threshold_days:
        return None
    return IntegrityFinding(
        check="stale_source",
        severity="soft",
        bucket="Stale price",
        detail=(
            f"{symbol}'s last trade was {calendar_days_since_last_trade} days ago — its price is "
            "stale and any signal built on it should be marked provisional, not rendered as current."
        ),
        evidence={"days_since_last_trade": str(calendar_days_since_last_trade)},
    )
