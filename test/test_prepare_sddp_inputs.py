# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for assembling the first SDDP policy's real inputs (ADR-0005,
SDDP epic stage 1f)."""

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


prep = _load("prepare_sddp_inputs", REPO_ROOT / "scripts" / "prepare_sddp_inputs.py")


class TestMonthlyDemand:
    def test_averages_hourly_to_monthly_per_subsystem(self):
        demand_t0 = pd.DataFrame(
            {
                "snapshot": ["2024-01-01 00:00:00", "2024-01-01 01:00:00", "2024-02-01 00:00:00"],
                "subsystem": ["N", "N", "N"],
                "load_mw": [100.0, 200.0, 50.0],
            }
        )
        monthly = prep.monthly_demand(demand_t0)

        assert len(monthly) == 2
        jan = monthly[(monthly["month"] == 1) & (monthly["subsystem"] == "N")]
        assert jan["demand_mw"].iloc[0] == pytest.approx(150.0)


class TestHydroThermalCapacity:
    def test_pivots_to_one_row_per_subsystem(self):
        generators_t0 = pd.DataFrame(
            {
                "subsystem": ["N", "N", "N", "S", "S"],
                "carrier": ["hydro", "thermal", "wind", "hydro", "thermal"],
                "p_nom_mw": [1000.0, 500.0, 200.0, 800.0, 300.0],
            }
        )
        capacity = prep.hydro_thermal_capacity(generators_t0)

        assert set(capacity["subsystem"]) == {"N", "S"}
        n_row = capacity[capacity["subsystem"] == "N"].iloc[0]
        assert n_row["hydro_mw"] == pytest.approx(1000.0)
        assert n_row["thermal_mw"] == pytest.approx(500.0)
        assert "wind" not in capacity.columns

    def test_raises_when_a_subsystem_is_missing_a_carrier(self):
        generators_t0 = pd.DataFrame(
            {"subsystem": ["N"], "carrier": ["hydro"], "p_nom_mw": [1000.0]}
        )
        with pytest.raises(ValueError, match="missing"):
            prep.hydro_thermal_capacity(generators_t0)


class TestThermalCost:
    def test_selects_subsystem_and_cost_columns(self):
        costs_t0 = pd.DataFrame(
            {
                "subsystem": ["N", "S"],
                "carrier": ["thermal", "thermal"],
                "marginal_cost": [200.0, 300.0],
            }
        )
        cost = prep.thermal_cost(costs_t0)
        assert list(cost.columns) == ["subsystem", "marginal_cost"]
        assert len(cost) == 2


class TestInitialStorage:
    def test_uses_the_most_recent_date(self):
        history = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"]),
                "subsystem": ["N", "N", "S", "S"],
                "ear_verif_mwmes": [100.0, 150.0, 200.0, 250.0],
            }
        )
        storage0 = prep.initial_storage(history)

        assert storage0.set_index("subsystem")["initial_storage_mwmes"]["N"] == pytest.approx(150.0)
        assert storage0.set_index("subsystem")["initial_storage_mwmes"]["S"] == pytest.approx(250.0)


class TestSampleMonthShocks:
    def test_shape(self):
        corr_matrix = pd.DataFrame([[1.0, 0.3], [0.3, 1.0]], index=["A", "B"], columns=["A", "B"])

        shocks = prep.sample_month_shocks(corr_matrix, n_scenarios=5, rng=np.random.default_rng(0))

        assert len(shocks) == 12 * 5 * 2
        assert set(shocks["subsystem"]) == {"A", "B"}
        assert set(shocks["month"]) == set(range(1, 13))

    def test_probabilities_sum_to_one_within_each_month(self):
        corr_matrix = pd.DataFrame([[1.0]], index=["A"], columns=["A"])

        shocks = prep.sample_month_shocks(corr_matrix, n_scenarios=4, rng=np.random.default_rng(1))

        for _month, group in shocks.groupby("month"):
            assert group["probability"].sum() == pytest.approx(1.0)

    def test_induces_the_target_cross_subsystem_correlation(self):
        """Correctness check, not just shape: draws with a strong target
        correlation should show it when re-estimated from a large sample -
        the same discipline as PR-28/29's known-parameter recovery tests."""
        corr_matrix = pd.DataFrame([[1.0, 0.8], [0.8, 1.0]], index=["A", "B"], columns=["A", "B"])

        shocks = prep.sample_month_shocks(
            corr_matrix, n_scenarios=2000, rng=np.random.default_rng(2)
        )
        wide = shocks.pivot_table(index=["month", "scenario"], columns="subsystem", values="shock")
        recovered = wide["A"].corr(wide["B"])

        assert recovered == pytest.approx(0.8, abs=0.05)

    def test_shocks_are_standardized_not_transformed(self):
        """Real semantic change (PR-38): this function used to return
        exp(mu + sigma*shock) inflow LEVELS; now it returns the raw shock
        itself, since the exp() transform moved into Julia after the AR(1)
        recursion. A single-subsystem draw's shocks should look like
        standard normal samples, not like log-normal inflow levels."""
        corr_matrix = pd.DataFrame([[1.0]], index=["A"], columns=["A"])

        shocks = prep.sample_month_shocks(
            corr_matrix, n_scenarios=500, rng=np.random.default_rng(3)
        )
        assert shocks["shock"].mean() == pytest.approx(0.0, abs=0.1)
        assert shocks["shock"].std() == pytest.approx(1.0, abs=0.1)
        assert (shocks["shock"] < 0).any()


class TestWriteParquet:
    def test_round_trips(self, tmp_path):
        df = pd.DataFrame({"a": [1, 2, 3]})
        out = prep.write_parquet(df, tmp_path / "test.parquet")
        reloaded = pd.read_parquet(out)
        assert len(reloaded) == 3
