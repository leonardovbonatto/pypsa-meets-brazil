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


JUMPER_X_PU = 1.0e-3  # on 100 MVA; EPE writes busbar ties as x = 0.001 %


def substation_branches(t3: pypsa.Network) -> pd.Index:
    """Branches whose two ends are one substation: transformers, jumpers
    (|x| below JUMPER_X_PU, EPE's busbar ties) and series capacitors
    (x < 0). PR-78: single 69/138 kV jumpers across a state border became
    inter-node lines of near-zero reactance and 54-126 MVA, which a DC
    power flow loads first, blocking the Northeast's exports."""
    kv = t3.lines["bus0"].map(t3.buses["v_nom"])
    x_pu = t3.lines["x"] * 100.0 / kv**2
    keep = (t3.lines["kind"] == "transformer") | (x_pu.abs() < JUMPER_X_PU) | (x_pu < 0)
    return t3.lines.index[keep]


def keep_substations_whole(t3: pypsa.Network, busmap: pd.Series) -> pd.Series:
    """Buses joined by a substation branch (transformer, jumper, series
    capacitor) are one substation: every bus of such a group takes the node
    of the group's highest-voltage buses (ties: the node most of them
    are in, then by name). Without this, 116
    transformers (unrated) joined buses of different nodes and made those
    corridors unlimited."""
    import networkx as nx

    tr = t3.lines.loc[substation_branches(t3)]
    g = nx.Graph()
    g.add_nodes_from(t3.buses.index)
    g.add_edges_from(zip(tr["bus0"], tr["bus1"], strict=True))
    out = busmap.copy()
    v = t3.buses["v_nom"].where(t3.buses["v_nom"] < 900, 0)  # 999 kV marks fictitious buses
    for group in nx.connected_components(g):
        if len(group) > 1:
            members = sorted(group)  # set order varies between runs
            vm = v.loc[members]
            top = busmap.loc[vm.index[vm == vm.max()]]
            counts = top.value_counts()
            out.loc[members] = sorted(counts.index[counts == counts.max()])[0]
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

# PR-78 (b), adopted: drop inter-node branches below this voltage where a
# corridor at or above it joins the same nodes (0 = keep all).
MIN_TIE_KV = 230.0


def low_voltage_ties(t3: pypsa.Network, busmap: pd.Series, min_kv: float) -> pd.Index:
    """Lines joining two nodes below min_kv, only where the same two nodes
    are also joined at min_kv or above (so no node is cut off)."""
    lines = t3.lines
    n0, n1 = lines["bus0"].map(busmap), lines["bus1"].map(busmap)
    pair = pd.Series(["-".join(sorted(p)) for p in zip(n0, n1, strict=True)], index=lines.index)
    kv = lines["bus0"].map(t3.buses["v_nom"])
    between = n0 != n1
    high_pairs = set(pair[between & (kv >= min_kv)])
    low = between & (kv < min_kv) & pair.isin(high_pairs)
    return lines.index[low]


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


# PR-78 (c), adopted: fit each inter-node reactance to T3's own power flow.
FIT_REACTANCES = True
MIN_FIT_X_PU = 1.0e-4  # on 100 MVA; jumpers below this are floored for the solve


def bus_weights(t3: pypsa.Network) -> pd.Series:
    """bus -> weight for spreading a node's injection: mean load, plus
    generator capacity, so nodes without load still have weights."""
    load = t3.loads_t.p_set.mean() if not t3.loads_t.p_set.empty else pd.Series(dtype=float)
    load = load.reindex(t3.loads.index).fillna(t3.loads["p_set"]).groupby(t3.loads["bus"]).sum()
    gen = t3.generators.loc[t3.generators["p_nom"] < 1.0e5].groupby("bus")["p_nom"].sum()
    w = load.reindex(t3.buses.index, fill_value=0.0).clip(lower=0.0)
    return w + gen.reindex(t3.buses.index, fill_value=0.0)


