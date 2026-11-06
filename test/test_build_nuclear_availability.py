# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for PR-62's nuclear availability from ONS operational availability."""

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


nuclear = _load(
    "build_nuclear_availability", REPO_ROOT / "scripts" / "build_nuclear_availability.py"
)

RAW = pd.DataFrame(
    {
        "id_subsistema": ["SE", "SE", "SE"],
        "id_tipousina": ["UTN", "UTN", "UTE"],
        "din_instante": ["2024-11-01 00:00:00"] * 3,
        "val_dispoperacional": [640.0, 0.0, 300.0],
    }
)
CAPACITY = pd.DataFrame({"subsystem": ["SE_CO"], "carrier": ["nuclear"], "p_nom_mw": [1990.0]})


class TestNuclearAvailability:
    def test_sums_nuclear_plants_over_p_nom(self):
        out = nuclear.build_nuclear_availability(RAW, CAPACITY)
        assert len(out) == 1
        assert out["p_max_pu"].iloc[0] == pytest.approx(640.0 / 1990.0)

    def test_raises_when_availability_exceeds_p_nom(self):
        raw = RAW.assign(val_dispoperacional=[2000.0, 100.0, 0.0])
        with pytest.raises(ValueError, match="exceeds p_nom"):
            nuclear.build_nuclear_availability(raw, CAPACITY)
