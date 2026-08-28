from decimal import Decimal

from app.domain.fundamental_cross_check import (
    FilingFacts,
    evaluate_filing,
)


def _balanced_bs() -> dict[str, Decimal]:
    """A balance sheet that satisfies every computable identity."""
    return {
        "total_assets": Decimal("1000000000"),
        "total_equity": Decimal("600000000"),
        "total_liabilities": Decimal("400000000"),
        "total_equity_and_liabilities": Decimal("1000000000"),
        "total_current_assets": Decimal("300000000"),
        "total_non_current_assets": Decimal("700000000"),
        "total_current_liabilities": Decimal("250000000"),
        "total_non_current_liabilities": Decimal("150000000"),
        "inventories": Decimal("80000000"),
        "trade_receivables": Decimal("90000000"),
        "trade_payables": Decimal("70000000"),
    }


def _facts(values, **kw) -> FilingFacts:
    base = dict(
        ticker="TEST.N0000",
        period_end="2024-03-31",
        period_type="annual",
        values=values,
    )
    base.update(kw)
    return FilingFacts(**base)


def _verdict(facts, line):
    return next(v for v in evaluate_filing(facts) if v.statement_line == line)


class TestSignalS1Identities:
    def test_balanced_filing_earns_s1_for_identity_member_lines(self):
        v = _verdict(_facts(_balanced_bs()), "total_assets")
        assert "S1_identities" in v.signals

    def test_a_line_in_no_identity_never_earns_s1(self):
        v = _verdict(_facts(_balanced_bs()), "inventories")
        assert "S1_identities" not in v.signals

    def test_rounding_slop_still_passes_s1_but_a_real_break_does_not(self):
        ok = _balanced_bs()
        ok["total_assets"] = Decimal("1000000500")  # Rs 500 over — publication rounding
        assert "S1_identities" in _verdict(_facts(ok), "total_equity").signals

        broken = _balanced_bs()
        broken["total_assets"] = Decimal("1050000000")  # Rs 50m over — a real break
        assert "S1_identities" not in _verdict(_facts(broken), "total_equity").signals


class TestSignalS2Reextract:
    def test_reextraction_reproducing_the_value_earns_s2(self):
        vals = _balanced_bs()
        facts = _facts(vals, reextracted_values=dict(vals))
        assert "S2_reextract" in _verdict(facts, "inventories").signals

    def test_a_different_reextraction_does_not(self):
        vals = _balanced_bs()
        fresh = dict(vals)
        fresh["inventories"] = Decimal("123456789")
        assert "S2_reextract" not in _verdict(_facts(vals, reextracted_values=fresh), "inventories").signals

    def test_no_reextraction_at_all_means_no_s2(self):
        assert "S2_reextract" not in _verdict(_facts(_balanced_bs()), "inventories").signals


class TestSignalS3CrossSource:
    def test_an_agreeing_independently_sourced_value_earns_s3(self):
        vals = _balanced_bs()
        facts = _facts(vals, cross_source_values={"inventories": [Decimal("80000400")]})  # within Rs 1000
        assert "S3_cross_source" in _verdict(facts, "inventories").signals

    def test_a_disagreeing_one_does_not(self):
        vals = _balanced_bs()
        facts = _facts(vals, cross_source_values={"inventories": [Decimal("11111111")]})
        assert "S3_cross_source" not in _verdict(facts, "inventories").signals


class TestSignalS5AnnualQuarterly:
    def test_annual_flow_equal_to_sum_of_four_quarters_earns_s5(self):
        vals = {"revenue": Decimal("400000000"), "total_assets": Decimal("2000000000")}
        facts = _facts(
            vals,
            quarterly_values={"revenue": [Decimal("100000000")] * 4},
            quarterly_period_count=4,
        )
        assert "S5_annual_quarterly" in _verdict(facts, "revenue").signals

    def test_a_stock_line_never_earns_s5_even_if_the_arithmetic_would_match(self):
        vals = {"inventories": Decimal("400000000"), "total_assets": Decimal("2000000000")}
        facts = _facts(
            vals,
            quarterly_values={"inventories": [Decimal("100000000")] * 4},
            quarterly_period_count=4,
        )
        assert "S5_annual_quarterly" not in _verdict(facts, "inventories").signals

    def test_fewer_than_four_quarters_means_no_s5(self):
        vals = {"revenue": Decimal("300000000"), "total_assets": Decimal("2000000000")}
        facts = _facts(
            vals,
            quarterly_values={"revenue": [Decimal("100000000")] * 3},
            quarterly_period_count=3,
        )
        assert "S5_annual_quarterly" not in _verdict(facts, "revenue").signals

    def test_s5_is_not_computed_for_a_quarterly_filing(self):
        vals = {"revenue": Decimal("100000000"), "total_assets": Decimal("2000000000")}
        facts = _facts(
            vals,
            period_type="quarterly",
            quarterly_values={"revenue": [Decimal("25000000")] * 4},
            quarterly_period_count=4,
        )
        assert "S5_annual_quarterly" not in _verdict(facts, "revenue").signals


class TestSignalS6DualListing:
    def test_matching_dual_listing_value_earns_s6(self):
        vals = _balanced_bs()
        facts = _facts(vals, dual_listing_values={"inventories": Decimal("80000000")})
        assert "S6_dual_listing" in _verdict(facts, "inventories").signals


