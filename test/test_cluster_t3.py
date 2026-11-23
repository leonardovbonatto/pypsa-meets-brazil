# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0026 decision 4: T1 by clustering T3, on small synthetic
networks (EPE's data stay local)."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import ClassVar

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


t3mod = _load("build_network_t3", REPO_ROOT / "scripts" / "build_network_t3.py")
cl = _load("cluster_t3", REPO_ROOT / "scripts" / "cluster_t3.py")
logging.getLogger("pypsa").setLevel(logging.WARNING)


def _net(buses: dict, lines: list) -> pypsa.Network:
    """buses: name -> (v_nom, state, subsystem); lines: (name, bus0, bus1,
    kind, x_ohm, s_nom)."""
    n = pypsa.Network()
    for b, (v, _state, _sub) in buses.items():
        n.add("Bus", b, v_nom=v)
    n.buses["state"] = [buses[b][1] for b in n.buses.index]
    n.buses["subsystem"] = [buses[b][2] for b in n.buses.index]
    for name, b0, b1, _, x, s in lines:
        n.add("Line", name, bus0=b0, bus1=b1, x=x, r=0.0, s_nom=s)
    n.lines["kind"] = [k for _, _, _, k, _, _ in lines]
    return n


class TestNodes:
    def test_node_is_state_or_state_and_minor_subsystem(self):
        buses = pd.DataFrame(
            {"state": ["PR", "PR", "PR", "SP"], "subsystem": ["S", "S", "SE_CO", "SE_CO"]}
        )
        assert list(cl.node_of(buses)) == ["PR", "PR", "PR_SE_CO", "SP"]

    def test_node_subsystem_from_name(self):
        main = pd.Series({"PR": "S"})
        assert cl.node_subsystem("PR", main) == "S"
        assert cl.node_subsystem("PR_SE_CO", main) == "SE_CO"


class TestSubstationRule:
    BUSES: ClassVar[dict] = {
        "a": (138.0, "MA", "N"),
        "b": (138.0, "TO", "N"),
        "c": (500.0, "TO", "N"),
        "d": (500.0, "BA", "NE"),
        "e": (230.0, "BA", "NE"),
    }
    # x in ohm at bus0's voltage; 138 kV: 1 pu on 100 MVA = 190.44 ohm
    LINES: ClassVar[list] = [
        ("jumper", "a", "b", "line", 1.0e-5 * 190.44, 54.0),
        ("tr", "b", "c", "transformer", 10.0, 1.0e6),
        ("line", "c", "d", "line", 25.0, 2000.0),
        ("cap", "d", "e", "line", -1.0, 500.0),
    ]

    def test_transformers_jumpers_and_capacitors_are_substation_branches(self):
        n = _net(self.BUSES, self.LINES)
        assert sorted(cl.substation_branches(n)) == ["cap", "jumper", "tr"]

    def test_group_takes_node_of_highest_voltage_bus(self):
        n = _net(self.BUSES, self.LINES)
        out = cl.keep_substations_whole(n, cl.node_of(n.buses))
        # a (MA) is jumpered to b, which is transformed to c (500 kV, TO)
        assert out["a"] == "TO"
        # only the real 500 kV line c-d crosses a node border
        crossing = [k for k, r in n.lines.iterrows() if out[r["bus0"]] != out[r["bus1"]]]
        assert crossing == ["line"]


def test_unrated_line_gets_its_voltage_class_median():
    n = _net(
        {"a": (230.0, "X", "N"), "b": (230.0, "X", "N"), "c": (230.0, "Y", "N")},
        [
            ("l1", "a", "b", "line", 10.0, 300.0),
            ("l2", "b", "c", "line", 10.0, 500.0),
            ("l3", "a", "c", "line", 10.0, 1.0e6),  # 99999 is read as 1e6
        ],
    )
    assert cl.rate_unrated_lines(n) == 1
    assert n.lines.loc["l3", "s_nom"] == pytest.approx(400.0)


def test_common_base_keeps_per_unit_reactance():
    n = _net(
        {"a": (230.0, "X", "N"), "b": (230.0, "X", "N")},
        [("l", "a", "b", "line", 52.9, 300.0)],
    )
    before = n.lines.loc["l", "x"] / 230.0**2
    cl.to_common_base(n)
    assert n.lines.loc["l", "x"] / cl.COMMON_KV**2 == pytest.approx(before)
    assert set(n.buses["v_nom"]) == {cl.COMMON_KV}


def test_main_component_keeps_islands_reached_over_hvdc():
    n = pypsa.Network()
    for b in ["a", "b", "c", "island", "alone"]:
        n.add("Bus", b)
    n.add("Line", "ab", bus0="a", bus1="b", x=1.0, s_nom=1.0)
    n.add("Line", "bc", bus0="b", bus1="c", x=1.0, s_nom=1.0)
    n.add("Link", "hvdc", bus0="island", bus1="a", p_nom=1.0)
    assert list(t3mod.main_component(n)) == ["a", "b", "c", "island"]


def test_low_voltage_ties_dropped_only_beside_a_high_voltage_corridor():
    n = _net(
        {
            "a": (500.0, "X", "N"),
            "b": (138.0, "X", "N"),
            "c": (500.0, "Y", "N"),
            "d": (138.0, "Y", "N"),
            "e": (138.0, "Z", "N"),
        },
        [
            ("hv", "a", "c", "line", 25.0, 2000.0),
            ("lv_parallel", "b", "d", "line", 5.0, 100.0),
            ("lv_only", "d", "e", "line", 5.0, 100.0),
        ],
    )
    busmap = pd.Series({"a": "X", "b": "X", "c": "Y", "d": "Y", "e": "Z"})
    assert list(cl.low_voltage_ties(n, busmap, 230.0)) == ["lv_parallel"]


def test_fitted_reactance_sees_impedance_inside_a_node():
    """X = a - b, Y = c; corridor b - c (x = 1). A transfer X -> Y spread
    over a and b also crosses a - b (x = 1), so the fitted corridor is
    longer than the copper-plate x = 1; with injections only at b it would
    be exactly 1."""
    n = _net(
        {"a": (500.0, "X", "N"), "b": (500.0, "X", "N"), "c": (500.0, "Y", "N")},
        [("ab", "a", "b", "line", 1.0, 100.0), ("bc", "b", "c", "line", 1.0, 100.0)],
    )
    n.add("Load", "la", bus="a", p_set=1.0)
    n.add("Load", "lb", bus="b", p_set=1.0)
    n.add("Load", "lc", bus="c", p_set=1.0)
    busmap = pd.Series({"a": "X", "b": "X", "c": "Y"})
    x = cl.fitted_reactances(n, busmap)
    # a and b get half the injection each; X's mean angle sits 0.25 above b
    assert x["X-Y"] == pytest.approx(1.25)


def test_equal_voltage_tie_goes_to_the_same_node_every_time():
    n = _net(
        {"z": (138.0, "TO", "N"), "y": (138.0, "MA", "N"), "x": (138.0, "TO", "N")},
        [("j1", "z", "y", "line", 1.0e-4, 54.0), ("j2", "y", "x", "line", 1.0e-4, 54.0)],
    )
    out = cl.keep_substations_whole(n, cl.node_of(n.buses))
    assert set(out) == {"TO"}  # two of the three top buses are in TO
