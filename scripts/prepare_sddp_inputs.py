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
genuinely new judgement call is shock sampling (below).

**Temporal persistence (PR-38, corrected by PR-40): this module emits
SHOCKS, not inflow levels.**

PR-40 correction, read this before trusting anything below: the AR(1)
recursion described here does make the sampled SCENARIOS autocorrelated
(real and working), but it does NOT make the SDDP policy aware of that
autocorrelation. `z` never enters the Julia model's LP - it is read with
`fix_value`, used in plain-Julia arithmetic, and fixed back as a constant -
so its dual is identically zero and every exported cut coefficient on it is
exactly 0.0 (measured across all 22,000 cuts). The policy is
persistence-blind; fixing that needs a different formulation and its own
ADR. See docs/handoffs/PR-40-*.md.
 Earlier (PR-31-36), `sample_month_scenarios` drew i.i.d. inflow
LEVELS directly (`exp(mu + sigma*shock)`) - the fitted phi went along for
the ride in `par1_params.csv` but was never applied, so the SDDP policy
saw no autocorrelation month-to-month (named explicitly in
KNOWN_LIMITATIONS at the time). Wiring phi in needs a state variable that
carries the previous month's standardized log-inflow anomaly forward - the
AR(1) recursion `z_t = phi*z_{t-1} + shock_t` and the `exp(mu+sigma*z_t)`
transform now both happen in Julia (`julia/sddp_first_policy.jl`), inside
`SDDP.parameterize`, using a plain (non-experimental) `SDDP.State` for `z`
- verified directly (a real Julia smoke test, not assumed) that a normal
state's incoming value is queryable via `JuMP.fix_value` inside
`parameterize`, letting `z.out` and the real `inflow` variable (which must
enter the storage-balance CONSTRAINT, not just the objective) both be
`fix()`-ed to plain-Julia-computed numbers with no nonlinear JuMP
expression involved. SDDP.jl's own `add_objective_state` mechanism was
investigated and REJECTED first: its own docs state the price/objective
state "cannot appear in any @constraint" - inflow must, by definition, so
that mechanism does not apply here (see docs/handoffs/PR-38-*.md for the
full investigation).

This module's job is now only to supply the CORRELATED STANDARDIZED SHOCKS
per (month, scenario) - `sample_month_shocks`, Cholesky-correlated across
subsystems exactly as before, just without the now-relocated `exp(mu +
sigma*.)` transform - plus a straight pass-through of `par1_params.csv`
(mu/sigma/phi) for Julia to apply the AR(1) recursion with.

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
    "The AR(1) root node (start of the annual cycle) uses z=0 for every "
    "subsystem - the unconditional mean anomaly, not a real observed "
    "December's actual wet/dry state. SDDP.jl's root node must be a single "
    "deterministic starting point; a deployment that starts from a known "
    "real (e.g. severely dry) prior month would need a different, "
    "scenario-conditioned root, not attempted here.",
    "The discrete shock set per month (n_scenarios, currently 10) is drawn "
    "once and reused across all years of the annual cycle - the same "
    "finite-scenario discretization PR-31 already used for i.i.d. levels, "
    "now applied to the raw shocks that feed the AR(1) recursion instead.",
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


def sample_month_shocks(
    corr_matrix: pd.DataFrame,
    *,
    n_scenarios: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    (month, scenario, subsystem) -> a standardized-normal SHOCK (mean 0,
    unit variance before phi/sigma are applied), drawn i.i.d. across
    months and scenarios but CORRELATED across subsystems within each
    (month, scenario) draw via Cholesky decomposition of `corr_matrix` -
    the same cross-subsystem correlation mechanism as before (PR-29), just
    stopping short of the `exp(mu + sigma*.)` transform, which now happens
    in Julia after the AR(1) recursion (see module docstring). Each
    scenario within a month is equally likely (1/n_scenarios) - a real,
    named simplification; unequal historically-weighted probabilities are
    a possible refinement, not attempted here.
    """
    subsystems = list(corr_matrix.columns)
    cholesky_factor = np.linalg.cholesky(corr_matrix.loc[subsystems, subsystems].to_numpy())

    rows = []
    for month in range(1, 13):
        for scenario in range(n_scenarios):
            correlated_unit = cholesky_factor @ rng.normal(size=len(subsystems))
            for i, subsystem in enumerate(subsystems):
                rows.append(
                    {
                        "month": month,
                        "scenario": scenario,
                        "subsystem": subsystem,
                        "shock": float(correlated_unit[i]),
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
    shocks = sample_month_shocks(corr_matrix, n_scenarios=int(snake.params.n_scenarios), rng=rng)

    write_parquet(demand, Path(snake.output.demand))
    write_parquet(capacity, Path(snake.output.capacity))
    write_parquet(cost, Path(snake.output.cost))
    write_parquet(reservoir_capacity, Path(snake.output.reservoir_capacity))
    write_parquet(storage0, Path(snake.output.initial_storage))
    write_parquet(par1_params, Path(snake.output.inflow_params))
    write_parquet(shocks, Path(snake.output.shocks))


if __name__ == "__main__":
    main()
