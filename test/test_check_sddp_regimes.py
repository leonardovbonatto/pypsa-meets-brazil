# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for ADR-0009's acceptance test, read from the exported cuts."""

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


check = _load("check_sddp_regimes", REPO_ROOT / "scripts" / "check_sddp_regimes.py")

CAPACITY = {"N": 100.0, "S": 100.0}


def _cut(stage: int, regime: int, intercept: float, slope_n: float, slope_s: float) -> dict:
    return {
        "stage": stage,
        "markov_state": regime,
        "intercept": intercept,
        "state_variable": "storage[N],storage[S]",
        "coefficient": f"{slope_n},{slope_s}",
    }


def _cuts(dry: tuple, wet: tuple) -> pd.DataFrame:
    """One cut per regime at the reference stage, `(intercept, slope_n,
    slope_s)`, with a normal regime between them."""
    stage = check.REFERENCE_STAGE
    middle = tuple((a + b) / 2 for a, b in zip(dry, wet, strict=True))
    return pd.DataFrame([_cut(stage, 1, *dry), _cut(stage, 2, *middle), _cut(stage, 3, *wet)])


class TestAcceptance:
    def test_steeper_dry_regime_passes(self):
        report = check.regime_report(_cuts((100.0, -3.0, -2.0), (100.0, -1.0, -1.0)), CAPACITY)

        assert report["passed"]
        assert report["water_value_by_regime"]["1"] == pytest.approx([3.0, 2.0])

    def test_a_level_gap_with_identical_slopes_fails(self):
        """The whole point of this check, and what PR-45's first version got
        wrong: a dry regime that is merely more expensive by a constant has
        the same water value, so nothing about dispatch changes."""
        report = check.regime_report(_cuts((900.0, -2.0, -2.0), (100.0, -2.0, -2.0)), CAPACITY)

        assert report["cost_to_go_by_regime"]["1"] > report["cost_to_go_by_regime"]["3"]
        assert not report["passed"]

    def test_one_subsystem_inverted_fails(self):
        report = check.regime_report(_cuts((100.0, -5.0, -1.0), (100.0, -1.0, -3.0)), CAPACITY)

        assert report["dry_above_wet_somewhere"]
        assert not report["dry_at_least_wet_everywhere"]
        assert not report["passed"]

    def test_a_tie_in_one_subsystem_is_allowed(self):
        """Water value saturates at the shedding cost, so a tie at the cap is
        physics rather than a failure - as long as something differs."""
        report = check.regime_report(_cuts((100.0, -7.44, -2.0), (100.0, -7.44, -1.0)), CAPACITY)

        assert report["passed"]

    def test_a_single_regime_cannot_be_compared(self):
        one = pd.DataFrame([_cut(check.REFERENCE_STAGE, 1, 100.0, -1.0, -1.0)])

        with pytest.raises(ValueError, match="two regimes"):
            check.regime_report(one, CAPACITY)


class TestWaterValues:
    def test_reads_the_slope_of_the_highest_cut(self):
        """Two cuts crossing at storage 50: below it the steep cut is active,
        above it the shallow one is, so the fraction selects the slope."""
        intercepts = np.array([1000.0, 550.0])
        coefficients = np.array([[-10.0], [-1.0]])
        capacity = np.array([100.0])

        assert check.water_values(intercepts, coefficients, capacity, 0.25) == pytest.approx([10.0])
        assert check.water_values(intercepts, coefficients, capacity, 0.75) == pytest.approx([1.0])

    def test_maps_coefficients_by_name_not_position(self):
        """Each exported cut carries its own name order."""
        cuts = pd.DataFrame(
            [
                {
                    "stage": 1,
                    "markov_state": 1,
                    "intercept": 0.0,
                    "state_variable": "storage[S],storage[N]",
                    "coefficient": "-2.0,-5.0",
                }
            ]
        )
        _, coefficients = check.parse_cuts(cuts, ["N", "S"])[(1, 1)]

        assert coefficients.tolist() == [[-5.0, -2.0]]

    def test_rejects_an_unknown_state(self):
        """A `z[N]` column would be a regression to PR-38's formulation."""
        cuts = pd.DataFrame(
            [
                {
                    "stage": 1,
                    "markov_state": 1,
                    "intercept": 0.0,
                    "state_variable": "z[N]",
                    "coefficient": "0.0",
                }
            ]
        )
        with pytest.raises(KeyError):
            check.parse_cuts(cuts, ["N", "S"])


class TestGrid:
    def test_counts_every_stage_fraction_and_subsystem(self):
        cuts = pd.concat(
            [
                _cuts((100.0, -3.0, -1.0), (100.0, -1.0, -1.0)),
                _cuts((100.0, -1.0, -3.0), (100.0, -2.0, -1.0)).assign(stage=7),
            ]
        )
        counts = check.regime_report(cuts, CAPACITY)["grid_counts"]

        # 2 stages x 3 fractions x 2 subsystems.
        assert sum(counts.values()) == 12
        assert counts == {"dry_above_wet": 6, "tied": 3, "wet_above_dry": 3}
