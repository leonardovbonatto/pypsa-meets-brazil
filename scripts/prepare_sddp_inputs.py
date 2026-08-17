# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Assemble every real input the first SDDP policy (ADR-0005 stage 1f) needs
into Parquet files `julia/sddp_first_policy.jl` reads: monthly demand,
hydro/thermal capacity, thermal cost, initial reservoir storage, and
correlated monthly inflow scenarios.

**Real data throughout, joined from what earlier PRs already built** -
`resources/demand_t0.csv` (T0), `resources/generators_t0.csv` (T0),
`resources/costs_t0.csv` (T0), `resources/reservoir_ear_capacity.csv` and
`_history.csv` (PR-30), `resources/inflow_par1_params.csv` and
`_correlation.csv` (PR-28/29). Nothing here is fabricated; the one
genuinely new judgement call is scenario sampling (below).

**A real, named simplification**: inflow scenarios are drawn i.i.d. per
month from each month's fitted marginal distribution, correlated ACROSS
subsystems within a month (PR-29's matrix, via Cholesky) but NOT
autocorrelated month-to-month WITHIN the policy. PR-28's fitted phi
(temporal persistence) is real and validated, but wiring it into an SDDP
policy graph needs state augmentation (carrying the previous month's
standardized shock as an extra state variable) - a real, separately
scoped follow-up, not attempted in this first policy. Named explicitly in
KNOWN_LIMITATIONS, not silently dropped.

Units, checked not assumed (see docs/handoffs/PR-31-*.md for the full
reasoning): at monthly granularity, ENA (MWmed), EAR (MWmes), and MW-based
generation/demand/capacity are all directly commensurable - Brazil's own
NEWAVE convention exists exactly so this arithmetic works without unit
conversion.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

KNOWN_LIMITATIONS = [
    "Inflow scenarios are i.i.d. per month, NOT autocorrelated month-to-month "
    "within the policy - PAR(1)'s fitted phi (PR-28) is real and validated but "
    "not yet wired into SDDP's state, which would need carrying the previous "
    "month's standardized shock as an extra state variable per subsystem.",
    "12 monthly stages, one annual cycle - not the infinite-horizon cyclic "
    "policy graph SDDP.jl also supports and Brazil's real planning uses.",
    "No CVaR - expectation-only (ADR-0005 names this as this stage's explicit "
    "scope; risk aversion is the next stage).",
    "No inter-subsystem transmission in the SDDP subproblem itself - PRIMER "
    "Sec 4.5's architecture puts real network coupling in PyPSA/linopy once "
    "cuts are consumed there, not in this reduced hydro-thermal model.",
    "Hydro/thermal capacity from generators_t0.csv is instantaneous nameplate "
    "MW, applied as a bound on MONTHLY AVERAGE generation - rarely binding "
    "at this timescale, a real simplification of within-month unit commitment.",
    "Wind, solar and nuclear are excluded from this reduced model - they are "
    "not part of the reservoir-storage decision SDDP solves; PyPSA handles "
    "them directly once cuts are coupled in.",
]


def monthly_demand(demand_t0: pd.DataFrame) -> pd.DataFrame:
    """(month, subsystem) -> mean hourly load, MW. T0's demand spans exactly
    one calendar year, so grouping by month number alone gives 12 rows/subsystem."""
    work = demand_t0.assign(month=pd.to_datetime(demand_t0["snapshot"]).dt.month)
    return (
        work.groupby(["month", "subsystem"], as_index=False)["load_mw"]
        .mean()
        .rename(columns={"load_mw": "demand_mw"})
        .sort_values(["month", "subsystem"])
        .reset_index(drop=True)
    )


def hydro_thermal_capacity(generators_t0: pd.DataFrame) -> pd.DataFrame:
    """subsystem -> hydro_mw, thermal_mw nameplate capacity - the two carriers
    this reduced model dispatches (see KNOWN_LIMITATIONS on wind/solar/nuclear)."""
    wide = (
        generators_t0[generators_t0["carrier"].isin(["hydro", "thermal"])]
        .pivot(index="subsystem", columns="carrier", values="p_nom_mw")
        .rename(columns={"hydro": "hydro_mw", "thermal": "thermal_mw"})
        .reset_index()
    )
    missing = {"hydro_mw", "thermal_mw"} - set(wide.columns)
    if missing:
        raise ValueError(f"subsystem(s) missing {missing} in generators_t0.csv")
    return wide.sort_values("subsystem").reset_index(drop=True)


def thermal_cost(costs_t0: pd.DataFrame) -> pd.DataFrame:
    """subsystem -> marginal_cost, R$/MWh. costs_t0.csv already carries only
    thermal (PR-10) - non-thermal carriers get marginal_cost=0 elsewhere in the
    pipeline, not stored here at all."""
    return costs_t0[["subsystem", "marginal_cost"]].sort_values("subsystem").reset_index(drop=True)


def initial_storage(reservoir_history: pd.DataFrame) -> pd.DataFrame:
    """subsystem -> the MOST RECENT date's real verified storage, MWmes - a
    genuine observed starting condition, not an assumed full/empty reservoir."""
    latest_date = reservoir_history["date"].max()
    return (
        reservoir_history[reservoir_history["date"] == latest_date][
            ["subsystem", "ear_verif_mwmes"]
        ]
        .rename(columns={"ear_verif_mwmes": "initial_storage_mwmes"})
        .sort_values("subsystem")
        .reset_index(drop=True)
    )


def sample_month_scenarios(
    params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    n_scenarios: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    (month, scenario, subsystem) -> a sampled inflow (MWmed), drawn i.i.d.
    across months and scenarios but CORRELATED across subsystems within
    each (month, scenario) draw - see module docstring for why not
    autocorrelated across months too. Each scenario within a month is
    equally likely (1/n_scenarios) - a real, named simplification;
    unequal historically-weighted probabilities are a possible refinement,
    not attempted here.
    """
    subsystems = list(corr_matrix.columns)
    cholesky_factor = np.linalg.cholesky(corr_matrix.loc[subsystems, subsystems].to_numpy())

    rows = []
    for month in range(1, 13):
        month_params = params[params["month"] == month].set_index("subsystem")
        for scenario in range(n_scenarios):
            correlated_unit = cholesky_factor @ rng.normal(size=len(subsystems))
            for i, subsystem in enumerate(subsystems):
                row = month_params.loc[subsystem]
                inflow = float(np.exp(row["mu"] + row["sigma"] * correlated_unit[i]))
                rows.append(
                    {
                        "month": month,
                        "scenario": scenario,
                        "subsystem": subsystem,
                        "inflow_mwmed": inflow,
                        "probability": 1.0 / n_scenarios,
                    }
                )
    return pd.DataFrame(rows)


def write_parquet(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    demand = monthly_demand(pd.read_csv(snake.input.demand))
    capacity = hydro_thermal_capacity(pd.read_csv(snake.input.generators))
    cost = thermal_cost(pd.read_csv(snake.input.costs))
    reservoir_capacity = pd.read_csv(snake.input.reservoir_capacity)
    storage0 = initial_storage(pd.read_csv(snake.input.reservoir_history, parse_dates=["date"]))

    par1_params = pd.read_csv(snake.input.par1_params)
    corr_matrix = pd.read_csv(snake.input.par1_correlation).pivot(
        index="subsystem_a", columns="subsystem_b", values="correlation"
    )
    rng = np.random.default_rng(int(snake.params.seed))
    scenarios = sample_month_scenarios(
        par1_params, corr_matrix, n_scenarios=int(snake.params.n_scenarios), rng=rng
    )

    write_parquet(demand, Path(snake.output.demand))
    write_parquet(capacity, Path(snake.output.capacity))
    write_parquet(cost, Path(snake.output.cost))
    write_parquet(reservoir_capacity, Path(snake.output.reservoir_capacity))
    write_parquet(storage0, Path(snake.output.initial_storage))
    write_parquet(scenarios, Path(snake.output.scenarios))


if __name__ == "__main__":
    main()
