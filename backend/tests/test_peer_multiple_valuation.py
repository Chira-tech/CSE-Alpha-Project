"""§20.1 cross-sectional peer multiples — the "relative" anchor of last
resort (`app.domain.valuation_view.peer_multiples_for` /
`sector_relative_anchor_for`).

`cost_of_equity_for` is monkeypatched to a fixed Ke throughout, for the
same reason `test_valuation_view.py` does it: the Ke pipeline has its own
tests, and what is under test here is only the peer-multiple logic and
its wiring into `valuation_summary_for`.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.domain import valuation_view
from app.domain.cost_of_equity import CostOfEquityResult
from app.domain.valuation_view import (
    peer_multiples_for,
    sector_relative_anchor_for,
    valuation_summary_for,
)
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

FIRST_AVAILABLE = dt.date(2025, 6, 30)
AS_OF = dt.date(2026, 9, 2)
_NOW = dt.datetime(2026, 9, 2, tzinfo=dt.timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_ke(monkeypatch):
    def _fn(
        db, ticker, as_of=None, *,
        regime=None, universe_liquidity_ratios=None, universe_liquidity_percentiles=None,
    ):
        return CostOfEquityResult(
            ke=Decimal("0.15"), risk_free_rate=Decimal("0.10"), beta=Decimal("1.0"),
            erp_effective=Decimal("0.07"), beta_times_erp=Decimal("0.07"), size_premium=None,
            illiquidity_premium=None, implied_erp_cross_check=None, is_lower_bound=True,
            missing_components=(), note="stub",
        )
    monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fn)


def _peer(db, ticker, *, archetype, equity, revenue, shares, price):
    """A clean peer: one confirmed annual balance sheet + income
    statement, a share count, and a traded price — everything
    `peer_multiples_for` needs to read a P/B and a P/S off it."""
    db.add(Security(ticker=ticker, name=f"{ticker} PLC", archetype=archetype))
    for line, value in (("total_equity", equity), ("revenue", revenue), ("net_income", revenue / 10)):
        db.add(Fundamental(
            ticker=ticker, period_end=dt.date(2026, 3, 31), period_type="annual",
            first_available_date=FIRST_AVAILABLE, version=1, statement_line=line,
            value=value, provenance_tier=ProvenanceTier.REPORTED,
        ))
    db.add(FloatData(ticker=ticker, as_of=dt.date(2026, 1, 1), shares_issued=shares))
    db.add(PriceDaily(ticker=ticker, date=dt.date(2026, 9, 1), close=price, adj_factor=Decimal(1), fetched_at=_NOW))
    db.commit()


def _seed_consumer_peer_group(db, n=8):
    """`n` consumer names all trading at ~2x book and ~1x sales, so the
    archetype median is unambiguous and above `_PEER_GROUP_MIN`."""
    for i in range(n):
        _peer(
            db, f"PEER{i}.N0000", archetype="consumer",
            equity=Decimal(1000), revenue=Decimal(2000),
            shares=100, price=Decimal(20),  # mcap 2000 -> P/B 2.0, P/S 1.0
        )


def test_archetype_median_is_used_when_the_peer_group_is_deep_enough(db_session):
    _seed_consumer_peer_group(db_session, n=8)

    pm = peer_multiples_for(db_session, AS_OF)

    pb, pb_basis = pm.pb_for("consumer")
    ps, _ = pm.ps_for("consumer")
    assert pb == Decimal(2)
    assert ps == Decimal(1)
    assert "consumer peer median" in pb_basis


def test_thin_archetype_falls_back_to_the_whole_universe_median(db_session):
    _seed_consumer_peer_group(db_session, n=8)
    # A lone hotel name — one contributor, below _PEER_GROUP_MIN.
    _peer(
        db_session, "LONEHOTEL.N0000", archetype="hotel",
        equity=Decimal(500), revenue=Decimal(500), shares=100, price=Decimal(15),
    )

    pm = peer_multiples_for(db_session, AS_OF)
    pb, pb_basis = pm.pb_for("hotel")

    assert "whole-universe median" in pb_basis
    assert pb is not None


def test_a_company_with_only_a_revenue_line_still_gets_a_fair_value(db_session):
    """The core case: no confirmed annual ROE history, no computable DCF,
    no total_equity of its own — but a revenue line and a share count.
    Before §20.1 this was a permanent "Insufficient data" verdict."""
    _seed_consumer_peer_group(db_session, n=8)

    db_session.add(Security(ticker="TARGET.N0000", name="Target PLC", archetype="consumer"))
    db_session.add(Fundamental(
        ticker="TARGET.N0000", period_end=dt.date(2026, 3, 31), period_type="annual",
        first_available_date=FIRST_AVAILABLE, version=1, statement_line="revenue",
        value=Decimal(4000), provenance_tier=ProvenanceTier.REPORTED,
    ))
    db_session.add(FloatData(ticker="TARGET.N0000", as_of=dt.date(2026, 1, 1), shares_issued=100))
    db_session.add(PriceDaily(ticker="TARGET.N0000", date=dt.date(2026, 9, 1), close=Decimal(50), adj_factor=Decimal(1), fetched_at=_NOW))
    db_session.commit()

    pm = peer_multiples_for(db_session, AS_OF)
    anchor = sector_relative_anchor_for(db_session, "TARGET.N0000", "consumer", AS_OF, peer_multiples=pm)

    # peer P/S 1.0x x (revenue 4000 / 100 shares = 40/sh) = 40.
    assert anchor.fair_value_per_share == Decimal(40)
    assert anchor.basis and "peer P/S" in anchor.basis[0]

    summary = valuation_summary_for(
        db_session, "TARGET.N0000", "consumer", Decimal(50), AS_OF, universe_peer_multiples=pm
    )
    assert summary.triangulation.blended_fair_value_per_share == Decimal(40)
    assert summary.decision.verdict != "Insufficient data"
    # Single low-confidence anchor -> the decision engine must not let it
    # produce a high-confidence call.
    assert summary.decision.confidence == "low"
    assert summary.sector_relative.fair_value_per_share == Decimal(40)


def test_no_own_line_to_anchor_to_stays_insufficient(db_session):
    """A name with a share count and a price but not one confirmed
    balance-sheet or revenue line of its own genuinely cannot be valued
    off peers — the anchor is None, with a stated reason."""
    _seed_consumer_peer_group(db_session, n=8)
    db_session.add(Security(ticker="EMPTY.N0000", name="Empty PLC", archetype="consumer"))
    db_session.add(FloatData(ticker="EMPTY.N0000", as_of=dt.date(2026, 1, 1), shares_issued=100))
    db_session.commit()

    pm = peer_multiples_for(db_session, AS_OF)
    anchor = sector_relative_anchor_for(db_session, "EMPTY.N0000", "consumer", AS_OF, peer_multiples=pm)

    assert anchor.fair_value_per_share is None
    assert anchor.warnings


def test_peer_anchor_is_not_added_when_a_dcf_or_justified_pb_anchor_exists(db_session):
    """§20.1 is a fallback, not an extra vote — if the earnings/DCF path
    produced anything, the peer multiple must stay out of the blend."""
    _seed_consumer_peer_group(db_session, n=8)

    # A full, clean confirmed period for the target: ROE history + book
    # value, enough for Justified P/B to compute on its own.
    for period, fad in (
        (dt.date(2024, 3, 31), dt.date(2024, 6, 30)),
        (dt.date(2025, 3, 31), dt.date(2025, 6, 30)),
        (dt.date(2026, 3, 31), dt.date(2026, 6, 30)),
    ):
        for line, value in (("total_equity", Decimal(1000)), ("net_income", Decimal(150))):
            db_session.add(Fundamental(
                ticker="RICH.N0000", period_end=period, period_type="annual",
                first_available_date=fad, version=1, statement_line=line,
                value=value, provenance_tier=ProvenanceTier.REPORTED,
            ))
    db_session.add(Security(ticker="RICH.N0000", name="Rich PLC", archetype="consumer"))
    db_session.add(FloatData(ticker="RICH.N0000", as_of=dt.date(2026, 1, 1), shares_issued=100))
    db_session.add(PriceDaily(ticker="RICH.N0000", date=dt.date(2026, 9, 1), close=Decimal(12), adj_factor=Decimal(1), fetched_at=_NOW))
    db_session.commit()

    pm = peer_multiples_for(db_session, AS_OF)
    summary = valuation_summary_for(
        db_session, "RICH.N0000", "consumer", Decimal(12), AS_OF, universe_peer_multiples=pm
    )

    assert summary.sector_relative.fair_value_per_share is None
    assert summary.justified_pb.fair_value_per_share is not None
