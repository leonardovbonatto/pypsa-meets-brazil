# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0026's EPE network loader, on synthetic text in EPE's layout."""

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


epe = _load("epe_network", REPO_ROOT / "scripts" / "epe_network.py")

BUSES = pd.DataFrame(
    {
        "Code": [1, 2, 3, 4],
        "Name": ["SUBST-BA500", "GEN1--UHE013", "OTHER-SP230", "ISOLATED013"],
        "System": [3, 3, 1, 99],
        "Area": [1, 1, 2, 3],
        "BaseVoltage": [500.0, 13.8, 230.0, 13.8],
    }
)
TRANSFORMERS = pd.DataFrame({"BusFromCode": [2], "BusToCode": [1]})


class TestRead:
    def test_reads_version_and_bang_header(self, tmp_path):
        p = tmp_path / "dbus.dat"
        p.write_text("$version=1\n!Code,Name\n1,AÇU-RN500\n", encoding="latin-1")
        df = epe.read_psr(p)
        assert df.columns.tolist() == ["Code", "Name"]
        assert df["Name"].iloc[0] == "AÇU-RN500"

    def test_rejects_a_file_without_version(self, tmp_path):
        p = tmp_path / "x.dat"
        p.write_text("Code,Name\n", encoding="latin-1")
        with pytest.raises(ValueError, match="version"):
            epe.read_psr(p)


class TestBuses:
    def test_state_from_name_then_from_transformer_neighbour(self):
        states = epe.bus_states(BUSES, TRANSFORMERS)
        assert states[1] == "BA"
        assert states[2] == "BA"  # generator terminal, through its transformer
        assert states[3] == "SP"
        assert pd.isna(states[4])  # no name, no neighbour: reported, not guessed

    def test_subsystem_from_system_code_and_unknown_left_empty(self):
        coords = pd.DataFrame({"Code": [1], "Latitude": [-12.0], "Longitude": [-38.0]})
        buses = epe.tidy_buses(BUSES, TRANSFORMERS, coords).set_index("bus")
        assert buses.loc[1, "subsystem"] == "NE"
        assert buses.loc[3, "subsystem"] == "SE_CO"
        assert pd.isna(buses.loc[4, "subsystem"])
        assert buses.loc[1, "lat"] == pytest.approx(-12.0)


class TestImpedance:
    def test_percent_on_100_mva_to_ohm(self):
        lines = pd.DataFrame({"bus0": [1], "x_pct": [1.2]})
        buses = pd.DataFrame({"bus": [1], "v_nom_kv": [500.0]})
        # 1.2% x 500^2 / 100 MVA / 100 = 30 ohm
        assert epe.impedance_check(lines, buses)["500"] == pytest.approx(30.0)


class TestHvdc:
    def test_dc_line_joins_the_ac_buses_of_its_converters(self):
        dc_buses = pd.DataFrame({"Code": [10, 20], "DCLink": [1, 1]})
        dc_lines = pd.DataFrame(
            {"Code": [7], "Name": ["DC_7"], "BusFromCode": [10], "BusToCode": [20]}
        )
        converters = pd.DataFrame({"DCBusCode": [10, 20], "ACBusCode": [100, 200]})
        links = pd.DataFrame({"Code": [1], "Name": ["POLO 1"], "BasePower": [2000]})
        out = epe.hvdc_links(dc_buses, dc_lines, converters, links)
        assert out[["bus0", "bus1", "p_nom_mw"]].values.tolist() == [[100, 200, 2000]]

    def test_series_capacitor_bus_takes_state_across_a_line(self):
        buses = pd.DataFrame(
            {
                "Code": [1, 5],
                "Name": ["MARAB-PA500", "MARAB1CAP500"],
                "System": [4, 4],
                "Area": [1, 1],
                "BaseVoltage": [500.0, 500.0],
            }
        )
        lines = pd.DataFrame({"BusFromCode": [1], "BusToCode": [5]})
        states = epe.bus_states(buses, pd.DataFrame({"BusFromCode": [], "BusToCode": []}), lines)
        assert states[5] == "PA"
