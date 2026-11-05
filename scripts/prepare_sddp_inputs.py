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

**Temporal persistence reaches the policy through a MARKOV STATE
(ADR-0009), not through an augmented continuous state.**

History worth knowing before reading the code. PR-38 tried carrying the
standardized log-inflow anomaly `z` as an ordinary `SDDP.State`, running
the AR(1) recursion in plain Julia inside `parameterize`. PR-40 measured
that this leaves the POLICY blind: because `exp(mu + sigma*z)` is
nonlinear, `z` could never appear in a `@constraint`, so the LP never saw
it, its dual was identically zero, and **every exported cut coefficient on
`z` was exactly 0.0**. Persistent scenarios, persistence-blind policy.
SDDP.jl's `add_objective_state` does not rescue this either - its own docs
forbid the state appearing in a constraint, and inflow must.

ADR-0009's fix, implemented here: discretise the hydrological regime into
a small number of **Markov states** (dry / normal / wet) and let SDDP.jl
maintain a separate value function per state. The regime is then something
the policy genuinely sees, because the value function is indexed by it.

ADR-0010 makes the regime REGIONAL: N+NE, SE_CO and S each have their own,
and the policy sees the joint regime (27 states at K=3). Transitions and
scenarios are counted and sampled from a large seeded simulation of the
fitted PAR(1), which keeps each region's own persistence and the
cross-region correlation without any new estimation. A separate set of PAR(1)
paths scores the trained policy out of sample.

Units, checked not assumed (see docs/handoffs/PR-31-*.md for the full
reasoning): at monthly granularity, ENA (MWmed), EAR (MWmes), and MW-based
generation/demand/capacity are all directly commensurable - Brazil's own
NEWAVE convention exists exactly so this arithmetic works without unit
conversion.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

