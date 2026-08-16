# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for the MMGD (distributed PV) capacity and availability backcast."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "geracao_usina.yaml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_mmgd = _load("build_mmgd", REPO_ROOT / "scripts" / "build_mmgd.py")


@pytest.fixture
def raw_df():
    """
    Hand-built rather than a carved fixture: the committed geracao_usina
    sample has no MMGD rows, and the arithmetic here needs to be checkable
    by eye. Column names and values match the real dataset's conventions.
    """
    rows = []
    for hour, (n_gen, se_gen) in enumerate([(0.0, 0.0), (50.0, 200.0), (100.0, 150.0)]):
        ts = f"2024-01-01 {hour:02d}:00:00"
        rows += [
            {
                "din_instante": ts,
                "id_subsistema": "N",
                "cod_modalidadeoperacao": "Pequenas Usinas (MMGD)",
                "nom_tipousina": "FOTOVOLTAICA",
                "val_geracao": n_gen,
            },
            {
                "din_instante": ts,
                "id_subsistema": "SE",
                "cod_modalidadeoperacao": "Pequenas Usinas (MMGD)",
                "nom_tipousina": "FOTOVOLTAICA",
                "val_geracao": se_gen,
            },
            # a non-MMGD row that must be filtered out
            {
                "din_instante": ts,
                "id_subsistema": "SE",
                "cod_modalidadeoperacao": "TIPO I",
                "nom_tipousina": "HIDROELÉTRICA",
                "val_geracao": 9999.0,
            },
        ]
    return pd.DataFrame(rows)


class TestFilterMmgd:
    def test_keeps_only_mmgd_rows(self, raw_df):
        filtered = build_mmgd.filter_mmgd(raw_df)
        assert set(filtered["cod_modalidadeoperacao"]) == {"Pequenas Usinas (MMGD)"}
        assert len(filtered) == 6


class TestBuildMmgdCapacity:
    def test_p_nom_is_the_observed_peak(self, raw_df):
        capacity = build_mmgd.build_mmgd_capacity(raw_df).set_index("subsystem")
        assert capacity.loc["N", "p_nom_mw"] == pytest.approx(100.0)
        assert capacity.loc["SE_CO", "p_nom_mw"] == pytest.approx(200.0)

    def test_carrier_is_distinct_from_utility_solar(self, raw_df):
        capacity = build_mmgd.build_mmgd_capacity(raw_df)
        assert set(capacity["carrier"]) == {"solar_mmgd"}

    def test_se_becomes_se_co(self, raw_df):
        capacity = build_mmgd.build_mmgd_capacity(raw_df)
        assert "SE_CO" in set(capacity["subsystem"])
        assert "SE" not in set(capacity["subsystem"])

    def test_excludes_non_mmgd_generation(self, raw_df):
        """The 9999 MW hydro row must not leak into MMGD capacity."""
        capacity = build_mmgd.build_mmgd_capacity(raw_df)
        assert capacity["p_nom_mw"].max() == pytest.approx(200.0)


class TestBuildMmgdAvailability:
    def test_ratio_is_generation_over_peak(self, raw_df):
        capacity = build_mmgd.build_mmgd_capacity(raw_df)
        avail = build_mmgd.build_mmgd_availability(raw_df, capacity)

        se = avail[avail["subsystem"] == "SE_CO"].sort_values("snapshot")["p_max_pu"].tolist()
        # SE peak is 200 -> 0/200, 200/200, 150/200
        assert se == pytest.approx([0.0, 1.0, 0.75])

    def test_stays_within_the_unit_interval(self, raw_df):
        capacity = build_mmgd.build_mmgd_capacity(raw_df)
        avail = build_mmgd.build_mmgd_availability(raw_df, capacity)
        assert avail["p_max_pu"].between(0.0, 1.0).all()

    def test_raises_if_the_denominator_is_wrong(self, raw_df):
        """A too-small p_nom would push p_max_pu above 1 - must fail loudly."""
        bad = pd.DataFrame(
            [
                {"subsystem": "N", "carrier": "solar_mmgd", "p_nom_mw": 1.0},
                {"subsystem": "SE_CO", "carrier": "solar_mmgd", "p_nom_mw": 1.0},
            ]
        )
        with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
            build_mmgd.build_mmgd_availability(raw_df, bad)

    def test_columns_match_what_attach_availability_expects(self, raw_df):
        capacity = build_mmgd.build_mmgd_capacity(raw_df)
        avail = build_mmgd.build_mmgd_availability(raw_df, capacity)
        assert list(avail.columns) == ["snapshot", "subsystem", "carrier", "p_max_pu"]
