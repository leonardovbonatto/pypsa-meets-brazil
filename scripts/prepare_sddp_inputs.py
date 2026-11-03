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

This module therefore emits two things instead of shocks-plus-parameters:

1. `transition_matrices` - one per stage, derived ANALYTICALLY from
   PR-28/29's already-fitted `phi_m`. No new estimation: given
   `z_t = phi_m*z_{t-1} + eps`, the probability of moving between
   quantile bins of the standard normal follows directly.
2. `scenarios` - inflow levels per (month, markov_state, scenario,
   subsystem). Within a regime, cross-subsystem spatial correlation is
   preserved exactly as before via Cholesky (PR-29).

One SHARED, system-wide regime is used rather than one per subsystem:
four independent chains would mean `K^4` joint states (81 at K=3) against
a model with a measured convergence ceiling. The system-wide `phi_m` is an
inflow-weighted mean of the per-subsystem values, weighted by each
subsystem's own lognormal mean inflow so that SE_CO (roughly four times
the others) dominates the national regime as it does in reality.

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

# scipy is present in this environment only transitively (via pypsa) and is
# not a declared dependency of this project, so the normal CDF is built from
# the standard library instead of importing it.
_ERF = np.vectorize(math.erf)
_SQRT2 = math.sqrt(2.0)

