# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0015's 2024 backtest."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bt = _load("backtest_2024", REPO_ROOT / "scripts" / "backtest_2024.py")

SUBSYSTEMS = ["N", "NE", "S", "SE_CO"]
SHAPE = np.array([60, 65, 70, 72, 70, 62, 55, 48, 40, 35, 38, 45], dtype=float)
CMO_SHAPE = np.array([5, 5, 8, 9, 10, 26, 78, 111, 366, 516, 152, 14], dtype=float)


def _table(model_storage, model_price) -> pd.DataFrame:
    rows = []
    for s in SUBSYSTEMS:
        for m in range(1, 13):
            rows.append(
                {
                    "month": m,
                    "subsystem": s,
                    "model_storage_pct": model_storage[m - 1],
                    "observed_storage_pct": SHAPE[m - 1],
                    "model_price": model_price[m - 1],
                    "observed_cmo": CMO_SHAPE[m - 1],
                }
            )
    return pd.DataFrame(rows)


class TestObserved:
    def test_storage_takes_the_last_day_of_each_month(self):
        history = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-30", "2024-01-31", "2024-02-29", "2023-12-31"]),
                "subsystem": "N",
                "ear_verif_pct": [10.0, 11.0, 12.0, 99.0],
            }
        )
        out = bt.observed_storage(history, 2024).set_index("month")["observed_storage_pct"]
        assert out.to_dict() == {1: 11.0, 2: 12.0}

    def test_cmo_filters_the_year(self):
        cmo = pd.DataFrame(
            {"month": ["2023-12", "2024-01"], "subsystem": "N", "cmo_mean": [1.0, 2.0]}
        )
        out = bt.observed_cmo(cmo, 2024)
        assert out[["month", "observed_cmo"]].values.tolist() == [[1, 2.0]]


class TestComparisonTable:
    def test_converts_model_storage_to_percent_of_capacity(self):
        model = pd.DataFrame(
            {
                "month": [1],
                "subsystem": ["N"],
                "storage_end_mwmes": [50.0],
                "price_mean_rs_per_mwh": [3.0],
            }
        )
        capacity = pd.DataFrame({"subsystem": ["N"], "ear_max_mwmes": [200.0]})
        storage = pd.DataFrame({"month": [1], "subsystem": ["N"], "observed_storage_pct": [30.0]})
        cmo = pd.DataFrame({"month": [1], "subsystem": ["N"], "observed_cmo": [4.0]})
        out = bt.comparison_table(model, capacity, storage, cmo).iloc[0]
        assert out["model_storage_pct"] == pytest.approx(25.0)
        assert out["model_price"] == 3.0


class TestReport:
    def test_matching_shapes_pass_even_at_different_levels(self):
        report = bt.backtest_report(_table(SHAPE * 0.5 + 10, CMO_SHAPE * 3))
        assert report["passed"]
        assert report["by_subsystem"]["SE_CO"]["model_mean_price"] > 0

    def test_inverted_storage_fails(self):
        report = bt.backtest_report(_table(100 - SHAPE, CMO_SHAPE))
        assert not report["storage_passed"]
        assert not report["passed"]

    def test_flat_or_inverted_price_fails(self):
        report = bt.backtest_report(_table(SHAPE, -CMO_SHAPE))
        assert report["storage_passed"]
        assert not report["price_passed"]

    def test_december_is_outside_the_window(self):
        storage = SHAPE.copy()
        storage[11] = 0.0  # December drawdown, ADR-0014's end effect
        report = bt.backtest_report(_table(storage, CMO_SHAPE))
        assert report["by_subsystem"]["N"]["storage_correlation"] == pytest.approx(1.0)

    def test_missing_observations_raise(self):
        table = _table(SHAPE, CMO_SHAPE)
        table.loc[0, "observed_cmo"] = np.nan
        with pytest.raises(ValueError, match="missing"):
            bt.backtest_report(table)
