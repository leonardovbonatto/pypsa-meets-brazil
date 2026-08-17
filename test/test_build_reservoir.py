# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for turning raw ONS EAR data into the tidy reservoir storage series
(ADR-0005, SDDP epic stage 1e)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "ear_subsistema_sample.csv"
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "ear_subsistema.yaml"
SUBSYSTEMS = ["SE_CO", "S", "NE", "N"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_reservoir = _load("build_reservoir", REPO_ROOT / "scripts" / "build_reservoir.py")


@pytest.fixture
def raw_df():
    return build_reservoir.load_raw([FIXTURE])


class TestLoadRaw:
    def test_concatenates_and_reads_real_fixture(self, raw_df):
        # 5 days x 4 subsystems, cut from the real 2024 file (see PR-30 handoff).
        assert len(raw_df) == 20
        assert set(raw_df["id_subsistema"]) == {"N", "NE", "S", "SE"}


class TestValidateAgainstDictionary:
    def test_accepts_real_fixture(self, raw_df):
        build_reservoir.validate_against_dictionary(raw_df, DICTIONARY)  # must not raise

    def test_rejects_a_dropped_column(self, raw_df):
        import pandera.pandas as pa

        drifted = raw_df.drop(columns=["ear_max_subsistema"])
        with pytest.raises(pa.errors.SchemaError):
            build_reservoir.validate_against_dictionary(drifted, DICTIONARY)


class TestBuildTidyReservoir:
    def test_shape_and_columns(self, raw_df):
        tidy = build_reservoir.build_tidy_reservoir(raw_df, subsystems=SUBSYSTEMS)
        assert list(tidy.columns) == [
            "date",
            "subsystem",
            "ear_max_mwmes",
            "ear_verif_mwmes",
            "ear_verif_pct",
        ]
        assert len(tidy) == 20
        assert tidy["date"].nunique() == 5
        assert set(tidy["subsystem"]) == set(SUBSYSTEMS)
        assert not tidy.isna().any().any()

    def test_se_becomes_se_co(self, raw_df):
        tidy = build_reservoir.build_tidy_reservoir(raw_df, subsystems=SUBSYSTEMS)
        assert "SE_CO" in set(tidy["subsystem"])
        assert "SE" not in set(tidy["subsystem"])

    def test_raises_when_a_configured_subsystem_is_absent(self, raw_df):
        with pytest.raises(ValueError, match="absent"):
            build_reservoir.build_tidy_reservoir(raw_df, subsystems=[*SUBSYSTEMS, "ISOLATED_RR"])

    def test_raises_on_a_gap_in_the_daily_sequence(self, raw_df):
        gappy = raw_df[raw_df["ear_data"] != "2024-01-03"]
        with pytest.raises(ValueError, match="gap"):
            build_reservoir.build_tidy_reservoir(gappy, subsystems=SUBSYSTEMS)

    def test_raises_on_a_duplicated_day(self, raw_df):
        duped = pd.concat([raw_df, raw_df.iloc[[0]]], ignore_index=True)
        with pytest.raises(ValueError, match="gap"):
            build_reservoir.build_tidy_reservoir(duped, subsystems=SUBSYSTEMS)

    def test_clips_verified_storage_that_exceeds_capacity(self, raw_df):
        """Real bug found on real data (PR-30): 99 of 37,988 rows have
        verified storage marginally above max capacity. Clipped, not
        rejected - see the module docstring and data dictionary notes."""
        broken = raw_df.copy()
        broken.loc[0, "ear_verif_subsistema_mwmes"] = broken.loc[0, "ear_max_subsistema"] * 1.02

        tidy = build_reservoir.build_tidy_reservoir(broken, subsystems=SUBSYSTEMS)

        clipped_row = tidy[
            (tidy["date"] == pd.Timestamp(broken.loc[0, "ear_data"]))
            & (
                tidy["subsystem"]
                == build_reservoir.map_subsystems(broken.iloc[[0]])["subsystem"].iloc[0]
            )
        ]
        assert clipped_row["ear_verif_mwmes"].iloc[0] == pytest.approx(
            broken.loc[0, "ear_max_subsistema"]
        )
        assert clipped_row["ear_verif_pct"].iloc[0] == pytest.approx(100.0)


class TestLatestCapacity:
    def test_uses_the_most_recent_date_not_an_average(self, raw_df):
        """Real capacity grows over time (PR-30 handoff) - averaging
        across history would understate present-day capacity."""
        tidy = build_reservoir.build_tidy_reservoir(raw_df, subsystems=SUBSYSTEMS)
        capacity = build_reservoir.latest_capacity(tidy)

        assert list(capacity.columns) == ["subsystem", "ear_max_mwmes"]
        assert len(capacity) == len(SUBSYSTEMS)

        latest_date = tidy["date"].max()
        expected = tidy[tidy["date"] == latest_date].set_index("subsystem")["ear_max_mwmes"]
        for _, row in capacity.iterrows():
            assert row["ear_max_mwmes"] == pytest.approx(expected[row["subsystem"]])


class TestWriteTidyReservoir:
    def test_round_trips_through_csv(self, raw_df, tmp_path):
        tidy = build_reservoir.build_tidy_reservoir(raw_df, subsystems=SUBSYSTEMS)
        out = build_reservoir.write_tidy_reservoir(tidy, tmp_path / "reservoir.csv")

        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(tidy)
        assert list(reloaded.columns) == list(tidy.columns)
