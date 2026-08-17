"""
§30 step 2's own routing rule, made real: "All I(1) with Johansen
cointegration → VECM. Mixed I(0)/I(1), none I(2), short sample → ARDL
bounds test [THIS WILL BE THE DEFAULT]. No cointegration → VAR in first
differences." This module encodes only the FIRST half of that sentence
— which estimator to ATTEMPT, given each series' own real integration
order — not the fallback chain (a Johansen candidate that finds no real
cointegration, or an ARDL bounds test that concludes "not cointegrated,"
both genuinely fall through to VAR-in-differences; that fallback logic
lives in `app.domain.estimator_selection_view`, the layer that actually
runs each estimator and can see its real conclusion).

REUSES `app.domain.stationarity`'s OWN CONSENSUS VOCABULARY DIRECTLY —
`"stationary"`/`"non_stationary"`/`"mixed_evidence"`/`"insufficient_
data"` — rather than inventing a parallel "integration order" enum.
A series `assess_stationarity` calls `"non_stationary"` in levels IS,
for this purpose, I(1); `"stationary"` IS I(0). This module does not
itself test for I(2) (a series that needs differencing TWICE) — §30
step 2's own text assumes "none I(2)" as a precondition rather than
something this routing step verifies, and neither `app.domain.
stationarity` nor this module currently checks it. That is a real,
named gap, not a silent assumption: a genuinely I(2) input series would
be routed here as if it were I(1) or I(0) by whatever `assess_
stationarity` reports on its LEVEL values, and every one of §30 step
2's three estimators would then be fit on data outside its own valid
scope without warning. Detecting I(2) properly means re-running
`assess_stationarity` on each series' own FIRST DIFFERENCE and checking
that comes back stationary too — genuinely unbuilt, named here rather
than glossed over.

BOTH-I(0) IS ROUTED TO ARDL, NOT TREATED AS A MISSING CASE. §30's own
text only names three cases, but Pesaran-Shin-Smith's own bounds test is
explicitly designed to work "regardless of whether the underlying
regressors are purely I(0), purely I(1), or a mixture of the two" (as
long as none are I(2)) — that is the whole point of a BOUNDS test rather
than a single-distribution test. So two genuinely stationary series
route to the same `"ardl_bounds_test"` choice as a mixed I(0)/I(1) pair,
not to a fourth, unnamed branch — a real, disclosed extension of §30's
own three named cases to the one combination its own text doesn't
explicitly mention, not a shortcut.
"""
from __future__ import annotations

from typing import Literal

StationarityConsensus = Literal["stationary", "non_stationary", "mixed_evidence", "insufficient_data"]
EstimatorChoice = Literal["johansen_vecm", "ardl_bounds_test", "insufficient_data"]


def select_estimator(
    dependent_consensus: StationarityConsensus | None,
    independent_consensus: StationarityConsensus | None,
) -> tuple[EstimatorChoice, str]:
    """`(choice, reason)` — `reason` is always populated, including for
    a real choice, so a caller never has to separately explain why a
    given estimator was attempted.

    `"insufficient_data"` whenever either series' own real stationarity
    consensus is unknown (`None` — the series had no assessment at all)
    or itself `"insufficient_data"`, OR whenever either series' own four
    stationarity tests disagreed enough to be `"mixed_evidence"` — a
    genuinely ambiguous integration order for that one series. Picking
    an estimator on top of an already-uncertain input would compound one
    real uncertainty with another; honest refusal is preferred to a
    guess."""
    if dependent_consensus is None or independent_consensus is None:
        missing = []
        if dependent_consensus is None:
            missing.append("the dependent series")
        if independent_consensus is None:
            missing.append("the independent series")
        return "insufficient_data", f"No stationarity assessment available for {' and '.join(missing)}."

    if dependent_consensus == "insufficient_data" or independent_consensus == "insufficient_data":
        return "insufficient_data", (
            "At least one series has too few real observations for its own stationarity "
            "tests to run, so its integration order is unknown."
        )

    if dependent_consensus == "mixed_evidence" or independent_consensus == "mixed_evidence":
        return "insufficient_data", (
            "At least one series' own stationarity tests disagree with each other — its real "
            "integration order is genuinely ambiguous, not just unmeasured."
        )

    if dependent_consensus == "non_stationary" and independent_consensus == "non_stationary":
        return "johansen_vecm", (
            "Both series are non-stationary in levels (I(1)) — §30 step 2's \"all I(1)\" case."
        )

    return "ardl_bounds_test", (
        "At least one series is stationary in levels (I(0)) — a mixed I(0)/I(1) pair (or two "
        "I(0) series, which the bounds test also handles by design) uses this project's own "
        "disclosed default estimator."
    )
