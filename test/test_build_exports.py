# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for PR-64's international exports as load."""

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


exports = _load("build_exports", REPO_ROOT / "scripts" / "build_exports.py")


class TestExports:
    def test_nets_countries_at_their_border_subsystem(self):
        raw = pd.DataFrame(
            {
                "din_instante": ["2024-01-01 00:00:00"] * 2,
                "nom_paisdestino": ["ARGENTINA", "URUGUAI"],
                "val_intercambiomwmed": [300.0, -50.0],
            }
        )
        out = exports.build_exports(raw)
        assert len(out) == 1
        assert out["subsystem"].iloc[0] == "S"
        assert out["p_set_mw"].iloc[0] == pytest.approx(250.0)

    def test_unknown_country_raises(self):
        raw = pd.DataFrame(
            {
                "din_instante": ["2024-01-01 00:00:00"],
                "nom_paisdestino": ["CHILE"],
                "val_intercambiomwmed": [1.0],
            }
        )
        with pytest.raises(ValueError, match="no border subsystem"):
            exports.build_exports(raw)
