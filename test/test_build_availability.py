# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for aggregating raw ONS capacity-factor data into the T0 availability profile."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "fator_capacidade_sample.csv"
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "fator_capacidade.yaml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_availability = _load("build_availability", REPO_ROOT / "scripts" / "build_availability.py")


@pytest.fixture
def raw_df():
    return build_availability.load_raw([FIXTURE])


class TestLoadRaw:
    def test_reads_the_real_fixture(self, raw_df):
        assert len(raw_df) == 28


class TestValidateAgainstDictionary:
    def test_accepts_real_fixture(self, raw_df):
        build_availability.validate_against_dictionary(raw_df, DICTIONARY)  # must not raise


class TestMapTechnology:
    def test_maps_both_known_types(self, raw_df):
        mapped = build_availability.map_technology(raw_df)
        assert set(mapped["carrier"]) == {"wind", "solar"}

    def test_raises_on_unknown_plant_type(self, raw_df):
        bad = raw_df.copy()
        bad.loc[bad.index[0], "nom_tipousina"] = "Geotermica"
        with pytest.raises(ValueError, match="unmapped"):
            build_availability.map_technology(bad)


class TestBuildAvailability:
    def test_columns_and_row_count(self, raw_df):
        tidy = build_availability.build_availability(raw_df)
        assert list(tidy.columns) == ["snapshot", "subsystem", "carrier", "p_max_pu"]
        # 3 hours x (N/wind, NE/wind, NE/solar, S/wind, SE_CO/solar) + 1 extra
        # (the appended >1.0 row, a sixth NE/solar timestamp).
        assert len(tidy) == 16

    def test_clips_to_the_unit_interval(self, raw_df):
        tidy = build_availability.build_availability(raw_df)
        assert (tidy["p_max_pu"] >= 0.0).all()
        assert (tidy["p_max_pu"] <= 1.0).all()

    def test_clipped_row_hits_exactly_one(self, raw_df):
        """The real val_fatorcapacidade > 1.0 row (PR-14) must clip to exactly 1.0, not be dropped."""
        tidy = build_availability.build_availability(raw_df)
        clipped = tidy[(tidy["subsystem"] == "NE") & (tidy["carrier"] == "solar")]
        assert clipped["p_max_pu"].max() == pytest.approx(1.0)

    def test_single_plant_group_matches_its_own_factor(self, raw_df):
        """
        N's fixture has one plant-group only, so the capacity-weighted
        aggregate must equal that group's own reported factor exactly -
        hand-verified against the raw fixture bytes.
        """
        tidy = build_availability.build_availability(raw_df)
        n_wind = tidy[tidy["subsystem"] == "N"].sort_values("snapshot")["p_max_pu"].tolist()
        assert n_wind == pytest.approx([0.005148, 0.007007, 0.067383], abs=1e-6)

    def test_se_becomes_se_co(self, raw_df):
        tidy = build_availability.build_availability(raw_df)
        assert "SE_CO" in set(tidy["subsystem"])
        assert "SE" not in set(tidy["subsystem"])

    def test_no_row_for_a_combination_absent_from_the_data(self, raw_df):
        """SE_CO has no wind in the real data (PR-14) - must not be invented here."""
        tidy = build_availability.build_availability(raw_df)
        combos = set(zip(tidy["subsystem"], tidy["carrier"], strict=True))
        assert ("SE_CO", "wind") not in combos


class TestWriteAvailability:
    def test_round_trips_through_csv(self, raw_df, tmp_path):
        import pandas as pd

        tidy = build_availability.build_availability(raw_df)
        out = build_availability.write_availability(tidy, tmp_path / "availability_t0.csv")

        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(tidy)
        assert list(reloaded.columns) == ["snapshot", "subsystem", "carrier", "p_max_pu"]
