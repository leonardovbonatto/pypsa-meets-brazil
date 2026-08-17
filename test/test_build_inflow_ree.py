# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for turning raw ONS ENA-per-REE data into the tidy REE-level
inflow series (ADR-0008, SDDP epic stage 2)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "ena_ree_sample.csv"
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "ena_ree.yaml"

# The 4 REEs in the fixture, real mapping (PR-35's registry) - matches
# what build_reservoir_registry actually produced, checked not assumed.
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


build_inflow_ree = _load("build_inflow_ree", REPO_ROOT / "scripts" / "build_inflow_ree.py")


@pytest.fixture
def raw_df():
    return build_inflow_ree.load_raw([FIXTURE])


class TestLoadRaw:
    def test_concatenates_and_reads_real_fixture(self, raw_df):
        # 5 days x 4 REEs, cut from the real 2024 file (see PR-36 handoff).
        assert len(raw_df) == 20
        assert set(raw_df["nom_reservatorioee"]) == {"BELO MONTE", "IGUACU", "NORDESTE", "SUDESTE"}


class TestValidateAgainstDictionary:
    def test_accepts_real_fixture(self, raw_df):
        build_inflow_ree.validate_against_dictionary(raw_df, DICTIONARY)  # must not raise

    def test_rejects_a_dropped_column(self, raw_df):
        import pandera.pandas as pa

        drifted = raw_df.drop(columns=["ena_bruta_ree_mwmed"])
        with pytest.raises(pa.errors.SchemaError):
            build_inflow_ree.validate_against_dictionary(drifted, DICTIONARY)


class TestAttachSubsystem:
    def test_joins_the_real_mapping(self, raw_df):
        attached = build_inflow_ree.attach_subsystem(raw_df, REE_MAP)
        assert set(attached["subsystem"]) == {"N", "S", "NE", "SE_CO"}

    def test_raises_on_an_unmapped_ree(self, raw_df):
        bad_map = REE_MAP[REE_MAP["ree"] != "BELO MONTE"]
        with pytest.raises(ValueError, match="no subsystem mapping"):
            build_inflow_ree.attach_subsystem(raw_df, bad_map)


class TestBuildTidyInflow:
    def test_shape_and_columns(self, raw_df):
        tidy = build_inflow_ree.build_tidy_inflow(raw_df, REE_MAP)
        assert list(tidy.columns) == [
            "date",
            "ree",
            "subsystem",
            "ena_bruta_mwmed",
            "ena_bruta_pct_mlt",
            "ena_armazenavel_mwmed",
            "ena_armazenavel_pct_mlt",
        ]
        assert len(tidy) == 20
        assert tidy["date"].nunique() == 5
        assert not tidy.isna().any().any()

    def test_raises_on_a_gap_in_the_daily_sequence(self, raw_df):
        gappy = raw_df[raw_df["ena_data"] != "2024-01-03"]
        with pytest.raises(ValueError, match="gap"):
            build_inflow_ree.build_tidy_inflow(gappy, REE_MAP)

    def test_raises_on_a_duplicated_day(self, raw_df):
        duped = pd.concat([raw_df, raw_df.iloc[[0]]], ignore_index=True)
        with pytest.raises(ValueError, match="gap"):
            build_inflow_ree.build_tidy_inflow(duped, REE_MAP)

    def test_clips_storable_exceeding_gross(self, raw_df):
        """Real finding (PR-36): unlike ena_subsistema, this check DOES
        trigger on real REE-level data (346/41,649 rows) - clipped, not
        raised. See the data dictionary's notes."""
        broken = raw_df.copy()
        broken.loc[0, "ena_armazenavel_ree_mwmed"] = broken.loc[0, "ena_bruta_ree_mwmed"] * 1.4

        tidy = build_inflow_ree.build_tidy_inflow(broken, REE_MAP)

        clipped_row = tidy[
            (tidy["date"] == pd.Timestamp(broken.loc[0, "ena_data"]))
            & (tidy["ree"] == broken.loc[0, "nom_reservatorioee"])
        ]
        assert clipped_row["ena_armazenavel_mwmed"].iloc[0] == pytest.approx(
            broken.loc[0, "ena_bruta_ree_mwmed"]
        )

    def test_does_not_require_every_ree_to_share_the_same_date_count(self, raw_df):
        """Real finding (PR-36): 3 REEs only exist as tracked units from
        2017-12-30 onward - a genuine REE-structure revision, not a bug.
        Dropping one REE's coverage down to fewer days than the others
        must not raise, unlike build_inflow.py's subsystem-level check."""
        shorter = raw_df[
            ~((raw_df["nom_reservatorioee"] == "IGUACU") & (raw_df["ena_data"] == "2024-01-05"))
        ]
        tidy = build_inflow_ree.build_tidy_inflow(shorter, REE_MAP)
        assert len(tidy) == 19


class TestWriteTidyInflow:
    def test_round_trips_through_csv(self, raw_df, tmp_path):
        tidy = build_inflow_ree.build_tidy_inflow(raw_df, REE_MAP)
        out = build_inflow_ree.write_tidy_inflow(tidy, tmp_path / "inflow_ena_ree.csv")

        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(tidy)
        assert list(reloaded.columns) == list(tidy.columns)
