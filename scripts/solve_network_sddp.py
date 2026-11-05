# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Solve 2024 on the T0 network with SDDP water values instead of the hydro
backcast (ADR-0014).

**What changes from solve_network.py.** Hydro there is told what it actually
did (ADR-0007). Here each subsystem's hydro is one reservoir (a PyPSA
StorageUnit) fed by observed 2024 inflow, starting from observed storage on
2023-12-31, and free to decide when to use its water. What stops it spending
everything now is the SDDP cost-to-go: the cuts say what water left at the end
of each month is worth.

**Monthly rolling, as NEWAVE hands water values to DECOMP.** Each month is
one hourly PyPSA solve. A variable `alpha` (R$) is added to its objective,
with one constraint per cut of that month's SDDP node,

    alpha >= MONEY_SCALE * (a_k + sum_s beta_ks * storage_end_s / HOURS_PER_MWMES),

where `storage_end_s` is the reservoir's MWh at the month's last hour. The node
is (month, observed 2024 regime), the regime read from that month's inflow
exactly as prepare_sddp_inputs labels its training years. The month's ending
storage is the next month's start.

**Units.** SDDP storage is MWmes; PyPSA's is MWh. One MWmes is taken as
HOURS_PER_MWMES = 730 MWh (8760 / 12), the convention-level approximation the
SDDP model already makes (its known-limitations note on month length).

**December has no water value.** SDDP's year has 12 stages and the last has
no cuts, so water left at the end of December is worth nothing in both
models. December results carry that end effect.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_sddp_regimes import parse_cuts
from prepare_sddp_inputs import regional_states
from solve_network import KNOWN_LIMITATIONS as T0_LIMITATIONS

HOURS_PER_MWMES = 730.0
MONEY_SCALE = 1.0e6
INFLOW_COLUMN = "ena_bruta_mwmed"
RESERVOIR_CARRIER = "hydro"

# Breaks a tie, not a price. Where the cuts value water at zero, spilling
# inflow and storing it cost the same, and the first coupled run took the
# spill vertex: SE_CO spilled 36.8 GW in January 2024 while drawing its stored
# water down, and was empty by April. A cost this small never outbids a real
# price, but keeps water rather than dumping it, so free curtailment of wind
# and solar goes first.
SPILL_COST = 0.01

KNOWN_LIMITATIONS = [
    "HYDRO IS OPTIMISED, NOT BACKCAST (ADR-0014): one reservoir per subsystem, "
    "observed 2024 inflow, observed 2023-12-31 storage, valued at month ends by "
    "SDDP cuts. Supersedes T0's backcast caveat for this run only.",
    "Water values come from the regional SDDP policy (ADR-0010), which has "
    "transmission (ADR-0012) and net load (ADR-0013) but no minimum outflows, "
    "run-of-river limits, or storable-vs-gross inflow distinction.",
    "December has no water value: SDDP's last stage has no cuts, so reservoirs "
    "may be drawn down in December.",
    "One MWmes = 730 MWh for every month.",
    "Each month is solved with perfect foresight of its own hourly inflow, "
    "demand and renewables; uncertainty enters only through the cuts.",
    *[
        note
        for note in T0_LIMITATIONS
        if not note.startswith(("HYDRO IS A BACKCAST", "Hydro also"))
    ],
]


def hourly_inflow(
    ena: pd.DataFrame, snapshots: pd.DatetimeIndex, subsystems: list[str]
) -> pd.DataFrame:
    """snapshot x subsystem -> inflow MW, each day's mean ENA held for its hours."""
    daily = ena.assign(day=pd.to_datetime(ena["date"]).dt.normalize()).pivot_table(
        index="day", columns="subsystem", values=INFLOW_COLUMN
    )
    missing = set(subsystems) - set(daily.columns)
    if missing:
        raise ValueError(f"inflow has no data for {sorted(missing)}")
    hourly = daily[subsystems].reindex(snapshots.normalize())
    if hourly.isna().any().any():
        raise ValueError("inflow does not cover every snapshot day")
    hourly.index = snapshots
    return hourly


