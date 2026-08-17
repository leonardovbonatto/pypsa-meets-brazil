# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for turning raw ONS EAR-per-REE data into the tidy REE-level
reservoir storage series (ADR-0008, SDDP epic stage 2)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "ear_ree_sample.csv"
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "ear_ree.yaml"

REE_MAP = pd.DataFrame(
    {
        "ree": ["BELO MONTE", "IGUACU", "NORDESTE", "SUDESTE"],
        "subsystem": ["N", "S", "NE", "SE_CO"],
    }
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_reservoir_ree = _load("build_reservoir_ree", REPO_ROOT / "scripts" / "build_reservoir_ree.py")


@pytest.fixture
def raw_df():
    return build_reservoir_ree.load_raw([FIXTURE])


class TestLoadRaw:
    def test_reads_real_fixture(self, raw_df):
        assert len(raw_df) == 20
        assert set(raw_df["nom_ree"]) == {"BELO MONTE", "IGUACU", "NORDESTE", "SUDESTE"}


class TestValidateAgainstDictionary:
    def test_accepts_real_fixture(self, raw_df):
        build_reservoir_ree.validate_against_dictionary(raw_df, DICTIONARY)  # must not raise

    def test_rejects_a_dropped_column(self, raw_df):
        import pandera.pandas as pa

        drifted = raw_df.drop(columns=["ear_max_ree"])
        with pytest.raises(pa.errors.SchemaError):
            build_reservoir_ree.validate_against_dictionary(drifted, DICTIONARY)


class TestBuildTidyReservoir:
    def test_shape_and_columns(self, raw_df):
        tidy = build_reservoir_ree.build_tidy_reservoir(raw_df, REE_MAP)
        assert list(tidy.columns) == [
            "date",
            "ree",
            "subsystem",
            "ear_max_mwmes",
            "ear_verif_mwmes",
            "ear_verif_pct",
        ]
        assert len(tidy) == 20
        assert not tidy.isna().any().any()

    def test_raises_on_an_unexpected_gap(self, raw_df):
        gappy = raw_df[raw_df["ear_data"] != "2024-01-03"]
        with pytest.raises(ValueError, match="gap"):
            build_reservoir_ree.build_tidy_reservoir(gappy, REE_MAP)

    def test_known_teles_pires_gap_does_not_raise(self, raw_df):
        """Real finding (PR-36): TELES PIRES has a specific, already-
        investigated 13-day gap in 2019 (tied to ITAIPU's EAR reporting
        stopping the same day) - a REPORTING_GAPS entry, so it prints a
        warning instead of raising. Simulated here since the 5-day
        fixture doesn't span the real gap."""
        tp_rows = pd.DataFrame(
            {
                "nom_ree": ["TELES PIRES"] * 3,
                "ear_data": ["2024-01-01", "2024-01-02", "2024-01-15"],
                "ear_max_ree": [900.0, 900.0, 900.0],
                "ear_verif_ree_mwmes": [400.0, 410.0, 420.0],
                "ear_verif_ree_percentual": [44.4, 45.6, 46.7],
            }
        )
        tp_map = pd.DataFrame({"ree": ["TELES PIRES"], "subsystem": ["SE_CO"]})
        tidy = build_reservoir_ree.build_tidy_reservoir(tp_rows, tp_map)
        assert len(tidy) == 3

    def test_clips_negative_verified_storage_to_zero(self, raw_df):
        """Real finding (PR-36): 73/39,366 rows have verified storage
        below zero, concentrated in the smallest-capacity REEs."""
        broken = raw_df.copy()
        broken.loc[0, "ear_verif_ree_mwmes"] = -5.0

        tidy = build_reservoir_ree.build_tidy_reservoir(broken, REE_MAP)

        clipped_row = tidy[
            (tidy["date"] == pd.Timestamp(broken.loc[0, "ear_data"]))
            & (tidy["ree"] == broken.loc[0, "nom_ree"])
        ]
        assert clipped_row["ear_verif_mwmes"].iloc[0] == pytest.approx(0.0)
        assert clipped_row["ear_verif_pct"].iloc[0] == pytest.approx(0.0)

    def test_clips_verified_storage_exceeding_capacity(self, raw_df):
        """Real finding (PR-36): 547/39,366 rows have verified storage
        above ear_max_ree, concentrated in the smallest-capacity REEs -
        a larger rate than ear_subsistema's equivalent (PR-30)."""
        broken = raw_df.copy()
        broken.loc[0, "ear_verif_ree_mwmes"] = broken.loc[0, "ear_max_ree"] * 1.05

        tidy = build_reservoir_ree.build_tidy_reservoir(broken, REE_MAP)

        clipped_row = tidy[
            (tidy["date"] == pd.Timestamp(broken.loc[0, "ear_data"]))
            & (tidy["ree"] == broken.loc[0, "nom_ree"])
        ]
        assert clipped_row["ear_verif_mwmes"].iloc[0] == pytest.approx(broken.loc[0, "ear_max_ree"])
        assert clipped_row["ear_verif_pct"].iloc[0] == pytest.approx(100.0)


class TestLatestCapacity:
    def test_uses_each_ree_own_most_recent_date(self, raw_df):
        """Real finding (PR-36): ITAIPU's series ends in 2019, well before
        other REEs' - latest_capacity() must use each REE's OWN latest
        date, not one global latest date (which would exclude ITAIPU or
        silently use a stale value)."""
        mixed = pd.concat(
            [
                raw_df,
                pd.DataFrame(
                    {
                        "nom_ree": ["ITAIPU"],
                        "ear_data": ["2019-10-13"],
                        "ear_max_ree": [0.0],
                        "ear_verif_ree_mwmes": [0.0],
                        "ear_verif_ree_percentual": [0.0],
                    }
                ),
            ],
            ignore_index=True,
        )
        full_map = pd.concat(
            [REE_MAP, pd.DataFrame({"ree": ["ITAIPU"], "subsystem": ["SE_CO"]})], ignore_index=True
        )
        tidy = build_reservoir_ree.build_tidy_reservoir(mixed, full_map)
        capacity = build_reservoir_ree.latest_capacity(tidy)

        assert "ITAIPU" in set(capacity["ree"])
        itaipu_row = capacity[capacity["ree"] == "ITAIPU"]
        assert itaipu_row["ear_max_mwmes"].iloc[0] == pytest.approx(0.0)


class TestWriteCsv:
    def test_round_trips(self, raw_df, tmp_path):
        tidy = build_reservoir_ree.build_tidy_reservoir(raw_df, REE_MAP)
        out = build_reservoir_ree.write_csv(tidy, tmp_path / "reservoir_ree.csv")

        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(tidy)
