# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Tests that committed data dictionaries describe reality.

The dictionary is the artifact every later session reads instead of the raw
file, so a dictionary that has drifted from the data is worse than none at
all: it is confidently wrong. These tests check it against a committed slice
of the real upstream bytes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DICT_DIR = REPO_ROOT / "docs" / "data-dictionary"
CURVA_CARGA_DICT = DICT_DIR / "ons" / "curva_carga.yaml"
CURVA_CARGA_FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "curva_carga_2024_sample.csv"
CAPACIDADE_DICT = DICT_DIR / "ons" / "capacidade_geracao.yaml"
CAPACIDADE_FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "capacidade_geracao_sample.csv"
CVU_DICT = DICT_DIR / "ons" / "cvu_usina_termica.yaml"
CVU_FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "cvu_usina_termica_sample.csv"
INTERCAMBIO_DICT = DICT_DIR / "ons" / "intercambio_nacional.yaml"
INTERCAMBIO_FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "intercambio_nacional_sample.csv"
FATOR_CAPACIDADE_DICT = DICT_DIR / "ons" / "fator_capacidade.yaml"
FATOR_CAPACIDADE_FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "fator_capacidade_sample.csv"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


inspect_mod = _load("_inspect", REPO_ROOT / "scripts" / "_inspect.py")

COMMITTED_DICTS = sorted(DICT_DIR.rglob("*.yaml"))


@pytest.fixture
def curva_carga_df():
    return inspect_mod.inspect_csv(CURVA_CARGA_FIXTURE, delimiter=";")


class TestCurvaCargaDictionary:
    def test_schema_validates_against_real_fixture(self, curva_carga_df):
        """The committed dictionary must accept real upstream bytes."""
        dictionary = inspect_mod.load_dictionary(CURVA_CARGA_DICT)
        schema = inspect_mod.to_pandera_schema(dictionary)

        schema.validate(curva_carga_df)  # must not raise

    def test_schema_hash_matches_fixture(self, curva_carga_df):
        """
        Guards against the dictionary and the data drifting apart. schema_hash
        covers column names and dtypes only, so the 24-row fixture hashes the
        same as the 35,136-row file it was cut from.
        """
        dictionary = inspect_mod.load_dictionary(CURVA_CARGA_DICT)
        assert inspect_mod.schema_hash(curva_carga_df) == dictionary["schema_hash"]

    def test_load_column_carries_its_unit(self):
        """MWmed vs MW vs MWh is the single most common silent error here."""
        dictionary = inspect_mod.load_dictionary(CURVA_CARGA_DICT)
        load_col = next(c for c in dictionary["columns"] if c["name"] == "val_cargaenergiahomwmed")
        assert load_col["unit"] == "MWmed"

    def test_documented_subsystem_codes_are_the_ones_present(self, curva_carga_df):
        assert set(curva_carga_df["id_subsistema"]) == {"N", "NE", "S", "SE"}


@pytest.fixture
def capacidade_df():
    return inspect_mod.inspect_csv(CAPACIDADE_FIXTURE, delimiter=";")


class TestCapacidadeGeracaoDictionary:
    def test_schema_validates_against_real_fixture(self, capacidade_df):
        dictionary = inspect_mod.load_dictionary(CAPACIDADE_DICT)
        schema = inspect_mod.to_pandera_schema(dictionary)

        schema.validate(capacidade_df)  # must not raise

    def test_schema_hash_matches_fixture(self, capacidade_df):
        dictionary = inspect_mod.load_dictionary(CAPACIDADE_DICT)
        assert inspect_mod.schema_hash(capacidade_df) == dictionary["schema_hash"]

    def test_capacity_column_carries_its_unit(self):
        dictionary = inspect_mod.load_dictionary(CAPACIDADE_DICT)
        col = next(c for c in dictionary["columns"] if c["name"] == "val_potenciaefetiva")
        assert col["unit"] == "MW"

    def test_fixture_includes_the_py_edge_case(self, capacidade_df):
        """PY (Itaipu 50Hz) must stay in fixtures/docs, not get quietly filtered out upstream."""
        assert "PY" in set(capacidade_df["id_subsistema"])

    def test_fixture_includes_a_decommissioned_unit(self, capacidade_df):
        assert capacidade_df["dat_desativacao"].notna().any()


@pytest.fixture
def cvu_df():
    return inspect_mod.inspect_csv(CVU_FIXTURE, delimiter=";")


class TestCvuUsinaTermicaDictionary:
    def test_schema_validates_against_real_fixture(self, cvu_df):
        dictionary = inspect_mod.load_dictionary(CVU_DICT)
        schema = inspect_mod.to_pandera_schema(dictionary)

        schema.validate(cvu_df)  # must not raise

    def test_schema_hash_matches_fixture(self, cvu_df):
        dictionary = inspect_mod.load_dictionary(CVU_DICT)
        assert inspect_mod.schema_hash(cvu_df) == dictionary["schema_hash"]

    def test_cost_column_carries_its_unit(self):
        dictionary = inspect_mod.load_dictionary(CVU_DICT)
        col = next(c for c in dictionary["columns"] if c["name"] == "val_cvu")
        assert col["unit"] == "R$/MWh"

    def test_fixture_includes_a_zero_cost_plant(self, cvu_df):
        """CVU=0 is a real value (e.g. bagasse co-generation), not a null - must not be dropped."""
        assert (cvu_df["val_cvu"] == 0).any()

    def test_fixture_shows_cvu_varies_by_week_for_the_same_plant(self, cvu_df):
        geramar1 = cvu_df[cvu_df["nom_usina"] == "GERAMAR1"]
        assert geramar1["dat_iniciosemana"].nunique() == 2
        assert geramar1["val_cvu"].nunique() == 2


