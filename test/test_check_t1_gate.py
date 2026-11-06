# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0022's T1 benchmark."""

from __future__ import annotations

import importlib.util
import logging
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


gate = _load("check_t1_gate", REPO_ROOT / "scripts" / "check_t1_gate.py")
logging.getLogger("pypsa").setLevel(logging.WARNING)
HOURS = pd.date_range("2024-01-01", periods=2, freq="h")


def _t1() -> pypsa.Network:
    """Two S-side nodes feeding one SE_CO node, 10 MW across the boundary."""
    n = pypsa.Network()
    n.set_snapshots(HOURS)
    for b in ["PR", "RS", "SP"]:
        n.add("Bus", b)
    n.add("Load", "SP", bus="SP", p_set=10.0)
    n.add("Generator", "PR hydro", bus="PR", carrier="hydro", p_nom=6.0, marginal_cost=1.0)
    n.add("Generator", "RS hydro", bus="RS", carrier="hydro", p_nom=6.0, marginal_cost=1.0)
    n.add("Link", "PR-SP", bus0="PR", bus1="SP", p_nom=20.0)
    n.add("Link", "RS-PR", bus0="RS", bus1="PR", p_nom=20.0)
    n.optimize(solver_name="highs", include_objective_constant=False)
    return n


class TestT1Gate:
    def test_boundary_flow_sums_links_that_cross_it(self):
        n = _t1()
        subsystem = pd.Series({"PR": "S", "RS": "S", "SP": "SE_CO"})
        boundaries = pd.DataFrame({"bus0": ["SE_CO"], "bus1": ["S"], "p_nom_mw": [100.0]})
        flows = gate.boundary_flows(n, subsystem, boundaries)
        # 10 MW goes S -> SE_CO, so SE_CO -> S is -10; RS-PR stays inside S.
        assert list(flows["SE_CO-S"]) == pytest.approx([-10.0, -10.0])

    def test_report_compares_generation_with_t0(self):
        n = _t1()
        subsystem = pd.Series({"PR": "S", "RS": "S", "SP": "SE_CO"})
        boundaries = pd.DataFrame({"bus0": ["SE_CO"], "bus1": ["S"], "p_nom_mw": [100.0]})
        observed = pd.DataFrame(
            {"snapshot": HOURS, "bus0": "SE_CO", "bus1": "S", "observed_mw": [-12.0, -12.0]}
        )
        report = gate.t1_report(n, n, subsystem, observed, boundaries)
        assert report["generation_matches_t0"]
        assert report["interchange"][0]["error_share_of_capacity"] == pytest.approx(0.02)
        assert report["passed"]
