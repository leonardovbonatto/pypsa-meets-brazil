# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Put T0's 2024 energy on T3's buses (ADR-0026, PR-76). EPE gives where;
ONS 2024 gives how much.

- Each T0 generator `{s} {name}` goes first to (state, subsystem) by that
  carrier's observed 2024 output share (`build_network_t1.observed_shares`),
  then to the buses of that state and subsystem by EPE's plant capacity of
  the matching kind (`epe_plants`), keeping T0's per-unit profiles, costs
  and floors. Fallbacks, in order: the state's buses by EPE base load; its
  highest-voltage bus; the subsystem's largest-load bus. Rooftop solar
  (MMGD) follows load.
- Each subsystem's T0 demand goes to its buses by EPE base load; exports to
  RS's load buses.
- Only the main AC island is used: buses outside it (2% of T3) get no
  load or generation.

Subsystem totals equal T0's by construction. EPE data stays local.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
import sys
from pathlib import Path

import pandas as pd
import pypsa

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_network_t1 import observed_shares

# T0 carrier -> EPE plant kind whose capacity places it.
EPE_KIND = {
    "hydro": "hydro",
    "thermal": "thermal",
    "nuclear": "nuclear",
    "wind": "wind",
    "solar": "solar",
    "hydro_small": "hydro_small",
    "thermal_small": "thermal_small",
    "wind_small": "wind",
    "solar_small": "solar",
    "solar_mmgd": "load",
}
EXPORT_STATE = "RS"
# PR-76: a few buses hold forced output (floors, small plants) their lines
# cannot carry; on 2024's first hour, 44 MW at two buses (MS 138 kV, SC
# 69 kV) made T3 infeasible. A priced outlet at every bus with forced output
# lets the solve go through and reports what it had to cut. Twice the
# load-shedding cost, so it is used only when nothing else can absorb it.
MUST_RUN_SHORTFALL_COST = 20_000.0


def candidate_weights(
    buses: pd.DataFrame, gen_weights: pd.DataFrame, load_weights: pd.DataFrame
) -> pd.DataFrame:
    """(state, subsystem, kind, bus) -> weight, kinds as EPE_KIND's values
    plus 'load'; only buses on the main island."""
    on = buses[buses["main_island"]]
    meta = on.set_index("bus")[["state", "subsystem"]]
    g = gen_weights[gen_weights["bus"].isin(meta.index) & (gen_weights["weight_mw"] > 0)]
    g = g.rename(columns={"carrier": "kind"})
    lw = load_weights[load_weights["bus"].isin(meta.index) & (load_weights["weight_mw"] > 0)]
    lw = lw.assign(kind="load")
    both = pd.concat([g[["bus", "kind", "weight_mw"]], lw[["bus", "kind", "weight_mw"]]])
    return both.join(meta, on="bus")


def place(
    state: str, subsystem: str, kind: str, cand: pd.DataFrame, buses: pd.DataFrame
) -> pd.Series:
    """bus -> share for one (state, subsystem, kind), with fallbacks."""
    here = cand[(cand["state"] == state) & (cand["subsystem"] == subsystem)]
    for k in (kind, "load"):
        rows = here[here["kind"] == k]
        if not rows.empty:
            w = rows.groupby("bus")["weight_mw"].sum()
            return w / w.sum()
    pool = buses[
        buses["main_island"] & (buses["state"] == state) & (buses["subsystem"] == subsystem)
    ]
    if not pool.empty:
        return pd.Series({pool.sort_values("v_nom_kv").iloc[-1]["bus"]: 1.0})
    loads = cand[(cand["subsystem"] == subsystem) & (cand["kind"] == "load")]
    return pd.Series({loads.groupby("bus")["weight_mw"].sum().idxmax(): 1.0})


