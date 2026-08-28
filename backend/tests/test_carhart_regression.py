"""§36's Dimson x Newey-West Carhart regression — app.domain.carhart_regression.

The load-bearing test here is the noiseless planted-coefficient
recovery: this codebase's own established "hand-worked reference value"
discipline (see test_portfolio_sort.py's known-double-premium universe,
test_beta.py's own reasoning) isn't literally hand-arithmetic for a
16-parameter regression, but its honest equivalent is — construct excess
returns as an EXACT linear combination of synthetic factor returns with
zero residual, and OLS must recover the planted coefficients to near-
machine precision. That IS a known, verifiable ground truth, the same
principle those other tests use, just expressed through construction
rather than arithmetic a human can check by hand.
"""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.carhart_regression import (
    FACTOR_NAMES,
    MIN_OBSERVATIONS_FOR_CARHART,
    fit_carhart_dimson,
    portfolio_beta_alert,
)


def _weekly_dates(n: int, start: dt.date = dt.date(2023, 1, 6)) -> list[dt.date]:
    return [start + dt.timedelta(weeks=i) for i in range(n)]


def _synthetic_factor_returns(dates: list[dt.date], seed: int) -> dict[str, dict[dt.date, Decimal]]:
    """5 real, independent (not collinear) synthetic weekly factor
    series — a fresh RNG stream per factor so they don't share structure."""
    result: dict[str, dict[dt.date, Decimal]] = {}
    for fi, name in enumerate(FACTOR_NAMES):
        rng = random.Random(seed * 100 + fi)
        result[name] = {d: Decimal(str(round(rng.gauss(0, 0.02), 8))) for d in dates}
    return result


class TestFitCarhartDimson:
    def test_insufficient_data_below_minimum_observations(self):
        dates = _weekly_dates(MIN_OBSERVATIONS_FOR_CARHART)  # too few once lag/lead trims the ends
        factors = _synthetic_factor_returns(dates, seed=1)
        excess = {d: Decimal("0.001") for d in dates}
        result = fit_carhart_dimson(excess, factors)
        assert result.insufficient_data is True
        assert result.betas == ()

    def test_missing_a_factor_series_is_insufficient_not_a_crash(self):
        dates = _weekly_dates(120)
        factors = _synthetic_factor_returns(dates, seed=1)
        del factors["LIQ"]
        excess = {d: Decimal("0.001") for d in dates}
        result = fit_carhart_dimson(excess, factors)
        assert result.insufficient_data is True
        assert "LIQ" in result.reason

    def test_recovers_planted_coefficients_from_a_noiseless_design(self):
        """The real ground-truth test: excess_return[t] is EXACTLY
        alpha + sum(beta_i * factor_i[t]) with zero noise and zero
        lag/lead structure (planted lag/lead coefficients are 0) — OLS
        on a noiseless linear DGP must recover every planted coefficient
        to near machine precision, and beta_true (lag+contemporaneous+
        lead) must equal the planted contemporaneous-only value."""
        dates = _weekly_dates(200)
        factors = _synthetic_factor_returns(dates, seed=42)
        planted_alpha = 0.0008
        planted_betas = {"MKT": 1.10, "SMB": 0.40, "HML_hard": -0.25, "MOM": 0.15, "LIQ": 0.05}

        excess: dict[dt.date, Decimal] = {}
        for d in dates:
            y = planted_alpha + sum(planted_betas[name] * float(factors[name][d]) for name in FACTOR_NAMES)
            excess[d] = Decimal(str(y))

        result = fit_carhart_dimson(excess, factors)
        assert result.insufficient_data is False
        assert result.collinearity_warning is None  # independently-drawn series, well-conditioned by construction

        betas_by_name = {b.factor_name: b for b in result.betas}
        for name, planted in planted_betas.items():
            recovered = float(betas_by_name[name].beta_true)
            assert abs(recovered - planted) < 1e-6, f"{name}: recovered={recovered} planted={planted}"
            # Lag/lead were never in the DGP -> must recover as ~0.
            assert abs(float(betas_by_name[name].lag_coefficient)) < 1e-6
            assert abs(float(betas_by_name[name].lead_coefficient)) < 1e-6

        recovered_alpha_weekly = float(result.alpha_annualized) / 52
        assert abs(recovered_alpha_weekly - planted_alpha) < 1e-6
        assert result.r_squared > Decimal("0.999")  # noiseless DGP -> near-perfect fit
        assert result.alpha_is_noise is False  # a real, large, precisely-estimated alpha on a noiseless fit

    def test_a_noisy_recovery_stays_within_a_wide_tolerance(self):
        """Same planted DGP, real Gaussian noise added — recovery should
        be close but not exact, and the fit should NOT be near-perfect
        R-squared anymore (a real, weaker but still genuine signal)."""
        dates = _weekly_dates(200)
        factors = _synthetic_factor_returns(dates, seed=7)
        rng = random.Random(99)
        planted_beta_mkt = 1.0

        excess: dict[dt.date, Decimal] = {}
        for d in dates:
            noise = rng.gauss(0, 0.015)
            y = planted_beta_mkt * float(factors["MKT"][d]) + noise
            excess[d] = Decimal(str(y))

        result = fit_carhart_dimson(excess, factors)
        assert result.insufficient_data is False
        mkt_beta = float(next(b for b in result.betas if b.factor_name == "MKT").beta_true)
        assert abs(mkt_beta - planted_beta_mkt) < 0.3  # wide tolerance -- real noise, not exact recovery
        assert result.r_squared < Decimal("0.99")

    def test_alpha_is_noise_when_r_squared_is_low(self):
        """Excess returns pure noise, uncorrelated with any factor —
        alpha should not be trusted regardless of its point estimate."""
        dates = _weekly_dates(150)
        factors = _synthetic_factor_returns(dates, seed=3)
        rng = random.Random(55)
        excess = {d: Decimal(str(round(rng.gauss(0, 0.03), 8))) for d in dates}

        result = fit_carhart_dimson(excess, factors)
        assert result.insufficient_data is False
        assert result.alpha_is_noise is True
        assert len(result.alpha_noise_reasons) > 0


class TestPortfolioBetaAlert:
    def test_no_alert_within_bounds(self):
        from app.domain.carhart_regression import FactorBeta

        betas = tuple(
            FactorBeta(
                factor_name=name, beta_true=Decimal("0.5"),
                lag_coefficient=Decimal(0), contemporaneous_coefficient=Decimal("0.5"), lead_coefficient=Decimal(0),
                t_stat=Decimal(2), p_value=Decimal("0.01"), significant=True,
            )
            for name in FACTOR_NAMES
        )
        assert portfolio_beta_alert(betas) == ()

    def test_alerts_on_both_hml_and_mom_breach(self):
        from app.domain.carhart_regression import FactorBeta

        def _beta(name: str, val: str) -> FactorBeta:
            return FactorBeta(
                factor_name=name, beta_true=Decimal(val),
                lag_coefficient=Decimal(0), contemporaneous_coefficient=Decimal(val), lead_coefficient=Decimal(0),
                t_stat=Decimal(2), p_value=Decimal("0.01"), significant=True,
            )

        betas = (_beta("HML_hard", "1.5"), _beta("MOM", "0.9"))
        alerts = portfolio_beta_alert(betas)
        assert len(alerts) == 2
        assert any("HML_hard" in a for a in alerts)
        assert any("MOM" in a for a in alerts)
