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


def _params(phi: float, subsystems=("A", "B")) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"subsystem": s, "month": m, "mu": 5.0, "sigma": 1.0, "phi": phi}
            for s in subsystems
            for m in range(1, 13)
        ]
    )


class TestMarkovBins:
    def test_bins_recover_the_standard_normal(self):
        """The bins must partition a standard normal exactly: probabilities
        sum to 1, the probability-weighted mean is 0, and the law of total
        variance recovers 1. If any of these drift, the regime decomposition
        in sample_markov_scenarios is silently changing the marginal inflow
        distribution."""
        bins = prep.markov_bins(3)

        assert bins["probability"].sum() == pytest.approx(1.0)
        assert (bins["probability"] * bins["mean"]).sum() == pytest.approx(0.0, abs=1e-12)
        total_variance = (bins["probability"] * (bins["sd"] ** 2 + bins["mean"] ** 2)).sum()
        assert total_variance == pytest.approx(1.0, abs=1e-9)

    def test_states_are_ordered_dry_to_wet(self):
        bins = prep.markov_bins(5)
        assert list(bins["markov_state"]) == [1, 2, 3, 4, 5]
        assert bins["mean"].is_monotonic_increasing

    def test_outer_bins_are_unbounded(self):
        bins = prep.markov_bins(3)
        assert np.isneginf(bins["lower"].iloc[0])
        assert np.isposinf(bins["upper"].iloc[-1])

    def test_rejects_a_degenerate_state_count(self):
        with pytest.raises(ValueError, match="at least 2"):
            prep.markov_bins(1)


class TestSystemPhiByMonth:
    def test_weights_by_inflow_so_the_larger_subsystem_dominates(self):
        """A single national persistence must be dominated by the biggest
        basin, not averaged evenly - SE_CO is roughly 4x the others."""
        params = pd.DataFrame(
            [
                {"subsystem": "big", "month": 1, "mu": 10.0, "sigma": 1.0, "phi": 0.9},
                {"subsystem": "small", "month": 1, "mu": 1.0, "sigma": 1.0, "phi": 0.1},
            ]
        )
        phi = prep.system_phi_by_month(params)

        # An unweighted mean would be 0.5; weighting by exp(mu) puts the
        # result essentially on the large subsystem's own phi.
        assert phi.loc[1] == pytest.approx(0.9, abs=0.01)


class TestSamplePar1Paths:
    @staticmethod
    def _paths(phi: float, n_states: int = 3, n_paths: int = 4000) -> pd.DataFrame:
        params = pd.DataFrame(
            [
                {"subsystem": s, "month": m, "mu": 5.0, "sigma": 0.5, "phi": phi}
                for s in ("A", "B")
                for m in range(1, 13)
            ]
        )
        corr = pd.DataFrame([[1.0, 0.3], [0.3, 1.0]], index=["A", "B"], columns=["A", "B"])
        return prep.sample_par1_paths(
            params, corr, n_states=n_states, n_paths=n_paths, rng=np.random.default_rng(0)
        )

    def test_keeps_the_fitted_persistence(self):
        """The reason these paths exist: within-regime Markov scenarios lose
        persistence, and this test set must not."""
        wide = self._paths(0.9).query("subsystem == 'A'")
        anomaly = np.log(wide.pivot(index="path", columns="month", values="inflow_mwmed"))

        assert anomaly[6].corr(anomaly[7]) == pytest.approx(0.9, abs=0.02)

    def test_regimes_are_equally_likely_and_ordered(self):
        paths = self._paths(0.5).query("month == 6")

        shares = paths["markov_state"].value_counts(normalize=True)
        assert shares.to_numpy() == pytest.approx([1 / 3] * 3, abs=0.03)
        means = paths.groupby("markov_state")["inflow_mwmed"].mean()
        assert means.is_monotonic_increasing

    def test_one_regime_per_path_and_month(self):
        """The regime is national, so subsystems in a month must agree."""
        counts = self._paths(0.5).groupby(["path", "month"])["markov_state"].nunique()

        assert counts.max() == 1


