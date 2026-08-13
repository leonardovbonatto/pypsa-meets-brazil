# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""Tests for the bare T0 network: buses, snapshots, and time-varying loads."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SUBSYSTEMS = ["SE_CO", "S", "NE", "N"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_network = _load("build_network", REPO_ROOT / "scripts" / "build_network.py")


@pytest.fixture
def tidy_demand():
    """3 hours x 4 subsystems, small and hand-computable rather than a big fixture."""
    snapshots = pd.date_range("2024-01-01", periods=3, freq="1h")
    rows = [
        {"snapshot": ts, "subsystem": s, "load_mw": float(i * 10 + j)}
        for i, ts in enumerate(snapshots)
        for j, s in enumerate(SUBSYSTEMS)
    ]
    return pd.DataFrame(rows)


class TestWideDemand:
    def test_pivots_to_one_column_per_subsystem(self, tidy_demand):
        wide = build_network.wide_demand(tidy_demand, subsystems=SUBSYSTEMS)
        assert list(wide.columns) == SUBSYSTEMS
        assert len(wide) == 3

    def test_raises_when_a_configured_subsystem_is_absent(self, tidy_demand):
        with pytest.raises(ValueError, match="missing"):
            build_network.wide_demand(tidy_demand, subsystems=[*SUBSYSTEMS, "ISOLATED_RR"])

    def test_raises_on_gaps_after_pivot(self, tidy_demand):
        gappy = tidy_demand.drop(index=0)  # drops one (snapshot, subsystem) cell
        with pytest.raises(ValueError, match="gaps"):
            build_network.wide_demand(gappy, subsystems=SUBSYSTEMS)


class TestBuildNetwork:
    def test_has_one_bus_per_subsystem(self, tidy_demand):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        assert sorted(n.buses.index) == sorted(SUBSYSTEMS)

    def test_snapshots_match_the_demand_series(self, tidy_demand):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        assert len(n.snapshots) == 3
        assert n.snapshots[0] == pd.Timestamp("2024-01-01 00:00:00")

    def test_one_load_per_bus_with_correct_values(self, tidy_demand):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        assert sorted(n.loads.index) == sorted(SUBSYSTEMS)
        assert (n.loads["bus"].sort_index() == n.loads.index.sort_values()).all()

        # subsystem index j=0 in the fixture is SE_CO; hour i=1 -> load 10 + 0 = 10.
        assert n.loads_t.p_set.loc[pd.Timestamp("2024-01-01 01:00:00"), "SE_CO"] == 10.0

    def test_passes_pypsa_consistency_check(self, tidy_demand):
        # build_network() already calls this; re-run explicitly so a future
        # refactor that drops the call still gets caught here.
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        n.consistency_check()  # must not raise

    def test_carrier_is_registered_not_just_referenced(self, tidy_demand):
        """
        consistency_check() only *warns* on a bus referencing an undefined
        carrier - it does not raise. Caught once for real: buses came out
        pointing at carrier="AC" with no matching row in n.carriers, which
        passed consistency_check() silently in the log but left the carrier's
        own attributes (color, nice_name, ...) undefined.
        """
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        assert "AC" in n.carriers.index
        assert set(n.buses["carrier"]) == {"AC"}


class TestWriteNetwork:
    def test_round_trips_through_netcdf(self, tidy_demand, tmp_path):
        import pypsa

        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        out = build_network.write_network(n, tmp_path / "t0.nc")

        reloaded = pypsa.Network(str(out))
        assert sorted(reloaded.buses.index) == sorted(SUBSYSTEMS)
        assert reloaded.loads_t.p_set.equals(n.loads_t.p_set)
        assert len(reloaded.snapshots) == len(n.snapshots)


@pytest.fixture
def tidy_generators():
    return pd.DataFrame(
        [
            {"subsystem": "SE_CO", "carrier": "hydro", "p_nom_mw": 100.0},
            {"subsystem": "SE_CO", "carrier": "thermal", "p_nom_mw": 50.0},
            {"subsystem": "S", "carrier": "wind", "p_nom_mw": 25.0},
        ]
    )


class TestAttachGenerators:
    def test_adds_one_generator_per_row(self, tidy_demand, tidy_generators):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)
        assert len(n.generators) == 3

    def test_generator_values_are_correct(self, tidy_demand, tidy_generators):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)

        gen = n.generators.loc["SE_CO hydro"]
        assert gen["bus"] == "SE_CO"
        assert gen["carrier"] == "hydro"
        assert gen["p_nom"] == pytest.approx(100.0)

    def test_registers_every_carrier(self, tidy_demand, tidy_generators):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)
        assert {"hydro", "thermal", "wind"} <= set(n.carriers.index)

    def test_raises_on_a_generator_bus_with_no_matching_bus(self, tidy_demand, tidy_generators):
        bad = pd.concat(
            [
                tidy_generators,
                pd.DataFrame([{"subsystem": "ISOLATED_RR", "carrier": "hydro", "p_nom_mw": 1.0}]),
            ],
            ignore_index=True,
        )
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        with pytest.raises(ValueError, match="no matching bus"):
            build_network.attach_generators(n, bad)

    def test_passes_consistency_check_after_attaching(self, tidy_demand, tidy_generators):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)
        n.consistency_check()  # must not raise
