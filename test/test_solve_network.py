# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Tests for solving and summarizing the T0 network.

These call the real HiGHS solver on tiny hand-built networks - fast (a
handful of variables), but exercising the actual solve path rather than
mocking it, same as PR-06 verified the real PyPSA API before trusting it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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


solve_network = _load("solve_network", REPO_ROOT / "scripts" / "solve_network.py")

SOLVER = {"solver_name": "highs", "solver_options": {}}


def _one_bus_network(*, load_mw: float) -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2024-01-01", periods=1, freq="1h"))
    n.add("Carrier", "AC")
    n.add("Bus", "A", carrier="AC")
    n.add("Load", "A", bus="A", p_set=load_mw)
    return n


class TestSolve:
    def test_feasible_network_solves_optimally(self):
        n = _one_bus_network(load_mw=100.0)
        n.add("Carrier", "cheap")
        n.add("Generator", "A cheap", bus="A", carrier="cheap", p_nom=200.0, marginal_cost=10.0)

        status, condition = solve_network.solve(n, **SOLVER)

        assert status == "ok"
        assert condition == "optimal"
        assert n.generators_t.p.loc[n.snapshots[0], "A cheap"] == pytest.approx(100.0)

    def test_merit_order_is_respected(self):
        """Cheap generator maxes out before the expensive one is touched."""
        n = _one_bus_network(load_mw=150.0)
        n.add("Carrier", ["cheap", "expensive"])
        n.add("Generator", "A cheap", bus="A", carrier="cheap", p_nom=100.0, marginal_cost=10.0)
        n.add(
            "Generator",
            "A expensive",
            bus="A",
            carrier="expensive",
            p_nom=100.0,
            marginal_cost=500.0,
        )

        solve_network.solve(n, **SOLVER)

        t = n.snapshots[0]
        assert n.generators_t.p.loc[t, "A cheap"] == pytest.approx(100.0)
        assert n.generators_t.p.loc[t, "A expensive"] == pytest.approx(50.0)
        assert n.objective == pytest.approx(100 * 10.0 + 50 * 500.0)

    def test_raises_when_infeasible(self):
        """No generator can cover the load, and there is no slack - must fail loudly."""
        n = _one_bus_network(load_mw=100.0)
        n.add("Carrier", "cheap")
        n.add("Generator", "A cheap", bus="A", carrier="cheap", p_nom=10.0, marginal_cost=10.0)

        with pytest.raises(RuntimeError, match="did not reach an optimal solution"):
            solve_network.solve(n, **SOLVER)


class TestSummarizeDispatch:
    def test_shape_and_keys(self):
        n = _one_bus_network(load_mw=100.0)
        n.add("Carrier", "cheap")
        n.add("Generator", "A cheap", bus="A", carrier="cheap", p_nom=200.0, marginal_cost=10.0)
        solve_network.solve(n, **SOLVER)

        summary = solve_network.summarize_dispatch(n)

        assert set(summary) == {
            "objective_rs",
            "mean_dispatch_mw_by_carrier",
            "load_shedding_mwh_by_bus",
            "mean_marginal_price_rs_per_mwh_by_bus",
            "all_prices_zero",
            "known_limitations",
        }
        assert summary["objective_rs"] == pytest.approx(1000.0)
        assert summary["mean_dispatch_mw_by_carrier"] == {"cheap": 100.0}
        assert summary["known_limitations"]  # non-empty, always present

    def test_no_load_shedding_when_none_occurs(self):
        n = _one_bus_network(load_mw=100.0)
        n.add("Carrier", "cheap")
        n.add("Generator", "A cheap", bus="A", carrier="cheap", p_nom=200.0, marginal_cost=10.0)
        solve_network.solve(n, **SOLVER)

        summary = solve_network.summarize_dispatch(n)
        assert summary["load_shedding_mwh_by_bus"] == {}

    def test_flags_load_shedding_when_it_occurs(self):
        """Load exceeds real capacity; only the load-shedding slack can cover the gap."""
        n = _one_bus_network(load_mw=100.0)
        n.add("Carrier", ["cheap", "load_shedding"])
        n.add("Generator", "A cheap", bus="A", carrier="cheap", p_nom=10.0, marginal_cost=10.0)
        n.add(
            "Generator",
            "A load_shedding",
            bus="A",
            carrier="load_shedding",
            p_nom=1_000_000.0,
            marginal_cost=10_000.0,
        )
        solve_network.solve(n, **SOLVER)

        summary = solve_network.summarize_dispatch(n)
        assert summary["load_shedding_mwh_by_bus"] == {"A": pytest.approx(90.0)}


class TestSummarizePrices:
    def test_reports_the_marginal_generator_cost(self):
        """
        Textbook merit order: the price is the marginal unit's cost, not the
        cheap unit's. Hour 1 needs only the cheap generator (10), hours 2-3
        need the expensive one (500).
        """
        n = pypsa.Network()
        n.set_snapshots(pd.date_range("2024-01-01", periods=3, freq="1h"))
        n.add("Carrier", ["AC", "cheap", "expensive"])
        n.add("Bus", "A", carrier="AC")
        n.add("Load", "A", bus="A", p_set=[50.0, 150.0, 250.0])
        n.add("Generator", "A cheap", bus="A", carrier="cheap", p_nom=100.0, marginal_cost=10.0)
        n.add(
            "Generator",
            "A expensive",
            bus="A",
            carrier="expensive",
            p_nom=200.0,
            marginal_cost=500.0,
        )
        solve_network.solve(n, **SOLVER)

        prices = solve_network.summarize_prices(n)

        assert prices["all_prices_zero"] is False
        # mean of (10, 500, 500)
        assert prices["mean_marginal_price_rs_per_mwh_by_bus"]["A"] == pytest.approx(
            336.67, abs=0.01
        )

    def test_flags_the_economically_degenerate_case(self):
        """
        A single zero-cost generator with headroom means nothing scarce ever
        sets a price - exactly the real T0 situation with free hydro.
        """
        n = _one_bus_network(load_mw=100.0)
        n.add("Carrier", "free")
        n.add("Generator", "A free", bus="A", carrier="free", p_nom=200.0, marginal_cost=0.0)
        n.add("Carrier", "backstop")
        n.add(
            "Generator",
            "A backstop",
            bus="A",
            carrier="backstop",
            p_nom=1000.0,
            marginal_cost=10_000.0,
        )
        solve_network.solve(n, **SOLVER)

        prices = solve_network.summarize_prices(n)

        assert prices["all_prices_zero"] is True
        assert prices["mean_marginal_price_rs_per_mwh_by_bus"]["A"] == pytest.approx(0.0)

    def test_handles_a_network_with_no_prices(self):
        """
        PyPSA drops an all-default series on export, so a reloaded solved
        network can legitimately have no marginal_price frame at all.
        """
        n = _one_bus_network(load_mw=100.0)

        prices = solve_network.summarize_prices(n)

        assert prices["mean_marginal_price_rs_per_mwh_by_bus"] == {}
        assert prices["all_prices_zero"] is None


class TestWriteSummary:
    def test_round_trips_through_json(self, tmp_path):
        import json

        summary = {
            "objective_rs": 123.0,
            "mean_dispatch_mw_by_carrier": {"hydro": 1.0},
            "load_shedding_mwh_by_bus": {},
            "mean_marginal_price_rs_per_mwh_by_bus": {"SE_CO": 0.0},
            "all_prices_zero": True,
            "known_limitations": ["a", "b"],
        }
        out = solve_network.write_summary(summary, tmp_path / "summary.json")

        assert json.loads(out.read_text()) == summary
