# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for the PAR(1) inflow model fit and its persistence validation
(ADR-0005, SDDP epic stage 1c)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


par1 = _load("fit_inflow_par1", REPO_ROOT / "scripts" / "fit_inflow_par1.py")


class TestAggregateToMonthly:
    def test_averages_daily_to_monthly(self):
        df = pd.DataFrame(
            {
                "date": ["2020-01-01", "2020-01-02", "2020-02-01"],
                "subsystem": ["N", "N", "N"],
                "ena_bruta_mwmed": [100.0, 200.0, 50.0],
            }
        )
        monthly = par1.aggregate_to_monthly(df)

        assert len(monthly) == 2
        jan = monthly[(monthly["year"] == 2020) & (monthly["month"] == 1)]
        assert jan["ena_bruta_mwmed"].iloc[0] == pytest.approx(150.0)

    def test_keeps_subsystems_separate(self):
        df = pd.DataFrame(
            {
                "date": ["2020-01-01", "2020-01-01"],
                "subsystem": ["N", "S"],
                "ena_bruta_mwmed": [100.0, 500.0],
            }
        )
        monthly = par1.aggregate_to_monthly(df)
        assert set(monthly["subsystem"]) == {"N", "S"}


def _synthetic_ar1_monthly(*, true_phi: float, n_years: int, mu: float, sigma: float, seed: int):
    """A single-subsystem synthetic monthly series with a KNOWN, constant
    (across calendar months) AR(1) coefficient - lets fit_par1_by_month's
    correctness be checked against ground truth, not just "runs without
    error"."""
    rng = np.random.default_rng(seed)
    n = n_years * 12
    z = np.zeros(n)
    shock_sd = np.sqrt(1 - true_phi**2)
    for t in range(1, n):
        z[t] = true_phi * z[t - 1] + rng.normal(scale=shock_sd)
    ena = np.exp(mu + sigma * z)

    rows = [
        {
            "subsystem": "N",
            "year": year,
            "month": month,
            "ena_bruta_mwmed": ena[year * 12 + month - 1],
        }
        for year in range(n_years)
        for month in range(1, 13)
    ]
    return pd.DataFrame(rows)


class TestFitPar1ByMonth:
    def test_recovers_a_known_phi_from_synthetic_data(self):
        monthly = _synthetic_ar1_monthly(true_phi=0.6, n_years=200, mu=5.0, sigma=1.0, seed=0)
        params = par1.fit_par1_by_month(monthly)

        assert params["phi"].mean() == pytest.approx(0.6, abs=0.05)

    def test_recovers_known_mu_and_sigma(self):
        monthly = _synthetic_ar1_monthly(true_phi=0.3, n_years=200, mu=8.0, sigma=0.5, seed=1)
        params = par1.fit_par1_by_month(monthly)

        assert params["mu"].mean() == pytest.approx(8.0, abs=0.05)
        assert params["sigma"].mean() == pytest.approx(0.5, abs=0.05)

    def test_near_zero_phi_for_independent_data(self):
        rng = np.random.default_rng(2)
        n_years = 200
        rows = [
            {
                "subsystem": "N",
                "year": year,
                "month": month,
                "ena_bruta_mwmed": np.exp(rng.normal(loc=5.0, scale=1.0)),
            }
            for year in range(n_years)
            for month in range(1, 13)
        ]
        params = par1.fit_par1_by_month(pd.DataFrame(rows))

        assert params["phi"].mean() == pytest.approx(0.0, abs=0.1)

    def test_one_row_per_subsystem_month(self):
        monthly = _synthetic_ar1_monthly(true_phi=0.5, n_years=10, mu=5.0, sigma=1.0, seed=3)
        params = par1.fit_par1_by_month(monthly)

        assert len(params) == 12
        assert sorted(params["month"]) == list(range(1, 13))


class TestSimulatePar1:
    def test_shape_matches_requested_years(self):
        monthly = _synthetic_ar1_monthly(true_phi=0.5, n_years=30, mu=5.0, sigma=1.0, seed=4)
        params = par1.fit_par1_by_month(monthly)

        sim = par1.simulate_par1(params, n_years=15, rng=np.random.default_rng(5))

        assert len(sim) == 15 * 12
        assert set(sim["subsystem"]) == {"N"}
        assert (sim["ena_bruta_mwmed"] > 0).all()

    def test_extreme_phi_does_not_crash(self):
        """phi is clipped to [-0.99, 0.99] so a fitted phi of exactly +/-1
        (possible on tiny/degenerate inputs) never divides by zero."""
        params = pd.DataFrame(
            [
                {"subsystem": "N", "month": m, "mu": 5.0, "sigma": 1.0, "phi": 1.0}
                for m in range(1, 13)
            ]
        )
        sim = par1.simulate_par1(params, n_years=5, rng=np.random.default_rng(6))
        assert len(sim) == 5 * 12
        assert np.isfinite(sim["ena_bruta_mwmed"]).all()


