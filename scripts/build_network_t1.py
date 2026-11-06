# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the T1 (state) network by splitting T0 across T1 nodes (ADR-0022).

Every T0 generator `{s} {carrier}` becomes one generator per T1 node of
subsystem `s` that produced that source in 2024, with p_nom scaled by the
node's share of the subsystem's observed output (`geracao_usina`, which
carries both `id_estado` and `id_subsystem`) and T0's per-unit profiles
kept. Subsystem totals equal T0's by construction, so T1's differences from
T0 come from topology. Each subsystem's load is split across its main
nodes by DLR's 2020 state shares averaged by (month, hour). Exports (PR-64)
go to RS.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd
import pypsa

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ons import map_subsystems
from build_network import LINK_TIE_BREAK_COST

ONS_SOURCE = {
    "EOLIELÉTRICA": "wind",
    "FOTOVOLTAICA": "solar",
    "NUCLEAR": "nuclear",
    "TÉRMICA": "thermal",
    "HIDROELÉTRICA": "hydro",
}
MMGD = "Pequenas Usinas (MMGD)"
SMALL = {"Pequenas Usinas (Tipo III)", "TIPO III"}
EXPORT_NODE = "RS"


def observed_shares(raw: pd.DataFrame, nodes: pd.DataFrame) -> pd.DataFrame:
    """(subsystem, carrier, node) -> share of the subsystem's observed output
    of that carrier, with carriers named as in T0 (solar_mmgd, *_small)."""
    df = map_subsystems(raw)
    source = df["nom_tipousina"].map(ONS_SOURCE)
    carrier = source.where(~df["cod_modalidadeoperacao"].isin(SMALL), source + "_small")
    carrier = carrier.where(df["cod_modalidadeoperacao"] != MMGD, "solar_mmgd")
    node_of = nodes.set_index(["state", "subsystem"])["node"]
    keys = pd.MultiIndex.from_arrays([df["id_estado"], df["subsystem"]])
    df = df.assign(carrier=carrier, node=node_of.reindex(keys).to_numpy())
    # A (state, subsystem) pair below the node threshold folds into the state's main node.
    main = nodes[nodes["main"]].set_index("state")["node"]
    df["node"] = df["node"].fillna(df["id_estado"].map(main))
    # States left out of T1 (islands, e.g. RR in 2024) fold into their
    # subsystem's largest main node, as T0 counted them.
    largest = nodes[nodes["main"]].sort_values("capacity_mw").groupby("subsystem")["node"].last()
    df["node"] = df["node"].fillna(df["subsystem"].map(largest))
    total = df.groupby(["subsystem", "carrier", "node"], as_index=False)["val_geracao"].sum()
    total = total[total["val_geracao"] > 0]
    total["share"] = total["val_geracao"] / total.groupby(["subsystem", "carrier"])[
        "val_geracao"
    ].transform("sum")
    return total[["subsystem", "carrier", "node", "share"]]


def load_shares(dlr_load: pd.DataFrame, nodes: pd.DataFrame) -> pd.DataFrame:
    """(subsystem, month, hour, node) -> the main node's share of its
    subsystem's load, DLR 2020 averaged by (month, hour)."""
    main = nodes[nodes["main"]].set_index("state")
    dlr_load = dlr_load[dlr_load["state"].isin(main.index)]
    time = pd.to_datetime(dlr_load["time"])
    work = dlr_load.assign(
        month=time.dt.month,
        hour=time.dt.hour,
        node=dlr_load["state"].map(main["node"]),
        subsystem=dlr_load["state"].map(main["subsystem"]),
    )
    if work["node"].isna().any():
        raise ValueError(
            f"DLR state(s) with no T1 node: {sorted(set(work.loc[work['node'].isna(), 'state']))}"
        )
    mean = work.groupby(["subsystem", "month", "hour", "node"], as_index=False)["value"].mean()
    mean["share"] = mean["value"] / mean.groupby(["subsystem", "month", "hour"])["value"].transform(
        "sum"
    )
    return mean[["subsystem", "month", "hour", "node", "share"]]


