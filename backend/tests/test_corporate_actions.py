"""
Master Spec §7 worked examples, translated into tests. The bonus-issue case
is lifted directly from the spec's own illustration: "A single unadjusted
1:1 bonus issue creates a fake -50% return that a momentum model will read
as a signal" — we assert the adjustment factor exactly cancels that.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.domain.corporate_actions import (
    ActionKind,
    CorporateActionEvent,
    build_adjustment_factor_series,
    compute_terp,
    price_ratio_for_event,
    total_return_from_adjusted_prices,
)


def test_terp_matches_appendix_p1_formula():
    # TERP = (N * cum-rights price + S * subscription price) / (N + S)
    terp = compute_terp(
        shares_held_n=Decimal(4),
        shares_subscribed_s=Decimal(1),
        cum_rights_price=Decimal("100.00"),
        subscription_price=Decimal("50.00"),
    )
    expected = (Decimal(4) * Decimal("100.00") + Decimal(1) * Decimal("50.00")) / Decimal(5)
    assert terp == expected
    assert terp == Decimal("90.00")


def test_terp_rejects_zero_denominator():
    with pytest.raises(ValueError):
        compute_terp(Decimal(0), Decimal(0), Decimal("100"), Decimal("50"))


def test_1for1_bonus_issue_cancels_the_fake_halving():
    """A 1:1 bonus issue roughly halves the raw price with zero change in
    holder wealth. The adjustment factor for dates before the ex-date must
    scale those prices down by exactly 1/2 so that adjusted total return
    across the ex-date is ~0%, not the fake -50% the spec warns about.
    """
    ex_date = dt.date(2025, 6, 1)
    event = CorporateActionEvent(
        ex_date=ex_date, kind=ActionKind.BONUS_ISSUE, new_shares_per_held_share=Decimal(1)
    )
    ratio = price_ratio_for_event(event)
    assert ratio == Decimal("0.5")

    price_before = Decimal("100.00")  # last raw close before the bonus
    price_after = Decimal("50.00")  # first raw close after (mechanical halving, no real move)

    dates = [ex_date - dt.timedelta(days=1), ex_date]
    factors = build_adjustment_factor_series(dates, [event])
    assert factors[ex_date] == Decimal(1)
    assert factors[ex_date - dt.timedelta(days=1)] == Decimal("0.5")

    total_return = total_return_from_adjusted_prices(
        price_before, price_after, factors[ex_date - dt.timedelta(days=1)], factors[ex_date]
    )
    assert total_return == Decimal("0")  # not -50%


def test_cash_dividend_ratio_grosses_up_history():
    event = CorporateActionEvent(
        ex_date=dt.date(2025, 3, 15),
        kind=ActionKind.DIVIDEND_CASH,
        cash_amount=Decimal("2.00"),
        close_price_day_before_ex=Decimal("100.00"),
    )
    ratio = price_ratio_for_event(event)
    assert ratio == Decimal("0.98")


def test_cash_dividend_rejects_implausible_amount():
    event = CorporateActionEvent(
        ex_date=dt.date(2025, 3, 15),
        kind=ActionKind.DIVIDEND_CASH,
        cash_amount=Decimal("150.00"),
        close_price_day_before_ex=Decimal("100.00"),
    )
    with pytest.raises(ValueError):
        price_ratio_for_event(event)


def test_rights_issue_uses_terp_not_simple_adjustment():
    event = CorporateActionEvent(
        ex_date=dt.date(2025, 9, 1),
        kind=ActionKind.RIGHTS_ISSUE,
        shares_held_n=Decimal(4),
        shares_subscribed_s=Decimal(1),
        subscription_price=Decimal("50.00"),
        cum_rights_price=Decimal("100.00"),
    )
    ratio = price_ratio_for_event(event)
    # TERP = 90.00, cum-rights price = 100.00 -> ratio = 0.9
    assert ratio == Decimal("0.9")


def test_consolidation_scales_history_up():
    # 5-for-1 consolidation: 5 old shares become 1 new share.
    event = CorporateActionEvent(
        ex_date=dt.date(2025, 1, 1), kind=ActionKind.CONSOLIDATION, old_shares_per_new_share=Decimal(5)
    )
    assert price_ratio_for_event(event) == Decimal(5)


def test_multiple_actions_compound_correctly_regardless_of_input_order():
    d0 = dt.date(2024, 1, 1)
    bonus = CorporateActionEvent(
        ex_date=dt.date(2024, 6, 1), kind=ActionKind.BONUS_ISSUE, new_shares_per_held_share=Decimal(1)
    )
    dividend = CorporateActionEvent(
        ex_date=dt.date(2024, 9, 1),
        kind=ActionKind.DIVIDEND_CASH,
        cash_amount=Decimal("5.00"),
        close_price_day_before_ex=Decimal("50.00"),
    )
    dates = [d0]

    factors_in_order = build_adjustment_factor_series(dates, [bonus, dividend])
    factors_reversed = build_adjustment_factor_series(dates, [dividend, bonus])

    expected = Decimal("0.5") * Decimal("0.9")
    assert factors_in_order[d0] == expected
    assert factors_reversed[d0] == expected


def test_action_on_or_after_a_date_does_not_affect_that_date():
    ex_date = dt.date(2024, 6, 1)
    event = CorporateActionEvent(
        ex_date=ex_date, kind=ActionKind.BONUS_ISSUE, new_shares_per_held_share=Decimal(1)
    )
    factors = build_adjustment_factor_series([ex_date, ex_date + dt.timedelta(days=1)], [event])
    assert factors[ex_date] == Decimal(1)
    assert factors[ex_date + dt.timedelta(days=1)] == Decimal(1)