def attach_energy(
    t3: pypsa.Network,
    t0: pypsa.Network,
    buses: pd.DataFrame,
    node_shares: pd.DataFrame,
    nodes: pd.DataFrame,
    cand: pd.DataFrame,
) -> dict:
    t3.set_snapshots(t0.snapshots)
    t3.snapshot_weightings = t0.snapshot_weightings
    for c in t0.carriers.index:
        if c not in t3.carriers.index:
            t3.add("Carrier", c)
    p_set = t0.get_switchable_as_dense("Load", "p_set")
    state_of_node = nodes.set_index("node")[["state", "subsystem"]]

    # Demand per subsystem by EPE load; exports on RS's load buses.
    for s in t0.buses.index:
        demand = p_set[
            [c for c in p_set.columns if t0.loads.at[c, "bus"] == s and not c.endswith("exports")]
        ].sum(axis=1)
        w = (
            cand[(cand["subsystem"] == s) & (cand["kind"] == "load")]
            .groupby("bus")["weight_mw"]
            .sum()
        )
        share = w / w.sum()
        t3.add(
            "Load",
            [f"{b} demand" for b in share.index],
            bus=[str(b) for b in share.index],
            p_set=pd.DataFrame(
                {f"{b} demand": demand.to_numpy() * v for b, v in share.items()}, index=t3.snapshots
            ),
        )
    for c in [c for c in t0.loads.index if c.endswith("exports")]:
        w = (
            cand[(cand["state"] == EXPORT_STATE) & (cand["kind"] == "load")]
            .groupby("bus")["weight_mw"]
            .sum()
        )
        share = w / w.sum()
        t3.add(
            "Load",
            [f"{b} exports" for b in share.index],
            bus=[str(b) for b in share.index],
            p_set=pd.DataFrame(
                {f"{b} exports": p_set[c].to_numpy() * v for b, v in share.items()},
                index=t3.snapshots,
            ),
        )

    # Generators: subsystem -> (state, subsystem) by ONS 2024 output -> bus by EPE.
    p_max = t0.get_switchable_as_dense("Generator", "p_max_pu")
    p_min = t0.get_switchable_as_dense("Generator", "p_min_pu")
    names, rows, pmax_cols, pmin_cols = [], [], {}, {}
    fallback = 0
    for name, g in t0.generators.iterrows():
        if g["carrier"] == "load_shedding":
            continue
        kind = EPE_KIND.get(g["carrier"], "load")
        ns = node_shares[
            (node_shares["subsystem"] == g["bus"]) & (node_shares["carrier"] == g["carrier"])
        ]
        if ns.empty:
            ns = pd.DataFrame({"node": [None], "share": [1.0]})
        for _, r in ns.iterrows():
            if r["node"] is None or r["node"] not in state_of_node.index:
                top = (
                    cand[(cand["subsystem"] == g["bus"]) & (cand["kind"] == "load")]
                    .groupby("state")["weight_mw"]
                    .sum()
                    .idxmax()
                )
                state, sub = top, g["bus"]
            else:
                state, sub = state_of_node.loc[r["node"]]
            split = place(state, sub, kind, cand, buses)
            fallback += int(
                not (
                    (cand["state"] == state) & (cand["subsystem"] == sub) & (cand["kind"] == kind)
                ).any()
            )
            for bus, b_share in split.items():
                new = f"{bus} {name.split(' ', 1)[1]}"
                if new in pmax_cols:  # same bus via two nodes: add capacity
                    rows[names.index(new)]["p_nom"] += (
                        float(g["p_nom"]) * float(r["share"]) * float(b_share)
                    )
                    continue
                names.append(new)
                rows.append(
                    {
                        "bus": str(bus),
                        "carrier": g["carrier"],
                        "p_nom": float(g["p_nom"]) * float(r["share"]) * float(b_share),
                        "marginal_cost": float(g["marginal_cost"]),
                    }
                )
                pmax_cols[new] = p_max[name].to_numpy()
                pmin_cols[new] = p_min[name].to_numpy()
    frame = pd.DataFrame(rows, index=names)
    t3.add("Generator", frame.index, **{k: frame[k].to_numpy() for k in frame.columns})
    t3.generators_t.p_max_pu = pd.DataFrame(pmax_cols, index=t3.snapshots)
    t3.generators_t.p_min_pu = pd.DataFrame(pmin_cols, index=t3.snapshots)
    forced = (t3.generators_t.p_min_pu.max() > 0).reindex(t3.generators.index, fill_value=False)
    forced_buses = sorted(set(t3.generators.loc[forced, "bus"]))
    if "must_run_shortfall" not in t3.carriers.index:
        t3.add("Carrier", "must_run_shortfall")
    t3.add(
        "Generator",
        [f"{b} must_run_shortfall" for b in forced_buses],
        bus=forced_buses,
        carrier="must_run_shortfall",
        p_nom=1.0e6,
        p_min_pu=-1.0,
        p_max_pu=0.0,
        marginal_cost=-MUST_RUN_SHORTFALL_COST,  # negative output x negative cost = penalty
    )
    shed = t0.generators[t0.generators["carrier"] == "load_shedding"].iloc[0]
    load_buses = sorted(set(t3.loads["bus"]))
    t3.add(
        "Generator",
        [f"{b} load_shedding" for b in load_buses],
        bus=load_buses,
        carrier="load_shedding",
        p_nom=float(shed["p_nom"]),
        marginal_cost=float(shed["marginal_cost"]),
    )
    return {
        "generators": len(frame),
        "must_run_shortfall_buses": len(forced_buses),
        "load_buses": len(load_buses),
        "placements_without_matching_epe_kind": fallback,
        "generation_capacity_mw_by_carrier": frame.groupby("carrier")["p_nom"]
        .sum()
        .round(0)
        .to_dict(),
        "t0_capacity_mw_by_carrier": t0.generators[t0.generators["carrier"] != "load_shedding"]
        .groupby("carrier")["p_nom"]
        .sum()
        .round(0)
        .to_dict(),
    }


def main() -> None:
    snake = globals()["snakemake"]
    t3 = pypsa.Network(str(snake.input.structure))
    t0 = pypsa.Network(str(snake.input.t0))
    main_sub = t3.buses["sub_network"].value_counts().idxmax()
    buses = t3.buses.reset_index().rename(
        columns={t3.buses.index.name or "index": "bus", "v_nom": "v_nom_kv"}
    )
    buses["bus"] = buses["bus"].astype(int)
    buses["main_island"] = buses["sub_network"] == main_sub
    nodes = pd.read_csv(snake.input.nodes)
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
    cand = candidate_weights(
        buses, pd.read_csv(snake.input.gen_weights), pd.read_csv(snake.input.load_weights)
    )
    report = attach_energy(t3, t0, buses, observed_shares(raw, nodes), nodes, cand)
    t3.export_to_netcdf(str(snake.output.network))
    Path(snake.output.report).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
