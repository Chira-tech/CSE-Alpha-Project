"""`scripts.universe_verdict_diff.diff_payloads` — the pure before/after
diff for `docs/CSE_Universe_Integrity_Rollout.md` Phase 4. Exercised on
crafted payloads so it needs no full universe recompute.
"""
from __future__ import annotations

import datetime as dt

from scripts.universe_verdict_diff import diff_payloads
from scripts.backfill_trading_status import _classify


def _payload(ranked, excluded=()):
    return {
        "as_of": "2026-08-31",
        "ranked": [
            {"ticker": t, "verdict": v, "total_score": s} for (t, v, s) in ranked
        ],
        "excluded": [
            {"ticker": t, "verdict": v, "total_score": None, "warnings": [w]}
            for (t, v, w) in excluded
        ],
    }


class TestDiffPayloads:
    def test_verdict_change_is_reported_with_both_scores(self):
        before = _payload([("AAA.N0000", "Buy", "70")])
        after = _payload([("AAA.N0000", "Hold", "58")])
        d = diff_payloads(before, after)
        assert d["verdict_changed"] == [["AAA.N0000", "Buy → Hold", "+70.0", "+58.0"]]

    def test_a_name_dropping_into_excluded_is_reported_with_its_reason(self):
        before = _payload([("BBB.N0000", "Strong Buy", "88")])
        after = _payload([], excluded=[("BBB.N0000", "Withheld", "BBB.N0000 is quarantined — suspended")])
        d = diff_payloads(before, after)
        assert d["newly_excluded"][0][0] == "BBB.N0000"
        assert "suspended" in d["newly_excluded"][0][2]
        assert d["verdict_changed"] == []

    def test_a_name_entering_the_ranked_set_is_reported(self):
        before = _payload([])
        after = _payload([("CCC.N0000", "Accumulate", "66")])
        d = diff_payloads(before, after)
        assert d["newly_included"] == [["CCC.N0000", "Accumulate", "+66.0"]]

    def test_small_score_moves_are_not_movers_large_ones_are(self):
        before = _payload([("D.N0000", "Hold", "50"), ("E.N0000", "Hold", "50")])
        after = _payload([("D.N0000", "Hold", "52"), ("E.N0000", "Hold", "61")])
        d = diff_payloads(before, after)
        tickers = [row[0] for row in d["score_movers"]]
        assert tickers == ["E.N0000"]  # +11 is a mover, +2 is not

    def test_no_changes_is_all_empty(self):
        p = _payload([("F.N0000", "Buy", "70")])
        d = diff_payloads(p, p)
        assert d == {
            "verdict_changed": [],
            "newly_excluded": [],
            "newly_included": [],
            "score_movers": [],
        }


class TestTradingStatusClassify:
    _TODAY = dt.date(2026, 8, 31)

    def test_a_delisting_date_wins_outright(self):
        assert _classify(dt.date(2020, 1, 1), self._TODAY, self._TODAY) == "delisted"

    def test_a_long_trade_gap_is_suspended(self):
        assert _classify(None, self._TODAY - dt.timedelta(days=120), self._TODAY) == "suspended"

    def test_a_recent_trade_is_active(self):
        assert _classify(None, self._TODAY - dt.timedelta(days=5), self._TODAY) == "active"

    def test_no_price_history_at_all_stays_active(self):
        # handled by other checks (UNRESOLVED / no-price warnings), not marked suspended here
        assert _classify(None, None, self._TODAY) == "active"
