# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for turning raw ONS ENA data into the tidy historical inflow series
(ADR-0005, SDDP epic stage 1)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "ena_subsistema_sample.csv"
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "ena_subsistema.yaml"
SUBSYSTEMS = ["SE_CO", "S", "NE", "N"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_inflow = _load("build_inflow", REPO_ROOT / "scripts" / "build_inflow.py")


@pytest.fixture
def raw_df():
    return build_inflow.load_raw([FIXTURE])


class TestLoadRaw:
    def test_concatenates_and_reads_real_fixture(self, raw_df):
        # 5 days x 4 subsystems, cut from the real 2024 file (see PR-27 handoff).
        assert len(raw_df) == 20
        assert set(raw_df["id_subsistema"]) == {"N", "NE", "S", "SE"}


class TestValidateAgainstDictionary:
    def test_accepts_real_fixture(self, raw_df):
        build_inflow.validate_against_dictionary(raw_df, DICTIONARY)  # must not raise

    def test_rejects_a_dropped_column(self, raw_df):
        import pandera.pandas as pa

        drifted = raw_df.drop(columns=["ena_bruta_regiao_mwmed"])
        with pytest.raises(pa.errors.SchemaError):
            build_inflow.validate_against_dictionary(drifted, DICTIONARY)


class TestParseDates:
    def test_is_a_plain_date_not_a_timestamp(self, raw_df):
        parsed = build_inflow.parse_dates(raw_df)
        assert parsed["date"].min() == pd.Timestamp("2024-01-01")

    def test_no_time_of_day_component(self, raw_df):
        parsed = build_inflow.parse_dates(raw_df)
        assert (parsed["date"].dt.time == pd.Timestamp("2024-01-01").time()).all()


class TestBuildTidyInflow:
    def test_shape_and_columns(self, raw_df):
        tidy = build_inflow.build_tidy_inflow(raw_df, subsystems=SUBSYSTEMS)
        assert list(tidy.columns) == [
            "date",
            "subsystem",
            "ena_bruta_mwmed",
            "ena_bruta_pct_mlt",
            "ena_armazenavel_mwmed",
            "ena_armazenavel_pct_mlt",
        ]
        assert len(tidy) == 20
        assert tidy["date"].nunique() == 5
        assert set(tidy["subsystem"]) == set(SUBSYSTEMS)
        assert not tidy.isna().any().any()

    def test_se_becomes_se_co(self, raw_df):
        tidy = build_inflow.build_tidy_inflow(raw_df, subsystems=SUBSYSTEMS)
        assert "SE_CO" in set(tidy["subsystem"])
        assert "SE" not in set(tidy["subsystem"])

    def test_raises_when_a_configured_subsystem_is_absent(self, raw_df):
        with pytest.raises(ValueError, match="absent"):
            build_inflow.build_tidy_inflow(raw_df, subsystems=[*SUBSYSTEMS, "ISOLATED_RR"])

    def test_raises_on_a_gap_in_the_daily_sequence(self, raw_df):
        gappy = raw_df[raw_df["ena_data"] != "2024-01-03"]
        with pytest.raises(ValueError, match="gap"):
            build_inflow.build_tidy_inflow(gappy, subsystems=SUBSYSTEMS)

    def test_raises_on_a_duplicated_day(self, raw_df):
        duped = pd.concat([raw_df, raw_df.iloc[[0]]], ignore_index=True)
        with pytest.raises(ValueError, match="gap"):
            build_inflow.build_tidy_inflow(duped, subsystems=SUBSYSTEMS)

    def test_raises_if_storable_exceeds_gross(self, raw_df):
        broken = raw_df.copy()
        broken.loc[0, "ena_armazenavel_regiao_mwmed"] = broken.loc[0, "ena_bruta_regiao_mwmed"] + 1
        with pytest.raises(ValueError, match="storable"):
            build_inflow.build_tidy_inflow(broken, subsystems=SUBSYSTEMS)


class TestWriteTidyInflow:
    def test_round_trips_through_csv(self, raw_df, tmp_path):
        tidy = build_inflow.build_tidy_inflow(raw_df, subsystems=SUBSYSTEMS)
        out = build_inflow.write_tidy_inflow(tidy, tmp_path / "inflow_ena.csv")

        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(tidy)
        assert list(reloaded.columns) == list(tidy.columns)