class TestDroughtRuns:
    def test_max_drought_run_counts_consecutive_dry_months(self):
        monthly = pd.DataFrame(
            {
                "subsystem": ["N"] * 6,
                "year": [2020] * 6,
                "month": [1, 2, 3, 4, 5, 6],
                "ena_bruta_mwmed": [100.0, 10.0, 5.0, 8.0, 100.0, 100.0],
            }
        )
        thresholds = pd.DataFrame(
            {"subsystem": ["N"] * 6, "month": [1, 2, 3, 4, 5, 6], "threshold": [50.0] * 6}
        )
        runs = par1.max_drought_run(monthly, thresholds)
        # months 2, 3, 4 are below threshold (10, 5, 8 < 50) - a 3-month run.
        assert runs["N"] == 3

    def test_no_dry_months_gives_zero_run(self):
        monthly = pd.DataFrame(
            {
                "subsystem": ["N"] * 3,
                "year": [2020] * 3,
                "month": [1, 2, 3],
                "ena_bruta_mwmed": [100.0] * 3,
            }
        )
        thresholds = pd.DataFrame(
            {"subsystem": ["N"] * 3, "month": [1, 2, 3], "threshold": [50.0] * 3}
        )
        assert par1.max_drought_run(monthly, thresholds)["N"] == 0


def _synthetic_correlated_monthly(
    *, true_phi: float, true_corr: float, n_years: int, mu: float, sigma: float, seed: int
):
    """Two subsystems ("A", "B") with a KNOWN cross-subsystem residual
    correlation - lets residual_correlation_matrix's and
    simulate_par1_correlated's correctness be checked against ground truth."""
    rng = np.random.default_rng(seed)
    n = n_years * 12
    shock_sd = np.sqrt(1 - true_phi**2)
    cholesky_factor = np.linalg.cholesky(np.array([[1.0, true_corr], [true_corr, 1.0]]))

    z = np.zeros((2, n))
    for t in range(1, n):
        correlated_unit = cholesky_factor @ rng.normal(size=2)
        z[:, t] = true_phi * z[:, t - 1] + correlated_unit * shock_sd
    ena = np.exp(mu + sigma * z)

    rows = [
        {
            "subsystem": subsystem,
            "year": year,
            "month": month,
            "ena_bruta_mwmed": ena[i, year * 12 + month - 1],
        }
        for i, subsystem in enumerate(["A", "B"])
        for year in range(n_years)
        for month in range(1, 13)
    ]
    return pd.DataFrame(rows)


class TestComputeResiduals:
    def test_drops_only_the_first_unlagged_month_per_subsystem(self):
        monthly = _synthetic_ar1_monthly(true_phi=0.5, n_years=10, mu=5.0, sigma=1.0, seed=10)
        params = par1.fit_par1_by_month(monthly)
        residuals = par1.compute_residuals(monthly, params)
        assert len(residuals) == 10 * 12 - 1


class TestResidualCorrelationMatrix:
    def test_diagonal_is_one(self):
        monthly = _synthetic_correlated_monthly(
            true_phi=0.4, true_corr=0.6, n_years=100, mu=5.0, sigma=1.0, seed=11
        )
        params = par1.fit_par1_by_month(monthly)
        corr = par1.residual_correlation_matrix(par1.compute_residuals(monthly, params))

        assert corr.loc["A", "A"] == pytest.approx(1.0)
        assert corr.loc["B", "B"] == pytest.approx(1.0)

    def test_recovers_a_known_correlation(self):
        monthly = _synthetic_correlated_monthly(
            true_phi=0.4, true_corr=0.6, n_years=200, mu=5.0, sigma=1.0, seed=12
        )
        params = par1.fit_par1_by_month(monthly)
        corr = par1.residual_correlation_matrix(par1.compute_residuals(monthly, params))

        assert corr.loc["A", "B"] == pytest.approx(0.6, abs=0.1)


