# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0011's levels PAR(1) inputs."""

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


prep = _load("prepare_sddp_inflow_state", REPO_ROOT / "scripts" / "prepare_sddp_inflow_state.py")


def _synthetic_monthly(n_years: int = 400, phi: float = 0.8, seed: int = 0) -> pd.DataFrame:
    """One subsystem, levels AR(1) in standardized units, mean 1000 + 100*month,
    sd 50 + 10*month."""
    rng = np.random.default_rng(seed)
    rows, z = [], 0.0
    for year in range(n_years):
        for month in range(1, 13):
            z = phi * z + np.sqrt(1 - phi**2) * rng.standard_normal()
            value = 1000 + 100 * month + (50 + 10 * month) * z
            rows.append({"subsystem": "N", "year": year, "month": month, prep.VALUE_COLUMN: value})
    return pd.DataFrame(rows)


class TestLognormal3:
    @pytest.mark.parametrize("skewness", [0.3, 1.0, 2.5])
    def test_has_mean_zero_variance_one_and_the_skewness(self, skewness):
        rng = np.random.default_rng(1)
        x = prep.standard_noise(rng.standard_normal(2_000_000), skewness)
        assert x.mean() == pytest.approx(0.0, abs=0.01)
        assert x.std() == pytest.approx(1.0, abs=0.01)
        assert prep._skew(pd.Series(x)) == pytest.approx(skewness, rel=0.05)

    def test_has_a_floor(self):
        _, _, floor = prep.lognormal3_by_moments(1.0)
        x = prep.standard_noise(np.random.default_rng(2).standard_normal(100_000), 1.0)
        assert x.min() > floor

    def test_rejects_non_positive_skewness(self):
        with pytest.raises(ValueError, match="positive skewness"):
            prep.lognormal3_by_moments(0.0)

    def test_gaussian_at_or_below_threshold(self):
        normals = np.array([-1.0, 0.0, 2.0])
        assert prep.standard_noise(normals, prep.SKEW_THRESHOLD) is normals


class TestFitLevels:
    def test_recovers_phi_and_builds_the_recursion(self):
        model = prep.fit_levels_par1(_synthetic_monthly()).set_index("month")
        assert model["phi"].mean() == pytest.approx(0.8, abs=0.05)
        june = model.loc[6]
        assert june["mu_prev"] == pytest.approx(model.loc[5, "mu"])
        assert june["Phi"] == pytest.approx(june["phi"] * june["sd"] / model.loc[5, "sd"])
        assert june["shock_scale"] == pytest.approx(june["sd"] * np.sqrt(1 - june["phi"] ** 2))

    def test_january_lags_the_previous_december(self):
        model = prep.fit_levels_par1(_synthetic_monthly()).set_index("month")
        assert model.loc[1, "mu_prev"] == pytest.approx(model.loc[12, "mu"])
        assert model.loc[1, "phi"] == pytest.approx(0.8, abs=0.1)


class TestRecoverNoise:
    def test_round_trips_the_recursion(self):
        model = prep.fit_levels_par1(_synthetic_monthly())
        lookup = model.set_index(["month", "subsystem"])
        start = pd.DataFrame({"subsystem": ["N"], "initial_inflow_mwmed": [2300.0]})
        e = np.random.default_rng(3).standard_normal(12)
        rows, last = [], 2300.0
        for month in range(1, 13):
            p = lookup.loc[(month, "N")]
            last = p["mu"] + p["Phi"] * (last - p["mu_prev"]) + p["shock_scale"] * e[month - 1]
            rows.append({"path": 0, "month": month, "subsystem": "N", "inflow_mwmed": last})
        recovered = prep.recover_noise(pd.DataFrame(rows), model, start)
        np.testing.assert_allclose(recovered.sort_values("month")["e"].to_numpy(), e)


class TestInitialInflow:
    def test_takes_the_latest_december(self):
        monthly = pd.DataFrame(
            {
                "subsystem": ["N", "N", "N"],
                "year": [2024, 2025, 2025],
                "month": [12, 11, 12],
                prep.VALUE_COLUMN: [1.0, 2.0, 3.0],
            }
        )
        start = prep.initial_inflow(monthly)
        assert start["initial_inflow_mwmed"].tolist() == [3.0]
        assert start["year"].tolist() == [2025]


class TestSampleNoise:
    def test_one_set_per_month_with_uniform_probability(self):
        model = prep.fit_levels_par1(_synthetic_monthly())
        corr = pd.DataFrame([[1.0]], index=["N"], columns=["N"])
        noise = prep.sample_noise(model, corr, n_noise=5, rng=np.random.default_rng(4))
        assert len(noise) == 12 * 5
        assert noise.groupby("month")["probability"].sum().to_numpy() == pytest.approx(1.0)


class TestPersistenceMetrics:
    def test_counts_negative_months(self):
        inflow = 100.0 + np.arange(36, dtype=float).reshape(3, 12) ** 1.5
        inflow[0, 0] = -5.0
        assert prep.persistence_metrics(inflow)["negative_month_share"] == pytest.approx(1 / 36)
