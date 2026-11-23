# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0026's T3 structure, on synthetic tables in the tidy layout."""

from __future__ import annotations

import importlib.util
import logging
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


t3 = _load("build_network_t3", REPO_ROOT / "scripts" / "build_network_t3.py")
logging.getLogger("pypsa").setLevel(logging.WARNING)

BUSES = pd.DataFrame(
    {
        "bus": [1, 2, 3, 4],
        "v_nom_kv": [500.0, 500.0, 13.8, 500.0],
        "state": ["BA", "BA", "BA", "SP"],
        "subsystem": ["NE", "NE", "NE", None],
        "lat": [-12.0, None, None, None],
        "lon": [-38.0, None, None, None],
    }
)
LINES = pd.DataFrame(
    {
        "line": [10, 11, 12],
        "bus0": [1, 1, 2],
        "bus1": [2, 2, 4],
        "r_pct": [0.1, 0.1, 0.1],
        "x_pct": [1.2, 1.2, 1.2],
        "b_mvar": [0.0, 0.0, 0.0],
        "s_nom_mva": [2000.0, None, 2000.0],
        "existing_flag": [0, 1, 0],
    }
)
TRANSFORMERS = pd.DataFrame(
    {
        "transformer": [20],
        "bus0": [3],
        "bus1": [2],
        "r_pct": [0.0],
        "x_pct": [4.0],
        "existing_flag": [0],
    }
)
HVDC = pd.DataFrame(
    {
        "hvdc": [30, 31],
        "bus0": [1, 1],
        "bus1": [2, 2],
        "p_nom_mw": [2000, 2500],
        "link_name": ["P1", "FUTURE"],
        "existing_flag": [0, 1],
    }
)


class TestStructure:
    def test_future_elements_and_unmapped_buses_are_left_out(self):
        n, report = t3.build_t3(BUSES, LINES, TRANSFORMERS, HVDC)
        assert "4" not in n.buses.index  # no subsystem
        assert "L11" not in n.lines.index  # Existing = 1
        assert "L12" not in n.lines.index  # touches the dropped bus
        assert list(n.links.index) == ["HVDC30"]
        assert n.links.loc["HVDC30", "p_min_pu"] == (0.0 if t3.HVDC_ONE_WAY else -1.0)
        assert (n.links.loc["HVDC30", "marginal_cost"] > 0.0) == t3.HVDC_ONE_WAY
        assert report["dropped_future_lines"] == 1

    def test_impedance_in_ohm_and_transformer_as_line(self):
        n, _ = t3.build_t3(BUSES, LINES, TRANSFORMERS, HVDC)
        assert n.lines.at["L10", "x"] == pytest.approx(30.0)  # 1.2% on 100 MVA at 500 kV
        # Transformer x referred to bus0 (13.8 kV): per unit x / v^2 gives back 4% on 100 MVA.
        x_pu = n.lines.at["T20", "x"] / 13.8**2 * t3.BASE_MVA
        assert x_pu == pytest.approx(0.04)
        assert n.lines.at["T20", "kind"] == "transformer"
