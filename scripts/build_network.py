# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the T0 network: one bus per subsystem, snapshots from config, the tidy
demand series (PR-05) attached as time-varying loads, and the aggregated
generator capacity (PR-08) attached as one Generator per (subsystem,
technology).

Still no lines, no marginal cost, no availability profile, no solver -
capacity and topology only. `n.optimize()` is still not callable: see
docs/handoffs/PR-08-*.md for exactly what is and isn't here yet.
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

    write_network(n, Path(snake.output[0]))


if __name__ == "__main__":
    main()
