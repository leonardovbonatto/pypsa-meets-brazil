# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0014's coupled solve: reservoirs valued by SDDP cuts."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


coupled = _load("solve_network_sddp", REPO_ROOT / "scripts" / "solve_network_sddp.py")

logging.getLogger("pypsa").setLevel(logging.WARNING)
logging.getLogger("linopy").setLevel(logging.WARNING)


def _network(hours_per_month: int = 4) -> pypsa.Network:
    """One bus, two short months, thermal at 100 R$/MWh, hydro 10 MW."""
    snapshots = pd.DatetimeIndex(
        list(pd.date_range("2024-01-01", periods=hours_per_month, freq="h"))
        + list(pd.date_range("2024-02-01", periods=hours_per_month, freq="h"))
    )
    n = pypsa.Network()
    n.set_snapshots(snapshots)
    n.add("Bus", "A")
    n.add("Load", "A", bus="A", p_set=10.0)
    n.add("Generator", "A hydro", bus="A", p_nom=10.0)
    n.add("Generator", "A thermal", bus="A", p_nom=20.0, marginal_cost=100.0)
    n.add("Generator", "A load_shedding", bus="A", p_nom=1e6, marginal_cost=1e4)
    return n


def _reservoir(n: pypsa.Network) -> list[str]:
    inflow = pd.DataFrame({"A": 0.0}, index=n.snapshots)
    # 40 MWh of water: enough for the whole first month at full hydro output.
    return coupled.add_reservoirs(n, {"A": 1.0}, {"A": 40.0 / coupled.HOURS_PER_MWMES}, inflow)


class TestHourlyInflow:
    def test_holds_each_days_mean_for_its_hours(self):
        ena = pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-02"],
                "subsystem": "A",
                coupled.INFLOW_COLUMN: [5.0, 7.0],
            }
        )
        snapshots = pd.date_range("2024-01-01 22:00", periods=4, freq="h")
        out = coupled.hourly_inflow(ena, snapshots, ["A"])
        assert out["A"].tolist() == [5.0, 5.0, 7.0, 7.0]

    def test_raises_on_missing_days(self):
        ena = pd.DataFrame({"date": ["2024-01-01"], "subsystem": "A", coupled.INFLOW_COLUMN: [5.0]})
        with pytest.raises(ValueError, match="does not cover"):
            coupled.hourly_inflow(ena, pd.date_range("2024-01-02", periods=2, freq="h"), ["A"])


class TestAddReservoirs:
    def test_replaces_hydro_with_a_reservoir_of_the_same_size(self):
        n = _network()
        names = _reservoir(n)
        assert names == ["A reservoir"]
        assert "A hydro" not in n.generators.index
        unit = n.storage_units.loc["A reservoir"]
        assert unit["p_nom"] == 10.0
        assert unit["p_nom"] * unit["max_hours"] == pytest.approx(coupled.HOURS_PER_MWMES)
        assert unit["state_of_charge_initial"] == pytest.approx(40.0)


class TestSolveYear:
    def _solve(self, nodes: dict) -> pd.DataFrame:
        n = _network()
        reservoirs = _reservoir(n)
        regimes = pd.Series(1, index=range(1, 13))
        # Only two months exist in this toy network.
        monthly, _ = coupled.solve_year(
            n, nodes, regimes.loc[[1, 2]], reservoirs, solver_name="highs", solver_options={}
        )
        return monthly.set_index("month")

    def test_without_water_value_the_reservoir_is_used_at_once(self):
        monthly = self._solve({})
        assert monthly.loc[1, "storage_end_mwmes"] == pytest.approx(0.0, abs=1e-9)

    def test_a_valuable_cut_keeps_water_for_later(self):
        # Future cost falls by 1 million R$ per MWmes kept: about 1370 R$/MWh,
        # above thermal's 100, so January should burn thermal and keep water.
        nodes = {(1, 1): (np.array([10.0]), np.array([[-1.0]]))}
        monthly = self._solve(nodes)
        assert monthly.loc[1, "storage_end_mwmes"] * coupled.HOURS_PER_MWMES == pytest.approx(40.0)
        assert monthly.loc[1, "thermal_mw"] == pytest.approx(10.0)
        assert monthly.loc[1, "future_cost_rs"] > 0

    def test_carries_ending_storage_into_the_next_month(self):
        nodes = {(1, 1): (np.array([10.0]), np.array([[-1.0]]))}
        monthly = self._solve(nodes)
        # February has no cuts, so it spends what January kept.
        assert monthly.loc[2, "hydro_mw"] == pytest.approx(10.0)
        assert monthly.loc[2, "storage_end_mwmes"] == pytest.approx(0.0, abs=1e-9)


