"""Spec §3-4 majority vote — `app.domain.fundamental_majority_vote.resolve`."""
from __future__ import annotations

from decimal import Decimal

from app.domain.fundamental_majority_vote import PRIMARY_LABEL, resolve


def test_primary_and_one_external_agreeing_is_accepted():
    r = resolve(Decimal("10_000_000"), [("stockanalysis.com", Decimal("10_004_000"))])
    assert not r.unresolved
    assert r.primary_is_corroborated
    assert r.agreed_value == Decimal("10_000_000")
    assert set(r.supporting) == {PRIMARY_LABEL, "stockanalysis.com"}


def test_two_externals_agree_against_the_primary(cse_disagrees=None):
    # Spec §4's worked example: CSE 12M, two externals 10M -> 10M.
    r = resolve(
        Decimal("12_000_000"),
        [("src2", Decimal("10_000_000")), ("src3", Decimal("10_010_000"))],
    )
    assert not r.unresolved
    assert not r.primary_is_corroborated
    assert r.agreed_value == Decimal("10_000_000")
    assert set(r.supporting) == {"src2", "src3"}
    assert PRIMARY_LABEL in r.conflicting


def test_all_three_disagree_is_unresolved():
    r = resolve(
        Decimal("10_000_000"),
        [("src2", Decimal("12_000_000")), ("src3", Decimal("15_000_000"))],
    )
    assert r.unresolved
    assert r.agreed_value is None
    assert PRIMARY_LABEL in r.conflicting


def test_primary_alone_is_unresolved():
    r = resolve(Decimal("10_000_000"), [])
    assert r.unresolved


def test_a_single_disagreeing_external_is_unresolved_not_accepted():
    r = resolve(Decimal("10_000_000"), [("stockanalysis.com", Decimal("13_000_000"))])
    assert r.unresolved
    assert not r.primary_is_corroborated
