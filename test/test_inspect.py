# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for the data-dictionary generator and its pandera schema derivation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
# Synthetic, not real ONS bytes: it carries a null value so null_rate has
# something to measure. Real-data checks live in test_data_dictionaries.py.
FIXTURE = REPO_ROOT / "test" / "fixtures" / "synthetic_load_sample.csv"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


inspect_mod = _load("_inspect", REPO_ROOT / "scripts" / "_inspect.py")


@pytest.fixture
def df():
    return inspect_mod.inspect_csv(FIXTURE, delimiter=";")


class TestInspectCsv:
    def test_reads_columns_and_row_count(self, df):
        assert list(df.columns) == ["din_instante", "val_cargaenergiamwmed"]
        assert len(df) == 5


class TestBuildDictionary:
    def test_unit_and_description_are_left_for_a_human(self, df):
        d = inspect_mod.build_dictionary(
            df,
            dataset="carga",
            source="ons",
            source_url="https://x",
            retrieved="2024-01-01T00:00:00Z",
        )
        for col in d["columns"]:
            assert col["unit"] is None
            assert col["description"] is None

    def test_null_rate_reflects_the_blank_cell(self, df):
        d = inspect_mod.build_dictionary(
            df,
            dataset="carga",
            source="ons",
            source_url="https://x",
            retrieved="2024-01-01T00:00:00Z",
        )
        load_col = next(c for c in d["columns"] if c["name"] == "val_cargaenergiamwmed")
        assert load_col["nullable"] is True
        assert load_col["null_rate"] == pytest.approx(0.2)

    def test_row_count_matches_dataframe(self, df):
        d = inspect_mod.build_dictionary(
            df,
            dataset="carga",
            source="ons",
            source_url="https://x",
            retrieved="2024-01-01T00:00:00Z",
        )
        assert d["row_count"] == 5


class TestSchemaHash:
    def test_deterministic(self, df):
        assert inspect_mod.schema_hash(df) == inspect_mod.schema_hash(df)

    def test_changes_when_dtype_changes(self, df):
        mutated = df.copy()
        mutated["val_cargaenergiamwmed"] = mutated["val_cargaenergiamwmed"].astype(str)
        assert inspect_mod.schema_hash(df) != inspect_mod.schema_hash(mutated)


class TestWriteAndLoadDictionary:
    def test_round_trips_through_yaml(self, df, tmp_path):
        d = inspect_mod.build_dictionary(
            df,
            dataset="carga",
            source="ons",
            source_url="https://x",
            retrieved="2024-01-01T00:00:00Z",
        )
        out = inspect_mod.write_dictionary(d, tmp_path / "ons" / "carga.yaml")

        assert inspect_mod.load_dictionary(out) == d


class TestToPanderaSchema:
    def test_matching_dataframe_validates(self, df):
        d = inspect_mod.build_dictionary(
            df,
            dataset="carga",
            source="ons",
            source_url="https://x",
            retrieved="2024-01-01T00:00:00Z",
        )
        schema = inspect_mod.to_pandera_schema(d)
        schema.validate(df)  # must not raise

    def test_dropped_column_is_caught(self, df):
        import pandera.pandas as pa

        d = inspect_mod.build_dictionary(
            df,
            dataset="carga",
            source="ons",
            source_url="https://x",
            retrieved="2024-01-01T00:00:00Z",
        )
        schema = inspect_mod.to_pandera_schema(d)
        drifted = df.drop(columns=["val_cargaenergiamwmed"])

        with pytest.raises(pa.errors.SchemaError):
            schema.validate(drifted)

    def test_retyped_column_is_caught(self, df):
        import pandera.pandas as pa

        d = inspect_mod.build_dictionary(
            df,
            dataset="carga",
            source="ons",
            source_url="https://x",
            retrieved="2024-01-01T00:00:00Z",
        )
        schema = inspect_mod.to_pandera_schema(d)
        drifted = df.copy()
        drifted["val_cargaenergiamwmed"] = drifted["val_cargaenergiamwmed"].astype(str)

        with pytest.raises(pa.errors.SchemaError):
            schema.validate(drifted)
