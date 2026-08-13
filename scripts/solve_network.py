# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Solve the T0 network and write a dispatch summary.

This is the first script in the project that calls `n.optimize()`. A clean
"optimal" status is necessary but not sufficient for the result to mean
anything: the T0 network has no transmission lines and no availability
profiles (see docs/handoffs/PR-11-*.md), so a technically successful solve
can still be a physically wrong one. `summarize_dispatch()` computes
load-shedding per bus specifically because it is the one number in this
network that directly measures the no-lines gap - see
`build_network.attach_load_shedding()` - and `KNOWN_LIMITATIONS` is written
into the summary itself so a result can never be read without it.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
import sys
from pathlib import Path

import pypsa

sys.path.insert(0, str(Path(__file__).resolve().parent))

KNOWN_LIMITATIONS = [
    "No transmission lines exist yet: each subsystem is solved as an "
    "electrically isolated bus. This is four independent single-bus "
    "problems, not a real interconnected dispatch.",
    "No availability profile (p_max_pu) exists yet for wind, solar or "
    "hydro: every MW of nameplate capacity is assumed available every "
    "hour. Real renewable and run-of-river output is materially lower.",
    "Thermal marginal_cost is a single subsystem-wide mean CVU for the "
    "whole year (PR-10), not per-plant or time-varying.",
    "Hydro, wind, solar and nuclear all carry marginal_cost = 0 "
    "(NON_THERMAL_MARGINAL_COST) - a stated T0 simplification, not a "
    "claim that generation is actually free.",
    "load_shedding generators are an unlimited, high-cost slack added "
    "only so the network solves despite having no transmission lines - "
    "their dispatch is diagnostic (see load_shedding_mwh below), not a "
    "real unserved-energy estimate.",
]


def load_network(path: Path) -> pypsa.Network:
    return pypsa.Network(str(path))


def solve(n: pypsa.Network, *, solver_name: str, solver_options: dict) -> tuple[str, str]:
    """Run n.optimize(); raise rather than let a failed solve pass silently."""
    status, condition = n.optimize(
        solver_name=solver_name,
        # Explicit rather than the current default of None (which warns):
        # PyPSA's own recommendation, better LP numerical conditioning.
        include_objective_constant=False,
        **solver_options,
    )
    if status != "ok":
        raise RuntimeError(f"solve did not reach an optimal solution: {status}/{condition}")
    return status, condition


def summarize_dispatch(n: pypsa.Network) -> dict:
    mean_by_generator = n.generators_t.p.mean()

    load_shed = n.generators[n.generators["carrier"] == "load_shedding"]
    load_shed_mwh_by_bus = {
        bus: float(n.generators_t.p[name].sum())
        for name, bus in load_shed["bus"].items()
        if float(n.generators_t.p[name].sum()) > 0
    }

    mean_by_carrier = (
        mean_by_generator.groupby(n.generators["carrier"]).sum().sort_values(ascending=False)
    )

    return {
        "objective_rs": float(n.objective),
        "mean_dispatch_mw_by_carrier": mean_by_carrier.round(1).to_dict(),
        "load_shedding_mwh_by_bus": load_shed_mwh_by_bus,
        "known_limitations": KNOWN_LIMITATIONS,
    }


def write_summary(summary: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    n = load_network(Path(snake.input[0]))
    solve(n, solver_name=snake.params.solver_name, solver_options=dict(snake.params.solver_options))

    summary = summarize_dispatch(n)
    if summary["load_shedding_mwh_by_bus"]:
        print(
            f"WARNING: load shedding occurred - {summary['load_shedding_mwh_by_bus']} "
            "(diagnostic only; see known_limitations in the summary)",
            file=sys.stderr,
        )

    n.export_to_netcdf(str(snake.output.network))
    write_summary(summary, Path(snake.output.summary))


if __name__ == "__main__":
    main()
