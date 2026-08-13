# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for the ONS subsystem-code mapping shared across connector/build scripts."""

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


ons = _load("_ons", REPO_ROOT / "scripts" / "_ons.py")


class TestMapSubsystems:
    def test_maps_known_codes(self):
        df = pd.DataFrame({"id_subsistema": ["N", "NE", "S", "SE"]})
        mapped = ons.map_subsystems(df)
        assert list(mapped["subsystem"]) == ["N", "NE", "S", "SE_CO"]

    def test_drops_py_without_raising(self):
        """PY (Itaipu 50 Hz) is known and excluded, not unmapped data."""
        df = pd.DataFrame({"id_subsistema": ["N", "PY", "SE"]})
        mapped = ons.map_subsystems(df)
        assert "PY" not in set(mapped["id_subsistema"])
        assert len(mapped) == 2

    def test_raises_on_a_genuinely_unknown_code(self):
        df = pd.DataFrame({"id_subsistema": ["N", "ISOLATED_RR"]})
        with pytest.raises(ValueError, match="unmapped"):
            ons.map_subsystems(df)

    def test_respects_a_custom_column_name(self):
        df = pd.DataFrame({"code": ["N", "NE"]})
        mapped = ons.map_subsystems(df, column="code")
        assert list(mapped["subsystem"]) == ["N", "NE"]
