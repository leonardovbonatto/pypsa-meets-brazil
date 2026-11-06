# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for aggregating raw ONS capacity data into the T0 generator table."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "capacidade_geracao_sample.csv"
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "capacidade_geracao.yaml"
SUBSYSTEMS = ["SE_CO", "S", "NE", "N"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_generators = _load("build_generators", REPO_ROOT / "scripts" / "build_generators.py")


@pytest.fixture
def raw_df():
    return build_generators.load_raw(FIXTURE)


class TestLoadRaw:
    def test_reads_the_real_fixture(self, raw_df):
        # 16 active units (one per subsystem x technology present) + 1 decommissioned.
        assert len(raw_df) == 17
        assert "PY" in set(raw_df["id_subsistema"])


class TestValidateAgainstDictionary:
    def test_accepts_real_fixture(self, raw_df):
        build_generators.validate_against_dictionary(raw_df, DICTIONARY)  # must not raise


class TestFilterActive:
    def test_drops_the_decommissioned_unit(self, raw_df):
        active = build_generators.filter_active(raw_df)
        assert len(active) == 16
        assert active["dat_desativacao"].isna().all()


class TestMapTechnology:
    def test_maps_all_five_known_types(self, raw_df):
        active = build_generators.filter_active(raw_df)
        mapped = build_generators.map_technology(active)
        assert set(mapped["carrier"]) == {"hydro", "wind", "solar", "thermal", "nuclear"}

    def test_raises_on_unknown_plant_type(self, raw_df):
        active = build_generators.filter_active(raw_df)
        bad = active.copy()
        bad.loc[bad.index[0], "nom_tipousina"] = "GEOTERMICA"
        with pytest.raises(ValueError, match="unmapped"):
            build_generators.map_technology(bad)


class TestBuildGeneratorCapacity:
    def test_excludes_py_and_decommissioned(self, raw_df):
        tidy = build_generators.build_generator_capacity(raw_df, subsystems=SUBSYSTEMS)
        assert "PY" not in set(tidy["subsystem"])
        # the decommissioned row was NE/thermal at 1.6 MW - must not appear in the sum.
        ne_thermal = tidy[(tidy["subsystem"] == "NE") & (tidy["carrier"] == "thermal")]
        assert ne_thermal["p_nom_mw"].iloc[0] == pytest.approx(39.68)

    def test_columns_and_no_duplicate_groups(self, raw_df):
        tidy = build_generators.build_generator_capacity(raw_df, subsystems=SUBSYSTEMS)
        assert list(tidy.columns) == ["subsystem", "carrier", "p_nom_mw"]
        assert not tidy.duplicated(["subsystem", "carrier"]).any()

    def test_se_becomes_se_co(self, raw_df):
        tidy = build_generators.build_generator_capacity(raw_df, subsystems=SUBSYSTEMS)
        assert "SE_CO" in set(tidy["subsystem"])
        assert "SE" not in set(tidy["subsystem"])

    def test_raises_when_a_configured_subsystem_is_absent(self, raw_df):
        with pytest.raises(ValueError, match="absent"):
            build_generators.build_generator_capacity(
                raw_df, subsystems=[*SUBSYSTEMS, "ISOLATED_RR"]
            )


class TestWriteGeneratorCapacity:
    def test_round_trips_through_csv(self, raw_df, tmp_path):
        import pandas as pd

        tidy = build_generators.build_generator_capacity(raw_df, subsystems=SUBSYSTEMS)
        out = build_generators.write_generator_capacity(tidy, tmp_path / "generators_t0.csv")

        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(tidy)
        assert list(reloaded.columns) == ["subsystem", "carrier", "p_nom_mw"]


class TestMonthlyOperatingCapacity:
    UNITS = pd.DataFrame(
        {
            "id_subsistema": ["SE", "SE", "SE", "PY"],
            "nom_tipousina": ["FOTOVOLTAICA", "FOTOVOLTAICA", "FOTOVOLTAICA", "HIDROELÉTRICA"],
            "dat_entradaoperacao": ["2020-01-01", "2024-02-15", "2025-06-01", "2000-01-01"],
            "dat_desativacao": [None, None, None, None],
            "val_potenciaefetiva": [100.0, 50.0, 70.0, 999.0],
        }
    )

    def test_counts_only_units_operating_at_each_month_end(self):
        monthly = build_generators.monthly_operating_capacity(
            self.UNITS, months=[(2024, 1), (2024, 2)]
        ).set_index("month")
        assert monthly.loc[1, "p_nom_mw"] == pytest.approx(100.0)
        assert monthly.loc[2, "p_nom_mw"] == pytest.approx(150.0)

    def test_deactivated_unit_counts_until_its_date(self):
        units = self.UNITS.copy()
        units.loc[0, "dat_desativacao"] = "2024-01-20"
        monthly = build_generators.monthly_operating_capacity(units, months=[(2024, 1)])
        assert monthly.empty  # the only unit operating in January left on the 20th

    def test_capacity_is_the_largest_month_and_share_follows(self):
        months = [(2024, 1), (2024, 2)]
        capacity = build_generators.build_generator_capacity(
            self.UNITS, subsystems=["SE_CO"], months=months
        )
        assert capacity["p_nom_mw"].iloc[0] == pytest.approx(150.0)
        share = build_generators.commissioning_share(
            build_generators.monthly_operating_capacity(self.UNITS, months=months), capacity
        ).set_index("month")["share"]
        assert share[1] == pytest.approx(100.0 / 150.0)
        assert share[2] == pytest.approx(1.0)
