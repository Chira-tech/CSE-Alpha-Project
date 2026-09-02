"""app.domain.sanity — TASK 0.1's plausibility gate. Fixture values for
COMB.N0000 are its own real, confirmed numbers (18 Aug 2026): both the
implausible pre-TTM-fix figures and the corrected post-fix ones — the
real bug this gate defends against, not an invented example."""
from __future__ import annotations

from decimal import Decimal

from app.domain.sanity import SanityContext, run_sanity_checks

COMB_PRICE = Decimal("205.75")


def _ctx(**overrides) -> SanityContext:
    defaults = dict(
        price=COMB_PRICE,
        bvps=Decimal("233.80"),  # COMB's real book value per share
        roe=Decimal("0.1792"),  # COMB's real, TTM-corrected ROE
        mcap=None,
        shares=None,
        equity=None,
        total_assets=None,
        pb=None,
        pe=None,
        net_profit=None,
    )
    defaults.update(overrides)
    return SanityContext(**defaults)


class TestNonVotingClass:
    """§6 / E7 — the fair-value-vs-price rules must account for the
    persistent .X discount rather than block on it."""

    def test_a_voting_basis_fair_value_far_above_a_discounted_x_price_blocks_without_the_ratio(self):
        # FV 200 vs .X price 30 → ratio 6.67x, past fv_within_5x_price —
        # but that is the voting/non-voting discount, not a bad valuation.
        blocked = run_sanity_checks(Decimal("200"), _ctx(price=Decimal("30")))
        assert "fv_within_5x_price" in blocked.blocked_by

    def test_no_observable_ratio_skips_the_price_rules_for_an_x_line(self):
        r = run_sanity_checks(
            Decimal("200"), _ctx(price=Decimal("30"), is_non_voting=True, nonvoting_price_ratio=None)
        )
        assert "fv_within_5x_price" in r.skipped
        assert "fv_within_2x_price" in r.skipped
        assert "fv_within_5x_price" not in r.blocked_by

    def test_an_observed_ratio_puts_the_fair_value_on_a_non_voting_basis(self):
        # .X trades at 0.15 of .N → fair value 200 becomes 30 for the
        # price comparison, which lines up with the 30 .X price.
        r = run_sanity_checks(
            Decimal("200"),
            _ctx(price=Decimal("30"), is_non_voting=True, nonvoting_price_ratio=Decimal("0.15")),
        )
        assert "fv_within_5x_price" not in r.blocked_by
        assert "fv_within_2x_price" not in r.warned_by

    def test_a_voting_line_is_unaffected(self):
        r = run_sanity_checks(Decimal("253.87"), _ctx(is_non_voting=False))
        assert "fv_within_5x_price" not in r.skipped


