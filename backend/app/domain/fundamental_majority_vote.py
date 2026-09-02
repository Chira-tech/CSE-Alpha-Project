"""Spec §3-4: independent-source verification and the three-source
majority rule, as a pure function.

A stored CSE value is the PRIMARY. Zero or more corroborators are
independent readings of the same (company, period, line) — a third-party
financial database, or the same figure re-typed by the company in a
later filing's comparative column. `resolve` buckets the values within a
tolerance and reports:

  - `agreed_value` — the figure at least two sources agree on (the
    primary if it is in that bucket; otherwise the corroborators'
    figure, which §4 makes the provisional validated value even when it
    disagrees with the primary).
  - `supporting` / `conflicting` — the source labels on each side, so the
    disagreement is always recorded (spec §4, §15).
  - `unresolved` — true when no two sources agree; §4 says such a value
    must not be used until a human resolves it.

Pure: no I/O, no DB. `app.domain.fundamental_validation_view` supplies
the corroborators and acts on the result.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: Two figures within this fraction of the larger are "the same source
#: value" — third-party databases round differently and carry JS float
#: artifacts (`scripts/external_crosscheck.py` sees 67316914000.00001).
DEFAULT_AGREEMENT_TOLERANCE = Decimal("0.005")  # 0.5%

PRIMARY_LABEL = "CSE (stored)"


@dataclass(frozen=True)
class Resolution:
    agreed_value: Decimal | None
    supporting: tuple[str, ...]
    conflicting: tuple[str, ...]
    unresolved: bool

    @property
    def primary_is_corroborated(self) -> bool:
        """The stored CSE value is the one two-plus sources agree on."""
        return not self.unresolved and PRIMARY_LABEL in self.supporting


def _close(a: Decimal, b: Decimal, tol: Decimal) -> bool:
    hi = max(abs(a), abs(b))
    if hi == 0:
        return a == b
    return abs(a - b) / hi <= tol


def resolve(
    primary: Decimal,
    corroborators: list[tuple[str, Decimal]],
    *,
    tolerance: Decimal = DEFAULT_AGREEMENT_TOLERANCE,
) -> Resolution:
    """`corroborators` is `[(source_label, value), ...]`, each an
    independent reading. Returns the majority `Resolution`."""
    labelled: list[tuple[str, Decimal]] = [(PRIMARY_LABEL, primary), *corroborators]

    # Greedy buckets: each value joins the first bucket it is close to.
    buckets: list[list[tuple[str, Decimal]]] = []
    for label, value in labelled:
        for bucket in buckets:
            if _close(bucket[0][1], value, tolerance):
                bucket.append((label, value))
                break
        else:
            buckets.append([(label, value)])

    biggest = max(buckets, key=len)
    if len(biggest) < 2:
        # Nobody agrees with anybody — every source stands alone.
        return Resolution(
            agreed_value=None,
            supporting=(),
            conflicting=tuple(label for label, _ in labelled),
            unresolved=True,
        )

    supporting = tuple(label for label, _ in biggest)
    conflicting = tuple(
        label for label, _ in labelled if label not in supporting
    )
    return Resolution(
        agreed_value=biggest[0][1],
        supporting=supporting,
        conflicting=conflicting,
        unresolved=False,
    )
