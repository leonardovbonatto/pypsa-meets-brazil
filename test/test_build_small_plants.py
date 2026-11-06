# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for PR-60's small-plant (TIPO III) backcast."""

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


small = _load("build_small_plants", REPO_ROOT / "scripts" / "build_small_plants.py")

RAW = pd.DataFrame(
    {
        "din_instante": [
            "2024-01-01 00:00:00",
            "2024-01-01 00:00:00",
            "2024-01-01 01:00:00",
            "2024-01-01 01:00:00",
        ],
        "id_subsistema": ["S", "S", "S", "S"],
        "nom_tipousina": ["HIDROELÉTRICA", "HIDROELÉTRICA", "TÉRMICA", "HIDROELÉTRICA"],
        "cod_modalidadeoperacao": ["TIPO III", "TIPO I", "Pequenas Usinas (Tipo III)", "TIPO III"],
        "val_geracao": [10.0, 500.0, 4.0, 20.0],
    }
)


class TestSmallPlants:
    def test_keeps_only_tipo_iii_and_fills_missing_hours(self):
        hourly = small.hourly_small(RAW).set_index(["carrier", "snapshot"])["generation_mw"]
        assert hourly[("hydro_small", "2024-01-01 00:00:00")] == pytest.approx(10.0)
        assert hourly[("hydro_small", "2024-01-01 01:00:00")] == pytest.approx(20.0)
        # Thermal had no row at 00:00: it produced nothing that hour.
        assert hourly[("thermal_small", "2024-01-01 00:00:00")] == pytest.approx(0.0)

    def test_capacity_is_peak_and_availability_its_share(self):
        hourly = small.hourly_small(RAW)
        capacity = small.build_small_capacity(hourly).set_index("carrier")["p_nom_mw"]
        assert capacity["hydro_small"] == pytest.approx(20.0)
        availability = small.build_small_availability(
            hourly, capacity.reset_index().assign(subsystem="S")
        )
        hydro = availability[availability["carrier"] == "hydro_small"]["p_max_pu"].tolist()
        assert hydro == pytest.approx([0.5, 1.0])
