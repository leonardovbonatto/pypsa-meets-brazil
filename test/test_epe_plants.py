# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for PR-76's EPE plant and load weights, on synthetic text."""

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


plants = _load("epe_plants", REPO_ROOT / "scripts" / "epe_plants.py")
energy = _load("build_network_t3_energy", REPO_ROOT / "scripts" / "build_network_t3_energy.py")

HEADER = "!NUM ...Nombre... .PV. .VAA ....Pot"


def _row(num: str, name: str, pv: str, vaa: str, pot: str) -> str:
    """A row aligned like EPE's: numbers right-aligned to their marker's end,
    the name left-aligned at its marker's start, blanks left blank."""
    return (
        " "
        + num.rjust(3)
        + " "
        + name.ljust(12)
        + " "
        + pv.rjust(4)
        + " "
        + vaa.rjust(4)
        + " "
        + pot.rjust(7)
    )


HYDRO = "\n".join(
    [
        HEADER,
        _row("117", "GUARAPIRANGA", "117", "118", "10"),
        _row("119", "HENRY BORDEN", "318", "", "889"),
    ]
)


class TestFixedWidth:
    def test_blank_fields_do_not_shift_columns(self):
        df = plants.fixed_width(HYDRO, {"code": "NUM", "name": "...Nombre...", "mw": "....Pot"})
        assert df["name"].tolist() == ["GUARAPIRANGA", "HENRY BORDEN"]
        assert df["mw"].tolist() == ["10", "889"]

    def test_missing_marker_raises(self):
        with pytest.raises(ValueError, match="no header"):
            plants.fixed_width(HYDRO, {"x": "TechTyp"})


class TestWeights:
    def test_plant_capacity_lands_on_its_bus(self):
        connection = pd.DataFrame(
            {
                "SystemId": ["se", "se"],
                "BusCode": [5, 6],
                "PlantType": ["H", "T"],
                "PlantCode": [117, 9],
            }
        )
        table = pd.DataFrame(
            {
                "system": ["se", "se"],
                "type": ["H", "T"],
                "code": [117, 9],
                "mw": [10.0, 640.0],
                "carrier": ["hydro", "nuclear"],
            }
        )
        w = plants.plant_weights(connection, table).set_index("bus")
        assert w.loc[5, "carrier"] == "hydro"
        assert w.loc[6, "weight_mw"] == pytest.approx(640.0)

    def test_load_is_the_base_case_mean_over_blocks(self):
        loads = pd.DataFrame({"Code": [1], "BusCode": [7]})
        loadp = pd.DataFrame(
            {
                "code": [1, 1, 1],
                "Date": ["1900/01/01", "1900/01/01", "2030/01/01"],
                "block": [1, 2, 1],
                "Pp": [10.0, 20.0, 99.0],
            }
        )
        assert plants.load_weights(loads, loadp)["weight_mw"].iloc[0] == pytest.approx(15.0)


class TestPlace:
    BUSES = pd.DataFrame(
        {
            "bus": [1, 2, 3],
            "state": ["BA", "BA", "BA"],
            "subsystem": ["NE"] * 3,
            "v_nom_kv": [500.0, 230.0, 13.8],
            "main_island": [True] * 3,
        }
    )

    def test_by_matching_kind_then_load_then_highest_voltage(self):
        cand = pd.DataFrame(
            {
                "bus": [2, 3, 1],
                "kind": ["wind", "wind", "load"],
                "weight_mw": [30.0, 10.0, 5.0],
                "state": ["BA"] * 3,
                "subsystem": ["NE"] * 3,
            }
        )
        wind = energy.place("BA", "NE", "wind", cand, self.BUSES)
        assert wind[2] == pytest.approx(0.75)
        solar = energy.place("BA", "NE", "solar", cand, self.BUSES)  # no solar: by load
        assert solar.to_dict() == {1: 1.0}
        empty = energy.place("BA", "NE", "solar", cand.iloc[0:0], self.BUSES)
        assert empty.to_dict() == {1: 1.0}  # highest-voltage bus
