# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for turning raw ONS load data into the tidy T0 demand series."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "curva_carga_2024_sample.csv"
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "curva_carga.yaml"
SUBSYSTEMS = ["SE_CO", "S", "NE", "N"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_demand = _load("build_demand", REPO_ROOT / "scripts" / "build_demand.py")


@pytest.fixture
def raw_df():
    return build_demand.load_raw([FIXTURE])


class TestLoadRaw:
    def test_concatenates_and_reads_real_fixture(self, raw_df):
        # 6 hours x 4 subsystems, cut from the real 2024 file (see PR-04 handoff).
        assert len(raw_df) == 24
        assert set(raw_df["id_subsistema"]) == {"N", "NE", "S", "SE"}


class TestValidateAgainstDictionary:
    def test_accepts_real_fixture(self, raw_df):
        build_demand.validate_against_dictionary(raw_df, DICTIONARY)  # must not raise

    def test_rejects_a_dropped_column(self, raw_df):
        import pandera.pandas as pa

        drifted = raw_df.drop(columns=["val_cargaenergiahomwmed"])
        with pytest.raises(pa.errors.SchemaError):
            build_demand.validate_against_dictionary(drifted, DICTIONARY)


class TestMapSubsystems:
    def test_se_becomes_se_co(self, raw_df):
        mapped = build_demand.map_subsystems(raw_df)
        assert set(mapped["subsystem"]) == set(SUBSYSTEMS)
        assert (mapped.loc[mapped["id_subsistema"] == "SE", "subsystem"] == "SE_CO").all()

    def test_raises_on_unknown_code(self, raw_df):
        bad = raw_df.copy()
        bad.loc[0, "id_subsistema"] = "ISOLATED_RR"
        with pytest.raises(ValueError, match="unmapped"):
            build_demand.map_subsystems(bad)


class TestParseTimestamps:
    def test_is_timezone_naive(self, raw_df):
        parsed = build_demand.parse_timestamps(raw_df)
        assert parsed["snapshot"].dt.tz is None

    def test_parses_the_expected_first_hour(self, raw_df):
        parsed = build_demand.parse_timestamps(raw_df)
        assert parsed["snapshot"].min() == pd.Timestamp("2024-01-01 00:00:00")


class TestBuildTidyDemand:
    def test_shape_and_columns(self, raw_df):
        tidy = build_demand.build_tidy_demand(raw_df, subsystems=SUBSYSTEMS)
        assert list(tidy.columns) == ["snapshot", "subsystem", "load_mw"]
        assert len(tidy) == 24
        assert tidy["snapshot"].nunique() == 6
        assert set(tidy["subsystem"]) == set(SUBSYSTEMS)
        assert not tidy["load_mw"].isna().any()

    def test_raises_when_a_configured_subsystem_is_absent(self, raw_df):
        with pytest.raises(ValueError, match="absent"):
            build_demand.build_tidy_demand(raw_df, subsystems=[*SUBSYSTEMS, "ISOLATED_RR"])

    def test_raises_on_a_gap_in_the_hourly_sequence(self, raw_df):
        gappy = raw_df[raw_df["din_instante"] != "2024-01-01 02:00:00"]
        with pytest.raises(ValueError, match="gap"):
            build_demand.build_tidy_demand(gappy, subsystems=SUBSYSTEMS)

    def test_raises_on_a_duplicated_hour(self, raw_df):
        duped = pd.concat([raw_df, raw_df.iloc[[0]]], ignore_index=True)
        with pytest.raises(ValueError, match="gap"):
            build_demand.build_tidy_demand(duped, subsystems=SUBSYSTEMS)


class TestWriteTidyDemand:
    def test_round_trips_through_csv(self, raw_df, tmp_path):
        tidy = build_demand.build_tidy_demand(raw_df, subsystems=SUBSYSTEMS)
        out = build_demand.write_tidy_demand(tidy, tmp_path / "demand_t0.csv")

        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(tidy)
        assert list(reloaded.columns) == ["snapshot", "subsystem", "load_mw"]