KNOWN_LIMITATIONS = [
    "The Markov root distribution is uniform across regimes (1/K each), the "
    "unconditional distribution of the standardized anomaly by construction "
    "of the equal-probability bins - not a real observed prior December. A "
    "deployment starting from a known dry regime would set the root "
    "distribution accordingly; SDDP.jl supports that directly, it is simply "
    "not what this annual-cycle model represents.",
    "The hydrological regime is discretized into K states (5 in rules/sddp.smk). "
    "Discretization is a real approximation and a coarse one: within a "
    "regime the anomaly is treated as a single conditional mean plus "
    "spatially-correlated variation, so a month at the dry edge of 'normal' "
    "and one at the wet edge are not distinguished.",
    "ONE system-wide regime is shared by all four subsystems, rather than a "
    "per-subsystem chain, to avoid K^4 joint states. Cross-subsystem "
    "correlation is preserved within a regime (PR-29's Cholesky), but a "
    "scenario where N is dry while S is wet is representable only through "
    "that within-regime variation, not as a distinct regime.",
    "The system-wide phi is an inflow-weighted mean of the per-subsystem "
    "fitted values. Real subsystem persistence varies widely (N 0.80-0.98, "
    "S 0.34-0.81, PR-28) and a single national figure cannot capture that.",
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


def _norm_cdf(x):
    """Standard normal CDF, built from stdlib `math.erf` - see the note at
    the import block for why not scipy."""
    return 0.5 * (1.0 + _ERF(np.asarray(x, dtype=float) / _SQRT2))


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


def system_phi_by_month(params: pd.DataFrame) -> pd.Series:
    """
    month -> ONE national persistence coefficient, an inflow-weighted mean
    of the per-subsystem fitted `phi_m`.

    Weighted by each subsystem's own lognormal mean inflow
    `exp(mu + sigma^2/2)` so that SE_CO - roughly four times the others -
    dominates the national regime as it does in reality. An unweighted mean
    would let the smallest subsystem move the national persistence as much
    as the largest.
    """
    work = params.assign(weight=np.exp(params["mu"] + 0.5 * params["sigma"] ** 2))
    weighted = work.groupby("month").apply(
        lambda g: np.average(g["phi"], weights=g["weight"]), include_groups=False
    )
    return weighted.rename("phi")


def transition_matrices(params: pd.DataFrame, *, n_states: int) -> pd.DataFrame:
    """
    (stage, from_state, to_state) -> transition probability, derived
    ANALYTICALLY from the fitted `phi_m` rather than estimated afresh.

    Given `z_t = phi_m * z_{t-1} + eps` with `eps ~ N(0, 1 - phi_m^2)`, and
    `z_{t-1}` distributed as a standard normal truncated to bin `i`:

        P(j | i) = (1/p) * integral over bin_i of
                   pdf(x) * [Phi((b_j - phi*x)/s) - Phi((a_j - phi*x)/s)] dx

    integrated numerically over a fine grid (infinite edges clipped at
    +-6 standard deviations, beyond which the standard normal carries
    ~1e-9 of its mass).

    `stage == 1` carries the ROOT distribution and uses `from_state = 0`:
    SDDP.jl requires the first transition matrix to be 1 x n_states. It is
    uniform, the unconditional distribution of the equal-probability bins.
    """
    bins = markov_bins(n_states)
    phi_by_month = system_phi_by_month(params)
    lower = bins["lower"].to_numpy()
    upper = bins["upper"].to_numpy()
    p = 1.0 / n_states

    rows = [
        {"stage": 1, "from_state": 0, "to_state": int(state), "probability": p}
        for state in bins["markov_state"]
    ]

    for stage in range(2, 13):
        # The transition INTO this stage is governed by the persistence of
        # the month being entered, matching how phi_m was fitted (this
        # month's anomaly regressed on the preceding month's).
        phi = float(np.clip(phi_by_month.loc[stage], -0.99, 0.99))
        shock_sd = math.sqrt(max(1.0 - phi**2, 1e-12))

        for i in range(n_states):
            a_i = max(lower[i], -6.0)
            b_i = min(upper[i], 6.0)
            grid = np.linspace(a_i, b_i, 2001)
            density = _norm_pdf(grid)

            probabilities = []
            for j in range(n_states):
                hi = _norm_cdf((min(upper[j], 6.0) - phi * grid) / shock_sd)
                lo = _norm_cdf((max(lower[j], -6.0) - phi * grid) / shock_sd)
                probabilities.append(float(np.trapezoid(density * (hi - lo), grid) / p))

            # Renormalize: the +-6 clipping and the quadrature both leave a
            # small residual, and SDDP.jl requires each row to sum to 1.
            total = sum(probabilities)
            for j, prob in enumerate(probabilities):
                rows.append(
                    {
                        "stage": stage,
                        "from_state": i + 1,
                        "to_state": j + 1,
                        "probability": prob / total,
                    }
                )

    return pd.DataFrame(rows)


def sample_markov_scenarios(
    params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    n_states: int,
    n_scenarios: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    (month, markov_state, scenario, subsystem) -> inflow in MWmed.

    The anomaly is decomposed into a regime level plus within-regime
    variation:

        z_s = regime_mean + regime_sd * u_s

    where `regime_mean`/`regime_sd` are the conditional moments of the bin
    (shared by all subsystems - this is the national regime) and `u_s` is a
    Cholesky-correlated standard normal draw preserving PR-29's real
    cross-subsystem correlation. Constructed this way, `z_s` recovers its
    unconditional N(0,1) distribution when averaged over regimes, so the
    marginal inflow distribution is unchanged from PR-31's - only its
    conditioning on an observable regime is new.
    """
    subsystems = list(corr_matrix.columns)
    cholesky_factor = np.linalg.cholesky(corr_matrix.loc[subsystems, subsystems].to_numpy())
    bins = markov_bins(n_states).set_index("markov_state")

    rows = []
    for month in range(1, 13):
        month_params = params[params["month"] == month].set_index("subsystem")
        for state in bins.index:
            regime_mean = float(bins.loc[state, "mean"])
            regime_sd = float(bins.loc[state, "sd"])
            for scenario in range(n_scenarios):
                correlated_unit = cholesky_factor @ rng.normal(size=len(subsystems))
                for i, subsystem in enumerate(subsystems):
                    row = month_params.loc[subsystem]
                    z = regime_mean + regime_sd * correlated_unit[i]
                    rows.append(
                        {
                            "month": month,
                            "markov_state": int(state),
                            "scenario": scenario,
                            "subsystem": subsystem,
                            "inflow_mwmed": float(np.exp(row["mu"] + row["sigma"] * z)),
                            "probability": 1.0 / n_scenarios,
                        }
                    )
    return pd.DataFrame(rows)


def sample_par1_paths(
    params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    n_states: int,
    n_paths: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    (path, month, subsystem) -> inflow in MWmed and the regime a policy would
    observe, simulated directly from the fitted PAR(1).

    An out-of-sample test set. `sample_markov_scenarios` draws independently
    within a regime, so it loses much of PAR(1)'s month-to-month persistence
    (PR-45 measured 0.48 vs 0.88 for N at K=3), and a policy scored on those
    scenarios is scored on milder droughts than the fit describes. These paths
    keep the full AR(1) and per-subsystem `phi`, so every K can be scored on
    the same world.

    The regime is read from the path itself: the inflow-weighted national
    anomaly, standardized and placed in the same bins as training.
    """
    subsystems = list(corr_matrix.columns)
    correlation = corr_matrix.loc[subsystems, subsystems].to_numpy()
    cholesky_factor = np.linalg.cholesky(correlation)
    upper = markov_bins(n_states)["upper"].to_numpy()
    lookup = params.set_index(["month", "subsystem"])

    rows = []
    z = rng.normal(size=(n_paths, len(subsystems))) @ cholesky_factor.T
    for month in range(1, 13):
        month_params = lookup.loc[month].loc[subsystems]
        mu = month_params["mu"].to_numpy()
        sigma = month_params["sigma"].to_numpy()
        if month > 1:
            phi = np.clip(month_params["phi"].to_numpy(), -0.99, 0.99)
            shock = rng.normal(size=(n_paths, len(subsystems))) @ cholesky_factor.T
            z = phi * z + np.sqrt(1.0 - phi**2) * shock

        weights = np.exp(mu + 0.5 * sigma**2)
        national = (z @ weights) / math.sqrt(weights @ correlation @ weights)
        states = np.searchsorted(upper, national) + 1
        inflow = np.exp(mu + sigma * z)
        for path in range(n_paths):
            for i, subsystem in enumerate(subsystems):
                rows.append(
                    {
                        "path": path,
                        "month": month,
                        "subsystem": subsystem,
                        "markov_state": int(states[path]),
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
    rng = np.random.default_rng(int(snake.params.seed))
    transitions = transition_matrices(par1_params, n_states=n_states)
    scenarios = sample_markov_scenarios(
        par1_params,
        corr_matrix,
        n_states=n_states,
        n_scenarios=int(snake.params.n_scenarios),
        rng=rng,
    )
    # A generator of its own, so that the inflows do not depend on how many
    # draws the scenarios above consumed: every K is scored on the same paths.
    par1_paths = sample_par1_paths(
        par1_params,
        corr_matrix,
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


if __name__ == "__main__":
    main()
