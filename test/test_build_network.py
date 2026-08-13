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


@pytest.fixture
def tidy_costs():
    # Must reference generators that actually exist in `tidy_generators`
    # (SE_CO hydro, SE_CO thermal, S wind) - only SE_CO has a thermal row.
    return pd.DataFrame(
        [
            {"subsystem": "SE_CO", "carrier": "thermal", "marginal_cost": 650.0},
        ]
    )


class TestAttachMarginalCosts:
    def test_thermal_generators_get_the_cvu_value(self, tidy_demand, tidy_generators, tidy_costs):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)
        build_network.attach_marginal_costs(n, tidy_costs)

        assert n.generators.loc["SE_CO thermal", "marginal_cost"] == pytest.approx(650.0)

    def test_non_thermal_generators_get_the_explicit_default(
        self, tidy_demand, tidy_generators, tidy_costs
    ):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)
        build_network.attach_marginal_costs(n, tidy_costs)

        assert n.generators.loc["SE_CO hydro", "marginal_cost"] == pytest.approx(
            build_network.NON_THERMAL_MARGINAL_COST
        )
        assert n.generators.loc["S wind", "marginal_cost"] == pytest.approx(
            build_network.NON_THERMAL_MARGINAL_COST
        )

    def test_raises_when_a_cost_row_has_no_matching_generator(
        self, tidy_demand, tidy_generators, tidy_costs
    ):
        bad = pd.concat(
            [
                tidy_costs,
                pd.DataFrame([{"subsystem": "N", "carrier": "thermal", "marginal_cost": 1.0}]),
            ],
            ignore_index=True,
        )
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)  # tidy_generators has no N thermal row
        with pytest.raises(ValueError, match="no matching generator"):
            build_network.attach_marginal_costs(n, bad)

    def test_passes_consistency_check_after_attaching(
        self, tidy_demand, tidy_generators, tidy_costs
    ):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)
        build_network.attach_marginal_costs(n, tidy_costs)
        n.consistency_check()  # must not raise


@pytest.fixture
def tidy_links():
    return pd.DataFrame(
        [
            {"bus0": "N", "bus1": "NE", "p_nom_mw": 100.0},
            {"bus0": "N", "bus1": "SE_CO", "p_nom_mw": 200.0},
            {"bus0": "NE", "bus1": "SE_CO", "p_nom_mw": 300.0},
            {"bus0": "SE_CO", "bus1": "S", "p_nom_mw": 400.0},
        ]
    )


class TestAttachLinks:
    def test_adds_one_link_per_row(self, tidy_demand, tidy_links):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_links(n, tidy_links)
        assert len(n.links) == 4

    def test_link_values_are_correct(self, tidy_demand, tidy_links):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_links(n, tidy_links)

        link = n.links.loc["N-NE"]
        assert link["bus0"] == "N"
        assert link["bus1"] == "NE"
        assert link["p_nom"] == pytest.approx(100.0)

    def test_links_are_bidirectional(self, tidy_demand, tidy_links):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_links(n, tidy_links)
        assert (n.links["p_min_pu"] == -1.0).all()

    def test_raises_on_a_link_bus_with_no_matching_bus(self, tidy_demand, tidy_links):
        bad = pd.concat(
            [tidy_links, pd.DataFrame([{"bus0": "S", "bus1": "ISOLATED_RR", "p_nom_mw": 1.0}])],
            ignore_index=True,
        )
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        with pytest.raises(ValueError, match="no matching bus"):
            build_network.attach_links(n, bad)

    def test_passes_consistency_check(self, tidy_demand, tidy_links):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_links(n, tidy_links)
        n.consistency_check()  # must not raise


@pytest.fixture
def tidy_availability():
    # Matches tidy_generators' "S wind" row and tidy_demand's 3 snapshots.
    snapshots = pd.date_range("2024-01-01", periods=3, freq="1h")
    return pd.DataFrame(
        [
            {"snapshot": snapshots[0], "subsystem": "S", "carrier": "wind", "p_max_pu": 0.1},
            {"snapshot": snapshots[1], "subsystem": "S", "carrier": "wind", "p_max_pu": 0.5},
            {"snapshot": snapshots[2], "subsystem": "S", "carrier": "wind", "p_max_pu": 0.9},
        ]
    )


class TestAttachAvailability:
    def test_sets_p_max_pu_for_the_covered_generator(
        self, tidy_demand, tidy_generators, tidy_availability
    ):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)
        build_network.attach_availability(n, tidy_availability)

        p_max_pu = n.get_switchable_as_dense("Generator", "p_max_pu")["S wind"]
        assert p_max_pu.tolist() == pytest.approx([0.1, 0.5, 0.9])

    def test_uncovered_generators_keep_the_pypsa_default(
        self, tidy_demand, tidy_generators, tidy_availability
    ):
        """SE_CO hydro has no availability row - must stay at PyPSA's default of 1.0."""
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)
        build_network.attach_availability(n, tidy_availability)

        p_max_pu = n.get_switchable_as_dense("Generator", "p_max_pu")["SE_CO hydro"]
        assert (p_max_pu == 1.0).all()

    def test_raises_when_a_row_has_no_matching_generator(
        self, tidy_demand, tidy_generators, tidy_availability
    ):
        bad = pd.concat(
            [
                tidy_availability,
                pd.DataFrame(
                    [
                        {
                            "snapshot": tidy_demand["snapshot"].iloc[0],
                            "subsystem": "N",
                            "carrier": "solar",
                            "p_max_pu": 0.5,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)  # no "N solar" generator
        with pytest.raises(ValueError, match="no matching generator"):
            build_network.attach_availability(n, bad)

    def test_raises_on_a_gap_after_aligning_to_snapshots(
        self, tidy_demand, tidy_generators, tidy_availability
    ):
        gappy = tidy_availability.iloc[:-1]  # drop the last snapshot's row
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)
        with pytest.raises(ValueError, match="gaps"):
            build_network.attach_availability(n, gappy)

    def test_passes_consistency_check(self, tidy_demand, tidy_generators, tidy_availability):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)
        build_network.attach_availability(n, tidy_availability)
        n.consistency_check()  # must not raise


class TestAttachLoadShedding:
    def test_adds_one_generator_per_subsystem(self, tidy_demand):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_load_shedding(n, subsystems=SUBSYSTEMS)

        shed = n.generators[n.generators["carrier"] == "load_shedding"]
        assert sorted(shed["bus"]) == sorted(SUBSYSTEMS)

    def test_cost_is_above_any_real_generator_cost(self, tidy_demand, tidy_generators, tidy_costs):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_generators(n, tidy_generators)
        build_network.attach_marginal_costs(n, tidy_costs)
        build_network.attach_load_shedding(n, subsystems=SUBSYSTEMS)

        real_costs = n.generators.loc[n.generators["carrier"] != "load_shedding", "marginal_cost"]
        assert build_network.LOAD_SHED_COST > real_costs.max()

    def test_registers_the_carrier(self, tidy_demand):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_load_shedding(n, subsystems=SUBSYSTEMS)
        assert "load_shedding" in n.carriers.index

    def test_passes_consistency_check(self, tidy_demand):
        n = build_network.build_network(tidy_demand, subsystems=SUBSYSTEMS)
        build_network.attach_load_shedding(n, subsystems=SUBSYSTEMS)
        n.consistency_check()  # must not raise
