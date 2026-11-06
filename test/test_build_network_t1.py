# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0022's T1 network (T0 split across state nodes)."""

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


t1 = _load("build_network_t1", REPO_ROOT / "scripts" / "build_network_t1.py")
logging.getLogger("pypsa").setLevel(logging.WARNING)

NODES = pd.DataFrame(
    {
        "node": ["PR", "PR_SE_CO", "SP", "RS"],
        "state": ["PR", "PR", "SP", "RS"],
        "subsystem": ["S", "SE_CO", "SE_CO", "S"],
        "capacity_mw": [100.0, 70.0, 50.0, 30.0],
        "main": [True, False, True, True],
    }
)
HOURS = pd.date_range("2024-01-01", periods=2, freq="h")


class TestShares:
    def test_generation_share_follows_observed_output_per_node(self):
        raw = pd.DataFrame(
            {
                "id_estado": ["PR", "PR", "SP"],
                "id_subsistema": ["SE", "S", "SE"],
                "nom_tipousina": ["HIDROELÉTRICA"] * 3,
                "cod_modalidadeoperacao": ["TIPO I"] * 3,
                "val_geracao": [300.0, 50.0, 100.0],
            }
        )
        shares = t1.observed_shares(raw, NODES).set_index(["subsystem", "node"])["share"]
        assert shares[("SE_CO", "PR_SE_CO")] == pytest.approx(0.75)
        assert shares[("SE_CO", "SP")] == pytest.approx(0.25)
        assert shares[("S", "PR")] == pytest.approx(1.0)

    def test_load_share_is_within_the_subsystem(self):
        dlr = pd.DataFrame(
            {
                "time": ["2020-01-01 00:00:00"] * 2,
                "state": ["PR", "RS"],
                "value": [300.0, 100.0],
            }
        )
        shares = t1.load_shares(dlr, NODES).set_index("node")["share"]
        assert shares["PR"] == pytest.approx(0.75)


class TestBuild:
    def test_subsystem_totals_equal_t0(self):
        t0 = pypsa.Network()
        t0.set_snapshots(HOURS)
        for s in ["S", "SE_CO"]:
            t0.add("Bus", s)
            t0.add("Load", s, bus=s, p_set=10.0)
            t0.add(
                "Generator",
                f"{s} load_shedding",
                bus=s,
                carrier="load_shedding",
                p_nom=1e6,
                marginal_cost=1e4,
            )
        t0.add("Generator", "SE_CO hydro", bus="SE_CO", carrier="hydro", p_nom=100.0)
        shares = pd.DataFrame(
            {
                "subsystem": ["SE_CO", "SE_CO"],
                "carrier": ["hydro", "hydro"],
                "node": ["PR_SE_CO", "SP"],
                "share": [0.75, 0.25],
            }
        )
        load = pd.DataFrame(
            {
                "subsystem": ["S", "S", "SE_CO"],
                "month": [1, 1, 1],
                "hour": [0, 0, 0],
                "node": ["PR", "RS", "SP"],
                "share": [0.75, 0.25, 1.0],
            }
        )
        load = pd.concat([load, load.assign(hour=1)], ignore_index=True)
        links = pd.DataFrame(
            {
                "bus0": ["PR", "PR_SE_CO", "PR"],
                "bus1": ["SP", "SP", "RS"],
                "p_nom_mw": [50.0, 70.0, 50.0],
                "efficiency": [1.0, 1.0, 1.0],
            }
        )
        n = t1.build_t1(t0, NODES, links, shares, load)
        hydro = n.generators[n.generators["carrier"] == "hydro"]["p_nom"]
        assert hydro.sum() == pytest.approx(100.0)
        assert hydro["PR_SE_CO hydro"] == pytest.approx(75.0)
        demand = n.loads_t.p_set.sum(axis=1)
        assert list(demand) == pytest.approx([20.0, 20.0])
        assert len(n.links) == 6  # one-way pairs