class TestSimulatePar1Correlated:
    def test_shape(self):
        monthly = _synthetic_correlated_monthly(
            true_phi=0.4, true_corr=0.3, n_years=50, mu=5.0, sigma=1.0, seed=13
        )
        params = par1.fit_par1_by_month(monthly)
        corr = par1.residual_correlation_matrix(par1.compute_residuals(monthly, params))

        sim = par1.simulate_par1_correlated(params, corr, n_years=20, rng=np.random.default_rng(14))

        assert len(sim) == 20 * 12 * 2
        assert set(sim["subsystem"]) == {"A", "B"}

    def test_induces_the_target_correlation(self):
        """Build params with a strong target correlation and verify the
        simulator's OWN output, re-estimated, is close to it - not just
        that a correlation matrix was accepted as an argument."""
        params = pd.DataFrame(
            [
                {"subsystem": s, "month": m, "mu": 5.0, "sigma": 1.0, "phi": 0.3}
                for s in ["A", "B"]
                for m in range(1, 13)
            ]
        )
        corr_matrix = pd.DataFrame([[1.0, 0.7], [0.7, 1.0]], index=["A", "B"], columns=["A", "B"])

        sim = par1.simulate_par1_correlated(
            params, corr_matrix, n_years=300, rng=np.random.default_rng(15)
        )
        recovered = par1.residual_correlation_matrix(par1.compute_residuals(sim, params))

        assert recovered.loc["A", "B"] == pytest.approx(0.7, abs=0.1)


class TestValidateSpatialCorrelation:
    def test_returns_one_entry_per_pair_with_expected_keys(self):
        monthly = _synthetic_correlated_monthly(
            true_phi=0.3, true_corr=0.5, n_years=26, mu=8.0, sigma=0.5, seed=16
        )
        params = par1.fit_par1_by_month(monthly)
        corr = par1.residual_correlation_matrix(par1.compute_residuals(monthly, params))

        report = par1.validate_spatial_correlation(
            monthly, params, corr, n_realizations=10, seed=17
        )

        assert set(report.keys()) == {"A-B"}
        assert set(report["A-B"].keys()) == {"historical_correlation", "mean_simulated_correlation"}


class TestValidatePersistence:
    def test_returns_one_entry_per_subsystem_with_expected_keys(self):
        monthly = _synthetic_ar1_monthly(true_phi=0.5, n_years=26, mu=8.0, sigma=0.5, seed=7)
        params = par1.fit_par1_by_month(monthly)

        report = par1.validate_persistence(monthly, params, n_realizations=20, seed=8)

        assert set(report.keys()) == {"N"}
        expected_keys = {
            "historical_max_drought_run_months",
            "simulated_median_max_drought_run_months",
            "historical_percentile_within_simulated",
        }
        assert set(report["N"].keys()) == expected_keys
        assert 0.0 <= report["N"]["historical_percentile_within_simulated"] <= 1.0


class TestWriteOutputs:
    def test_params_round_trip_through_csv(self, tmp_path):
        monthly = _synthetic_ar1_monthly(true_phi=0.5, n_years=10, mu=5.0, sigma=1.0, seed=9)
        params = par1.fit_par1_by_month(monthly)

        out = par1.write_params(params, tmp_path / "params.csv")
        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(params)

    def test_correlation_matrix_round_trips_as_tidy_long_format(self, tmp_path):
        """Regression test for a real bug: corr_matrix.stack().reset_index()
        raised `ValueError: cannot insert subsystem, already exists` because
        .corr() leaves both axes named "subsystem"."""
        corr_matrix = pd.DataFrame([[1.0, 0.5], [0.5, 1.0]], index=["A", "B"], columns=["A", "B"])
        corr_matrix.index.name = "subsystem"
        corr_matrix.columns.name = "subsystem"

        out = par1.write_correlation_matrix(corr_matrix, tmp_path / "corr.csv")
        reloaded = pd.read_csv(out)

        assert list(reloaded.columns) == ["subsystem_a", "subsystem_b", "correlation"]
        assert len(reloaded) == 4  # 2x2 matrix, tidy long format

    def test_validation_report_includes_known_limitations(self, tmp_path):
        out = par1.write_validation_report(
            {"N": {"historical_max_drought_run_months": 3}},
            {"N-NE": {"historical_correlation": 0.5, "mean_simulated_correlation": 0.48}},
            tmp_path / "v.json",
        )

        import json

        payload = json.loads(out.read_text())
        assert payload["known_limitations"] == par1.KNOWN_LIMITATIONS
        assert "persistence_by_subsystem" in payload
        assert "spatial_correlation_by_subsystem_pair" in payload