def build_t1(
    t0: pypsa.Network,
    nodes: pd.DataFrame,
    links: pd.DataFrame,
    gen_shares: pd.DataFrame,
    load_share: pd.DataFrame,
) -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(t0.snapshots)
    n.snapshot_weightings = t0.snapshot_weightings
    for c in t0.carriers.index:
        n.add("Carrier", c)
    n.add("Bus", nodes["node"].tolist(), carrier="AC")
    snapshots = pd.DatetimeIndex(t0.snapshots)

    # Load: each subsystem's T0 loads (demand and exports) split across nodes.
    # Static and time-varying p_set alike (a static load is absent from loads_t).
    p_set = t0.get_switchable_as_dense("Load", "p_set")
    keys = pd.DataFrame({"month": snapshots.month, "hour": snapshots.hour})
    for s in t0.buses.index:
        demand = p_set[
            [c for c in p_set.columns if t0.loads.at[c, "bus"] == s and not c.endswith("exports")]
        ].sum(axis=1)
        shares = load_share[load_share["subsystem"] == s].pivot_table(
            index=["month", "hour"], columns="node", values="share"
        )
        aligned = keys.merge(shares.reset_index(), on=["month", "hour"], how="left").drop(
            columns=["month", "hour"]
        )
        if aligned.isna().any().any():
            raise ValueError(f"load shares missing for some (month, hour) in {s}")
        for node in aligned.columns:
            n.add(
                "Load",
                f"{node} demand",
                bus=node,
                p_set=demand.to_numpy() * aligned[node].to_numpy(),
            )
    exports = [c for c in t0.loads.index if c.endswith("exports")]
    for c in exports:
        n.add("Load", f"{EXPORT_NODE} exports", bus=EXPORT_NODE, p_set=p_set[c].to_numpy())

    # Generators: split by observed output share; load shedding at every node.
    p_max = t0.get_switchable_as_dense("Generator", "p_max_pu")
    p_min = t0.get_switchable_as_dense("Generator", "p_min_pu")
    for name, g in t0.generators.iterrows():
        if g["carrier"] == "load_shedding":
            continue
        carrier = g["carrier"]
        rows = gen_shares[
            (gen_shares["subsystem"] == g["bus"]) & (gen_shares["carrier"] == carrier)
        ]
        if rows.empty:  # no observed output for it: keep it whole at the largest main node
            target = nodes[(nodes["subsystem"] == g["bus"]) & nodes["main"]].nlargest(
                1, "capacity_mw"
            )["node"]
            rows = pd.DataFrame({"node": target, "share": [1.0]})
        for _, r in rows.iterrows():
            new = f"{r['node']} {name.split(' ', 1)[1]}"
            n.add(
                "Generator",
                new,
                bus=r["node"],
                carrier=carrier,
                p_nom=float(g["p_nom"]) * float(r["share"]),
                marginal_cost=float(g["marginal_cost"]),
            )
            n.generators_t.p_max_pu[new] = p_max[name].to_numpy()
            n.generators_t.p_min_pu[new] = p_min[name].to_numpy()
    shed = t0.generators[t0.generators["carrier"] == "load_shedding"].iloc[0]
    n.add(
        "Generator",
        [f"{b} load_shedding" for b in nodes["node"]],
        bus=nodes["node"].tolist(),
        carrier="load_shedding",
        p_nom=float(shed["p_nom"]),
        marginal_cost=float(shed["marginal_cost"]),
    )

    # Links: one-way pairs with T0's routing tie-break (PR-61).
    for b0, b1 in (("bus0", "bus1"), ("bus1", "bus0")):
        n.add(
            "Link",
            [f"{a}-{b}" for a, b in zip(links[b0], links[b1], strict=True)],
            bus0=links[b0].to_numpy(),
            bus1=links[b1].to_numpy(),
            p_nom=links["p_nom_mw"].to_numpy(),
            efficiency=links["efficiency"].to_numpy(),
            p_min_pu=0.0,
            marginal_cost=LINK_TIE_BREAK_COST,
            carrier="AC",
        )
    return n


def main() -> None:
    snake = globals()["snakemake"]
    t0 = pypsa.Network(str(snake.input.t0))
    links = pd.read_csv(snake.input.links)
    nodes = pd.read_csv(snake.input.nodes)
    # Islands (no corridor; RR in 2024) are left out of T1, load and all.
    nodes = nodes[nodes["node"].isin(set(links["bus0"]) | set(links["bus1"]))]
    columns = [
        "id_estado",
        "id_subsistema",
        "nom_tipousina",
        "cod_modalidadeoperacao",
        "val_geracao",
    ]
    raw = pd.concat(
        [pd.read_csv(p, sep=";", usecols=columns) for p in snake.input.generation],
        ignore_index=True,
    )
    n = build_t1(
        t0,
        nodes,
        links,
        observed_shares(raw, nodes),
        load_shares(pd.read_csv(snake.input.dlr_load), nodes),
    )
    Path(snake.output[0]).parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(str(snake.output[0]))


if __name__ == "__main__":
    main()
