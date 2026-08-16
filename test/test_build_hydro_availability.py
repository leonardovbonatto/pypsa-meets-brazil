# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for the observed-generation hydro backcast profile (ADR-0007)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "geracao_usina_sample.csv"
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "geracao_usina.yaml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_hydro = _load(
    "build_hydro_availability", REPO_ROOT / "scripts" / "build_hydro_availability.py"
)


@pytest.fixture
def raw_df():
    return build_hydro.load_raw([FIXTURE])


@pytest.fixture
def capacity():
    """Generous capacities so the fixture's real generation stays well under 1.0."""
    return pd.DataFrame(
        [
            {"subsystem": "N", "carrier": "hydro", "p_nom_mw": 22089.8},
            {"subsystem": "NE", "carrier": "hydro", "p_nom_mw": 10830.8},
            {"subsystem": "S", "carrier": "hydro", "p_nom_mw": 15505.5},
            {"subsystem": "SE_CO", "carrier": "hydro", "p_nom_mw": 54252.3},
            {"subsystem": "SE_CO", "carrier": "thermal", "p_nom_mw": 17422.9},
        ]
    )


class TestValidateAgainstDictionary:
    def test_accepts_real_fixture(self, raw_df):
        build_hydro.validate_against_dictionary(raw_df, DICTIONARY)  # must not raise


class TestFilterHydro:
    def test_drops_non_hydro_technologies(self, raw_df):
        filtered = build_hydro.filter_hydro(raw_df)
        assert set(filtered["nom_tipousina"]) == {"HIDROELÉTRICA"}

    def test_drops_modalidades_capacidade_geracao_does_not_cover(self, raw_df):
        """
        The population-mismatch guard (PR-17): Tipo III and MMGD plants are
        in this dataset but not in the capacity denominator, so including
        them pushes the ratio above 1.0.
        """
        filtered = build_hydro.filter_hydro(raw_df)
        assert set(filtered["cod_modalidadeoperacao"]) <= build_hydro.MATCHING_MODALIDADES
        # the fixture really does contain excluded rows, so this filter bites
        assert len(filtered) < len(raw_df[raw_df["nom_tipousina"] == "HIDROELÉTRICA"])


class TestBuildHydroAvailability:
    def test_columns_and_carrier(self, raw_df, capacity):
        tidy = build_hydro.build_hydro_availability(raw_df, capacity)
        assert list(tidy.columns) == ["snapshot", "subsystem", "carrier", "p_max_pu"]
        assert set(tidy["carrier"]) == {"hydro"}

    def test_stays_within_the_unit_interval(self, raw_df, capacity):
        tidy = build_hydro.build_hydro_availability(raw_df, capacity)
        assert (tidy["p_max_pu"] >= 0.0).all()
        assert (tidy["p_max_pu"] <= 1.0).all()

    def test_se_becomes_se_co(self, raw_df, capacity):
        tidy = build_hydro.build_hydro_availability(raw_df, capacity)
        assert "SE_CO" in set(tidy["subsystem"])
        assert "SE" not in set(tidy["subsystem"])

    def test_ratio_is_generation_over_capacity(self, raw_df, capacity):
        """Hand-check one cell against the raw fixture rather than trusting the pipeline."""
        filtered = build_hydro.filter_hydro(raw_df)
        mapped = filtered[filtered["id_subsistema"] == "N"]
        first_hour = sorted(mapped["din_instante"])[0]
        expected = mapped[mapped["din_instante"] == first_hour]["val_geracao"].sum() / 22089.8

        tidy = build_hydro.build_hydro_availability(raw_df, capacity)
        got = tidy[(tidy["subsystem"] == "N") & (tidy["snapshot"] == first_hour)]["p_max_pu"]

        assert got.iloc[0] == pytest.approx(expected)

    def test_raises_rather_than_clipping_when_generation_exceeds_capacity(self, raw_df):
        """
        A ratio above 1 means the population assumption broke - that must
        surface loudly, not get clipped into a plausible-looking number.
        """
        tiny = pd.DataFrame(
            [
                {"subsystem": s, "carrier": "hydro", "p_nom_mw": 1.0}
                for s in ["N", "NE", "S", "SE_CO"]
            ]
        )
        with pytest.raises(ValueError, match="exceeds installed capacity"):
            build_hydro.build_hydro_availability(raw_df, tiny)

    def test_raises_when_a_subsystem_has_generation_but_no_capacity(self, raw_df):
        incomplete = pd.DataFrame([{"subsystem": "N", "carrier": "hydro", "p_nom_mw": 22089.8}])
        with pytest.raises(ValueError, match="no capacity"):
            build_hydro.build_hydro_availability(raw_df, incomplete)


class TestWriteHydroAvailability:
    def test_round_trips_through_csv(self, raw_df, capacity, tmp_path):
        tidy = build_hydro.build_hydro_availability(raw_df, capacity)
        out = build_hydro.write_hydro_availability(tidy, tmp_path / "hydro_availability_t0.csv")

        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(tidy)
        assert list(reloaded.columns) == ["snapshot", "subsystem", "carrier", "p_max_pu"]