def observed_regimes(
    monthly_inflow: pd.DataFrame,
    par1_params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    regions: dict[str, list[str]],
    n_states: int,
) -> pd.Series:
    """month -> joint regime of the observed year, labelled exactly as
    prepare_sddp_inputs labels simulated years. `monthly_inflow` is (month,
    subsystem, inflow_mwmed) for twelve months."""
    subsystems = list(corr_matrix.columns)
    wide = monthly_inflow.pivot(index="month", columns="subsystem", values="inflow_mwmed")
    lookup = par1_params.set_index(["month", "subsystem"])
    z = np.empty((1, 12, len(subsystems)))
    for month in range(1, 13):
        for i, s in enumerate(subsystems):
            p = lookup.loc[(month, s)]
            z[0, month - 1, i] = (np.log(wide.loc[month, s]) - p["mu"]) / p["sigma"]
    states = regional_states(z, par1_params, corr_matrix, regions=regions, n_states=n_states)
    return pd.Series(states[0], index=range(1, 13), name="markov_state")


def add_reservoirs(
    n: pypsa.Network,
    capacity_mwmes: dict[str, float],
    initial_mwmes: dict[str, float],
    inflow_mw: pd.DataFrame,
) -> list[str]:
    """Replace each subsystem's backcast hydro generator with a reservoir of the
    same p_nom. Returns the reservoir names, ordered as `inflow_mw.columns`."""
    names = []
    for s in inflow_mw.columns:
        generator = f"{s} {RESERVOIR_CARRIER}"
        p_nom = float(n.generators.loc[generator, "p_nom"])
        n.remove("Generator", generator)
        name = f"{s} reservoir"
        n.add(
            "StorageUnit",
            name,
            bus=s,
            carrier=RESERVOIR_CARRIER,
            p_nom=p_nom,
            max_hours=capacity_mwmes[s] * HOURS_PER_MWMES / p_nom,
            inflow=inflow_mw[s],
            state_of_charge_initial=initial_mwmes[s] * HOURS_PER_MWMES,
            cyclic_state_of_charge=False,
            p_min_pu=0.0,
            marginal_cost=0.0,
            spill_cost=SPILL_COST,
        )
        names.append(name)
    return names


def water_value(
    n: pypsa.Network, intercepts: np.ndarray, coefficients: np.ndarray, reservoirs: list[str]
):
    """extra_functionality: alpha (R$) above every cut at the last hour's storage."""

    def extra(n, snapshots):
        m = n.model
        storage = m["StorageUnit-state_of_charge"].sel(snapshot=snapshots[-1], name=reservoirs)
        alpha = m.add_variables(lower=0.0, name="water_value_alpha")
        cuts = np.arange(len(intercepts))
        slopes = xr.DataArray(
            MONEY_SCALE * coefficients / HOURS_PER_MWMES,
            dims=("cut", "name"),
            coords={"cut": cuts, "name": reservoirs},
        )
        rhs = xr.DataArray(MONEY_SCALE * intercepts, dims="cut", coords={"cut": cuts})
        future = (storage * slopes).sum("name")
        m.add_constraints(alpha - future >= rhs, name="water_value_cuts")
        m.objective = m.objective.expression + alpha

    return extra


def month_summary(n: pypsa.Network, snapshots: pd.DatetimeIndex, reservoirs: list[str]) -> dict:
    """Per subsystem: ending storage (MWmes), mean reservoir output, thermal
    and load shed (MW), and the mean and median hourly price (R$/MWh)."""
    out = {}
    prices = n.buses_t.marginal_price.loc[snapshots]
    p = n.generators_t.p.loc[snapshots]
    for name in reservoirs:
        s = n.storage_units.loc[name, "bus"]
        out[s] = {
            "storage_end_mwmes": float(n.storage_units_t.state_of_charge.loc[snapshots[-1], name])
            / HOURS_PER_MWMES,
            "hydro_mw": float(n.storage_units_t.p.loc[snapshots, name].mean()),
            "spill_mw": float(n.storage_units_t.spill.loc[snapshots, name].mean())
            if name in n.storage_units_t.spill
            else 0.0,
            "thermal_mw": float(p[f"{s} thermal"].mean()),
            "load_shed_mwh": float(p[f"{s} load_shedding"].sum()),
            "price_mean_rs_per_mwh": float(prices[s].mean()),
            "price_median_rs_per_mwh": float(prices[s].median()),
        }
    return out


