# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0016's thermal floor."""

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


tf = _load("build_thermal_floor", REPO_ROOT / "scripts" / "build_thermal_floor.py")


def _rows(records):
    return pd.DataFrame(
        records,
        columns=["din_instante", "id_subsistema", tf.TOTAL, tf.PRICE_DRIVEN, tf.INFLEXIBLE],
    )


class TestMonthlyFloor:
    def test_floor_is_total_minus_price_driven_summed_over_plants(self):
        df = _rows(
            [
                ("2024-01-01 00:00:00", "SE", 100.0, 30.0, 60.0),
                ("2024-01-01 00:00:00", "SE", 50.0, 0.0, 50.0),
                ("2024-01-01 01:00:00", "SE", 40.0, 40.0, 0.0),
            ]
        )
        out = tf.monthly_floor(df).iloc[0]
        assert out["subsystem"] == "SE_CO"
        # Hour 0: 70 + 50 = 120; hour 1: 0. Mean over the month's hours: 60.
        assert out["floor_mw"] == pytest.approx(60.0)
        assert out["verified_thermal_mw"] == pytest.approx(95.0)
        assert out["inflexible_mw"] == pytest.approx(55.0)

    def test_months_are_kept_apart(self):
        df = _rows(
            [
                ("2024-01-31 23:00:00", "N", 10.0, 0.0, 10.0),
                ("2024-02-01 00:00:00", "N", 20.0, 0.0, 20.0),
            ]
        )
        assert tf.monthly_floor(df)["floor_mw"].tolist() == [10.0, 20.0]


class TestCap:
    def test_caps_at_thermal_capacity_and_records_the_cut(self):
        floor = pd.DataFrame({"month": [1], "subsystem": ["N"], "floor_mw": [120.0]})
        generators = pd.DataFrame(
            {"subsystem": ["N", "N"], "carrier": ["thermal", "hydro"], "p_nom_mw": [100.0, 500.0]}
        )
        out = tf.cap_at_capacity(floor, generators).iloc[0]
        assert out["floor_mw"] == 100.0
        assert out["floor_capped_mw"] == 20.0

    def test_raises_without_capacity(self):
        floor = pd.DataFrame({"month": [1], "subsystem": ["S"], "floor_mw": [1.0]})
        generators = pd.DataFrame({"subsystem": ["N"], "carrier": ["thermal"], "p_nom_mw": [1.0]})
        with pytest.raises(ValueError, match="no T0 thermal"):
            tf.cap_at_capacity(floor, generators)


bn = _load("build_network", REPO_ROOT / "scripts" / "build_network.py")


class TestAttachToNetwork:
    def _network(self):
        import pypsa

        n = pypsa.Network()
        n.set_snapshots(pd.DatetimeIndex(["2024-01-31 23:00", "2024-02-01 00:00"]))
        n.add("Bus", "N")
        n.add("Generator", "N thermal", bus="N", p_nom=200.0)
        return n

    def test_sets_p_min_pu_from_the_monthly_floor(self):
        n = self._network()
        floor = pd.DataFrame({"month": [1, 2], "subsystem": ["N", "N"], "floor_mw": [50.0, 100.0]})
        bn.attach_thermal_floor(n, floor)
        assert n.generators_t.p_min_pu["N thermal"].tolist() == [0.25, 0.5]

    def test_raises_when_a_month_is_missing(self):
        n = self._network()
        floor = pd.DataFrame({"month": [1], "subsystem": ["N"], "floor_mw": [50.0]})
        with pytest.raises(ValueError, match="missing"):
            bn.attach_thermal_floor(n, floor)
