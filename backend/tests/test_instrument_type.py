"""
Instrument-type classification from CSE symbols.

Every symbol below is real, taken from `allSecurityCode` and
`tradeSummary` on 17 August 2026.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.coverage_gates import Gate2Inputs, evaluate_gate2_structural
from app.domain.instrument_type import (
    InstrumentType,
    classify,
    is_common_equity,
    is_primary_line,
    issuer_code,
)


class TestClassification:
    @pytest.mark.parametrize(
        ("symbol", "expected"),
        [
            ("COMB.N0000", InstrumentType.ORDINARY),
            ("COMB.X0000", InstrumentType.NON_VOTING),
            ("AAF.P0000", InstrumentType.PREFERENCE),
            ("BOC.D0000", InstrumentType.DEBENTURE),
            ("AAF.R0000", InstrumentType.RIGHTS),
            ("CALC.U0000", InstrumentType.UNIT),
            ("SHL.W0000", InstrumentType.WARRANT),
        ],
    )
    def test_real_symbols_classify_by_suffix(self, symbol, expected):
        assert classify(symbol) == expected

    @pytest.mark.parametrize("symbol", ["SLFL", "AFIN", "MIFL", "SIC"])
    def test_suffixless_codes_are_unknown_not_ordinary(self, symbol):
        """These four exist in allSecurityCode but `companyInfoSummery`
        returns no ISIN, par value or shares issued for them. Defaulting
        an unrecognised code to ORDINARY would admit them — and every
        future letter the exchange invents — straight into the investable
        universe."""
        assert classify(symbol) is InstrumentType.UNKNOWN
        assert not is_common_equity(symbol)

    def test_an_unseen_suffix_letter_is_unknown(self):
        assert classify("XYZ.Q0000") is InstrumentType.UNKNOWN

    def test_serial_suffixes_beyond_zero_still_classify(self):
        """HNB Finance listed two concurrent rights lines, R0000 and
        R0001."""
        assert classify("HNBF.R0001") is InstrumentType.RIGHTS


class TestIssuerGrouping:
    def test_voting_and_non_voting_lines_share_an_issuer(self):
        """The exchange's own ISINs agree: LK0053N00005 and LK0053X00004.
        Without this, Commercial Bank is two companies — it appears twice
        on a screen, and the §27.1 single-issuer concentration cap counts
        one bank as two positions."""
        assert issuer_code("COMB.N0000") == issuer_code("COMB.X0000") == "COMB"

    def test_every_line_of_an_issuer_groups_together(self):
        lines = ["MBSL.P0000", "MBSL.R0001", "MBSL.N0000"]
        assert {issuer_code(s) for s in lines} == {"MBSL"}

    def test_a_suffixless_code_is_its_own_issuer(self):
        assert issuer_code("SLFL") == "SLFL"

    def test_case_and_whitespace_are_normalised(self):
        assert issuer_code(" comb.n0000 ") == "COMB"
        assert classify(" comb.n0000 ") is InstrumentType.ORDINARY


class TestEquityEligibility:
    def test_non_voting_shares_are_investable(self):
        """COMB.X, HNB.X and SEYB.X are liquid, genuine equity in the same
        company. Excluding them would drop real investable universe — the
        problem they cause is double-counting an issuer, not ineligibility."""
        assert is_common_equity("COMB.X0000")

    def test_but_non_voting_is_not_the_primary_line(self):
        assert is_primary_line("COMB.N0000")
        assert not is_primary_line("COMB.X0000")

    @pytest.mark.parametrize(
        "symbol", ["AAF.P0000", "BOC.D0000", "AAF.R0000", "CALC.U0000", "SHL.W0000"]
    )
    def test_non_equity_lines_are_excluded(self, symbol):
        assert not is_common_equity(symbol)


class TestGate2:
    def _passing_inputs(self, **overrides):
        base = dict(
            free_float_pct=Decimal("0.40"),
            on_watch_list=False,
            trading_suspended=False,
            months_listed=60,
            market_cap_lkr=Decimal("5000000000"),
            consecutive_quarters_history=12,
        )
        base.update(overrides)
        return Gate2Inputs(**base)

    def test_an_ordinary_share_still_passes(self):
        assert evaluate_gate2_structural(self._passing_inputs()).passed

    def test_a_fund_unit_fails_even_with_perfect_metrics(self):
        """CALC.U0000 traded in the real universe. Its metrics can look
        fine; it is still a fund, and a P/E for it is a category error."""
        result = evaluate_gate2_structural(
            self._passing_inputs(instrument_type=InstrumentType.UNIT)
        )
        assert not result.passed
        assert result.reasons_failed == (
            "not common equity — unit lines are outside the investable universe",
        )

    def test_the_non_equity_reason_replaces_rather_than_joins_the_others(self):
        """A rights line has no free float and no reporting history, so it
        would otherwise collect a list of failures implying it might
        qualify once the data improves. It never will."""
        result = evaluate_gate2_structural(
            Gate2Inputs(
                instrument_type=InstrumentType.RIGHTS,
                free_float_pct=None,
                on_watch_list=False,
                trading_suspended=False,
                months_listed=0,
                market_cap_lkr=None,
                consecutive_quarters_history=0,
            )
        )
        assert len(result.reasons_failed) == 1
        assert "rights" in result.reasons_failed[0]

    def test_non_voting_passes_the_instrument_check(self):
        assert evaluate_gate2_structural(
            self._passing_inputs(instrument_type=InstrumentType.NON_VOTING)
        ).passed

    def test_unknown_instrument_fails_closed(self):
        assert not evaluate_gate2_structural(
            self._passing_inputs(instrument_type=InstrumentType.UNKNOWN)
        ).passed

    def test_default_is_ordinary_so_existing_callers_are_unaffected(self):
        """The field is keyword-only with a default precisely so adding it
        could not silently change the meaning of existing positional
        construction elsewhere."""
        assert Gate2Inputs(
            free_float_pct=Decimal("0.40"),
            on_watch_list=False,
            trading_suspended=False,
            months_listed=60,
            market_cap_lkr=Decimal("5000000000"),
            consecutive_quarters_history=12,
        ).instrument_type is InstrumentType.ORDINARY
