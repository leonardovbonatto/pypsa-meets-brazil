# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for PR-70's availability before curtailment."""

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


unc = _load("build_uncurtailment", REPO_ROOT / "scripts" / "build_uncurtailment.py")


class TestFactor:
    def test_only_restricted_half_hours_add_unrealised_output(self):
        raw = pd.DataFrame(
            {
                "id_subsistema": ["NE", "NE", "NE"],
                "din_instante": [
                    "2024-01-01 00:00:00",
                    "2024-01-01 00:30:00",
                    "2024-01-01 00:30:00",
                ],
                "val_geracaoestimada": [120.0, 150.0, 90.0],
                "val_geracaoverificada": [100.0, 100.0, 100.0],
                "flg_geracaorestrita": [0, 1, 1],
            }
        )
        out = unc.hourly_factor(raw, "wind")
        # verified 300; unrealised 50 (restricted, estimate above verified) + 0.
        assert out["factor"].iloc[0] == pytest.approx(350.0 / 300.0)
        assert out["carrier"].iloc[0] == "wind"

    def test_no_output_gives_factor_one(self):
        raw = pd.DataFrame(
            {
                "id_subsistema": ["NE"],
                "din_instante": ["2024-01-01 03:00:00"],
                "val_geracaoestimada": [0.0],
                "val_geracaoverificada": [0.0],
                "flg_geracaorestrita": [0],
            }
        )
        assert unc.hourly_factor(raw, "solar")["factor"].iloc[0] == pytest.approx(1.0)


class TestReasons:
    def test_only_transmission_and_energy_curtailment_count(self):
        raw = pd.DataFrame(
            {
                "id_subsistema": ["NE"] * 4,
                "din_instante": [
                    "2024-01-01 00:00:00",
                    "2024-01-01 00:00:00",
                    "2024-01-01 00:30:00",
                    "2024-01-01 00:30:00",
                ],
                "val_geracao": [100.0, 100.0, 100.0, 100.0],
                "val_geracaonaorealizadaapurada": [10.0, 20.0, 40.0, 5.0],
                "cod_razaorestricao": ["REL", "ENE", "CNF", None],
            }
        )
        out = unc.hourly_factor_reasons(raw, "wind")
        # verified 400; REL 10 + ENE 20 count, CNF 40 does not.
        assert out["factor"].iloc[0] == pytest.approx(430.0 / 400.0)