def solve_year(
    n: pypsa.Network,
    nodes: dict,
    regimes: pd.Series,
    reservoirs: list[str],
    *,
    solver_name: str,
    solver_options: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One solve per calendar month in the snapshots, in order. Returns
    (monthly rows, hourly prices)."""
    rows, prices = [], []
    for month in sorted(set(n.snapshots.month)):
        snapshots = n.snapshots[n.snapshots.month == month]
        regime = int(regimes[month])
        extra = None
        if (month, regime) in nodes:
            intercepts, coefficients = nodes[(month, regime)]
            extra = water_value(n, intercepts, coefficients, reservoirs)
        status, condition = n.optimize(
            snapshots=snapshots,
            solver_name=solver_name,
            include_objective_constant=False,
            extra_functionality=extra,
            **solver_options,
        )
        if status != "ok":
            raise RuntimeError(f"month {month} did not solve: {status}/{condition}")
        alpha = float(n.model["water_value_alpha"].solution) if extra else 0.0
        for s, values in month_summary(n, snapshots, reservoirs).items():
            rows.append(
                {
                    "month": month,
                    "subsystem": s,
                    "markov_state": regime,
                    "future_cost_rs": alpha,
                    **values,
                }
            )
        prices.append(n.buses_t.marginal_price.loc[snapshots])
        end = n.storage_units_t.state_of_charge.loc[snapshots[-1], reservoirs]
        n.storage_units.loc[reservoirs, "state_of_charge_initial"] = end.to_numpy()
    return pd.DataFrame(rows), pd.concat(prices)


def main() -> None:
    snake = globals()["snakemake"]
    logging.getLogger("pypsa").setLevel(logging.WARNING)

    n = pypsa.Network(str(snake.input.network))
    subsystems = sorted(n.buses.index)
    capacity = pd.read_csv(snake.input.reservoir_capacity)
    history = pd.read_csv(snake.input.reservoir_history, parse_dates=["date"])
    start = history[history["date"] == pd.Timestamp(snake.params.start_storage_date)]
    if sorted(start["subsystem"]) != subsystems:
        raise ValueError(f"no storage for every subsystem on {snake.params.start_storage_date}")

    ena = pd.read_csv(snake.input.inflow, parse_dates=["date"])
    year = ena[ena["date"].dt.year == n.snapshots[0].year]
    inflow = hourly_inflow(year, n.snapshots, subsystems)
    reservoirs = add_reservoirs(
        n,
        dict(zip(capacity["subsystem"], capacity["ear_max_mwmes"], strict=True)),
        dict(zip(start["subsystem"], start["ear_verif_mwmes"], strict=True)),
        inflow,
    )

    monthly_inflow = (
        year.assign(month=year["date"].dt.month)
        .groupby(["month", "subsystem"], as_index=False)[INFLOW_COLUMN]
        .mean()
        .rename(columns={INFLOW_COLUMN: "inflow_mwmed"})
    )
    corr_matrix = pd.read_csv(snake.input.par1_correlation).pivot(
        index="subsystem_a", columns="subsystem_b", values="correlation"
    )
    regimes = observed_regimes(
        monthly_inflow,
        pd.read_csv(snake.input.par1_params),
        corr_matrix,
        regions=dict(snake.params.regions),
        n_states=int(snake.params.n_markov_states),
    )
    nodes = parse_cuts(pd.read_parquet(snake.input.cuts), subsystems)

    monthly, hourly_prices = solve_year(
        n,
        nodes,
        regimes,
        reservoirs,
        solver_name=snake.params.solver_name,
        solver_options=dict(snake.params.solver_options),
    )

    Path(snake.output.monthly).parent.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(snake.output.monthly, index=False)
    hourly_prices.rename_axis("snapshot").to_csv(snake.output.hourly_prices)
    summary = {
        "regimes_by_month": {int(k): int(v) for k, v in regimes.items()},
        "mean_price_rs_per_mwh_by_subsystem": hourly_prices.mean().round(2).to_dict(),
        "load_shed_mwh_by_subsystem": monthly.groupby("subsystem")["load_shed_mwh"]
        .sum()
        .round(0)
        .to_dict(),
        "storage_end_of_year_mwmes": monthly[monthly["month"] == 12]
        .set_index("subsystem")["storage_end_mwmes"]
        .round(0)
        .to_dict(),
        "known_limitations": KNOWN_LIMITATIONS,
    }
    Path(snake.output.summary).write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
