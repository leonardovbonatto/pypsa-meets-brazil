# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for the REE-level PAR(1) inflow model fit (ADR-0008, SDDP epic
stage 2), the REE counterpart of test_fit_inflow_par1.py."""

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


par1 = _load("fit_inflow_par1_ree", REPO_ROOT / "scripts" / "fit_inflow_par1_ree.py")


class TestDropPreTrackingZeros:
    def test_drops_zero_rows_and_reports_them(self, capsys):
        """Real finding (this PR): TELES PIRES reports ena_bruta_mwmed==0.0
        for its first 213 days before real tracking starts - would corrupt
        log-space mu to -inf if fit on directly."""
        df = pd.DataFrame(
            {
                "date": ["2016-01-01", "2016-01-02", "2016-01-03"],
                "ree": ["TELES PIRES", "TELES PIRES", "BELO MONTE"],
                "ena_bruta_mwmed": [0.0, 0.0, 150.0],
            }
        )
        cleaned = par1.drop_pre_tracking_zeros(df)

        assert len(cleaned) == 1
        assert cleaned["ree"].iloc[0] == "BELO MONTE"
        assert "TELES PIRES" in capsys.readouterr().err

    def test_no_zeros_is_a_no_op(self):
        df = pd.DataFrame(
            {
                "date": ["2016-01-01", "2016-01-02"],
                "ree": ["BELO MONTE", "BELO MONTE"],
                "ena_bruta_mwmed": [150.0, 160.0],
            }
        )
        cleaned = par1.drop_pre_tracking_zeros(df)
        assert len(cleaned) == 2


class TestAggregateToMonthly:
    def test_averages_daily_to_monthly(self):
        df = pd.DataFrame(
            {
                "date": ["2020-01-01", "2020-01-02", "2020-02-01"],
                "ree": ["BELO MONTE", "BELO MONTE", "BELO MONTE"],
                "ena_bruta_mwmed": [100.0, 200.0, 50.0],
            }
        )
        monthly = par1.aggregate_to_monthly(df)

        assert len(monthly) == 2
        jan = monthly[(monthly["year"] == 2020) & (monthly["month"] == 1)]
        assert jan["ena_bruta_mwmed"].iloc[0] == pytest.approx(150.0)

    def test_keeps_rees_separate(self):
        df = pd.DataFrame(
            {
                "date": ["2020-01-01", "2020-01-01"],
                "ree": ["BELO MONTE", "SUL"],
                "ena_bruta_mwmed": [100.0, 500.0],
            }
        )
        monthly = par1.aggregate_to_monthly(df)
        assert set(monthly["ree"]) == {"BELO MONTE", "SUL"}

    def test_a_ree_with_a_shorter_history_contributes_fewer_rows(self):
        """Real REE-level quirk (PR-36): some REEs are only tracked from a
        later date than others - no uniform-coverage assumption here,
        unlike the subsystem-level equivalent."""
        df = pd.DataFrame(
            {
                "date": ["2020-01-01", "2020-02-01", "2020-01-01"],
                "ree": ["BELO MONTE", "BELO MONTE", "IGUACU"],
                "ena_bruta_mwmed": [100.0, 110.0, 200.0],
            }
        )
        monthly = par1.aggregate_to_monthly(df)
        assert len(monthly[monthly["ree"] == "BELO MONTE"]) == 2
        assert len(monthly[monthly["ree"] == "IGUACU"]) == 1


def _synthetic_ar1_monthly(*, true_phi: float, n_years: int, mu: float, sigma: float, seed: int):
    """A single-REE synthetic monthly series with a KNOWN, constant
    AR(1) coefficient - ground truth for fit_par1_by_month."""
    rng = np.random.default_rng(seed)
    n = n_years * 12
    z = np.zeros(n)
    shock_sd = np.sqrt(1 - true_phi**2)
    for t in range(1, n):
        z[t] = true_phi * z[t - 1] + rng.normal(scale=shock_sd)
    ena = np.exp(mu + sigma * z)

    rows = [
        {
            "ree": "BELO MONTE",
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

    def test_one_row_per_ree_month(self):
        monthly = _synthetic_ar1_monthly(true_phi=0.5, n_years=10, mu=5.0, sigma=1.0, seed=3)
        params = par1.fit_par1_by_month(monthly)

        assert len(params) == 12
        assert sorted(params["month"]) == list(range(1, 13))

    def test_a_ree_with_a_gap_still_fits_the_other_months(self):
        """A REE missing one calendar month in one year (a real gap, not
        just a shorter overall history) should still fit every month it
        has enough lagged pairs for."""
        monthly = _synthetic_ar1_monthly(true_phi=0.4, n_years=20, mu=5.0, sigma=1.0, seed=21)
        gappy = monthly[~((monthly["year"] == 5) & (monthly["month"] == 6))]

        params = par1.fit_par1_by_month(gappy)
        assert len(params) == 12
        assert params["phi"].notna().all()


class TestSimulatePar1:
    def test_shape_matches_requested_years(self):
        monthly = _synthetic_ar1_monthly(true_phi=0.5, n_years=30, mu=5.0, sigma=1.0, seed=4)
        params = par1.fit_par1_by_month(monthly)

        sim = par1.simulate_par1(params, n_years=15, rng=np.random.default_rng(5))

        assert len(sim) == 15 * 12
        assert set(sim["ree"]) == {"BELO MONTE"}
        assert (sim["ena_bruta_mwmed"] > 0).all()


class TestDroughtRuns:
    def test_max_drought_run_counts_consecutive_dry_months(self):
        monthly = pd.DataFrame(
            {
                "ree": ["BELO MONTE"] * 6,
                "year": [2020] * 6,
                "month": [1, 2, 3, 4, 5, 6],
                "ena_bruta_mwmed": [100.0, 10.0, 5.0, 8.0, 100.0, 100.0],
            }
        )
        thresholds = pd.DataFrame(
            {"ree": ["BELO MONTE"] * 6, "month": [1, 2, 3, 4, 5, 6], "threshold": [50.0] * 6}
        )
        runs = par1.max_drought_run(monthly, thresholds)
        assert runs["BELO MONTE"] == 3


def _synthetic_correlated_monthly(
    *, true_phi: float, true_corr: float, n_years: int, mu: float, sigma: float, seed: int
):
    """Two REEs ("A", "B") with a KNOWN cross-REE residual correlation."""
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
            "ree": ree,
            "year": year,
            "month": month,
            "ena_bruta_mwmed": ena[i, year * 12 + month - 1],
        }
        for i, ree in enumerate(["A", "B"])
        for year in range(n_years)
        for month in range(1, 13)
    ]
    return pd.DataFrame(rows)


class TestResidualCorrelationMatrix:
    def test_recovers_a_known_correlation(self):
        monthly = _synthetic_correlated_monthly(
            true_phi=0.4, true_corr=0.6, n_years=200, mu=5.0, sigma=1.0, seed=12
        )
        params = par1.fit_par1_by_month(monthly)
        corr = par1.residual_correlation_matrix(par1.compute_residuals(monthly, params))

        assert corr.loc["A", "B"] == pytest.approx(0.6, abs=0.1)

    def test_handles_rees_with_different_coverage_windows(self):
        """Real REE-level quirk: two REEs with only partial (year, month)
        overlap must still produce a well-defined pairwise correlation
        (pandas .corr()'s pairwise-complete-observations default), not NaN
        or a dropped column."""
        monthly = _synthetic_correlated_monthly(
            true_phi=0.3, true_corr=0.5, n_years=50, mu=5.0, sigma=1.0, seed=22
        )
        # B only exists from year 20 onward - a ragged coverage window.
        ragged = monthly[(monthly["ree"] == "A") | (monthly["year"] >= 20)]

        params = par1.fit_par1_by_month(ragged)
        corr = par1.residual_correlation_matrix(par1.compute_residuals(ragged, params))

        assert {"A", "B"} <= set(corr.columns)
        assert np.isfinite(corr.loc["A", "B"])


class TestSimulatePar1Correlated:
    def test_induces_the_target_correlation(self):
        params = pd.DataFrame(
            [
                {"ree": r, "month": m, "mu": 5.0, "sigma": 1.0, "phi": 0.3}
                for r in ["A", "B"]
                for m in range(1, 13)
            ]
        )
        corr_matrix = pd.DataFrame([[1.0, 0.7], [0.7, 1.0]], index=["A", "B"], columns=["A", "B"])

        sim = par1.simulate_par1_correlated(
            params, corr_matrix, n_years=300, rng=np.random.default_rng(15)
        )
        recovered = par1.residual_correlation_matrix(par1.compute_residuals(sim, params))

        assert recovered.loc["A", "B"] == pytest.approx(0.7, abs=0.1)


class TestValidatePersistence:
    def test_uses_each_rees_own_year_count(self):
        """Real REE-level design choice: unlike the subsystem-level
        version (one shared n_years for all subsystems, valid since all 4
        have identical history), each REE here is simulated for ITS OWN
        number of historical years - a REE with a shorter record must not
        be judged against droughts simulated over a longer one."""
        long_ree = _synthetic_ar1_monthly(true_phi=0.5, n_years=20, mu=8.0, sigma=0.5, seed=30)
        short_ree = _synthetic_ar1_monthly(true_phi=0.5, n_years=5, mu=8.0, sigma=0.5, seed=31)
        short_ree = short_ree.assign(ree="IGUACU")
        monthly = pd.concat([long_ree, short_ree], ignore_index=True)
        params = par1.fit_par1_by_month(monthly)

        report = par1.validate_persistence(monthly, params, n_realizations=20, seed=8)

        assert set(report.keys()) == {"BELO MONTE", "IGUACU"}
        for _ree, stats in report.items():
            assert 0.0 <= stats["historical_percentile_within_simulated"] <= 1.0


class TestWriteOutputs:
    def test_correlation_matrix_round_trips_as_tidy_long_format(self, tmp_path):
        corr_matrix = pd.DataFrame([[1.0, 0.5], [0.5, 1.0]], index=["A", "B"], columns=["A", "B"])
        corr_matrix.index.name = "ree"
        corr_matrix.columns.name = "ree"

        out = par1.write_correlation_matrix(corr_matrix, tmp_path / "corr.csv")
        reloaded = pd.read_csv(out)

        assert list(reloaded.columns) == ["ree_a", "ree_b", "correlation"]
        assert len(reloaded) == 4

    def test_validation_report_includes_known_limitations(self, tmp_path):
        out = par1.write_validation_report(
            {"BELO MONTE": {"historical_max_drought_run_months": 3}},
            {"A-B": {"historical_correlation": 0.5, "mean_simulated_correlation": 0.48}},
            tmp_path / "v.json",
        )

        import json

        payload = json.loads(out.read_text())
        assert payload["known_limitations"] == par1.KNOWN_LIMITATIONS
        assert "persistence_by_ree" in payload
        assert "spatial_correlation_by_ree_pair" in payload
