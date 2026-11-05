# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0011's acceptance test, read from the exported cuts."""

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


check = _load("check_sddp_inflow_state", REPO_ROOT / "scripts" / "check_sddp_inflow_state.py")

CAPACITY = {"S": 100.0}

# log-PAR(1) with mu = log(1000), sigma = 1: P10 ~ 278, mean ~ 1649, P90 ~ 3602.
PAR1 = pd.DataFrame(
    {"month": range(1, 13), "subsystem": "S", "mu": np.log(1000.0), "sigma": 1.0, "phi": 0.5}
)

OK_DEFICIT = {"S": {"share_of_inflow_energy": 0.001}}


# Keeps every fixture cut above the models lower bound of 0 where tested.
INTERCEPT_OFFSET = 1000.0


def _cuts(rows: list[tuple[int, float, float, float]]) -> pd.DataFrame:
    """(stage, intercept, storage coefficient, inflow coefficient)."""
    return pd.DataFrame(
        [
            {
                "stage": stage,
                "markov_state": 1,
                "intercept": intercept + INTERCEPT_OFFSET,
                "state_variable": "storage[S],inflow[S]",
                "coefficient": f"{storage},{inflow}",
            }
            for stage, intercept, storage, inflow in rows
        ]
    )


# At 50% storage, a steep cut is active after a dry month and a flat one after
# a wet month: water is worth 3 when dry, 1 when wet.
LEARNED = _cuts([(6, 60.0, -1.0, 0.0), (6, 190.0, -3.0, -0.02)])


class TestParseStateCuts:
    def test_splits_storage_and_inflow_coefficients(self):
        nodes = check.parse_state_cuts(LEARNED, ["S"])
        intercepts, storage, inflow = nodes[6]
        assert intercepts.tolist() == [60.0 + INTERCEPT_OFFSET, 190.0 + INTERCEPT_OFFSET]
        assert storage[:, 0].tolist() == [-1.0, -3.0]
        assert inflow[:, 0].tolist() == [0.0, -0.02]

    def test_rejects_unknown_state_names(self):
        cuts = LEARNED.assign(state_variable="storage[S],z[S]")
        with pytest.raises(ValueError, match="unexpected state variable"):
            check.parse_state_cuts(cuts, ["S"])


class TestReport:
    def test_passes_when_dry_water_is_worth_more(self):
        report = check.inflow_state_report(LEARNED, CAPACITY, PAR1, OK_DEFICIT)
        assert report["passed"]
        assert report["by_subsystem"]["S"]["dry"] == pytest.approx(3.0)
        assert report["by_subsystem"]["S"]["wet"] == pytest.approx(1.0)

    def test_fails_when_memory_changes_nothing(self):
        flat = _cuts([(6, 60.0, -1.0, -0.01)])
        report = check.inflow_state_report(flat, CAPACITY, PAR1, OK_DEFICIT)
        assert not report["passed"]
        assert not report["dry_above_wet_somewhere"]

    def test_fails_when_the_deficit_slack_carries_too_much_of_s(self):
        report = check.inflow_state_report(
            LEARNED, CAPACITY, PAR1, {"S": {"share_of_inflow_energy": 0.02}}
        )
        assert not report["passed"]
        assert not report["s_deficit_within_limit"]

    def test_grid_covers_every_stage_and_storage_level(self):
        report = check.inflow_state_report(LEARNED, CAPACITY, PAR1, OK_DEFICIT)
        assert sum(report["grid_counts"].values()) == len(check.GRID_FRACTIONS)
