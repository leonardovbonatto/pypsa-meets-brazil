# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Solve the T0 network and write a dispatch summary.

A clean "optimal" status is necessary but not sufficient for the result to
mean anything - the T0 network still carries real simplifications (see
`KNOWN_LIMITATIONS`, and docs/handoffs/PR-15-*.md), so a technically
successful solve can still be a physically wrong one.
`summarize_dispatch()` computes load-shedding per bus because it is the one
number that directly measures whether generation and transfer capacity
actually covered demand - see `build_network.attach_load_shedding()` - and
`KNOWN_LIMITATIONS` is written into the summary itself so a result can
never be read without it.

Keep `KNOWN_LIMITATIONS` current as gaps close: a stale caveat that names
an already-fixed problem is as misleading as a missing one.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
import sys
from pathlib import Path

import pypsa

sys.path.insert(0, str(Path(__file__).resolve().parent))

KNOWN_LIMITATIONS = [
    "HYDRO IS UNCONSTRAINED AND FREE, and this dominates every result "
    "below. Hydro has no availability profile (p_max_pu = 1.0 always: "
    "102,678 MW of nameplate capacity assumed available every hour) and "
    "marginal_cost = 0. National hydro capacity alone exceeds national "
    "demand in all 8784 hours of 2024, so the solver covers essentially "
    "all demand with hydro and dispatches thermal at exactly 0 MW, every "
    "hour. Real hydro is limited by water availability - an opportunity "
    "cost that must be computed (PRIMER Sec 4, SDDP.jl), not looked up - "
    "and until that exists, this model cannot say anything meaningful "
    "about thermal dispatch, merit order or prices.",
    "Wind and solar DO have a real hourly availability profile (PR-15, "
    "from ONS measured capacity factors), so their dispatch is "
    "physically constrained - but it is economically irrelevant while "
    "unconstrained free hydro can cover all demand regardless.",
    "Transmission is a transport model (ADR-0006): Links with a "
    "transfer-capacity limit derived from historical flows, not real "
    "DC power flow with impedances. No losses.",
    "Thermal marginal_cost is a single subsystem-wide mean CVU for the "
    "whole year (PR-10), not per-plant or time-varying.",
    "Wind, solar and nuclear carry marginal_cost = 0 "
    "(NON_THERMAL_MARGINAL_COST). Near-zero is defensible for wind and "
    "solar; nuclear is a must-run baseload approximation.",
    "load_shedding generators are an unlimited, high-cost slack whose "
    "dispatch is diagnostic (see load_shedding_mwh_by_bus below), not a "
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


def summarize_prices(n: pypsa.Network) -> dict:
    """
    Mean `marginal_price` per bus (R$/MWh), plus whether every price is zero.

    This is the project's headline validation target (PRIMER Sec 2.6/3.4):
    the dual of the nodal energy balance is the CMO. It is reported here so
    the number is visible in a committed artifact rather than only via
    manual inspection of the solved network.

    `all_prices_zero` is the explicit signal that the model is
    *economically degenerate*: some zero-marginal-cost generator always has
    headroom, so nothing scarce ever sets a price. That is the current
    state (unconstrained free hydro - see KNOWN_LIMITATIONS), and it means
    no price-based validation is meaningful yet. Note PyPSA drops an
    all-default time series on export, so an all-zero price frame does not
    survive to `network_t0_solved.nc` at all - another reason to record it
    here explicitly.
    """
    prices = n.buses_t.marginal_price
    if prices.empty:
        return {"mean_marginal_price_rs_per_mwh_by_bus": {}, "all_prices_zero": None}

    return {
        "mean_marginal_price_rs_per_mwh_by_bus": prices.mean().round(2).to_dict(),
        "all_prices_zero": bool((prices == 0).all().all()),
    }


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
        **summarize_prices(n),
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
    if summary["all_prices_zero"]:
        print(
            "WARNING: every marginal price is 0 - the model is economically "
            "degenerate (a zero-cost generator always has headroom). No "
            "price-based validation is meaningful in this state; see "
            "known_limitations in the summary.",
            file=sys.stderr,
        )

    n.export_to_netcdf(str(snake.output.network))
    write_summary(summary, Path(snake.output.summary))


if __name__ == "__main__":
    main()
