# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the bare T0 network: one bus per subsystem, snapshots from config, and
the tidy demand series PR-05 built, attached as time-varying loads.

Deliberately bare. No generators, no lines, no solver. Those are separate
concerns for separate PRs (see docs/handoffs/PR-06-*.md) - this PR only
proves buses and load attach correctly and the network survives a round
trip through NetCDF, which is the artifact every later PR builds on.
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


def write_network(n: pypsa.Network, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(str(out_path))
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    demand = load_demand(Path(snake.input.demand))
    n = build_network(demand, subsystems=list(snake.params.subsystems))
    write_network(n, Path(snake.output[0]))


if __name__ == "__main__":
    main()
