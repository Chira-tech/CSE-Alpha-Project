from __future__ import annotations

import pytest

from app.domain.provenance import can_enter_valuation, weakest
from app.models.enums import ProvenanceTier as PT


def test_weakest_of_mixed_tiers_is_estimated():
    assert weakest([PT.REPORTED, PT.DERIVED, PT.ESTIMATED]) is PT.ESTIMATED


def test_weakest_all_reported_is_reported():
    assert weakest([PT.REPORTED, PT.REPORTED]) is PT.REPORTED


def test_weakest_empty_raises():
    with pytest.raises(ValueError):
        weakest([])


def test_unavailable_beats_everything_as_worst():
    assert weakest([PT.REPORTED, PT.UNAVAILABLE, PT.DERIVED]) is PT.UNAVAILABLE


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        (PT.REPORTED, True),
        (PT.DERIVED, True),
        (PT.NORMALISED, True),
        (PT.ESTIMATED, True),
        (PT.FORECAST, True),
        (PT.AI_ASSISTED, False),
        (PT.UNAVAILABLE, False),
    ],
)
def test_can_enter_valuation(tier: PT, expected: bool):
    assert can_enter_valuation(tier) is expected
