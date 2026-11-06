# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
T1 nodes and links (ADR-0022, decisions 1 and 1b).

Nodes are (state, subsystem) pairs holding at least NODE_MIN_SHARE of the
state's registry capacity: `{state}` for the state's main subsystem,
`{state}_{subsystem}` for a secondary one (PR's Itaipu side, PR_SE). Links
are DLR's operating corridors between main nodes, plus one dedicated link
per secondary node to its state's largest same-subsystem neighbour, sized
at the secondary node's capacity. Corridors to foreign nodes are dropped;
international flows enter as exports (PR-64).
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ons import map_subsystems

NODE_MIN_SHARE = 0.01
FOREIGN = {"ARG", "PRY", "URY", "VEN"}
CAPACITY_COLUMN = "val_potenciaefetiva"


def state_nodes(registry: pd.DataFrame) -> pd.DataFrame:
    """One row per node: node, state, subsystem, capacity_mw (active units),
    main. Shares use every registry row, deactivated ones included, so a state
    whose units are all retired (AC and DF today) still gets its main node:
    it has load."""
    mapped = map_subsystems(registry)
    active = mapped["dat_desativacao"].isna()
    by_pair = (
        mapped.assign(active_mw=mapped[CAPACITY_COLUMN].where(active, 0.0))
        .groupby(["id_estado", "subsystem"], as_index=False)[[CAPACITY_COLUMN, "active_mw"]]
        .sum()
        .rename(columns={"id_estado": "state", "active_mw": "capacity_mw"})
    )
    total = by_pair.groupby("state")[CAPACITY_COLUMN].transform("sum")
    by_pair["share"] = by_pair[CAPACITY_COLUMN] / total
    by_pair["main"] = by_pair["share"] == by_pair.groupby("state")["share"].transform("max")
    nodes = by_pair[(by_pair["share"] >= NODE_MIN_SHARE) | by_pair["main"]].copy()
    nodes["node"] = nodes["state"].where(nodes["main"], nodes["state"] + "_" + nodes["subsystem"])
    return (
        nodes[["node", "state", "subsystem", "capacity_mw", "main"]]
        .sort_values("node")
        .reset_index(drop=True)
    )


def corridors(grid: pd.DataFrame) -> pd.DataFrame:
    """Domestic DLR corridors, one row per unordered state pair (parallel
    rows summed, efficiency capacity-weighted)."""
    domestic = grid[~grid["node0"].isin(FOREIGN) & ~grid["node1"].isin(FOREIGN)].copy()
    pair = domestic[["node0", "node1"]].apply(sorted, axis=1, result_type="expand")
    domestic["a"], domestic["b"] = pair[0], pair[1]
    domestic["weighted"] = domestic["efficiency"] * domestic["transfer_capacity"]
    out = domestic.groupby(["a", "b"], as_index=False)[["transfer_capacity", "weighted"]].sum()
    out["efficiency"] = out.pop("weighted") / out["transfer_capacity"]
    return out.rename(columns={"transfer_capacity": "p_nom_mw"})


def t1_links(grid: pd.DataFrame, nodes: pd.DataFrame) -> pd.DataFrame:
    """bus0, bus1, p_nom_mw, efficiency, kind ('corridor' or 'dedicated')."""
    pairs = corridors(grid)
    main = nodes[nodes["main"]].set_index("state")
    missing = (set(pairs["a"]) | set(pairs["b"])) - set(main.index)
    if missing:
        raise ValueError(f"corridor state(s) with no node: {sorted(missing)}")
    links = pairs.assign(
        bus0=pairs["a"].map(main["node"]), bus1=pairs["b"].map(main["node"]), kind="corridor"
    )
    rows = [links[["bus0", "bus1", "p_nom_mw", "efficiency", "kind"]]]
    for _, sec in nodes[~nodes["main"]].iterrows():
        touching = pairs[(pairs["a"] == sec["state"]) | (pairs["b"] == sec["state"])]
        other = touching["a"].where(touching["a"] != sec["state"], touching["b"])
        same = touching[other.map(main["subsystem"]) == sec["subsystem"]]
        if same.empty:
            raise ValueError(f"{sec['node']}: no neighbour in subsystem {sec['subsystem']}")
        best = same.loc[same["p_nom_mw"].idxmax()]
        neighbour = best["a"] if best["a"] != sec["state"] else best["b"]
        rows.append(
            pd.DataFrame(
                [
                    {
                        "bus0": sec["node"],
                        "bus1": main.at[neighbour, "node"],
                        "p_nom_mw": float(sec["capacity_mw"]),
                        "efficiency": float(best["efficiency"]),
                        "kind": "dedicated",
                    }
                ]
            )
        )
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    snake = globals()["snakemake"]
    registry = pd.read_csv(snake.input.registry, sep=";")
    nodes = state_nodes(registry)
    links = t1_links(pd.read_csv(snake.input.grid), nodes)
    Path(snake.output.nodes).parent.mkdir(parents=True, exist_ok=True)
    nodes.to_csv(snake.output.nodes, index=False)
    links.to_csv(snake.output.links, index=False)


if __name__ == "__main__":
    main()