@pytest.fixture
def intercambio_df():
    return inspect_mod.inspect_csv(INTERCAMBIO_FIXTURE, delimiter=";")


class TestIntercambioNacionalDictionary:
    def test_schema_validates_against_real_fixture(self, intercambio_df):
        dictionary = inspect_mod.load_dictionary(INTERCAMBIO_DICT)
        schema = inspect_mod.to_pandera_schema(dictionary)

        schema.validate(intercambio_df)  # must not raise

    def test_schema_hash_matches_fixture(self, intercambio_df):
        dictionary = inspect_mod.load_dictionary(INTERCAMBIO_DICT)
        assert inspect_mod.schema_hash(intercambio_df) == dictionary["schema_hash"]

    def test_flow_column_carries_its_unit(self):
        dictionary = inspect_mod.load_dictionary(INTERCAMBIO_DICT)
        col = next(c for c in dictionary["columns"] if c["name"] == "val_intercambiomwmed")
        assert col["unit"] == "MWmed"

    def test_fixture_has_exactly_the_four_real_boundaries(self, intercambio_df):
        """No N-S or NE-S boundary exists in the real data - not a complete graph."""
        pairs = set(
            zip(
                intercambio_df["id_subsistema_origem"],
                intercambio_df["id_subsistema_destino"],
                strict=True,
            )
        )
        assert pairs == {("N", "NE"), ("N", "SE"), ("NE", "SE"), ("SE", "S")}

    def test_fixture_includes_both_flow_directions(self, intercambio_df):
        """Sign is directional; a capacity proxy must use abs(), not assume one sign."""
        assert (intercambio_df["val_intercambiomwmed"] > 0).any()
        assert (intercambio_df["val_intercambiomwmed"] < 0).any()


@pytest.fixture
def fator_capacidade_df():
    return inspect_mod.inspect_csv(FATOR_CAPACIDADE_FIXTURE, delimiter=";")


class TestFatorCapacidadeDictionary:
    def test_schema_validates_against_real_fixture(self, fator_capacidade_df):
        dictionary = inspect_mod.load_dictionary(FATOR_CAPACIDADE_DICT)
        schema = inspect_mod.to_pandera_schema(dictionary)

        schema.validate(fator_capacidade_df)  # must not raise

    def test_schema_hash_matches_fixture(self, fator_capacidade_df):
        dictionary = inspect_mod.load_dictionary(FATOR_CAPACIDADE_DICT)
        assert inspect_mod.schema_hash(fator_capacidade_df) == dictionary["schema_hash"]

    def test_capacity_factor_column_is_dimensionless(self):
        dictionary = inspect_mod.load_dictionary(FATOR_CAPACIDADE_DICT)
        col = next(c for c in dictionary["columns"] if c["name"] == "val_fatorcapacidade")
        assert col["unit"] == "dimensionless (fraction of installed capacity)"

    def test_only_wind_and_solar_technologies_appear(self, fator_capacidade_df):
        assert set(fator_capacidade_df["nom_tipousina"]) == {"Eólica", "Solar"}

    def test_fixture_includes_a_factor_above_one(self, fator_capacidade_df):
        """Real measurement noise near the nameplate boundary - a build step must clip it."""
        assert (fator_capacidade_df["val_fatorcapacidade"] > 1.0).any()

    def test_fixture_covers_every_real_subsystem_technology_combination(self, fator_capacidade_df):
        """
        SE_CO has no wind rows in the real data at all (verified in both
        January and July 2024) even though it has ~261 MW of wind capacity -
        a real gap, not a fixture omission. This fixture's coverage should
        match that: every combination that exists in the real data, and
        nothing invented for SE wind.
        """
        combos = set(
            zip(
                fator_capacidade_df["id_subsistema"],
                fator_capacidade_df["nom_tipousina"],
                strict=True,
            )
        )
        assert combos == {
            ("N", "Eólica"),
            ("NE", "Eólica"),
            ("NE", "Solar"),
            ("S", "Eólica"),
            ("SE", "Solar"),
        }


@pytest.mark.parametrize("path", COMMITTED_DICTS, ids=lambda p: p.name)
class TestEveryCommittedDictionary:
    """
    Repo-wide invariants. `_inspect.py` emits `description` as null and `notes`
    as empty on purpose — they cannot be inferred. Committing a dictionary in
    that state means nobody did the inspection, so fail the build.
    """

    def test_every_column_has_a_description(self, path):
        dictionary = inspect_mod.load_dictionary(path)
        undocumented = [c["name"] for c in dictionary["columns"] if not c["description"]]
        assert not undocumented, f"columns missing a description: {undocumented}"

    def test_has_notes(self, path):
        dictionary = inspect_mod.load_dictionary(path)
        assert dictionary["notes"], "dictionary has no notes — was it inspected by hand?"

    def test_records_where_it_came_from(self, path):
        dictionary = inspect_mod.load_dictionary(path)
        assert dictionary["source_url"].startswith("http")
        assert dictionary["retrieved"]
        assert dictionary["schema_hash"].startswith("sha256:")
