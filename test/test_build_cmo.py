# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for the tidy CMO series, the SDDP backtest target (roadmap Phase 7)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "test" / "fixtures" / "ons"
DICTIONARIES = REPO_ROOT / "docs" / "data-dictionary" / "ons"
SUBSYSTEMS = ["SE_CO", "S", "NE", "N"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_cmo = _load("build_cmo", REPO_ROOT / "scripts" / "build_cmo.py")


@pytest.fixture
def weekly_raw():
    return build_cmo.load_raw([FIXTURES / "cmo_semanal_sample.csv"])


@pytest.fixture
def half_hourly_raw():
    return build_cmo.load_raw([FIXTURES / "cmo_semi_horario_sample.csv"])


class TestDictionaries:
    def test_weekly_fixture_validates(self, weekly_raw):
        build_cmo.validate_against_dictionary(weekly_raw, DICTIONARIES / "cmo_semanal.yaml")

    def test_half_hourly_fixture_validates(self, half_hourly_raw):
        build_cmo.validate_against_dictionary(
            half_hourly_raw, DICTIONARIES / "cmo_semi_horario.yaml"
        )

    def test_rejects_a_dropped_column(self, weekly_raw):
        import pandera.pandas as pa

        with pytest.raises(pa.errors.SchemaError):
            build_cmo.validate_against_dictionary(
                weekly_raw.drop(columns=["val_cmopesada"]), DICTIONARIES / "cmo_semanal.yaml"
            )


class TestBuildWeekly:
    def test_shape_and_columns(self, weekly_raw):
        weekly = build_cmo.build_weekly(weekly_raw, subsystems=SUBSYSTEMS)

        assert list(weekly.columns) == [
            "week_start",
            "week_end",
            "subsystem",
            "cmo_mean",
            "cmo_light",
            "cmo_medium",
            "cmo_heavy",
        ]
        assert len(weekly) == 24
        assert set(weekly["subsystem"]) == set(SUBSYSTEMS)

    def test_week_runs_saturday_to_friday(self, weekly_raw):
        """The measured convention: the reference date ends the week."""
        weekly = build_cmo.build_weekly(weekly_raw, subsystems=SUBSYSTEMS)

        assert set(weekly["week_start"].dt.day_name()) == {"Saturday"}
        assert set(weekly["week_end"].dt.day_name()) == {"Friday"}

    def test_raises_on_a_missing_week(self, weekly_raw):
        gap = weekly_raw[weekly_raw["din_instante"] != "2024-10-04"]
        with pytest.raises(ValueError, match="gap or duplicate"):
            build_cmo.build_weekly(gap, subsystems=SUBSYSTEMS)

    def test_raises_when_subsystems_cover_different_weeks(self, weekly_raw):
        uneven = weekly_raw[
            ~((weekly_raw["id_subsistema"] == "S") & (weekly_raw["din_instante"] == "2024-10-25"))
        ]
        with pytest.raises(ValueError, match="same operating weeks"):
            build_cmo.build_weekly(uneven, subsystems=SUBSYSTEMS)

    def test_raises_when_a_configured_subsystem_is_absent(self, weekly_raw):
        with pytest.raises(ValueError, match="absent"):
            build_cmo.build_weekly(weekly_raw, subsystems=[*SUBSYSTEMS, "ISOLATED_RR"])


class TestBuildMonthly:
    def test_one_row_per_month_and_subsystem(self, half_hourly_raw):
        monthly = build_cmo.build_monthly(half_hourly_raw, subsystems=SUBSYSTEMS)

        assert list(monthly.columns) == [
            "month",
            "subsystem",
            "cmo_mean",
            "cmo_median",
            "slots",
            "coverage",
        ]
        assert len(monthly) == 4
        assert set(monthly["month"]) == {"2024-08"}

    def test_coverage_counts_whole_days(self, half_hourly_raw):
        """Two of August's 31 days are in the fixture."""
        monthly = build_cmo.build_monthly(half_hourly_raw, subsystems=SUBSYSTEMS)

        assert (monthly["slots"] == 96).all()
        assert monthly["coverage"].to_numpy() == pytest.approx([2 / 31] * 4)

    def test_negative_values_are_kept(self, half_hourly_raw):
        """Real negative CMO in NE, August 2024: published values, not errors."""
        assert (half_hourly_raw["val_cmo"] < 0).any()
        monthly = build_cmo.build_monthly(half_hourly_raw, subsystems=SUBSYSTEMS).set_index(
            "subsystem"
        )

        ne = half_hourly_raw[half_hourly_raw["id_subsistema"] == "NE"]["val_cmo"]
        assert monthly.loc["NE", "cmo_mean"] == pytest.approx(ne.mean())

    def test_raises_on_a_partial_day(self, half_hourly_raw):
        partial = half_hourly_raw.drop(index=half_hourly_raw.index[0])
        with pytest.raises(ValueError, match="partial days"):
            build_cmo.build_monthly(partial, subsystems=SUBSYSTEMS)

    def test_raises_when_subsystems_miss_different_days(self, half_hourly_raw):
        one_day = half_hourly_raw["din_instante"].str.startswith("2024-08-04")
        uneven = half_hourly_raw[~(one_day & (half_hourly_raw["id_subsistema"] == "N"))]
        with pytest.raises(ValueError, match="different days"):
            build_cmo.build_monthly(uneven, subsystems=SUBSYSTEMS)

    def test_a_whole_day_missing_everywhere_lowers_coverage(self, half_hourly_raw):
        """The gap pattern the real files show: allowed, and visible."""
        one_day = half_hourly_raw[half_hourly_raw["din_instante"].str.startswith("2024-08-03")]
        monthly = build_cmo.build_monthly(one_day, subsystems=SUBSYSTEMS)

        assert monthly["coverage"].to_numpy() == pytest.approx([1 / 31] * 4)

    def test_raises_on_a_duplicate_half_hour(self, half_hourly_raw):
        doubled = pd.concat([half_hourly_raw, half_hourly_raw.iloc[[0]]], ignore_index=True)
        with pytest.raises(ValueError, match="duplicate"):
            build_cmo.build_monthly(doubled, subsystems=SUBSYSTEMS)
