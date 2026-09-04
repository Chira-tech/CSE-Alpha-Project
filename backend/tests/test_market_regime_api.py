"""GET /market/regime — API-layer wiring, including `history`/`history_note`
(4 Sep 2026: the Markov fit's per-day regime path, previously computed
and discarded every call — `.iloc[-1]` was the only row ever read out of
`result.smoothed_marginal_probabilities`). Same reasoning as
test_market_sector_sensitivity_api.py: catches a Pydantic-serialization
bug at the domain-to-API boundary a purely domain-level test can't see.
"""
from __future__ import annotations

import datetime as dt
import math
import random
from decimal import Decimal

from app.domain.macro import SERIES_ASPI
from app.models.macro import MacroSeries


def _seed_aspi(db, base: dt.date, days: int, seed: int) -> dt.date:
    rng = random.Random(seed)
    price = 13000.0
    obs_date = base
    for i in range(days):
        price *= math.exp(rng.gauss(0.0008, 0.008))
        obs_date = base + dt.timedelta(days=i)
        db.add(MacroSeries(
            series_id=SERIES_ASPI, obs_date=obs_date, first_available_date=obs_date,
            value=Decimal(str(round(price, 2))), source="test",
        ))
    db.commit()
    return obs_date


def test_no_data_returns_empty_history_with_a_reason(client):
    r = client.get("/market/regime")
    assert r.status_code == 200
    body = r.json()
    assert body["history"] == []
    assert "no statistical" in body["history_note"].lower()


def test_history_matches_the_statistical_fit_when_enough_real_data_exists(client, db_session):
    last = _seed_aspi(db_session, dt.date(2025, 1, 1), 250, seed=7)

    r = client.get("/market/regime")
    assert r.status_code == 200
    body = r.json()

    if body["sub_reads"] and any(s["kind"] == "markov" for s in body["sub_reads"]):
        # A real fit converged on this synthetic draw — history must be
        # populated, one entry per real trading day, correctly shaped and
        # chronologically ordered, ending on the last seeded date.
        assert len(body["history"]) >= 60
        dates = [pt["date"] for pt in body["history"]]
        assert dates == sorted(dates)
        assert dates[-1] == last.isoformat()
        assert all(pt["label"] in ("risk_on", "transition", "risk_off") for pt in body["history"])
        assert "statistical" in body["history_note"].lower()
    else:
        # A real, valid outcome on some synthetic draws (see
        # test_macro_engine_view.py's own note on this) — history must
        # then be honestly empty, not partially populated.
        assert body["history"] == []