KNOWN_LIMITATIONS = [
    "The Markov root distribution is the simulated stationary distribution of "
    "joint regimes - not a real observed prior December. A "
    "deployment starting from a known dry regime would set the root "
    "distribution accordingly; SDDP.jl supports that directly, it is simply "
    "not what this annual-cycle model represents.",
    "Each region's anomaly is discretized into K states (3 in rules/sddp.smk), "
    "and within a joint regime months are drawn independently, so some PAR(1) "
    "persistence is lost; sample_par1_paths measures how much (PR-45, ADR-0010).",
    "Three regions (N+NE, SE_CO, S), not four: N and NE share a regime, so a "
    "month where only one of them is dry is visible only within the regime.",
    "Transition probabilities and scenarios come from a finite simulation and "
    "carry sampling noise, set by n_simulated_years.",
    "12 monthly stages, one annual cycle - not the infinite-horizon cyclic "
    "policy graph SDDP.jl also supports and Brazil's real planning uses.",
    "No CVaR - expectation-only (ADR-0005 names this as this stage's explicit "
    "scope; risk aversion is the next stage).",
    "Transmission is the four T0 boundaries as transport flows bounded by "
    "links_t0.csv (ADR-0012): monthly-average flow against an hourly-maximum "
    "limit, which is generous; no losses, no load blocks.",
    "Hydro/thermal capacity from generators_t0.csv is instantaneous nameplate "
    "MW, applied as a bound on MONTHLY AVERAGE generation - rarely binding "
    "at this timescale, a real simplification of within-month unit commitment.",
    "Wind, solar, rooftop solar and nuclear enter as monthly-mean available "
    "MW from the T0 network, with free curtailment (ADR-0013); within-month "
    "variability (solar at night, wind lulls) is averaged away.",
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


# ADR-0013: the carriers SDDP takes as given each month rather than
# dispatching. Their availability comes from the built T0 network itself, so
# SDDP and PyPSA see the same wind, solar, rooftop solar and nuclear.
NET_LOAD_CARRIERS = ("wind", "solar", "solar_mmgd", "nuclear")


def monthly_renewables(
    available_mw: pd.DataFrame, bus_by_generator: pd.Series, *, subsystems: list[str]
) -> pd.DataFrame:
    """
    (month, subsystem) -> mean available MW of the net-load carriers.

    `available_mw` is hourly `p_max_pu * p_nom` per generator (columns), as
    PyPSA would cap it; `bus_by_generator` maps each column to its subsystem.
    A subsystem with none of these carriers gets 0, not a missing row.
    """
    unknown = set(available_mw.columns) - set(bus_by_generator.index)
    if unknown:
        raise ValueError(f"generator(s) without a bus: {sorted(unknown)}")
    by_bus = available_mw.T.groupby(bus_by_generator[available_mw.columns]).sum().T
    by_bus = by_bus.reindex(columns=subsystems, fill_value=0.0)
    monthly = by_bus.groupby(pd.DatetimeIndex(by_bus.index).month).mean()
    return (
        monthly.rename_axis(index="month", columns="subsystem")
        .stack()
        .rename("renewable_mw")
        .reset_index()
        .sort_values(["month", "subsystem"])
        .reset_index(drop=True)
    )


def network_renewables(network_path: Path, *, subsystems: list[str]) -> pd.DataFrame:
    """monthly_renewables on the built T0 network."""
    import pypsa

    n = pypsa.Network(str(network_path))
    generators = n.generators[n.generators["carrier"].isin(NET_LOAD_CARRIERS)]
    p_max_pu = n.get_switchable_as_dense("Generator", "p_max_pu")[generators.index]
    return monthly_renewables(
        p_max_pu * generators["p_nom"], generators["bus"], subsystems=subsystems
    )


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


def _norm_pdf(x):
    x = np.asarray(x, dtype=float)
    return np.exp(-0.5 * x**2) / math.sqrt(2.0 * math.pi)


def markov_bins(n_states: int) -> pd.DataFrame:
    """
    Equal-probability quantile bins of the standard normal, one per
    hydrological regime (state 1 = driest).

    `z` is standard normal unconditionally by construction of PR-28/29's
    standardization, so equal-probability bins need no data - they follow
    from the distribution itself. Returns each bin's edges, its conditional
    mean, and its conditional standard deviation:

        E[Z | a<Z<b]   = (pdf(a) - pdf(b)) / p
        Var[Z | a<Z<b] = 1 + (a*pdf(a) - b*pdf(b)) / p - mean^2

    with p = 1/n_states and the infinite tails contributing 0 to both
    `pdf(+-inf)` and `x*pdf(x)`.
    """
    if n_states < 2:
        raise ValueError(f"n_states must be at least 2, got {n_states}")

    standard_normal = NormalDist()
    inner = [standard_normal.inv_cdf(k / n_states) for k in range(1, n_states)]
    lower = [-np.inf, *inner]
    upper = [*inner, np.inf]
    p = 1.0 / n_states

    rows = []
    for state, (a, b) in enumerate(zip(lower, upper, strict=True), start=1):
        pdf_a = 0.0 if np.isneginf(a) else float(_norm_pdf(a))
        pdf_b = 0.0 if np.isposinf(b) else float(_norm_pdf(b))
        a_pdf_a = 0.0 if np.isneginf(a) else a * pdf_a
        b_pdf_b = 0.0 if np.isposinf(b) else b * pdf_b

        mean = (pdf_a - pdf_b) / p
        variance = 1.0 + (a_pdf_a - b_pdf_b) / p - mean**2
        rows.append(
            {
                "markov_state": state,
                "lower": a,
                "upper": b,
                "probability": p,
                "mean": mean,
                "sd": math.sqrt(max(variance, 0.0)),
            }
        )
    return pd.DataFrame(rows)


def _month_parameters(lookup: pd.DataFrame, subsystems: list[str], month: int):
    month_params = lookup.loc[month].loc[subsystems]
    return (
        month_params["mu"].to_numpy(),
        month_params["sigma"].to_numpy(),
        np.clip(month_params["phi"].to_numpy(), -0.99, 0.99),
    )


def simulate_par1_anomalies(
    params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    n_paths: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Standardized log-inflow anomalies `z`, shape (n_paths, 12, subsystems),
    from the fitted PAR(1): each subsystem's own `phi_m` and PR-29's
    cross-subsystem correlation, starting from the stationary distribution.
    Subsystems are ordered as `corr_matrix.columns`.
    """
    subsystems = list(corr_matrix.columns)
    cholesky_factor = np.linalg.cholesky(corr_matrix.loc[subsystems, subsystems].to_numpy())
    lookup = params.set_index(["month", "subsystem"])

    z = np.empty((n_paths, 12, len(subsystems)))
    z[:, 0] = rng.normal(size=(n_paths, len(subsystems))) @ cholesky_factor.T
    for month in range(2, 13):
        _, _, phi = _month_parameters(lookup, subsystems, month)
        shock = rng.normal(size=(n_paths, len(subsystems))) @ cholesky_factor.T
        z[:, month - 1] = phi * z[:, month - 2] + np.sqrt(1.0 - phi**2) * shock
    return z


def regional_states(
    z: np.ndarray,
    params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    regions: dict[str, list[str]],
    n_states: int,
) -> np.ndarray:
    """
    The joint regime, 1 to n_states**len(regions), for every path and month.

    Each region's regime is its own inflow-weighted anomaly, standardized
    with the fitted correlation so that it is N(0,1), placed in
    `markov_bins`. Weighting by `exp(mu + sigma^2/2)` lets the larger
    subsystem of a region dominate it, as it does in reality. The first region
    is the most significant digit, so state 1 is dry everywhere and the last
    state is wet everywhere.
    """
    subsystems = list(corr_matrix.columns)
    members = [s for names in regions.values() for s in names]
    if sorted(members) != sorted(subsystems):
        raise ValueError(f"regions {regions} must cover {subsystems} exactly once each")

    correlation = corr_matrix.loc[subsystems, subsystems].to_numpy()
    upper = markov_bins(n_states)["upper"].to_numpy()
    lookup = params.set_index(["month", "subsystem"])

    joint = np.zeros(z.shape[:2], dtype=int)
    for names in regions.values():
        columns = [subsystems.index(s) for s in names]
        block = correlation[np.ix_(columns, columns)]
        for month in range(1, 13):
            mu, sigma, _ = _month_parameters(lookup, names, month)
            weights = np.exp(mu + 0.5 * sigma**2)
            index = (z[:, month - 1, columns] @ weights) / math.sqrt(weights @ block @ weights)
            joint[:, month - 1] = joint[:, month - 1] * n_states + np.searchsorted(upper, index)
    return joint + 1


def joint_transitions(states: np.ndarray, *, n_joint: int) -> pd.DataFrame:
    """
    (stage, from_state, to_state) -> probability, counted from simulated
    regimes. `stage == 1` is the root, `from_state = 0`, as SDDP.jl requires
    a 1 x n first matrix.

    Counting replaces ADR-0009's analytic integrals, which do not extend
    cleanly to correlated regions (ADR-0010). A state never visited in a month
    would leave an empty row, which SDDP.jl cannot use, so that raises.
    """
    n_paths = states.shape[0]
    root = np.bincount(states[:, 0] - 1, minlength=n_joint) / n_paths
    rows = [
        {"stage": 1, "from_state": 0, "to_state": j + 1, "probability": float(p)}
        for j, p in enumerate(root)
    ]
    for stage in range(2, 13):
        counts = np.zeros((n_joint, n_joint))
        np.add.at(counts, (states[:, stage - 2] - 1, states[:, stage - 1] - 1), 1)
        totals = counts.sum(axis=1)
        if (totals == 0).any():
            missing = (np.flatnonzero(totals == 0) + 1).tolist()
            raise ValueError(f"states {missing} never visited before stage {stage}")
        probabilities = counts / totals[:, None]
        for i in range(n_joint):
            for j in range(n_joint):
                rows.append(
                    {
                        "stage": stage,
                        "from_state": i + 1,
                        "to_state": j + 1,
                        "probability": float(probabilities[i, j]),
                    }
                )
    return pd.DataFrame(rows)


def sample_regional_scenarios(
    z: np.ndarray,
    states: np.ndarray,
    params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    n_joint: int,
    n_scenarios: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    (month, markov_state, scenario, subsystem) -> inflow in MWmed, drawn from
    the simulated months that fell in that joint regime.

    Sampling whole simulated months keeps cross-subsystem correlation and each
    region's conditional distribution exactly as the PAR(1) produces them,
    with no moment-matching step to get wrong.
    """
    subsystems = list(corr_matrix.columns)
    lookup = params.set_index(["month", "subsystem"])

    rows = []
    for month in range(1, 13):
        mu, sigma, _ = _month_parameters(lookup, subsystems, month)
        for state in range(1, n_joint + 1):
            pool = np.flatnonzero(states[:, month - 1] == state)
            if len(pool) < n_scenarios:
                raise ValueError(
                    f"month {month} state {state}: {len(pool)} simulated months, need {n_scenarios}"
                )
            chosen = rng.choice(pool, size=n_scenarios, replace=False)
            inflow = np.exp(mu + sigma * z[chosen, month - 1])
            for scenario in range(n_scenarios):
                for i, subsystem in enumerate(subsystems):
                    rows.append(
                        {
                            "month": month,
                            "markov_state": state,
                            "scenario": scenario,
                            "subsystem": subsystem,
                            "inflow_mwmed": float(inflow[scenario, i]),
                            "probability": 1.0 / n_scenarios,
                        }
                    )
    return pd.DataFrame(rows)


def sample_par1_paths(
    params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    regions: dict[str, list[str]],
    n_states: int,
    n_paths: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    (path, month, subsystem) -> inflow in MWmed and the joint regime a policy
    would observe, simulated directly from the fitted PAR(1).

    An out-of-sample test set. Training scenarios are drawn independently
    month to month within a regime, so they lose some of PAR(1)'s persistence
    (PR-45 measured 0.48 vs 0.88 for N with one national regime at K=3). These
    paths keep the full AR(1), so every regime design is scored on the same
    world: with the same `rng` seed the inflows do not depend on `regions` or
    `n_states`.
    """
    subsystems = list(corr_matrix.columns)
    z = simulate_par1_anomalies(params, corr_matrix, n_paths=n_paths, rng=rng)
    states = regional_states(z, params, corr_matrix, regions=regions, n_states=n_states)
    lookup = params.set_index(["month", "subsystem"])

    rows = []
    for month in range(1, 13):
        mu, sigma, _ = _month_parameters(lookup, subsystems, month)
        inflow = np.exp(mu + sigma * z[:, month - 1])
        for path in range(n_paths):
            for i, subsystem in enumerate(subsystems):
                rows.append(
                    {
                        "path": path,
                        "month": month,
                        "subsystem": subsystem,
                        "markov_state": int(states[path, month - 1]),
                        "inflow_mwmed": float(inflow[path, i]),
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
    n_states = int(snake.params.n_markov_states)
    regions = dict(snake.params.regions)
    n_joint = n_states ** len(regions)

    z = simulate_par1_anomalies(
        par1_params,
        corr_matrix,
        n_paths=int(snake.params.n_simulated_years),
        rng=np.random.default_rng(int(snake.params.seed)),
    )
    states = regional_states(z, par1_params, corr_matrix, regions=regions, n_states=n_states)
    transitions = joint_transitions(states, n_joint=n_joint)
    scenarios = sample_regional_scenarios(
        z,
        states,
        par1_params,
        corr_matrix,
        n_joint=n_joint,
        n_scenarios=int(snake.params.n_scenarios),
        rng=np.random.default_rng(int(snake.params.seed) + 2),
    )
    # A generator of its own, so that the inflows are the same for any regime
    # design: every design is scored on the same paths.
    par1_paths = sample_par1_paths(
        par1_params,
        corr_matrix,
        regions=regions,
        n_states=n_states,
        n_paths=int(snake.params.n_par1_paths),
        rng=np.random.default_rng(int(snake.params.seed) + 1),
    )

    write_parquet(demand, Path(snake.output.demand))
    write_parquet(capacity, Path(snake.output.capacity))
    write_parquet(cost, Path(snake.output.cost))
    write_parquet(reservoir_capacity, Path(snake.output.reservoir_capacity))
    write_parquet(storage0, Path(snake.output.initial_storage))
    write_parquet(transitions, Path(snake.output.transitions))
    write_parquet(scenarios, Path(snake.output.scenarios))
    write_parquet(par1_paths, Path(snake.output.par1_paths))
    # ADR-0012: the T0 boundaries and capacities, unchanged, so SDDP and PyPSA
    # see one network.
    write_parquet(pd.read_csv(snake.input.links), Path(snake.output.links))
    write_parquet(
        network_renewables(Path(snake.input.network), subsystems=sorted(storage0["subsystem"])),
        Path(snake.output.renewables),
    )


if __name__ == "__main__":
    main()