def fitted_reactances(t3: pypsa.Network, busmap: pd.Series) -> pd.Series:
    """ "node0-node1" (sorted) -> equivalent x, fitted to T3's DC power flow.

    For each node but one, a unit transfer from that node to the reference
    node (spread over buses by bus_weights) is solved on T3's main AC
    island. A node's angle is the weighted mean of its buses' angles. A
    corridor's susceptance is then the least-squares fit of
    flow = b * (angle difference) over all transfers. Parallel combination
    instead treats each node as a copper plate and loses the impedance
    inside it, which sets how parallel corridors share a transfer.
    Lines are on one voltage base (to_common_base) when this runs."""
    import networkx as nx
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import splu

    lines = t3.lines
    g = nx.Graph()
    g.add_edges_from(zip(lines["bus0"], lines["bus1"], strict=True))
    island = max(nx.connected_components(g), key=len)
    lines = lines[lines["bus0"].isin(island) & lines["bus1"].isin(island)]
    buses = pd.Index(sorted(island))
    pos = pd.Series(np.arange(len(buses)), index=buses)
    floor = MIN_FIT_X_PU * COMMON_KV**2 / 100.0
    x = lines["x"].where(lines["x"].abs() >= floor, floor)
    b = 1.0 / x.to_numpy()
    i, j = pos[lines["bus0"]].to_numpy(), pos[lines["bus1"]].to_numpy()
    nb = len(buses)
    B = coo_matrix(
        (np.concatenate([b, b, -b, -b]), (np.r_[i, j, i, j], np.r_[i, j, j, i])), shape=(nb, nb)
    ).tocsc()

    node = busmap.reindex(buses)
    w = bus_weights(t3).reindex(buses, fill_value=0.0)
    nodes = sorted(node.unique())
    share = pd.DataFrame(0.0, index=buses, columns=nodes)
    for z in nodes:
        m = node == z
        wz = w[m] if w[m].sum() > 0 else pd.Series(1.0, index=buses[m])
        share.loc[wz.index, z] = (wz / wz.sum()).to_numpy()

    ref_node = node.value_counts().idxmax()
    ref_bus = 0 if node.iloc[0] == ref_node else int(np.flatnonzero(node == ref_node)[0])
    keep = np.setdiff1d(np.arange(nb), [ref_bus])
    lu = splu(B[keep][:, keep].tocsc())
    others = [z for z in nodes if z != ref_node]
    inj = share[others].to_numpy() - share[[ref_node]].to_numpy()
    theta = np.zeros((nb, len(others)))
    theta[keep] = lu.solve(inj[keep])

    zone_theta = share.to_numpy().T @ theta  # nodes x transfers
    zt = pd.DataFrame(zone_theta, index=nodes)
    flow = (theta[i] - theta[j]) * b[:, None]
    n0, n1 = node.iloc[i].to_numpy(), node.iloc[j].to_numpy()
    out = {}
    cross = np.flatnonzero(n0 != n1)
    pairs = pd.Series(
        ["-".join(sorted(p)) for p in zip(n0[cross], n1[cross], strict=True)], index=cross
    )
    for key, rows in pairs.groupby(pairs).groups.items():
        a, c = key.split("-")  # node names use "_", never "-"
        sign = np.where(n0[rows] == a, 1.0, -1.0)[:, None]
        f = (flow[rows] * sign).sum(axis=0)
        d = zt.loc[a].to_numpy() - zt.loc[c].to_numpy()
        denom = float(d @ d)
        if denom > 0:
            susceptance = float(f @ d) / denom
            if susceptance > 0:
                out[key] = 1.0 / susceptance
    return pd.Series(out, dtype=float)


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

    by_state = node_of(t3.buses)
    busmap = keep_substations_whole(t3, by_state)
    moved = int((busmap != by_state).sum())
    rated_by_class = rate_unrated_lines(t3)
    dropped_ties = low_voltage_ties(t3, busmap, MIN_TIE_KV) if MIN_TIE_KV else pd.Index([])
    t3.remove("Line", dropped_ties)
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
            t3.lines.index.isin(substation_branches(t3))
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

    fitted = fitted_reactances(t3, busmap) if FIT_REACTANCES else pd.Series(dtype=float)
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
    pair = pd.Series(
        ["-".join(sorted(p)) for p in zip(n.lines["bus0"], n.lines["bus1"], strict=True)],
        index=n.lines.index,
    )
    x_fitted = pair.map(fitted)
    n.lines["x"] = x_fitted.fillna(n.lines["x"])
    n.generators["carrier"] = n.generators["carrier"].map(carrier_of_kind)
    n.buses["subsystem"] = [node_subsystem(b, main) for b in n.buses.index]
    n.buses["state"] = n.buses.index.str.split("_").str[0]
    sub = n.buses["subsystem"]
    cross = n.lines[n.lines["bus0"].map(sub) != n.lines["bus1"].map(sub)]
    report = {
        "t3_buses_off_the_main_grid": len(off),
        "substation_branches_between_nodes": transformers_between_nodes,
        "buses_moved_by_substation_rule": moved,
        "unrated_lines_given_class_median": rated_by_class,
        "min_tie_kv": MIN_TIE_KV,
        "low_voltage_ties_dropped": len(dropped_ties),
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
        "fit_reactances": FIT_REACTANCES,
        "lines_with_fitted_x": int(x_fitted.notna().sum()),
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