class TestSpillTieBreak:
    def test_worthless_water_is_kept_not_spilled(self):
        """With no water value and room to store, the first coupled run could
        spill inflow and run stored water instead; the spill cost forbids it."""
        n = _network()
        inflow = pd.DataFrame({"A": 5.0}, index=n.snapshots)
        reservoirs = coupled.add_reservoirs(
            n, {"A": 1.0}, {"A": 40.0 / coupled.HOURS_PER_MWMES}, inflow
        )
        coupled.solve_year(
            n, {}, pd.Series(1, index=[1, 2]), reservoirs, solver_name="highs", solver_options={}
        )
        assert n.storage_units_t.spill["A reservoir"].sum() == pytest.approx(0.0, abs=1e-6)

    def test_free_wind_runs_before_worthless_stored_water(self):
        """With no water value, wind and stored water both cost zero; the
        dispatch cost makes the solver burn wind and keep the water."""
        n = _network()
        n.add("Generator", "A wind", bus="A", p_nom=10.0, marginal_cost=0.0)
        reservoirs = _reservoir(n)
        coupled.solve_year(
            n, {}, pd.Series(1, index=[1, 2]), reservoirs, solver_name="highs", solver_options={}
        )
        assert n.storage_units_t.p["A reservoir"].sum() == pytest.approx(0.0, abs=1e-6)
        assert n.generators_t.p["A wind"].sum() == pytest.approx(80.0)
        assert coupled.RESERVOIR_DISPATCH_COST < coupled.SPILL_COST


class TestRunOfRiver:
    def test_run_of_river_is_used_first_and_shares_the_turbines(self):
        """ADR-0018: non-storable inflow runs before stored water, and the
        two together never exceed the subsystem's hydro capacity."""
        n = _network()
        n.loads_t.p_set["A"] = 30.0
        reservoirs = _reservoir(n)
        pairs = coupled.add_run_of_river(n, pd.DataFrame({"A": 6.0}, index=n.snapshots))
        coupled.solve_year(
            n,
            {},
            pd.Series(1, index=[1, 2]),
            reservoirs,
            solver_name="highs",
            solver_options={},
            run_of_river=pairs,
        )
        ror = n.generators_t.p["A run_of_river"]
        reservoir = n.storage_units_t.p["A reservoir"]
        assert ror.min() == pytest.approx(6.0)
        assert (ror + reservoir).max() <= 10.0 + 1e-6
        assert reservoir.sum() == pytest.approx(4.0 * 8)


class TestMinimumStorage:
    def test_thermal_runs_to_keep_storage_at_the_minimum(self):
        """ADR-0019: with worthless water, the month-end minimum makes the
        solver burn thermal (100 R$/MWh) rather than fall below it at a penalty
        of 200 R$/MWh."""
        n = _network()
        reservoirs = _reservoir(n)
        vminop = pd.DataFrame(
            {
                "month": [1, 2],
                "subsystem": ["A", "A"],
                "min_share": [0.5, 0.5],
                "penalty_rs_per_mwh": [200.0, 200.0],
            }
        )
        coupled.solve_year(
            n,
            {},
            pd.Series(1, index=[1, 2]),
            reservoirs,
            solver_name="highs",
            solver_options={},
            vminop=vminop,
        )
        soc = n.storage_units_t.state_of_charge["A reservoir"]
        # 1 MWmes = 730 MWh of capacity; half of it is far above the 40 MWh
        # held, so the reservoir keeps everything and thermal serves the load.
        assert soc.iloc[-1] == pytest.approx(40.0)
        assert n.generators_t.p["A thermal"].sum() == pytest.approx(80.0)
