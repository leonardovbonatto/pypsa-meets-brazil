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
        variance recovers 1. If any of these drift, regimes no longer
        partition the anomaly and their shares stop being 1/K."""
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


def _corr(rho: float) -> pd.DataFrame:
    return pd.DataFrame([[1.0, rho], [rho, 1.0]], index=["A", "B"], columns=["A", "B"])


TWO_REGIONS = {"a": ["A"], "b": ["B"]}


def _simulate(phi: float, rho: float = 0.3, n_paths: int = 20000, seed: int = 0):
    params = _params(phi)
    z = prep.simulate_par1_anomalies(
        params, _corr(rho), n_paths=n_paths, rng=np.random.default_rng(seed)
    )
    states = prep.regional_states(z, params, _corr(rho), regions=TWO_REGIONS, n_states=3)
    return params, z, states


class TestSimulatePar1Anomalies:
    def test_recovers_phi_and_correlation(self):
        _, z, _ = _simulate(0.9, rho=0.5)

        assert np.corrcoef(z[:, 5, 0], z[:, 6, 0])[0, 1] == pytest.approx(0.9, abs=0.01)
        assert np.corrcoef(z[:, 6, 0], z[:, 6, 1])[0, 1] == pytest.approx(0.5, abs=0.02)
        assert z[:, 6].std(axis=0) == pytest.approx([1.0, 1.0], abs=0.02)


class TestRegionalStates:
    def test_joint_states_are_ordered_dry_to_wet(self):
        """State 1 must be dry in every region and the last state wet in every
        region: the acceptance test compares exactly those two."""
        _, z, states = _simulate(0.5)
        month = 6

        driest = z[states[:, month - 1] == 1, month - 1]
        wettest = z[states[:, month - 1] == 9, month - 1]
        assert (driest.max(axis=0) < 0).all()
        assert (wettest.min(axis=0) > 0).all()

    def test_each_region_has_equal_probability_bins(self):
        _, _, states = _simulate(0.5)
        first_region = (states[:, 5] - 1) // 3

        shares = np.bincount(first_region) / len(first_region)
        assert shares == pytest.approx([1 / 3] * 3, abs=0.02)

    def test_regions_can_disagree(self):
        """The point of ADR-0010: with negatively correlated regions, one dry
        while the other is wet must be common, not a rarity."""
        _, _, opposed = _simulate(0.5, rho=-0.5)
        _, _, aligned = _simulate(0.5, rho=0.9)

        def dry_wet_share(states):
            return float(np.mean(states[:, 5] == 3))

        assert dry_wet_share(opposed) > 3 * dry_wet_share(aligned)

    def test_regions_must_cover_every_subsystem_once(self):
        params, z, _ = _simulate(0.5, n_paths=10)
        with pytest.raises(ValueError, match="exactly once"):
            prep.regional_states(z, params, _corr(0.3), regions={"a": ["A"]}, n_states=3)


class TestJointTransitions:
    def test_every_row_sums_to_one(self):
        _, _, states = _simulate(0.7)
        tm = prep.joint_transitions(states, n_joint=9)

        row_sums = tm.groupby(["stage", "from_state"])["probability"].sum()
        assert np.allclose(row_sums.to_numpy(), 1.0)
        assert set(tm.loc[tm["stage"] == 1, "from_state"]) == {0}

    def test_high_phi_is_more_persistent_than_low_phi(self):
        def stay_dry(phi):
            _, _, states = _simulate(phi)
            tm = prep.joint_transitions(states, n_joint=9)
            row = tm[(tm["stage"] == 7) & (tm["from_state"] == 1) & (tm["to_state"] == 1)]
            return float(row["probability"].iloc[0])

        assert stay_dry(0.95) > stay_dry(0.05)

    def test_zero_phi_gives_state_independent_transitions(self):
        """No persistence: the next joint state does not depend on this one."""
        _, _, states = _simulate(0.0, n_paths=60000)
        tm = prep.joint_transitions(states, n_joint=9)
        matrix = tm[tm["stage"] == 7].pivot(
            index="from_state", columns="to_state", values="probability"
        )

        assert np.allclose(matrix.to_numpy(), matrix.mean(axis=0).to_numpy(), atol=0.03)

    def test_an_unvisited_state_raises(self):
        states = np.ones((5, 12), dtype=int)
        with pytest.raises(ValueError, match="never visited"):
            prep.joint_transitions(states, n_joint=2)


class TestSampleRegionalScenarios:
    def _scenarios(self, n_scenarios: int = 20):
        params, z, states = _simulate(0.5)
        return prep.sample_regional_scenarios(
            z,
            states,
            params,
            _corr(0.3),
            n_joint=9,
            n_scenarios=n_scenarios,
            rng=np.random.default_rng(1),
        )

    def test_shape_and_probabilities(self):
        sc = self._scenarios(n_scenarios=5)

        assert len(sc) == 12 * 9 * 5 * 2
        assert (sc["inflow_mwmed"] > 0).all()
        for _node, group in sc.groupby(["month", "markov_state"]):
            assert group["probability"].sum() == pytest.approx(2.0)

    def test_dry_everywhere_is_drier_than_wet_everywhere(self):
        """The claim, not the mechanism: regimes only help a policy if they
        differ in inflow, in every subsystem."""
        sc = self._scenarios()
        means = sc.groupby(["markov_state", "subsystem"])["inflow_mwmed"].mean().unstack()

        assert (means.loc[1] < means.loc[9]).all()

    def test_a_too_small_pool_raises(self):
        params, z, states = _simulate(0.5, n_paths=30)
        with pytest.raises(ValueError, match="simulated months"):
            prep.sample_regional_scenarios(
                z,
                states,
                params,
                _corr(0.3),
                n_joint=9,
                n_scenarios=50,
                rng=np.random.default_rng(0),
            )


class TestSamplePar1Paths:
    def _paths(self, phi: float, regions=None, n_states: int = 3) -> pd.DataFrame:
        return prep.sample_par1_paths(
            _params(phi),
            _corr(0.3),
            regions=regions or TWO_REGIONS,
            n_states=n_states,
            n_paths=4000,
            rng=np.random.default_rng(0),
        )

    def test_keeps_the_fitted_persistence(self):
        """The reason these paths exist: training scenarios lose
        persistence, and this test set must not."""
        wide = self._paths(0.9).query("subsystem == 'A'")
        anomaly = np.log(wide.pivot(index="path", columns="month", values="inflow_mwmed"))

        assert anomaly[6].corr(anomaly[7]) == pytest.approx(0.9, abs=0.02)

    def test_inflows_do_not_depend_on_the_regime_design(self):
        """Every design must be scored on the same world."""
        regional = self._paths(0.5)
        national = self._paths(0.5, regions={"all": ["A", "B"]}, n_states=5)

        assert np.array_equal(regional["inflow_mwmed"], national["inflow_mwmed"])
        assert not np.array_equal(regional["markov_state"], national["markov_state"])

    def test_one_regime_per_path_and_month(self):
        counts = self._paths(0.5).groupby(["path", "month"])["markov_state"].nunique()

        assert counts.max() == 1


class TestWriteParquet:
    def test_round_trips(self, tmp_path):
        df = pd.DataFrame({"a": [1, 2, 3]})
        out = prep.write_parquet(df, tmp_path / "test.parquet")
        reloaded = pd.read_parquet(out)
        assert len(reloaded) == 3


class TestMonthlyRenewables:
    def test_averages_available_mw_by_month_and_bus(self):
        index = pd.to_datetime(["2024-01-01 00:00", "2024-01-01 01:00", "2024-02-01 00:00"])
        available = pd.DataFrame(
            {"NE wind": [100.0, 300.0, 50.0], "NE solar": [0.0, 100.0, 10.0]}, index=index
        )
        buses = pd.Series({"NE wind": "NE", "NE solar": "NE"})
        out = prep.monthly_renewables(available, buses, subsystems=["N", "NE"]).set_index(
            ["month", "subsystem"]
        )["renewable_mw"]
        assert out[(1, "NE")] == pytest.approx(250.0)
        assert out[(2, "NE")] == pytest.approx(60.0)

    def test_subsystem_without_carriers_gets_zero(self):
        index = pd.to_datetime(["2024-01-01 00:00"])
        available = pd.DataFrame({"NE wind": [10.0]}, index=index)
        out = prep.monthly_renewables(
            available, pd.Series({"NE wind": "NE"}), subsystems=["N", "NE"]
        )
        assert out.loc[out["subsystem"] == "N", "renewable_mw"].tolist() == [0.0]

    def test_rejects_generators_without_a_bus(self):
        available = pd.DataFrame({"X wind": [1.0]}, index=pd.to_datetime(["2024-01-01"]))
        with pytest.raises(ValueError, match="without a bus"):
            prep.monthly_renewables(available, pd.Series(dtype=str), subsystems=["N"])


class TestMultiYearHorizon:
    """ADR-0017: two simulated years, so December -> January exists."""

    def test_persistence_carries_across_the_year_boundary(self):
        z = prep.simulate_par1_anomalies(
            _params(0.9), _corr(0.0), n_paths=20000, rng=np.random.default_rng(0), n_months=24
        )
        assert z.shape == (20000, 24, 2)
        december, january = z[:, 11, 0], z[:, 12, 0]
        assert np.corrcoef(december, january)[0, 1] == pytest.approx(0.9, abs=0.02)

    def test_default_keeps_twelve_months_and_the_same_draws(self):
        a = prep.simulate_par1_anomalies(
            _params(0.5), _corr(0.0), n_paths=10, rng=np.random.default_rng(3)
        )
        b = prep.simulate_par1_anomalies(
            _params(0.5), _corr(0.0), n_paths=10, rng=np.random.default_rng(3), n_months=12
        )
        assert a.shape[1] == 12
        np.testing.assert_array_equal(a, b)

    def test_transitions_cover_every_stage(self):
        z = prep.simulate_par1_anomalies(
            _params(0.7), _corr(0.0), n_paths=5000, rng=np.random.default_rng(1), n_months=24
        )
        states = prep.regional_states(
            z, _params(0.7), _corr(0.0), regions={"a": ["A"], "b": ["B"]}, n_states=2
        )
        transitions = prep.joint_transitions(states, n_joint=4)
        assert sorted(transitions["stage"].unique()) == list(range(1, 25))
