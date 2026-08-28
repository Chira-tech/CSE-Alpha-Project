"""app.domain.sector_percentiles — §12's sector-relative percentiles:
winsorization, the ascending ranking direction, and the two-level
sector-fallback rule `app.domain.gics` was built for.
"""
from __future__ import annotations

from decimal import Decimal

from app.domain.sector_percentiles import (
    MIN_CONSTITUENTS_FOR_SECTOR_PERCENTILE,
    sector_percentiles_for_ratio,
    winsorize,
)


class TestSectorPercentilesForRatio:
    def test_hand_worked_five_member_group_ascending_direction(self):
        """The HIGHEST raw ROE gets the HIGHEST percentile — the
        conventional financial-ratio meaning, and the opposite direction
        from `app.domain.liquidity.percentile_rank`'s own Amihud-specific
        inversion (see this module's own docstring on why)."""
        values = {
            "A": Decimal("0.05"),
            "B": Decimal("0.10"),
            "C": Decimal("0.15"),
            "D": Decimal("0.20"),
            "E": Decimal("0.25"),
        }
        sector = {t: "Banks" for t in values}
        result = sector_percentiles_for_ratio("return_on_equity", values, sector, sector)
        assert result["A"].percentile == Decimal(0)
        assert result["B"].percentile == Decimal(25)
        assert result["C"].percentile == Decimal(50)
        assert result["D"].percentile == Decimal(75)
        assert result["E"].percentile == Decimal(100)
        for r in result.values():
            assert r.group_label == "Banks"
            assert r.group_size == 5
            assert r.used_wider_sector is False
            assert r.reason is None

    def test_a_single_ticker_group_still_below_threshold_gets_no_percentile(self):
        """A group of 1 (or 2) never even reaches
        MIN_CONSTITUENTS_FOR_SECTOR_PERCENTILE, so no rank is given —
        never a fabricated neutral midpoint standing in for a real one."""
        assert MIN_CONSTITUENTS_FOR_SECTOR_PERCENTILE == 3
        values = {"X": Decimal("0.10")}
        result = sector_percentiles_for_ratio(
            "return_on_equity", values, {"X": "Automobiles"}, {"X": "Consumer Discretionary"}
        )
        assert result["X"].percentile is None
        assert "Fewer than 3 peers" in result["X"].reason

    def test_falls_back_to_the_wider_gics_sector_when_the_narrow_one_is_too_thin(self):
        """Sri Lanka's real shape: one automobile company, three
        telecoms — `app.domain.gics`'s own reasoning for having both
        levels, applied here exactly as that module's docstring
        describes."""
        values = {"X": Decimal("0.05"), "Y": Decimal("0.10"), "Z": Decimal("0.20")}
        narrow = {"X": "Automobiles", "Y": "Automobiles", "Z": "Construction Materials"}
        wide = {"X": "Industrials", "Y": "Industrials", "Z": "Industrials"}
        result = sector_percentiles_for_ratio("return_on_equity", values, narrow, wide)
        # "Automobiles" only has 2 members -> too thin; both X and Y fall
        # back to "Industrials", which has all 3 tickers.
        assert result["X"].used_wider_sector is True
        assert result["X"].group_label == "Industrials"
        assert result["X"].group_size == 3
        assert result["Y"].used_wider_sector is True
        # Z's own narrow sector ("Construction Materials") is itself too
        # thin (1 member), so it ALSO falls back to the wider group.
        assert result["Z"].used_wider_sector is True
        assert result["Z"].group_label == "Industrials"

    def test_too_thin_even_at_the_wider_level_reports_a_named_reason_not_a_guess(self):
        values = {"X": Decimal("0.05"), "Y": Decimal("0.10")}
        narrow = {"X": "Automobiles", "Y": "Automobiles"}
        wide = {"X": "Industrials", "Y": "Industrials"}
        result = sector_percentiles_for_ratio("return_on_equity", values, narrow, wide)
        assert result["X"].percentile is None
        assert result["X"].used_wider_sector is False
        assert "Fewer than 3 peers" in result["X"].reason
        assert "found 2" in result["X"].reason

    def test_no_sector_classification_at_all(self):
        result = sector_percentiles_for_ratio(
            "return_on_equity", {"Q": Decimal("0.1")}, {"Q": None}, {"Q": None}
        )
        assert result["Q"].percentile is None
        assert result["Q"].reason == "No sector classification on file for this ticker."

    def test_a_ticker_with_no_ratio_value_gets_no_entry_at_all(self):
        """This function's whole job is turning a value that DOES exist
        into a rank — a ticker absent from `values_by_ticker` (ratio not
        computable for it) is the caller's concern, not a missing-key
        crash here."""
        values = {"A": Decimal("0.1"), "B": Decimal("0.2"), "C": Decimal("0.3")}
        sector = {t: "Banks" for t in values}
        sector["D"] = "Banks"  # D has a sector but no ratio value
        result = sector_percentiles_for_ratio("return_on_equity", values, sector, sector)
        assert "D" not in result
        assert len(result) == 3


class TestWinsorize:
    def test_groups_smaller_than_two_are_returned_unchanged(self):
        assert winsorize({}) == {}
        assert winsorize({"A": Decimal("5")}) == {"A": Decimal("5")}

    def test_clips_a_genuine_outlier_at_a_large_enough_group_size(self):
        # 100 members, evenly spaced 1..100, plus one wild outlier —
        # winsorization only does real work once a group is large enough
        # to have a genuine tail beyond its extremes (see module
        # docstring on why small CSE sector groups rarely trigger this).
        values = {f"T{i}": Decimal(i) for i in range(1, 101)}
        values["OUTLIER"] = Decimal("100000")
        clipped = winsorize(values)
        # The 99th percentile (nearest-rank) of 101 sorted values sits at
        # index int(101*0.99)=99, i.e. the 100th-smallest real value (100
        # itself) — the outlier is clamped down to it.
        assert clipped["OUTLIER"] == Decimal(100)
        # An ordinary interior value is untouched.
        assert clipped["T50"] == Decimal(50)

    def test_on_a_small_group_the_bounds_are_just_the_min_and_max(self):
        """Honestly documented limitation: with the handful-of-names
        groups this exchange actually has, 1%/99% resolves to the
        group's own extremes, not a real clip — still applied uniformly
        and correctly, just rarely doing visible work."""
        values = {"A": Decimal("1"), "B": Decimal("2"), "C": Decimal("3")}
        clipped = winsorize(values)
        assert clipped == values