class TestTransitionMatrices:
    def test_every_row_sums_to_one(self):
        tm = prep.transition_matrices(_params(0.7), n_states=3)
        row_sums = tm.groupby(["stage", "from_state"])["probability"].sum()
        assert np.allclose(row_sums.to_numpy(), 1.0)

    def test_root_stage_is_uniform_and_comes_from_state_zero(self):
        tm = prep.transition_matrices(_params(0.7), n_states=3)
        root = tm[tm["stage"] == 1]
        assert set(root["from_state"]) == {0}
        assert np.allclose(root["probability"].to_numpy(), 1 / 3)

    def test_high_phi_is_more_persistent_than_low_phi(self):
        """The whole point of the transition matrix: stronger fitted
        persistence must make staying in the same regime more likely."""
        sticky = prep.transition_matrices(_params(0.95), n_states=3)
        loose = prep.transition_matrices(_params(0.05), n_states=3)

        def stay_dry(tm):
            row = tm[(tm["stage"] == 2) & (tm["from_state"] == 1) & (tm["to_state"] == 1)]
            return float(row["probability"].iloc[0])

        assert stay_dry(sticky) > stay_dry(loose)

    def test_zero_phi_gives_regime_independent_transitions(self):
        """With no persistence the next regime must be independent of the
        current one - every entry 1/K. A known-answer check on the
        numerical integration."""
        tm = prep.transition_matrices(_params(0.0), n_states=3)
        stage2 = tm[tm["stage"] == 2]
        assert np.allclose(stage2["probability"].to_numpy(), 1 / 3, atol=1e-6)


class TestSampleMarkovScenarios:
    def test_shape_and_regime_coverage(self):
        corr = pd.DataFrame([[1.0, 0.3], [0.3, 1.0]], index=["A", "B"], columns=["A", "B"])
        sc = prep.sample_markov_scenarios(
            _params(0.5), corr, n_states=3, n_scenarios=5, rng=np.random.default_rng(0)
        )

        assert len(sc) == 12 * 3 * 5 * 2
        assert set(sc["markov_state"]) == {1, 2, 3}
        assert (sc["inflow_mwmed"] > 0).all()

    def test_dry_regime_really_is_drier(self):
        """The claim, not the mechanism: a policy can only benefit from the
        regime if the regimes actually differ in inflow."""
        corr = pd.DataFrame([[1.0, 0.3], [0.3, 1.0]], index=["A", "B"], columns=["A", "B"])
        sc = prep.sample_markov_scenarios(
            _params(0.5), corr, n_states=3, n_scenarios=200, rng=np.random.default_rng(1)
        )
        by_state = sc.groupby("markov_state")["inflow_mwmed"].mean()

        assert by_state.is_monotonic_increasing

    def test_preserves_cross_subsystem_correlation_within_a_regime(self):
        corr = pd.DataFrame([[1.0, 0.8], [0.8, 1.0]], index=["A", "B"], columns=["A", "B"])
        sc = prep.sample_markov_scenarios(
            _params(0.0), corr, n_states=3, n_scenarios=3000, rng=np.random.default_rng(2)
        )
        within = sc[sc["markov_state"] == 2]
        wide = within.pivot_table(
            index=["month", "scenario"], columns="subsystem", values="inflow_mwmed"
        )
        recovered = np.log(wide["A"]).corr(np.log(wide["B"]))

        assert recovered == pytest.approx(0.8, abs=0.05)

    def test_probabilities_sum_to_one_within_each_node(self):
        corr = pd.DataFrame([[1.0]], index=["A"], columns=["A"])
        sc = prep.sample_markov_scenarios(
            _params(0.5), corr, n_states=3, n_scenarios=4, rng=np.random.default_rng(3)
        )
        for _node, group in sc.groupby(["month", "markov_state"]):
            assert group["probability"].sum() == pytest.approx(1.0)


class TestWriteParquet:
    def test_round_trips(self, tmp_path):
        df = pd.DataFrame({"a": [1, 2, 3]})
        out = prep.write_parquet(df, tmp_path / "test.parquet")
        reloaded = pd.read_parquet(out)
        assert len(reloaded) == 3
