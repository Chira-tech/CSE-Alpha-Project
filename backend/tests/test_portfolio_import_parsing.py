"""app.domain.portfolio_import_parsing — tested against a real CDS
portfolio export's own real rows (18 Aug 2026), with the title row's own
real account-holder/NIC identifier replaced by a generic placeholder
before being committed to this repository — see this module's own
docstring for why that identifier is never extracted or stored at all.
"""
from __future__ import annotations

from decimal import Decimal

from app.domain.portfolio_import_parsing import parse_portfolio_export

# The real header row, byte-for-byte, plus a trailing blank cell exactly
# as openpyxl hands back an unused final column.
_HEADER = (
    "Security", "Quantity", "Cleared Balance", "Available Balance",
    "Unsettled Buy", "Unsettled Sell", "Holding % (Quantity)", "Avg Price",
    "B.E.S Price", "Total Cost", "Traded Price", "Market Value",
    "Holding % (Market Value)", "Sales Commission", "Sales Proceeds",
    "Unrealized Gain / (Loss)", "Unrealized Gain/Loss %", "Unr Today Gain/(Loss)", None,
)

# The real nine position rows and the real "Total" row, verified by hand
# to sum correctly (75,131.13 total cost; 76,748.20 total market value —
# both match the file's own stated Total row exactly).
_REAL_ROWS = [
    ("Portfolio (REDACTED ACCOUNT) - EQUITY", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None),
    (None,) * 19,
    _HEADER,
    ("AHUN.N0000", 38.0, 38.0, 38.0, 0.0, 0.0, 1.08, 94.04132, 95.09, 3573.57, 87.4, 3321.2, 4.33, 37.2, 3284.0, -289.57, -8.1, 0.0, None),
    ("CBNK.N0000", 1000.0, 1000.0, 1000.0, 0.0, 0.0, 28.47, 8.0896, 8.18, 8089.6, 7.5, 7500.0, 9.77, 84.0, 7416.0, -673.6, -8.33, 0.0, None),
    ("EAST.N0000", 120.0, 120.0, 120.0, 0.0, 0.0, 3.42, 42.47033, 42.95, 5096.44, 63.4, 7608.0, 9.91, 85.21, 7522.79, 2426.35, 47.61, 0.0, None),
    ("JKH.N0000", 1000.0, 1000.0, 1000.0, 0.0, 0.0, 28.47, 20.224, 20.45, 20224.0, 20.0, 20000.0, 26.06, 224.0, 19776.0, -448.0, -2.22, 0.0, None),
    ("KZOO.N0000", 1000.0, 1000.0, 1000.0, 0.0, 0.0, 28.47, 9.80863, 9.92, 9808.63, 8.9, 8900.0, 11.6, 99.68, 8800.32, -1008.31, -10.28, 0.0, None),
    ("LWL.N0000", 5.0, 5.0, 5.0, 0.0, 0.0, 0.14, 64.516, 65.24, 322.58, 45.2, 226.0, 0.29, 2.53, 223.47, -99.11, -30.72, 0.0, None),
    ("NTB.N0000", 80.0, 80.0, 80.0, 0.0, 0.0, 2.28, 303.36, 306.76, 24268.8, 314.0, 25120.0, 32.73, 281.34, 24838.66, 569.86, 2.35, 0.0, None),
    ("PAP.N0000", 200.0, 200.0, 200.0, 0.0, 0.0, 5.69, 12.43775, 12.58, 2487.55, 16.2, 3240.0, 4.22, 36.29, 3203.71, 716.16, 28.79, 0.0, None),
    ("WLTH.N0000", 70.0, 70.0, 70.0, 0.0, 0.0, 1.99, 17.99943, 18.2, 1259.96, 11.9, 833.0, 1.09, 9.33, 823.67, -436.29, -34.63, 0.0, None),
    ("Total", None, None, None, None, None, None, None, None, 75131.13, None, 76748.2, None, 859.58, 75888.62, 757.49, None, 0.0, None),
]


