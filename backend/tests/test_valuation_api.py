"""GET /valuation/{ticker} — the full API-layer wiring, not just the
domain functions test_valuation_view.py already covers. Exists mainly to
catch Pydantic-serialization bugs at the domain-to-API boundary (a
dict-key-type mismatch, a missing field on `from_summary`, ...) that a
purely domain-level test can't see, since it never actually constructs
the response model.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.macro import MacroSeries
from app.models.securities import Security


def test_unknown_ticker_returns_404(client):
    r = client.get("/valuation/NOPE.N0000")
    assert r.status_code == 404


def test_fresh_ticker_with_no_data_still_returns_200_with_honest_nulls(client, db_session):
    db_session.add(Security(ticker="FRESH.N0000", name="Fresh PLC"))
    db_session.commit()

    r = client.get("/valuation/FRESH.N0000")
    assert r.status_code == 200
    body = r.json()

    assert body["ticker"] == "FRESH.N0000"
    assert body["regime"]["label"] is None
    assert body["regime"]["probabilities"] is None
    assert body["regime"]["signals"] == []
    assert len(body["regime"]["missing_signals"]) > 0
    assert len(body["regime"]["warnings"]) > 0
    assert body["dcf"]["fair_value_per_share"] is None
    assert body["hard_book"]["hard_book_value"] is None
    assert body["gordon_growth_ddm"]["value_per_share"] is None
    assert body["relative_valuation"]["justified_price_to_earnings"] is None
    assert body["relative_valuation"]["fair_value_per_share_pe"] is None
    assert len(body["relative_valuation"]["warnings"]) > 0


def test_regime_signals_surface_through_the_full_response(client, db_session):
    """A real (if partial) regime read reaches the HTTP response with
    correctly-typed fields — specifically the `probabilities` dict,
    whose keys are `RegimeLabel` (a `Literal[str]`) on the domain side
    and must round-trip through Pydantic/JSON as plain strings without
    error."""
    db_session.add(Security(ticker="MACRO.N0000", name="Macro Test PLC"))
    db_session.add_all(
        [
            MacroSeries(
                series_id="cbsl.policy_rate", obs_date=dt.date(2026, 5, 1),
                first_available_date=dt.date(2026, 5, 1), value=Decimal("0.0775"), source="manual",
            ),
            MacroSeries(
                series_id="cbsl.policy_rate", obs_date=dt.date(2026, 7, 1),
                first_available_date=dt.date(2026, 7, 1), value=Decimal("0.0875"), source="manual",
            ),
        ]
    )
    db_session.commit()

    r = client.get("/valuation/MACRO.N0000")
    assert r.status_code == 200
    body = r.json()
    assert body["regime"]["label"] == "risk_off"
    # Decimal fields serialize as JSON strings (FastAPI's default Decimal
    # encoding), not floats — compared via Decimal(), not a literal 1.0.
    assert Decimal(body["regime"]["probabilities"]["risk_off"]) == Decimal(1)
    assert any(s["name"] == "Policy rate direction" for s in body["regime"]["signals"])


def _seed_dcf_ready_ticker(db_session, monkeypatch, ticker="SCEN.N0000"):
    from app.domain import valuation_view
    from app.domain.cost_of_equity import CostOfEquityResult
    from app.models.float_data import FloatData

    def _fake_ke(db, t, as_of=None, *, regime=None, universe_liquidity_ratios=None, universe_liquidity_percentiles=None):
        return CostOfEquityResult(
            ke=Decimal("0.15"), risk_free_rate=Decimal("0.12"), beta=Decimal("1.0"),
            erp_effective=Decimal("0.07"), beta_times_erp=Decimal("0.07"), size_premium=None,
            illiquidity_premium=None, implied_erp_cross_check=None, is_lower_bound=True,
            missing_components=(), note="stub",
        )
    monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke)

    db_session.add(Security(ticker=ticker, name="Scenario Test PLC"))
    period_end = dt.date(2021, 12, 31)
    first_available = dt.date(2022, 3, 7)
    lines = {
        "revenue": Decimal(10000),
        "operating_profit": Decimal(1000),
        "profit_before_tax": Decimal(900),
        "income_tax_expense": Decimal(-252),
        "depreciation_and_amortisation": Decimal(50),
        "capital_expenditure": Decimal(-80),
        "net_working_capital": Decimal(500),
        "total_interest_bearing_debt": Decimal(500),
        "interest_expense": Decimal(50),
    }
    db_session.add_all(
        Fundamental(
            ticker=ticker, period_end=period_end, period_type="annual",
            first_available_date=first_available, version=1, statement_line=line,
            value=value, provenance_tier=ProvenanceTier.REPORTED,
        )
        for line, value in lines.items()
    )
    db_session.add(FloatData(ticker=ticker, as_of=dt.date(2022, 1, 1), shares_issued=100))
    from app.models.prices import PriceDaily

    db_session.add(
        PriceDaily(
            ticker=ticker, date=dt.date(2022, 3, 1), close=Decimal(20), adj_factor=Decimal(1),
            fetched_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db_session.commit()


def test_scenarios_endpoint_returns_a_real_bear_base_bull_spread(client, db_session, monkeypatch):
    _seed_dcf_ready_ticker(db_session, monkeypatch)
    r = client.get("/valuation/SCEN.N0000/scenarios")
    assert r.status_code == 200
    body = r.json()
    assert body["scenarios"] is not None
    bear = Decimal(body["scenarios"]["bear_value_per_share"])
    base = Decimal(body["scenarios"]["base_value_per_share"])
    bull = Decimal(body["scenarios"]["bull_value_per_share"])
    assert bear < base < bull


def test_scenarios_endpoint_404s_for_unknown_ticker(client):
    r = client.get("/valuation/NOPE.N0000/scenarios")
    assert r.status_code == 404


def test_tornado_endpoint_returns_bars_sorted_widest_first(client, db_session, monkeypatch):
    _seed_dcf_ready_ticker(db_session, monkeypatch)
    r = client.get("/valuation/SCEN.N0000/tornado")
    assert r.status_code == 200
    body = r.json()
    spreads = [Decimal(bar["spread"]) for bar in body["bars"]]
    assert spreads == sorted(spreads, reverse=True)
    assert len(body["bars"]) == 4


def test_monte_carlo_endpoint_returns_percentiles(client, db_session, monkeypatch):
    _seed_dcf_ready_ticker(db_session, monkeypatch)
    r = client.get("/valuation/SCEN.N0000/monte-carlo")
    assert r.status_code == 200
    body = r.json()
    assert body["draws"] == 10_000
    assert Decimal(body["p10"]) <= Decimal(body["p50"]) <= Decimal(body["p90"])
