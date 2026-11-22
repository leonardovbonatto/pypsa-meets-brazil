# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
A feasibility solve of the T3 network over its first `hours` snapshots
(PR-76): status, load shedding, and inter-subsystem flow over the T0
boundaries. A full year on 13k buses is left to the clustered tiers.
Local only (EPE-derived).
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
from pathlib import Path

import pypsa


def main() -> None:
    snake = globals()["snakemake"]
    n = pypsa.Network(str(snake.input.network))
    hours = int(snake.params.hours)
    # Slice before building the model: a year of profiles for 6,617
    # generators is most of the memory (PR-76).
    n.set_snapshots(n.snapshots[:hours])
    snapshots = n.snapshots
    status, condition = n.optimize(
        solver_name=snake.params.solver_name,
        include_objective_constant=False,
        **dict(snake.params.solver_options),
    )
    p = n.generators_t.p.loc[snapshots]
    shed = p[[g for g in p.columns if g.endswith("load_shedding")]].sum(axis=1)
    shortfall = -p[[g for g in p.columns if g.endswith("must_run_shortfall")]].sum(axis=1)
    sub = n.buses["subsystem"]
    flows = {}
    for comp, flow in ((n.lines, n.lines_t.p0), (n.links, n.links_t.p0)):
        s0, s1 = comp["bus0"].map(sub), comp["bus1"].map(sub)
        for name in comp.index[s0 != s1]:
            key = "-".join(sorted([s0[name], s1[name]]))
            sign = 1 if s0[name] <= s1[name] else -1
            flows[key] = flows.get(key, 0.0) + sign * float(flow.loc[snapshots, name].mean())
    gen = p.T.groupby(n.generators["carrier"]).sum().T.mean().round(0)
    report = {
        "status": status,
        "condition": condition,
        "hours": hours,
        "objective_rs": float(n.objective),
        "load_shed_mwh": float(shed.sum()),
        "must_run_shortfall_mwh": float(shortfall.sum()),
        "must_run_shortfall_buses": int(
            (-p[[g for g in p.columns if g.endswith("must_run_shortfall")]] > 0.5).any().sum()
        ),
        "mean_load_mw": float(n.loads_t.p.loc[snapshots].sum(axis=1).mean()),
        "mean_generation_mw_by_carrier": {k: float(v) for k, v in gen.items()},
        "mean_inter_subsystem_flow_mw": {k: round(v, 0) for k, v in flows.items()},
        "lines_at_limit_share": float(
            (n.lines_t.p0.loc[snapshots].abs() >= 0.999 * n.lines["s_nom"]).any().mean()
        ),
    }
    Path(snake.output.report).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
