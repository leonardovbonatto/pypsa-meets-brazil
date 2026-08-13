# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for aggregating raw ONS CVU data into the T0 thermal marginal-cost table."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "cvu_usina_termica_sample.csv"
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "cvu_usina_termica.yaml"
SUBSYSTEMS = ["SE_CO", "S", "NE", "N"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_costs = _load("build_costs", REPO_ROOT / "scripts" / "build_costs.py")


@pytest.fixture
def raw_df():
    return build_costs.load_raw([FIXTURE])


class TestLoadRaw:
    def test_reads_the_real_fixture(self, raw_df):
        # 6 N rows (incl. GERAMAR1 x2 weeks) + 2 each for NE/S/SE.
        assert len(raw_df) == 12


class TestValidateAgainstDictionary:
    def test_accepts_real_fixture(self, raw_df):
        build_costs.validate_against_dictionary(raw_df, DICTIONARY)  # must not raise


class TestBuildThermalMarginalCost:
    def test_columns_and_carrier(self, raw_df):
        tidy = build_costs.build_thermal_marginal_cost(raw_df, subsystems=SUBSYSTEMS)
        assert list(tidy.columns) == ["subsystem", "carrier", "marginal_cost"]
        assert set(tidy["carrier"]) == {"thermal"}

    def test_mean_includes_zero_cost_plants(self, raw_df):
        """
        N's fixture rows are 0, 0, 90.53, 90.53, 1020.40, 1012.53 - the zeros
        must pull the mean down, not get silently excluded.
        """
        tidy = build_costs.build_thermal_marginal_cost(raw_df, subsystems=SUBSYSTEMS)
        n_cost = tidy.loc[tidy["subsystem"] == "N", "marginal_cost"].iloc[0]
        assert n_cost == pytest.approx((0 + 0 + 90.53 + 90.53 + 1020.40 + 1012.53) / 6)

    def test_repeated_weeks_for_the_same_plant_both_count(self, raw_df):
        """GERAMAR1's two different weekly costs are two observations, not one averaged input."""
        tidy = build_costs.build_thermal_marginal_cost(raw_df, subsystems=SUBSYSTEMS)
        ne_cost = tidy.loc[tidy["subsystem"] == "NE", "marginal_cost"].iloc[0]
        assert ne_cost == pytest.approx((108.45 + 204.55) / 2)

    def test_se_becomes_se_co(self, raw_df):
        tidy = build_costs.build_thermal_marginal_cost(raw_df, subsystems=SUBSYSTEMS)
        assert "SE_CO" in set(tidy["subsystem"])
        assert "SE" not in set(tidy["subsystem"])

    def test_raises_when_a_configured_subsystem_is_absent(self, raw_df):
        with pytest.raises(ValueError, match="absent"):
            build_costs.build_thermal_marginal_cost(raw_df, subsystems=[*SUBSYSTEMS, "ISOLATED_RR"])


class TestWriteThermalMarginalCost:
    def test_round_trips_through_csv(self, raw_df, tmp_path):
        import pandas as pd

        tidy = build_costs.build_thermal_marginal_cost(raw_df, subsystems=SUBSYSTEMS)
        out = build_costs.write_thermal_marginal_cost(tidy, tmp_path / "costs_t0.csv")

        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(tidy)
        assert list(reloaded.columns) == ["subsystem", "carrier", "marginal_cost"]