class TestRunSanityChecks:
    def test_comb_after_the_ttm_fix_publishes_cleanly(self):
        """COMB's real, corrected post-fix numbers (fair value 253.87,
        price 205.75, ROE 17.92%) — a plausible accumulate-zone reading,
        confirmed live against the real dev DB. No rule fails at all."""
        result = run_sanity_checks(Decimal("253.87"), _ctx())
        assert result.blocked is False
        assert result.blocked_by == ()
        assert result.warned_by == ()

    def test_comb_before_the_ttm_fix_warns_but_is_not_blocked(self):
        """A real, disclosed limitation named in sanity.py's own module
        docstring: COMB's actual pre-fix numbers (fair value 93.06 vs
        price 205.75 — a 0.452x ratio, and a 9.73% "ROE") sit inside the
        0.2x-5x block band and inside the -50%/60% ROE band, so this gate
        ALONE would not have caught the real P0 bug — only warned. The
        gate is a backstop against egregious implausibility on top of the
        real TTM annualisation fix, never a substitute for it."""
        result = run_sanity_checks(
            Decimal("93.06"), _ctx(roe=Decimal("0.0973"))
        )
        assert result.blocked is False
        assert result.warned_by == ("fv_within_2x_price",)

    def test_sanity_blocks_implausible_bank_valuation(self):
        """A genuinely implausible fixture — the kind of gross units/
        share-count error TASK 0.1 asks this gate to catch even when the
        annualisation fix doesn't apply: a fair value near-zero relative
        to price, e.g. from a shares-in-millions-vs-thousands mixup."""
        result = run_sanity_checks(Decimal("15.00"), _ctx())  # 0.073x price
        assert result.blocked is True
        assert "fv_within_5x_price" in result.blocked_by
        assert result.block_reasons  # a human-readable reason is present

    def test_sanity_allows_ntb(self):
        """NTB.N0000 at roughly 1.11x price — a plausible, unremarkable
        reading — publishes normally with no block and no warning."""
        result = run_sanity_checks(
            Decimal("348.54"),  # 314.00 * 1.11
            _ctx(price=Decimal("314.00"), roe=Decimal("0.145")),
        )
        assert result.blocked is False
        assert result.warned_by == ()

    def test_bvps_zero_or_negative_blocks(self):
        result = run_sanity_checks(Decimal("200.00"), _ctx(bvps=Decimal("-5.00")))
        assert result.blocked is True
        assert result.blocked_by == ("bvps_positive",)

    def test_roe_outside_plausible_range_blocks(self):
        result = run_sanity_checks(Decimal("200.00"), _ctx(roe=Decimal("0.85")))
        assert result.blocked is True
        assert "roe_plausible" in result.blocked_by

    def test_equity_exceeding_total_assets_blocks_as_a_units_mismatch(self):
        result = run_sanity_checks(
            Decimal("200.00"),
            _ctx(equity=Decimal("500000"), total_assets=Decimal("400000")),
        )
        assert result.blocked is True
        assert "units_consistent" in result.blocked_by

    def test_equity_below_total_assets_passes_units_check(self):
        result = run_sanity_checks(
            Decimal("200.00"),
            _ctx(equity=Decimal("100000"), total_assets=Decimal("900000")),
        )
        assert "units_consistent" not in result.blocked_by

    def test_share_count_reconciling_within_two_percent_passes(self):
        result = run_sanity_checks(
            Decimal("200.00"),
            _ctx(mcap=Decimal("205750000"), shares=1000000),  # exact reconcile
        )
        assert "share_count_reconciles" not in result.blocked_by

    def test_share_count_off_by_more_than_two_percent_blocks(self):
        result = run_sanity_checks(
            Decimal("200.00"),
            # Published mcap implies ~2x the shares this valuation used —
            # exactly the voting/non-voting-mixup shape TASK 0.1 named.
            _ctx(mcap=Decimal("411500000"), shares=1000000),
        )
        assert result.blocked is True
        assert "share_count_reconciles" in result.blocked_by

    def test_reconciliation_uses_published_price_not_the_stale_eod_close(self):
        """The published market cap pairs with CSE's own `lastTradedPrice`
        from the same payload. Reconciling it against the EOD
        `prices_daily.close` — a different feed, often an older session —
        fails the moment the price has moved since the last capture, which
        is staleness between two feeds, not a share-count error. When
        `published_price` is supplied, that is what the rule must use.
        """
        result = run_sanity_checks(
            Decimal("200.00"),
            _ctx(
                price=Decimal("230.00"),  # stale EOD close, ~12% adrift
                published_price=Decimal("205.75"),  # pairs with the published mcap
                mcap=Decimal("205750000"),
                shares=1_000_000,
            ),
        )
        assert "share_count_reconciles" not in result.blocked_by

    def test_a_genuine_share_class_mismatch_still_blocks_with_published_price(self):
        result = run_sanity_checks(
            Decimal("200.00"),
            _ctx(
                published_price=Decimal("205.75"),
                mcap=Decimal("411500000"),  # implies ~2x the shares used
                shares=1_000_000,
            ),
        )
        assert "share_count_reconciles" in result.blocked_by

    def test_a_rule_with_a_missing_required_input_is_skipped_not_passed(self):
        """mcap and shares are both None by default in `_ctx()` — the
        rule must be recorded as `skipped`, distinct from silently
        assumed to have passed."""
        result = run_sanity_checks(Decimal("200.00"), _ctx())
        assert "share_count_reconciles" in result.skipped
        assert "share_count_reconciles" not in result.blocked_by
        assert "share_count_reconciles" not in result.warned_by

    def test_missing_equity_or_total_assets_skips_units_check(self):
        result = run_sanity_checks(Decimal("200.00"), _ctx())
        assert "units_consistent" in result.skipped

    def test_zero_price_is_skipped_not_a_crash(self):
        """A defensive edge case: dividing by a zero price must never
        raise — it is genuinely unevaluable, same treatment as a missing
        field."""
        result = run_sanity_checks(Decimal("200.00"), _ctx(price=Decimal("0")))
        assert "fv_within_5x_price" in result.skipped
        assert "fv_within_2x_price" in result.skipped


class TestImpliedMultipleBand:
    """docs/CSE_Universe_Integrity_Rollout.md §Check 4 — the AAF failure
    shape: a wrong-line / units / share-count error that produces a
    'confident cheap' verdict rather than a genuinely mispriced stock."""

    def test_aaf_at_the_wrong_line_price_is_blocked(self):
        # AAF's real numbers at the wrong (rights-line) price 11.30:
        # P/B 0.32 with ROE 24.3% — a Fitch A+(lka) lender has never
        # traded at a third of book.
        result = run_sanity_checks(
            Decimal("30.00"),
            _ctx(pb=Decimal("0.32"), roe=Decimal("0.243"), pe=Decimal("1.3"), net_profit=Decimal("500")),
        )
        assert result.blocked is True
        assert "pb_roe_coherent" in result.blocked_by
        assert "pe_floor" in result.blocked_by

    def test_a_real_cheap_but_low_return_bank_is_not_blocked(self):
        # A genuine deep-value read: cheap to book AND low ROE — allowed.
        result = run_sanity_checks(
            Decimal("50.00"),
            _ctx(pb=Decimal("0.35"), roe=Decimal("0.04"), pe=Decimal("8"), net_profit=Decimal("100")),
        )
        assert "pb_roe_coherent" not in result.blocked_by

    def test_extreme_multiple_ceiling_blocks(self):
        result = run_sanity_checks(
            Decimal("50.00"), _ctx(pb=Decimal("22"), pe=Decimal("11"))
        )
        assert result.blocked is True
        assert "multiple_ceiling" in result.blocked_by

    def test_bands_are_skipped_when_pb_pe_absent(self):
        result = run_sanity_checks(Decimal("253.87"), _ctx())
        for rule in ("pb_roe_coherent", "pe_floor", "multiple_ceiling"):
            assert rule in result.skipped

    def test_comb_real_multiples_pass_cleanly(self):
        # COMB post-fix: P/B ~0.88, P/E ~5, ROE 17.9%, profitable.
        result = run_sanity_checks(
            Decimal("253.87"),
            _ctx(pb=Decimal("0.88"), pe=Decimal("4.9"), net_profit=Decimal("25000")),
        )
        assert result.blocked is False
