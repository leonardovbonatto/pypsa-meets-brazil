# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for the reservoir registry and REE-to-subsystem mapping
(ADR-0008, SDDP epic stage 2)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "reservatorio_sample.csv"
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "reservatorio.yaml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_reservoir_registry = _load(
    "build_reservoir_registry", REPO_ROOT / "scripts" / "build_reservoir_registry.py"
)


@pytest.fixture
def raw_df():
    return build_reservoir_registry.load_raw(FIXTURE)


class TestLoadRaw:
    def test_reads_real_fixture(self, raw_df):
        # 3 reservoirs x 4 subsystems, cut from the real registry (see PR-35 handoff).
        assert len(raw_df) == 12
        assert set(raw_df["id_subsistema"]) == {"N", "NE", "S", "SE"}


class TestValidateAgainstDictionary:
    def test_accepts_real_fixture(self, raw_df):
        build_reservoir_registry.validate_against_dictionary(raw_df, DICTIONARY)  # must not raise

    def test_rejects_a_dropped_column(self, raw_df):
        import pandera.pandas as pa

        drifted = raw_df.drop(columns=["nom_ree"])
        with pytest.raises(pa.errors.SchemaError):
            build_reservoir_registry.validate_against_dictionary(drifted, DICTIONARY)


class TestBuildTidyRegistry:
    def test_se_becomes_se_co(self, raw_df):
        tidy = build_reservoir_registry.build_tidy_registry(raw_df)
        assert "SE_CO" in set(tidy["subsystem"])
        assert "SE" not in set(tidy["subsystem"])

    def test_keeps_all_rows_and_real_physical_columns(self, raw_df):
        tidy = build_reservoir_registry.build_tidy_registry(raw_df)
        assert len(tidy) == len(raw_df)
        for col in ["nom_ree", "val_volutiltot", "val_cotamaxima", "nom_bacia"]:
            assert col in tidy.columns


class TestBuildReeSubsystemMap:
    def test_one_row_per_ree(self, raw_df):
        tidy = build_reservoir_registry.build_tidy_registry(raw_df)
        ree_map = build_reservoir_registry.build_ree_subsystem_map(tidy)

        assert list(ree_map.columns) == ["ree", "subsystem"]
        assert len(ree_map) == tidy["nom_ree"].nunique()

    def test_real_fixture_mapping_matches_known_values(self, raw_df):
        """Real, checked values (ADR-0008/PR-35): corrects a domain-name
        guess made while drafting the ADR - MANAUS-AMAPA and BELO MONTE
        are subsystem N, NORDESTE is NE, SUL/IGUACU are S, PARANA/SUDESTE
        are SE_CO, matching what was actually verified against the data."""
        tidy = build_reservoir_registry.build_tidy_registry(raw_df)
        ree_map = build_reservoir_registry.build_ree_subsystem_map(tidy).set_index("ree")[
            "subsystem"
        ]

        assert ree_map["MANAUS-AMAPA"] == "N"
        assert ree_map["BELO MONTE"] == "N"
        assert ree_map["NORDESTE"] == "NE"
        assert ree_map["SUL"] == "S"
        assert ree_map["IGUACU"] == "S"
        assert ree_map["PARANA"] == "SE_CO"
        assert ree_map["SUDESTE"] == "SE_CO"

    def test_raises_when_a_ree_maps_to_two_subsystems(self, raw_df):
        tidy = build_reservoir_registry.build_tidy_registry(raw_df)
        broken = tidy.copy()
        # Force an ambiguity: give NORDESTE's first row a different subsystem.
        idx = broken[broken["nom_ree"] == "NORDESTE"].index[0]
        broken.loc[idx, "subsystem"] = "N"

        with pytest.raises(ValueError, match="more than one subsystem"):
            build_reservoir_registry.build_ree_subsystem_map(broken)


class TestWriteCsv:
    def test_round_trips(self, raw_df, tmp_path):
        tidy = build_reservoir_registry.build_tidy_registry(raw_df)
        out = build_reservoir_registry.write_csv(tidy, tmp_path / "registry.csv")

        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(tidy)
