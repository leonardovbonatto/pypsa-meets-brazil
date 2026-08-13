# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for aggregating raw ONS interchange data into the T0 transfer-capacity table."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "test" / "fixtures" / "ons" / "intercambio_nacional_sample.csv"
DICTIONARY = REPO_ROOT / "docs" / "data-dictionary" / "ons" / "intercambio_nacional.yaml"
SUBSYSTEMS = ["SE_CO", "S", "NE", "N"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_links = _load("build_links", REPO_ROOT / "scripts" / "build_links.py")


@pytest.fixture
def raw_df():
    return build_links.load_raw([FIXTURE])


class TestLoadRaw:
    def test_reads_the_real_fixture(self, raw_df):
        # 24 hours x 4 real boundaries.
        assert len(raw_df) == 96


class TestValidateAgainstDictionary:
    def test_accepts_real_fixture(self, raw_df):
        build_links.validate_against_dictionary(raw_df, DICTIONARY)  # must not raise


class TestBuildLinkCapacity:
    def test_columns_and_row_count(self, raw_df):
        tidy = build_links.build_link_capacity(raw_df, subsystems=SUBSYSTEMS)
        assert list(tidy.columns) == ["bus0", "bus1", "p_nom_mw"]
        assert len(tidy) == 4  # the four real boundaries

    def test_capacity_is_the_max_absolute_flow(self, raw_df):
        """
        Hand-computed from the fixture: max(abs(val_intercambiomwmed)) per
        boundary over the fixture's 24 hours. Confirms the function takes
        abs() before max(), not max() of the signed value.
        """
        tidy = build_links.build_link_capacity(raw_df, subsystems=SUBSYSTEMS).set_index(
            ["bus0", "bus1"]
        )
        assert tidy.loc[("N", "NE"), "p_nom_mw"] == pytest.approx(3107.705)
        assert tidy.loc[("N", "SE_CO"), "p_nom_mw"] == pytest.approx(4065.920)
        assert tidy.loc[("NE", "SE_CO"), "p_nom_mw"] == pytest.approx(3110.510)
        assert tidy.loc[("SE_CO", "S"), "p_nom_mw"] == pytest.approx(5195.297)

    def test_se_becomes_se_co_on_both_sides(self, raw_df):
        tidy = build_links.build_link_capacity(raw_df, subsystems=SUBSYSTEMS)
        assert "SE" not in set(tidy["bus0"]) | set(tidy["bus1"])
        assert "SE_CO" in set(tidy["bus0"]) | set(tidy["bus1"])

    def test_topology_has_no_direct_n_s_or_ne_s_boundary(self, raw_df):
        """The real SIN topology is a triangle plus a pendant, not a complete graph."""
        tidy = build_links.build_link_capacity(raw_df, subsystems=SUBSYSTEMS)
        pairs = set(zip(tidy["bus0"], tidy["bus1"], strict=True))
        assert ("N", "S") not in pairs
        assert ("S", "N") not in pairs
        assert ("NE", "S") not in pairs
        assert ("S", "NE") not in pairs

    def test_raises_when_a_configured_subsystem_has_no_link(self, raw_df):
        with pytest.raises(ValueError, match="no link"):
            build_links.build_link_capacity(raw_df, subsystems=[*SUBSYSTEMS, "ISOLATED_RR"])


class TestWriteLinkCapacity:
    def test_round_trips_through_csv(self, raw_df, tmp_path):
        import pandas as pd

        tidy = build_links.build_link_capacity(raw_df, subsystems=SUBSYSTEMS)
        out = build_links.write_link_capacity(tidy, tmp_path / "links_t0.csv")

        reloaded = pd.read_csv(out)
        assert len(reloaded) == len(tidy)
        assert list(reloaded.columns) == ["bus0", "bus1", "p_nom_mw"]
