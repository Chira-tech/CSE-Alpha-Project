"""
`app.domain.security_status_view` (the 4-state status) and
`app.domain.instrument_type_view` (primary-line resolution + confidence) —
`docs/CSE_Universe_Integrity_Rollout.md` §1.3 and Part 4.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from collections import Counter

from app.domain.instrument_type_view import BindingConfidence, resolve_primary_line
from app.domain.security_status_view import (
    SecurityStatus,
    security_status_for,
    universe_status_summary,
)
from app.models.data_quality import DataAlert
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

TODAY = dt.date(2026, 8, 30)
FETCHED = dt.datetime(2026, 8, 30, 15, 0, tzinfo=dt.timezone.utc)


def _sec(db, ticker, **kw):
    defaults = dict(name=ticker, issuer_code=ticker.split(".")[0], instrument_type="ordinary")
    defaults.update(kw)
    db.add(Security(ticker=ticker, **defaults))


def _fresh_price(db, ticker, days_ago=1):
    db.add(
        PriceDaily(
            ticker=ticker, date=TODAY - dt.timedelta(days=days_ago),
            close=Decimal("100"), fetched_at=FETCHED, source="cse.lk",
        )
    )


class TestResolvePrimaryLine:
    def test_single_ordinary_line_is_high_confidence(self, db_session):
        _sec(db_session, "COMB.N0000")
        db_session.commit()
        p = resolve_primary_line(db_session, "COMB", as_of=TODAY)
        assert p.ticker == "COMB.N0000" and p.confidence is BindingConfidence.HIGH

    def test_non_voting_only_is_medium_with_a_flag(self, db_session):
        _sec(db_session, "XYZ.X0000", instrument_type="non_voting")
        db_session.commit()
        p = resolve_primary_line(db_session, "XYZ", as_of=TODAY)
        assert p.ticker == "XYZ.X0000" and p.confidence is BindingConfidence.MEDIUM
        assert "NO_VOTING_LINE" in p.flags

    def test_multiple_voting_lines_pick_highest_turnover_at_low_confidence(self, db_session):
        _sec(db_session, "DUP.N0000")
        _sec(db_session, "DUP.N0001")
        db_session.add_all(
            [
                PriceDaily(ticker="DUP.N0000", date=TODAY - dt.timedelta(days=5), close=Decimal("10"),
                           turnover=Decimal("1000"), fetched_at=FETCHED, source="cse.lk"),
                PriceDaily(ticker="DUP.N0001", date=TODAY - dt.timedelta(days=5), close=Decimal("10"),
                           turnover=Decimal("999999"), fetched_at=FETCHED, source="cse.lk"),
            ]
        )
        db_session.commit()
        p = resolve_primary_line(db_session, "DUP", as_of=TODAY)
        assert p.ticker == "DUP.N0001" and p.confidence is BindingConfidence.LOW

    def test_rights_line_is_never_primary(self, db_session):
        _sec(db_session, "AAF.R0000", instrument_type="rights")
        db_session.commit()
        p = resolve_primary_line(db_session, "AAF", as_of=TODAY)
        assert p.ticker is None and p.confidence is BindingConfidence.NONE

    def test_a_delisted_line_is_not_eligible(self, db_session):
        _sec(db_session, "OLD.N0000", delisting_date=dt.date(2025, 1, 1))
        db_session.commit()
        assert resolve_primary_line(db_session, "OLD", as_of=TODAY).confidence is BindingConfidence.NONE


class TestSecurityStatus:
    def test_clean_when_nothing_is_wrong(self, db_session):
        _sec(db_session, "COMB.N0000")
        _fresh_price(db_session, "COMB.N0000")
        db_session.commit()
        v = security_status_for(db_session, "COMB.N0000", as_of=TODAY)
        assert v.status is SecurityStatus.CLEAN
        assert v.blockers == () and v.soft_flags == ()

    def test_unknown_instrument_type_is_unresolved(self, db_session):
        _sec(db_session, "SIC.N0000", instrument_type=None)
        db_session.commit()
        v = security_status_for(db_session, "SIC.N0000", as_of=TODAY)
        assert v.status is SecurityStatus.UNRESOLVED
        assert any("instrument type" in b for b in v.blockers)

    def test_fund_with_no_primary_line_is_unresolved(self, db_session):
        _sec(db_session, "CALC.U0000", instrument_type="unit")
        db_session.commit()
        v = security_status_for(db_session, "CALC.U0000", as_of=TODAY)
        assert v.status is SecurityStatus.UNRESOLVED

    def test_hard_alert_quarantines(self, db_session):
        _sec(db_session, "AAF.N0000")
        _fresh_price(db_session, "AAF.N0000")
        db_session.add(
            DataAlert(ticker="AAF.N0000", alert_type="wrong_line_fingerprint",
                      detail="bound series is the rights line", raised_at=FETCHED, resolved=False)
        )
        db_session.commit()
        v = security_status_for(db_session, "AAF.N0000", as_of=TODAY)
        assert v.status is SecurityStatus.QUARANTINED
        assert any("wrong_line_fingerprint" in b for b in v.blockers)

    def test_resolved_alert_does_not_quarantine(self, db_session):
        _sec(db_session, "AAF.N0000")
        _fresh_price(db_session, "AAF.N0000")
        db_session.add(
            DataAlert(ticker="AAF.N0000", alert_type="wrong_line_fingerprint", detail="fixed",
                      raised_at=FETCHED, resolved=True)
        )
        db_session.commit()
        assert security_status_for(db_session, "AAF.N0000", as_of=TODAY).status is SecurityStatus.CLEAN

    def test_stale_price_is_provisional_not_quarantined(self, db_session):
        _sec(db_session, "THIN.N0000")
        _fresh_price(db_session, "THIN.N0000", days_ago=40)
        db_session.commit()
        v = security_status_for(db_session, "THIN.N0000", as_of=TODAY)
        assert v.status is SecurityStatus.PROVISIONAL
        assert any("stale" in f for f in v.soft_flags)

    def test_trailing_net_loss_on_a_declining_trend_caps_the_verdict_at_hold(self, db_session):
        """Spec §Check 8 — the HDFC.N0000 shape."""
        _sec(db_session, "HDFC.N0000")
        _fresh_price(db_session, "HDFC.N0000")
        for year, ni in ((2021, "1200000000"), (2022, "600000000"), (2023, "150000000"),
                         (2024, "-40000000"), (2025, "-93000000")):
            db_session.add(
                Fundamental(
                    ticker="HDFC.N0000", period_end=dt.date(year, 12, 31), period_type="annual",
                    first_available_date=dt.date(year + 1, 3, 1), version=1,
                    statement_line="net_income", value=Decimal(ni),
                    provenance_tier=ProvenanceTier.REPORTED,
                )
            )
        db_session.commit()

        v = security_status_for(db_session, "HDFC.N0000", as_of=TODAY)
        assert v.status is SecurityStatus.PROVISIONAL
        assert v.verdict_cap == "hold"
        assert any("net LOSS" in f or "turnaround" in f.lower() for f in v.soft_flags)

    def test_a_profitable_declining_company_is_not_capped(self, db_session):
        _sec(db_session, "SLOW.N0000")
        _fresh_price(db_session, "SLOW.N0000")
        for year, ni in ((2023, "900000000"), (2024, "600000000"), (2025, "300000000")):
            db_session.add(
                Fundamental(
                    ticker="SLOW.N0000", period_end=dt.date(year, 12, 31), period_type="annual",
                    first_available_date=dt.date(year + 1, 3, 1), version=1,
                    statement_line="net_income", value=Decimal(ni),
                    provenance_tier=ProvenanceTier.REPORTED,
                )
            )
        db_session.commit()
        v = security_status_for(db_session, "SLOW.N0000", as_of=TODAY)
        assert v.verdict_cap is None
        assert v.status is SecurityStatus.CLEAN  # declining but still profitable — not a caveat

    def test_unconfirmed_core_line_is_provisional(self, db_session):
        _sec(db_session, "NEW.N0000")
        _fresh_price(db_session, "NEW.N0000")
        db_session.add(
            Fundamental(
                ticker="NEW.N0000", period_end=dt.date(2025, 12, 31), period_type="annual",
                first_available_date=dt.date(2026, 3, 1), version=1, statement_line="total_equity",
                value=Decimal("1000"), provenance_tier=ProvenanceTier.AI_ASSISTED,
            )
        )
        db_session.commit()
        v = security_status_for(db_session, "NEW.N0000", as_of=TODAY)
        assert v.status is SecurityStatus.PROVISIONAL

    def test_soft_alert_alone_is_provisional(self, db_session):
        _sec(db_session, "AAF.R0000", instrument_type="rights")
        db_session.add(
            PriceDaily(ticker="AAF.R0000", date=TODAY - dt.timedelta(days=2), close=Decimal("5"),
                       fetched_at=FETCHED, source="cse.lk")
        )
        # a rights line still needs a resolvable issuer primary line to
        # get past UNRESOLVED — give it an ordinary sibling.
        _sec(db_session, "AAF.N0000")
        _fresh_price(db_session, "AAF.N0000")
        db_session.add(
            DataAlert(ticker="AAF.R0000", alert_type="rights_line_expired",
                      detail="rights line, last trade 2 days ago", raised_at=FETCHED, resolved=False)
        )
        db_session.commit()
        v = security_status_for(db_session, "AAF.R0000", as_of=TODAY)
        assert v.status is SecurityStatus.PROVISIONAL


class TestUniverseStatusSummary:
    """`universe_status_summary` is the batched count behind the homepage
    trust bar. Its whole contract is "the same numbers as calling
    `security_status_for` for every ticker" — so the tests assert exactly
    that equivalence on a fixture covering all four states."""

    def _mixed_universe(self, db):
        # clean
        _sec(db, "COMB.N0000")
        _fresh_price(db, "COMB.N0000")
        # provisional — stale price
        _sec(db, "THIN.N0000")
        _fresh_price(db, "THIN.N0000", days_ago=40)
        # provisional — soft alert on a rights line with a resolvable sibling
        _sec(db, "AAF.N0000")
        _fresh_price(db, "AAF.N0000")
        _sec(db, "AAF.R0000", instrument_type="rights")
        _fresh_price(db, "AAF.R0000", days_ago=2)
        db.add(
            DataAlert(ticker="AAF.R0000", alert_type="rights_line_expired", detail="expired",
                      raised_at=FETCHED, resolved=False)
        )
        # quarantined — hard alert
        _sec(db, "JKH.N0000")
        _fresh_price(db, "JKH.N0000")
        db.add(
            DataAlert(ticker="JKH.N0000", alert_type="reconciliation_mismatch", detail="off",
                      raised_at=FETCHED, resolved=False)
        )
        # unresolved — unknown instrument type
        _sec(db, "SIC.N0000", instrument_type=None)
        # unresolved — unit with no primary line
        _sec(db, "CALC.U0000", instrument_type="unit")
        db.commit()

    def test_counts_equal_the_per_ticker_sweep(self, db_session):
        self._mixed_universe(db_session)
        tickers = [t for (t,) in db_session.query(Security.ticker).all()]
        expected = Counter(
            security_status_for(db_session, t, as_of=TODAY).status.value for t in tickers
        )
        s = universe_status_summary(db_session, as_of=TODAY)
        assert (s.clean, s.provisional, s.quarantined, s.unresolved) == (
            expected["clean"], expected["provisional"], expected["quarantined"], expected["unresolved"],
        )
        assert s.total == len(tickers) == s.clean + s.provisional + s.quarantined + s.unresolved

    def test_empty_universe_is_all_zeros(self, db_session):
        s = universe_status_summary(db_session, as_of=TODAY)
        assert (s.clean, s.provisional, s.quarantined, s.unresolved, s.total) == (0, 0, 0, 0, 0)