class TestAutoConfirmRule:
    def test_two_signals_including_reextraction_and_no_veto_auto_confirms(self):
        vals = _balanced_bs()
        v = _verdict(_facts(vals, reextracted_values=dict(vals)), "total_assets")  # S1 + S2
        assert v.signals >= {"S1_identities", "S2_reextract"}
        assert v.auto_confirm is True

    def test_two_signals_but_no_reextraction_does_not_auto_confirm(self):
        vals = _balanced_bs()
        # S1 + S3, but no S2
        facts = _facts(vals, cross_source_values={"total_assets": [Decimal("1000000000")]})
        v = _verdict(facts, "total_assets")
        assert "S2_reextract" not in v.signals
        assert v.auto_confirm is False

    def test_a_single_signal_does_not_auto_confirm(self):
        vals = _balanced_bs()
        v = _verdict(_facts(vals, reextracted_values=dict(vals)), "inventories")  # S2 only
        assert v.signals == {"S2_reextract"}
        assert v.auto_confirm is False
        assert v.confidence == "medium"


class TestVetoes:
    def test_magnitude_flag_blocks_auto_confirm_even_with_three_signals(self):
        vals = _balanced_bs()
        vals["inventories"] = Decimal("3")  # a millionth of total_assets — V1
        fresh = dict(vals)
        facts = _facts(
            vals,
            reextracted_values=fresh,  # S2
            cross_source_values={"inventories": [Decimal("3")]},  # S3
            dual_listing_values={"inventories": Decimal("3")},  # S6
        )
        v = _verdict(facts, "inventories")
        assert "V1_magnitude" in v.vetoes
        assert v.auto_confirm is False

    def test_component_ceiling_breach_is_a_veto(self):
        vals = _balanced_bs()
        vals["inventories"] = Decimal("500000000")  # > total_current_assets 300m * 1.1
        fresh = dict(vals)
        facts = _facts(vals, reextracted_values=fresh, cross_source_values={"inventories": [Decimal("500000000")]})
        v = _verdict(facts, "inventories")
        assert "V2_ceiling" in v.vetoes
        assert v.auto_confirm is False

    def test_a_gross_period_over_period_jump_with_no_corroboration_is_a_veto(self):
        vals = _balanced_bs()
        fresh = dict(vals)
        facts = _facts(
            vals,
            reextracted_values=fresh,  # S1 + S2
            prior_period_values={"total_assets": Decimal("5000000")},  # 200x smaller
        )
        v = _verdict(facts, "total_assets")
        assert "V3_discontinuity" in v.vetoes
        assert v.auto_confirm is False

    def test_the_same_jump_is_tolerated_when_an_independent_source_agrees(self):
        vals = _balanced_bs()
        fresh = dict(vals)
        facts = _facts(
            vals,
            reextracted_values=fresh,
            cross_source_values={"total_assets": [Decimal("1000000000")]},  # S3 — corroborates
            prior_period_values={"total_assets": Decimal("5000000")},
        )
        v = _verdict(facts, "total_assets")
        assert "V3_discontinuity" not in v.vetoes
        assert v.auto_confirm is True

    def test_an_extraction_failure_marker_on_the_filing_vetoes_every_row(self):
        vals = _balanced_bs()
        facts = _facts(vals, reextracted_values=dict(vals), has_filing_failure_marker=True)
        assert all("V4_filing_marker" in v.vetoes for v in evaluate_filing(facts))
        assert not any(v.auto_confirm for v in evaluate_filing(facts))


class TestRegressionOnKnownBugShapes:
    def test_oi1_note_reference_value_is_never_auto_confirmed(self):
        """OI-1/OI-4: a note number stored as the value. Today's parser
        re-extracts the REAL (large) figure, so S2 fails against the
        stored small value; the magnitude floor also vetoes. Not
        auto-confirmable by any path."""
        vals = _balanced_bs()
        vals["revenue"] = Decimal("8")  # note reference "8"
        vals["gross_profit"] = Decimal("8")
        vals["cost_of_sales"] = Decimal("0")
        fresh = dict(vals)
        fresh["revenue"] = Decimal("261589819")  # what today's parser really gets
        facts = _facts(vals, reextracted_values=fresh)
        v = _verdict(facts, "revenue")
        assert v.auto_confirm is False
        assert "S2_reextract" not in v.signals

    def test_uniform_offset_error_passing_its_one_identity_is_not_auto_confirmed(self):
        """JAT Holdings' real net_income: pbt AND net_income both carried
        the same +200,000,000 offset, so `pbt - tax = net_income` still
        balances exactly, and today's parser reproduces the same reading —
        S1 and S2 are both earned. But net_income sits in only ONE
        identity, and S1+S2 both read the same extraction of the same
        filing, so auto-confirm additionally requires an external signal
        (S3/S5/S6) that this row does not have."""
        vals = {
            "profit_before_tax": Decimal("238401649"),
            "income_tax_expense": Decimal("0"),
            "net_income": Decimal("238401649"),
            "revenue": Decimal("3000000000"),
            "total_assets": Decimal("5000000000"),
        }
        fresh = dict(vals)
        facts = _facts(vals, reextracted_values=fresh)
        v = _verdict(facts, "net_income")
        assert v.signals >= {"S1_identities", "S2_reextract"}
        assert v.identity_count == 1
        assert v.auto_confirm is False

    def test_but_an_annual_quarterly_reconciliation_would_clear_that_same_row(self):
        """The safe path for a single-identity flow line: the four
        quarters must add up to it."""
        vals = {
            "profit_before_tax": Decimal("400000000"),
            "income_tax_expense": Decimal("0"),
            "net_income": Decimal("400000000"),
            "revenue": Decimal("3000000000"),
            "total_assets": Decimal("5000000000"),
        }
        facts = _facts(
            vals,
            reextracted_values=dict(vals),
            quarterly_values={"net_income": [Decimal("100000000")] * 4},
            quarterly_period_count=4,
        )
        v = _verdict(facts, "net_income")
        assert v.signals >= {"S1_identities", "S2_reextract", "S5_annual_quarterly"}
        assert v.auto_confirm is True