class TestParsePortfolioExport:
    def test_none_when_no_header_row_matches(self):
        assert parse_portfolio_export([("not", "a", "real", "sheet")]) is None

    def test_parses_all_nine_real_positions(self):
        result = parse_portfolio_export(_REAL_ROWS)
        assert result is not None
        assert len(result.positions) == 9
        tickers = [p.ticker for p in result.positions]
        assert tickers == [
            "AHUN.N0000", "CBNK.N0000", "EAST.N0000", "JKH.N0000", "KZOO.N0000",
            "LWL.N0000", "NTB.N0000", "PAP.N0000", "WLTH.N0000",
        ]

    def test_a_hand_worked_real_position(self):
        result = parse_portfolio_export(_REAL_ROWS)
        assert result is not None
        jkh = next(p for p in result.positions if p.ticker == "JKH.N0000")
        assert jkh.quantity == Decimal("1000.0")
        assert jkh.avg_price == Decimal("20.224")
        assert jkh.total_cost == Decimal("20224.0")
        assert jkh.traded_price == Decimal("20.0")
        assert jkh.market_value == Decimal("20000.0")
        assert jkh.unrealized_gain_loss == Decimal("-448.0")

    def test_real_ieee754_float_noise_from_xlsx_cells_does_not_fail_the_check(self):
        """A real, live-found case (18 Aug 2026, running this parser
        against the user's own actual uploaded file, not just a hand-
        typed fixture): openpyxl reads one real market-value cell back
        as `76748.2` and another as `76748.2000000000003` — both
        genuinely the same "76,748.20" a human sees in Excel, differing
        only in IEEE-754 float noise. An exact-equality check flagged
        this real, internally-correct file as a false MISMATCH; fixed
        with a disclosed tolerance (`_IDENTITY_TOLERANCE`)."""
        rows = [
            _HEADER,
            ("JKH.N0000", 1000.0, 1000.0, 1000.0, 0.0, 0.0, 100.0, 20.224, 20.45, 20224.0, 20.0, 20000.00000000001, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, None),
            ("Total", None, None, None, None, None, None, None, None, 20224.0, None, 20000.0, None, 0.0, 0.0, 0.0, None, 0.0, None),
        ]
        result = parse_portfolio_export(rows)
        assert result is not None
        assert result.identity_check_passed is True

    def test_the_real_totals_row_cross_check_passes(self):
        """The file's own real numbers are internally consistent — the
        parsed positions' own summed total_cost (75,131.13) and market
        value (76,748.20) match the file's own stated Total row exactly,
        verified by hand before this test was written."""
        result = parse_portfolio_export(_REAL_ROWS)
        assert result is not None
        assert result.stated_total_cost == Decimal("75131.13")
        assert result.stated_total_market_value == Decimal("76748.2")
        assert result.identity_check_passed is True
        assert "MISMATCH" not in result.identity_check_note

    def test_a_real_mismatch_is_caught_not_silently_passed(self):
        """A single digit changed in one real row's total cost — the
        identity check must catch it, the same "arithmetic check finds
        a real corruption" discipline `app.domain.financial_statement_
        parsing.check_accounting_identities` already established."""
        corrupted = list(_REAL_ROWS)
        jkh_idx = next(i for i, r in enumerate(corrupted) if r and r[0] == "JKH.N0000")
        row = list(corrupted[jkh_idx])
        row[9] = 20324.0  # total cost, corrupted by 100 — well outside the real float-noise tolerance
        corrupted[jkh_idx] = tuple(row)

        result = parse_portfolio_export(corrupted)
        assert result is not None
        assert result.identity_check_passed is False
        assert "MISMATCH" in result.identity_check_note

    def test_no_title_or_account_text_ever_appears_in_the_parsed_output(self):
        """Never extracts the title row's own account/NIC identifier —
        checked directly rather than merely asserted in a docstring."""
        result = parse_portfolio_export(_REAL_ROWS)
        assert result is not None
        serialized = repr(result)
        assert "REDACTED ACCOUNT" not in serialized
        assert "Portfolio (" not in serialized

    def test_a_row_missing_a_required_field_is_skipped_not_guessed(self):
        rows = [_HEADER, ("BAD.N0000", None, 10.0, 100.0, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None)]
        result = parse_portfolio_export(rows)
        assert result is not None
        assert result.positions == ()
