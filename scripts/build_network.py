# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the T0 network: one bus per subsystem, snapshots from config, the tidy
demand series (PR-05) attached as time-varying loads, the aggregated
generator capacity (PR-08) attached as one Generator per (subsystem,
technology), a `marginal_cost` on every generator (PR-10) - CVU-derived for
thermal, an explicit documented default for everything else - and a
load-shedding slack generator per bus (PR-11) so the network is solvable
despite having no transmission lines yet.

Still no lines, no availability profile: see docs/handoffs/PR-11-*.md for
exactly what is and isn't here yet, and why the marginal costs and the
load-shedding usage are both a real simplification worth reading before
trusting a dispatch result.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd
import pypsa

sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_demand(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["snapshot"])


def wide_demand(demand: pd.DataFrame, *, subsystems: list[str]) -> pd.DataFrame:
    """One column per subsystem, one row per snapshot - what `n.add("Load", ...)` wants."""
    missing = set(subsystems) - set(demand["subsystem"])
    if missing:
        raise ValueError(f"demand series is missing configured subsystem(s): {sorted(missing)}")

    wide = demand.pivot(index="snapshot", columns="subsystem", values="load_mw").sort_index()
    wide = wide[subsystems]
    if wide.isna().any().any():
        raise ValueError("demand series has gaps after pivoting to wide form")
    return wide


def build_network(demand: pd.DataFrame, *, subsystems: list[str]) -> pypsa.Network:
    wide = wide_demand(demand, subsystems=subsystems)

    n = pypsa.Network()
    n.set_snapshots(wide.index)

    # Buses reference a carrier by name; PyPSA only resolves it against
    # n.carriers, which n.add("Bus", carrier=...) does not populate itself.
    # Skipping this passes consistency_check() (it only warns) but leaves the
    # carrier's own attributes (color, nice_name, ...) undefined.
    n.add("Carrier", "AC")
    for subsystem in subsystems:
        n.add("Bus", subsystem, carrier="AC")

    n.add("Load", subsystems, bus=subsystems, p_set=wide[subsystems])

    n.consistency_check()
    return n


def load_generators(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def attach_generators(n: pypsa.Network, generators: pd.DataFrame) -> pypsa.Network:
    """
    Add one Generator per (subsystem, technology) row: `p_nom` only.

    No `marginal_cost` (needs CVU for thermal, water value for hydro - both
    unbuilt) and no `p_max_pu` (needs atlite/ERA5 for renewables, also
    unbuilt) - both default to PyPSA's own defaults (0 and 1 respectively),
    which is a placeholder, not a modelling claim. Mutates `n` in place and
    returns it for convenience.
    """
    unknown_buses = set(generators["subsystem"]) - set(n.buses.index)
    if unknown_buses:
        raise ValueError(f"generator subsystem(s) have no matching bus: {sorted(unknown_buses)}")

    for carrier in generators["carrier"].unique():
        if carrier not in n.carriers.index:
            n.add("Carrier", carrier)

    names = (generators["subsystem"] + " " + generators["carrier"]).tolist()
    n.add(
        "Generator",
        names,
        bus=generators["subsystem"].to_numpy(),
        carrier=generators["carrier"].to_numpy(),
        p_nom=generators["p_nom_mw"].to_numpy(),
    )

    n.consistency_check()
    return n


def load_costs(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


# Every carrier this T0 network can produce that CVU does not cover, all get
# the same explicit value rather than PyPSA's implicit 0.0 default. Each is
# a real simplification, stated here instead of silently:
#   - hydro: true marginal cost is the water value, an opportunity cost that
#     has to be *computed* (PRIMER Sec 4), not looked up - unbuilt until
#     SDDP.jl lands. Treated as free/must-run in the interim, per the PR-08
#     handoff's own suggestion, now made an explicit decision rather than an
#     accident of the default.
#   - wind, solar: true marginal cost is genuinely near-zero (no fuel), so
#     0.0 is a defensible value here, not just a placeholder.
#   - nuclear: has a real but small fuel cost; approximated as a must-run
#     baseload at 0.0, the standard simplification at this level of detail.
NON_THERMAL_MARGINAL_COST = 0.0


def attach_marginal_costs(n: pypsa.Network, costs: pd.DataFrame) -> pypsa.Network:
    """
    Set `marginal_cost` (R$/MWh) on every generator: the CVU-derived value
    from `costs` for thermal, `NON_THERMAL_MARGINAL_COST` for everything
    else. Mutates `n` in place and returns it for convenience.
    """
    names = (costs["subsystem"] + " " + costs["carrier"]).tolist()
    unknown = set(names) - set(n.generators.index)
    if unknown:
        raise ValueError(
            f"cost row(s) have no matching generator in the network: {sorted(unknown)}"
        )

    n.generators["marginal_cost"] = NON_THERMAL_MARGINAL_COST
    n.generators.loc[names, "marginal_cost"] = costs["marginal_cost"].to_numpy()

    return n


# Every bus gets an always-available slack generator so the network is
# solvable at all despite having no transmission lines: with real 2024 data,
# S's own generator capacity falls short of S's own peak demand in 2 of
# 8784 hours (267 MWh/year total, see docs/handoffs/PR-11-*.md) - with no
# lines to import NE's 41 GW of spare capacity, that makes the network
# infeasible without a slack. LOAD_SHED_COST is not a researched value-of-
# lost-load estimate - it is picked only to sit clearly above every real
# generator's marginal_cost (max observed thermal CVU: 3681.59 R$/MWh, see
# the cvu_usina_termica data dictionary) so load shedding is always the
# dispatch of last resort, never competitive in merit order. LOAD_SHED_P_NOM
# is effectively unlimited so shedding itself is never the binding
# constraint - the real constraint is every other generator's own p_nom.
LOAD_SHED_CARRIER = "load_shedding"
LOAD_SHED_COST = 10_000.0
LOAD_SHED_P_NOM = 1_000_000.0


def attach_load_shedding(n: pypsa.Network, *, subsystems: list[str]) -> pypsa.Network:
    """
    Add one always-available load-shedding generator per bus.

    Its dispatch is the honest signal for "no transmission lines yet": any
    nonzero load-shedding after a solve means that bus's own generators
    could not cover that bus's own demand at that hour, which real
    transmission would resolve by importing from a neighbouring subsystem.
    Mutates `n` in place and returns it for convenience.
    """
    if LOAD_SHED_CARRIER not in n.carriers.index:
        n.add("Carrier", LOAD_SHED_CARRIER)

    names = [f"{subsystem} {LOAD_SHED_CARRIER}" for subsystem in subsystems]
    n.add(
        "Generator",
        names,
        bus=subsystems,
        carrier=LOAD_SHED_CARRIER,
        p_nom=LOAD_SHED_P_NOM,
        marginal_cost=LOAD_SHED_COST,
    )

    n.consistency_check()
    return n


def write_network(n: pypsa.Network, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(str(out_path))
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    demand = load_demand(Path(snake.input.demand))
    n = build_network(demand, subsystems=list(snake.params.subsystems))

    generators = load_generators(Path(snake.input.generators))
    attach_generators(n, generators)

    costs = load_costs(Path(snake.input.costs))
    attach_marginal_costs(n, costs)

    attach_load_shedding(n, subsystems=list(snake.params.subsystems))

    write_network(n, Path(snake.output[0]))


if __name__ == "__main__":
    main()
