# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0021's thermal cost bands."""

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


bands_mod = _load("build_thermal_bands", REPO_ROOT / "scripts" / "build_thermal_bands.py")

HOUR = "2024-01-01 00:00:00"
AVAILABILITY = pd.DataFrame(
    {
        "id_subsistema": ["NE", "NE", "NE", "NE"],
        "id_tipousina": ["UTE", "UTE", "UTE", "UHE"],
        "ceg": ["A", "B", "C", "H"],
        "din_instante": [HOUR] * 4,
        "val_potenciainstalada": [100.0, 300.0, 50.0, 999.0],
        "val_dispoperacional": [80.0, 300.0, 50.0, 999.0],
    }
)
CVU = pd.DataFrame(
    {
        "ano_referencia": [2024, 2024, 2024, 2023],
        "cod_usinaplanejamento": [1, 2, 3, 1],
        "val_cvu": [600.0, 700.0, 100.0, 1.0],
    }
)
BRIDGE = pd.DataFrame({"cod_usinaplanejamento": [1, 2, 3], "ceg": ["A", "B", "C"]})
DESPACHO = pd.DataFrame(
    {
        "din_instante": [HOUR] * 3,
        "ceg": ["A", "B", "C"],
        "val_verifgeracao": [50.0, 200.0, 40.0],
        "val_verifordemdemeritoacimadainflex": [0.0, 150.0, 40.0],
    }
)


class TestBands:
    def _build(self):
        cvu = bands_mod.plant_cvu(CVU, BRIDGE, year=2024)
        return bands_mod.build_bands(AVAILABILITY, cvu, bands_mod.plant_floor(DESPACHO))

    def test_groups_plants_by_cvu_band_with_weighted_cost(self):
        bands, _, _ = self._build()
        bands = bands.set_index("name")
        # A (600) and B (700) share band 4 (500-800); C (100) is band 1.
        assert set(bands.index) == {"NE thermal_b4", "NE thermal_b1"}
        assert bands.loc["NE thermal_b4", "p_nom_mw"] == pytest.approx(400.0)
        assert bands.loc["NE thermal_b4", "marginal_cost"] == pytest.approx(
            (600 * 100 + 700 * 300) / 400
        )

    def test_availability_and_floor_per_band(self):
        _, availability, floor = self._build()
        b4 = availability.set_index("name").loc["NE thermal_b4", "p_max_pu"]
        assert b4 == pytest.approx(380.0 / 400.0)
        floor = floor.set_index("name")["floor_mw"]
        assert floor["NE thermal_b4"] == pytest.approx(50.0 + 50.0)
        assert floor["NE thermal_b1"] == pytest.approx(0.0)

    def test_residual_takes_the_rest(self):
        bands, _, band_floor = self._build()
        generators = pd.DataFrame(
            {"subsystem": ["NE"], "carrier": ["thermal"], "p_nom_mw": [1000.0]}
        )
        subsystem_floor = pd.DataFrame({"month": [1], "subsystem": ["NE"], "floor_mw": [130.0]})
        capacity, floor = bands_mod.residual(generators, bands, subsystem_floor, band_floor)
        assert capacity["p_nom_mw"].iloc[0] == pytest.approx(550.0)
        assert floor["floor_mw"].iloc[0] == pytest.approx(30.0)
