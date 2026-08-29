"""
§29's hero variable — the equity earnings yield minus 364-day T-bill
spread — and the macro series layer underneath it.

The spec calls this "the single most powerful macro variable in the
system", and it feeds both the regime read and the cost of equity, so the
tests here lean on the two ways it could be silently wrong: mismatched
units, and pairing figures across dates that weren't both public yet.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.domain.macro import (
    SERIES_MARKET_PER,
    SERIES_TBILL_364D,
    compute_spread,
    earnings_yield_from_per,
)
from app.domain.macro_view import (
    CORE_TIER_MIN_COMPANIES_FOR_HERO_SPREAD,
    core_tier_hero_spread,
    current_spread,
    latest_observation,
    record_observation,
    risk_free_observation,
    spread_history,
)
from app.models.securities import Security


# --- pure arithmetic ----------------------------------------------------


def test_earnings_yield_is_the_reciprocal_of_pe():
    # Real figure from the CSE daily market summary: market P/E 11.4
    assert round(earnings_yield_from_per(Decimal("11.4")), 6) == Decimal("0.087719")


@pytest.mark.parametrize("per", [Decimal("0"), Decimal("-5")])
def test_non_positive_pe_has_no_earnings_yield(per):
    """A negative market P/E means aggregate losses — the reciprocal is
    not an earnings yield in any useful sense, and zero is a data error."""
    assert earnings_yield_from_per(per) is None


def test_spread_uses_real_figures():
    """Market P/E 11.4 (CSE, 14 Aug 2026) against a 10.2% 364-day T-bill
    (the level §2.3 records for that period) gives a NEGATIVE spread —
    equities yielding less than the risk-free alternative, which is the
    'equity as bond substitute' condition §29 is built around."""
    spread = compute_spread(
        obs_date=dt.date(2026, 8, 14),
        market_per=Decimal("11.4"),
        tbill_yield=Decimal("0.102"),
        tbill_obs_date=dt.date(2026, 8, 12),
        tbill_source="manual",
    )
    assert spread is not None
    assert round(spread.spread, 4) == Decimal("-0.0143")
    assert not spread.equities_cheap_versus_bills


def test_positive_spread_when_equities_out_yield_bills():
    spread = compute_spread(
        obs_date=dt.date(2026, 8, 14),
        market_per=Decimal("8.0"),  # 12.5% earnings yield
        tbill_yield=Decimal("0.09"),
        tbill_obs_date=dt.date(2026, 8, 12),
        tbill_source="manual",
    )
    assert spread.equities_cheap_versus_bills
    assert round(spread.spread, 4) == Decimal("0.0350")


def test_both_yields_are_fractions_not_percentages():
    """The unit trap: storing one side as 10.2 and the other as 0.0877
    would give a spread of about -10, i.e. -1000pp, which is nonsense but
    would still render as a number."""
    spread = compute_spread(
        obs_date=dt.date(2026, 8, 14),
        market_per=Decimal("11.4"),
        tbill_yield=Decimal("0.102"),
        tbill_obs_date=dt.date(2026, 8, 12),
        tbill_source="manual",
    )
    assert abs(spread.spread) < Decimal("1")
    assert abs(spread.earnings_yield) < Decimal("1")


# --- storage and point-in-time -----------------------------------------


def test_record_and_read_back(db_session):
    record_observation(
        db_session,
        series_id=SERIES_TBILL_364D,
        obs_date=dt.date(2026, 8, 12),
        value=Decimal("0.102"),
        source="manual",
    )
    row = latest_observation(db_session, SERIES_TBILL_364D)
    assert row is not None and row.value == Decimal("0.102")


def test_recording_the_same_date_updates_rather_than_duplicating(db_session):
    for value in ("0.102", "0.104"):
        record_observation(
            db_session,
            series_id=SERIES_TBILL_364D,
            obs_date=dt.date(2026, 8, 12),
            value=Decimal(value),
            source="manual",
        )
    assert latest_observation(db_session, SERIES_TBILL_364D).value == Decimal("0.104")


def test_observation_not_yet_public_is_invisible(db_session):
    """A CCPI figure for June released in July must not be visible in
    June — filing it under the observation date is the look-ahead §6
    forbids, which is why first_available_date is separate."""
    record_observation(
        db_session,
        series_id=SERIES_TBILL_364D,
        obs_date=dt.date(2026, 6, 30),
        value=Decimal("0.102"),
        first_available_date=dt.date(2026, 7, 15),
        source="manual",
    )
    assert latest_observation(db_session, SERIES_TBILL_364D, as_of=dt.date(2026, 7, 1)) is None
    assert latest_observation(db_session, SERIES_TBILL_364D, as_of=dt.date(2026, 7, 20)) is not None


def test_risk_free_returns_none_rather_than_substituting_another_tenor(db_session):
    """§17.1 Route A specifies the 364-day bill. Silently falling back to
    a 91-day rate would make every fair value in the system wrong in a
    way nothing downstream would catch."""
    record_observation(
        db_session,
        series_id="cbsl.tbill_91d",
        obs_date=dt.date(2026, 8, 12),
        value=Decimal("0.098"),
        source="manual",
    )
    assert risk_free_observation(db_session) is None


def test_spread_unavailable_until_both_inputs_exist(db_session):
    assert current_spread(db_session) is None

    record_observation(
        db_session,
        series_id=SERIES_MARKET_PER,
        obs_date=dt.date(2026, 8, 14),
        value=Decimal("11.4"),
        source="cse.lk",
    )
    assert current_spread(db_session) is None  # still no risk-free rate

    record_observation(
        db_session,
        series_id=SERIES_TBILL_364D,
        obs_date=dt.date(2026, 8, 12),
        value=Decimal("0.102"),
        source="manual",
    )
    assert current_spread(db_session) is not None


def test_history_pairs_each_day_with_the_rate_public_at_the_time(db_session):
    """Using today's T-bill rate against a historical earnings yield
    would rewrite history every time the rate moved."""
    record_observation(
        db_session,
        series_id=SERIES_TBILL_364D,
        obs_date=dt.date(2026, 8, 5),
        value=Decimal("0.095"),
        source="manual",
    )
    record_observation(
        db_session,
        series_id=SERIES_TBILL_364D,
        obs_date=dt.date(2026, 8, 12),
        value=Decimal("0.102"),
        source="manual",
    )
    for day, per in ((dt.date(2026, 8, 6), "11.0"), (dt.date(2026, 8, 14), "11.4")):
        record_observation(
            db_session,
            series_id=SERIES_MARKET_PER,
            obs_date=day,
            value=Decimal(per),
            source="cse.lk",
        )

    history = spread_history(db_session)
    assert len(history) == 2
    early, late = history
    assert early.tbill_yield == Decimal("0.095")  # the rate public on 6 Aug
    assert late.tbill_yield == Decimal("0.102")  # the later auction


def test_history_omits_days_before_any_rate_was_public(db_session):
    record_observation(
        db_session,
        series_id=SERIES_MARKET_PER,
        obs_date=dt.date(2026, 8, 1),
        value=Decimal("11.0"),
        source="cse.lk",
    )
    record_observation(
        db_session,
        series_id=SERIES_TBILL_364D,
        obs_date=dt.date(2026, 8, 12),
        value=Decimal("0.102"),
        source="manual",
    )
    # 1 Aug predates the only rate we have — omitted, not back-filled.
    assert spread_history(db_session) == []


# --- API ----------------------------------------------------------------


def test_endpoint_reports_what_is_missing_rather_than_a_zero(db_session, client):
    body = client.get("/market/spread").json()
    assert body["available"] is False
    assert body["spread"] is None
    assert len(body["missing"]) == 2
    assert any("T-bill" in m for m in body["missing"])


def test_endpoint_returns_the_spread_once_both_inputs_exist(db_session, client):
    record_observation(
        db_session,
        series_id=SERIES_MARKET_PER,
        obs_date=dt.date(2026, 8, 14),
        value=Decimal("11.4"),
        source="cse.lk",
    )
    record_observation(
        db_session,
        series_id=SERIES_TBILL_364D,
        obs_date=dt.date(2026, 8, 12),
        value=Decimal("0.102"),
        source="manual: CBSL weekly auction",
    )

    body = client.get("/market/spread").json()
    assert body["available"] is True
    assert round(Decimal(body["spread"]), 4) == Decimal("-0.0143")
    # provenance of a manually-entered rate must reach the caller
    assert "manual" in body["tbill_source"]
    # TASK 3.3: the Core-tier-restricted read rides alongside the
    # exchange-wide one, never replacing it — honestly unavailable today.
    assert body["core_tier_available"] is False
    assert body["core_tier_market_earnings_yield"] is None
    assert "Gate 2" in body["core_tier_note"]


def test_endpoint_reports_core_tier_gating_even_when_the_main_spread_is_unavailable(db_session, client):
    """The Core-tier read is independent of whether the exchange-wide
    spread's own two inputs exist — a caller must be able to see WHY the
    Core-tier chart is gated even on a day the main spread itself can't
    be computed."""
    body = client.get("/market/spread").json()
    assert body["available"] is False
    assert body["core_tier_available"] is False
    assert body["core_tier_company_count"] == 0
    assert body["core_tier_required_company_count"] == 100


class TestCoreTierHeroSpread:
    """TASK 3.3 (product-owner brief): the OWN Core-tier-aggregate hero
    spread, gated until >=100 real Core-tier companies exist — distinct
    from `current_spread`'s exchange-published whole-market figure."""

    def test_reports_unavailable_with_the_real_reason_and_count(self, db_session):
        result = core_tier_hero_spread(db_session)

        assert result.available is False
        assert result.market_earnings_yield is None
        assert result.core_tier_company_count == 0
        assert result.required_company_count == CORE_TIER_MIN_COMPANIES_FOR_HERO_SPREAD
        assert "Gate 2" in result.note
        assert "free-float" in result.note
        assert "currently 0" in result.note

    def test_result_is_independent_of_the_real_universe_size(self, db_session):
        """A real, current fact — not one this function happens not to
        check: adding real securities to the database must not change
        the Core-tier count, because Gate 2 fails unconditionally on
        every one of them (no free-float data source exists at all)."""
        db_session.add(Security(ticker="AEL.N0000", name="Access Engineering PLC"))
        db_session.add(Security(ticker="COMB.N0000", name="Commercial Bank of Ceylon PLC"))
        db_session.commit()

        result = core_tier_hero_spread(db_session)
        assert result.core_tier_company_count == 0
        assert result.available is False
