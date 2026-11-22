# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
T1 by clustering T3 (ADR-0026 decision 4): every T3 bus on the main AC
island goes to its (state, subsystem) node - `{state}` when the subsystem
is the state's main one, `{state}_{subsystem}` otherwise (Itaipu's side of
PR is PR_SE_CO) - and PyPSA merges buses, lines, links, loads and
generators per node.

Generators are merged per node by their T0 type (the name after the bus:
`thermal_b3`, `hydro_small`, ...), not by carrier, so ADR-0021's thermal
cost bands survive; the carrier is restored afterwards. A node's main
subsystem is the one most of its T3 load and capacity sits in; with the
node rule that is the node's own subsystem by construction.

EPE-derived, so local only: input and output under resources/epe/.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
import sys
from pathlib import Path

import pandas as pd
import pypsa
from pypsa.clustering.spatial import get_clustering_from_busmap

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_network_t3 import main_component


def node_of(buses: pd.DataFrame) -> pd.Series:
    """bus -> T1 node name. A state's main subsystem is where most of its
    buses are."""
    main = buses.groupby("state")["subsystem"].agg(lambda s: s.value_counts().idxmax())
    name = buses["state"].where(
        buses["subsystem"] == buses["state"].map(main), buses["state"] + "_" + buses["subsystem"]
    )
    return name


def keep_substations_whole(t3: pypsa.Network, busmap: pd.Series) -> pd.Series:
    """Buses joined by a transformer are one substation: give every bus of a
    transformer-connected group the node of the group's highest-voltage bus.
    Without this, 116 transformers (unrated) joined buses of different
    nodes and made those corridors unlimited."""
    import networkx as nx

    tr = t3.lines[t3.lines["kind"] == "transformer"]
    g = nx.Graph()
    g.add_nodes_from(t3.buses.index)
    g.add_edges_from(zip(tr["bus0"], tr["bus1"], strict=True))
    out = busmap.copy()
    v = t3.buses["v_nom"].where(t3.buses["v_nom"] < 900, 0)  # 999 kV marks fictitious buses
    for group in nx.connected_components(g):
        if len(group) > 1:
            members = list(group)
            out.loc[members] = busmap.loc[v.loc[members].idxmax()]
    return out


def rate_unrated_lines(t3: pypsa.Network, unlimited: float = 1.0e5) -> int:
    """EPE's 99999 placeholder was read as no limit (PR-75). Between nodes
    that makes a corridor unlimited, so an unrated line gets the median
    rating of rated lines of its voltage class. Returns how many."""
    lines = t3.lines[t3.lines["kind"] == "line"]
    kv = lines["bus0"].map(t3.buses["v_nom"])
    rated = lines["s_nom"] < unlimited
    median = lines[rated].groupby(kv[rated])["s_nom"].median()
    fill = ~rated & kv.isin(median.index)
    t3.lines.loc[fill[fill].index, "s_nom"] = kv[fill].map(median).to_numpy()
    return int(fill.sum())


COMMON_KV = 500.0


def to_common_base(t3: pypsa.Network) -> None:
    """Refer every line to one voltage before clustering. A line's x and r
    are ohm at bus0's voltage, and PyPSA's linear power flow uses
    x / v_nom(bus0)^2; merged buses take one v_nom (often EPE's fictitious
    999 kV), which corrupted merged reactances (111,668 ohm at first try).
    Keeping x_pu and setting every bus to COMMON_KV leaves the DC power flow
    unchanged and the merge consistent."""
    v0 = t3.lines["bus0"].map(t3.buses["v_nom"])
    for attr in ("x", "r"):
        t3.lines[attr] = t3.lines[attr] / v0**2 * COMMON_KV**2
    t3.buses["v_nom"] = COMMON_KV


def node_subsystem(node: str, main: pd.Series) -> str:
    """A node's subsystem from its name: `{state}_{subsystem}`, else the
    state's main subsystem."""
    state, _, sub = node.partition("_")
    return sub if sub else main[state]


