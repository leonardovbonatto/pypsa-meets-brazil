# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0022's T1 nodes and links."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


topo = _load("build_t1_topology", REPO_ROOT / "scripts" / "build_t1_topology.py")

REGISTRY = pd.DataFrame(
    {
        "id_estado": ["PR", "PR", "SP", "RS", "DF"],
        "id_subsistema": ["S", "SE", "SE", "S", "SE"],
        "val_potenciaefetiva": [900.0, 700.0, 500.0, 300.0, 10.0],
        "dat_desativacao": [None, None, None, None, "2020-01-01"],
    }
)
GRID = pd.DataFrame(
    {
        "node0": ["PR", "SP", "RS", "PR", "SP"],
        "node1": ["SP", "PR", "PR", "ARG", "DF"],
        "transfer_capacity": [1000.0, 500.0, 400.0, 50.0, 200.0],
        "efficiency": [0.99, 0.97, 0.98, 0.99, 1.0],
    }
)


class TestNodes:
    def test_split_state_gets_a_secondary_node_and_retired_state_keeps_one(self):
        nodes = topo.state_nodes(REGISTRY).set_index("node")
        assert nodes.loc["PR", "subsystem"] == "S"
        assert nodes.loc["PR_SE_CO", "capacity_mw"] == pytest.approx(700.0)
        assert not nodes.loc["PR_SE_CO", "main"]
        # DF's only unit is retired: no capacity, but a main node for its load.
        assert nodes.loc["DF", "capacity_mw"] == pytest.approx(0.0)
        assert nodes.loc["DF", "main"]


class TestLinks:
    def test_parallel_corridors_merge_and_foreign_ones_drop(self):
        pairs = topo.corridors(GRID).set_index(["a", "b"])
        assert pairs.loc[("PR", "SP"), "p_nom_mw"] == pytest.approx(1500.0)
        assert pairs.loc[("PR", "SP"), "efficiency"] == pytest.approx(
            (0.99 * 1000 + 0.97 * 500) / 1500
        )
        assert ("ARG", "PR") not in pairs.index

    def test_secondary_node_gets_a_dedicated_link_to_its_subsystem(self):
        links = topo.t1_links(GRID, topo.state_nodes(REGISTRY))
        dedicated = links[links["kind"] == "dedicated"]
        assert dedicated[["bus0", "bus1"]].values.tolist() == [["PR_SE_CO", "SP"]]
        assert dedicated["p_nom_mw"].iloc[0] == pytest.approx(700.0)