def cluster(t3: pypsa.Network) -> tuple[pypsa.Network, dict]:
    main = main_component(t3)  # lines and HVDC (PR-77)
    off = t3.buses.index.difference(main)
    t3.remove("Bus", off)
    for c in ("Line", "Link"):
        df = t3.static(c)
        t3.remove(c, df.index[df["bus0"].isin(off) | df["bus1"].isin(off)])
    for c in ("Generator", "Load"):
        df = t3.static(c)
        t3.remove(c, df.index[df["bus"].isin(off)])

    busmap = keep_substations_whole(t3, node_of(t3.buses))
    rated_by_class = rate_unrated_lines(t3)
    kind = t3.generators.index.str.split(" ", n=1).str[1]
    carrier_of_kind = dict(zip(kind, t3.generators["carrier"], strict=True))
    t3.generators["carrier"] = kind
    for k in set(kind) - set(t3.carriers.index):
        t3.add("Carrier", k)
    t3.lines["length"] = 1.0  # EPE gives no lengths; aggregation weights need a value
    # Clustering merges parallel lines between two nodes and refuses extra
    # columns that disagree (a line and a transformer between the same nodes).
    transformers_between_nodes = int(
        (
            (t3.lines["kind"] == "transformer")
            & (t3.lines["bus0"].map(busmap) != t3.lines["bus1"].map(busmap))
        ).sum()
    )
    t3.lines = t3.lines.drop(columns=["kind"])
    meta = t3.buses[["state", "subsystem"]].copy()  # may disagree inside a node
    main = meta.groupby("state")["subsystem"].agg(lambda s: s.value_counts().idxmax())
    to_common_base(t3)
    t3.buses = t3.buses.drop(columns=["state", "subsystem"])

    # Parallel combination, no length scaling: PyPSA would rescale x by the
    # distance between cluster centres over the original length, which EPE
    # does not give (and half the coordinates are approximate).
    def parallel(s: pd.Series) -> float:
        return float(1.0 / (1.0 / s).sum())

    clustering = get_clustering_from_busmap(
        t3,
        busmap,
        aggregate_generators_weighted=True,
        aggregate_one_ports={"Load"},
        line_strategies={"x": parallel, "r": parallel},
    )
    n = clustering.n
    # A merged equivalent through series capacitors can come out non-positive,
    # which a DC power flow cannot use; give it 0.01 pu and count it.
    floor_x = 0.01 * COMMON_KV**2 / 100.0
    nonpositive_x = int((n.lines["x"] <= 0).sum())
    n.lines["x"] = n.lines["x"].where(n.lines["x"] > 0, floor_x)
    n.generators["carrier"] = n.generators["carrier"].map(carrier_of_kind)
    n.buses["subsystem"] = [node_subsystem(b, main) for b in n.buses.index]
    n.buses["state"] = n.buses.index.str.split("_").str[0]
    sub = n.buses["subsystem"]
    cross = n.lines[n.lines["bus0"].map(sub) != n.lines["bus1"].map(sub)]
    report = {
        "t3_buses_off_the_main_grid": len(off),
        "transformers_between_nodes": transformers_between_nodes,
        "unrated_lines_given_class_median": rated_by_class,
        "nodes": len(n.buses),
        "lines": len(n.lines),
        "links": len(n.links),
        "generators": len(n.generators),
        "inter_subsystem_lines": len(cross),
        "inter_subsystem_line_capacity_mva": {
            k: round(float(v))
            for k, v in cross["s_nom"]
            .clip(upper=1e5)
            .groupby(
                [
                    "-".join(sorted([a, b]))
                    for a, b in zip(cross["bus0"].map(sub), cross["bus1"].map(sub), strict=True)
                ]
            )
            .sum()
            .items()
        },
        "nonpositive_x_lines_floored": nonpositive_x,
        "capacity_mw_by_carrier": n.generators.groupby("carrier")["p_nom"].sum().round(0).to_dict(),
    }
    return n, report


def main() -> None:
    snake = globals()["snakemake"]
    n, report = cluster(pypsa.Network(str(snake.input.network)))
    n.export_to_netcdf(str(snake.output.network))
    pd.DataFrame(
        {"node": n.buses.index, "state": n.buses["state"], "subsystem": n.buses["subsystem"]}
    ).to_csv(snake.output.nodes, index=False)
    Path(snake.output.report).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
