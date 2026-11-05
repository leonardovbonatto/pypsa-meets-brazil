# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Inputs for ADR-0011's policy: last month's inflow as an SDDP state.

**Why levels, not logs.** SDDP can remember something from one month to the
next only through a state that appears in the linear subproblem. The log-space
PAR(1) cannot: `inflow = exp(mu + sigma*z)` is nonlinear, and a `z` state got
zero cut coefficients (PR-40). In levels the recursion is linear,

    inflow_t = mu_m + Phi_m * (inflow_{t-1} - mu_{m-1}) + shock_scale_m * e_t,

with `Phi_m = phi_m * sd_m / sd_{m-1}` and `shock_scale_m = sd_m * sqrt(1 -
phi_m^2)`, so `inflow` can be a state and the cuts carry a coefficient on it.
This is NEWAVE's structure (PAR(p) in levels, past inflows as states).

**Noise.** `e_t` has mean 0 and variance 1 for every month. Where the fitted
residuals are right-skewed it is a three-parameter lognormal matched by
moments, with a floor that is fixed per month, so the recursion stays linear
(NEWAVE's floor depends on past inflows and is nonlinear). Spatial correlation
enters through the underlying normals, with PR-29's pooled matrix.

**Negative inflows remain possible** and are measured, not assumed away: the
Julia model absorbs them with a penalised slack. `validate_levels_model`
reproduces ADR-0011's table, which replaced ADR-0009's unreproducible one.

**Scoring stays on the log-PAR(1) paths** built by prepare_sddp_inputs. Each
path's inflows are converted back into the `e_t` that reproduce them exactly
under the levels recursion, so the policy is scored on the same water as every
earlier design.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fit_inflow_par1 import VALUE_COLUMN, aggregate_to_monthly

PHI_CLIP = 0.99

# At or below this residual skewness, Gaussian noise is used (ADR-0011).
SKEW_THRESHOLD = 0.05


def fit_levels_par1(monthly: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (subsystem, month) of the levels PAR(1): mean and standard
    deviation of that calendar month's inflow, `phi` (correlation with the
    preceding month, December -> January across the year boundary), the
    recursion's `Phi`, `mu_prev` and `shock_scale`, and the skewness of the
    standardized residuals.
    """
    rows = []
    for subsystem, group in monthly.groupby("subsystem"):
        wide = group.pivot(index="year", columns="month", values=VALUE_COLUMN)
        mu, sd = wide.mean(), wide.std()
        z = (wide - mu) / sd
        for month in range(1, 13):
            previous = 12 if month == 1 else month - 1
            lag = z[previous].shift(1) if month == 1 else z[previous]
            pair = pd.concat([z[month], lag], axis=1, keys=["z", "lag"]).dropna()
            phi = float(np.clip(pair["z"].corr(pair["lag"]), -PHI_CLIP, PHI_CLIP))
            residual = (pair["z"] - phi * pair["lag"]) / np.sqrt(1.0 - phi**2)
            rows.append(
                {
                    "subsystem": subsystem,
                    "month": month,
                    "mu": float(mu[month]),
                    "sd": float(sd[month]),
                    "phi": phi,
                    "mu_prev": float(mu[previous]),
                    "Phi": phi * float(sd[month] / sd[previous]),
                    "shock_scale": float(sd[month]) * np.sqrt(1.0 - phi**2),
                    "residual_skew": _skew(residual),
                }
            )
    return pd.DataFrame(rows).sort_values(["subsystem", "month"]).reset_index(drop=True)


def _skew(x: pd.Series) -> float:
    values = x.to_numpy(dtype=float)
    centred = values - values.mean()
    return float((centred**3).mean() / values.std() ** 3)


def lognormal3_by_moments(skewness: float) -> tuple[float, float, float]:
    """
    `(log_mu, log_sigma, floor)` of `floor + exp(N(log_mu, log_sigma^2))` with
    mean 0, variance 1 and the given positive skewness. Skewness alone sets
    `w = exp(log_sigma^2)` through `g = (w + 2) * sqrt(w - 1)`.
    """
    if skewness <= 0:
        raise ValueError(f"three-parameter lognormal needs positive skewness, got {skewness}")
    u = max(np.roots([1.0, 0.0, 3.0, -skewness]).real)  # u^3 + 3u = g, u = sqrt(w - 1)
    w = u**2 + 1.0
    scale = 1.0 / np.sqrt(w * (w - 1.0))
    return float(np.log(scale)), float(np.sqrt(np.log(w))), float(-scale * np.sqrt(w))


def standard_noise(normals: np.ndarray, skewness: float) -> np.ndarray:
    """Turn standard normals into ADR-0011's noise for one month: Gaussian at
    or below SKEW_THRESHOLD, otherwise the moments-matched lognormal."""
    if skewness <= SKEW_THRESHOLD:
        return normals
    log_mu, log_sigma, floor = lognormal3_by_moments(skewness)
    return floor + np.exp(log_mu + log_sigma * normals)


def sample_noise(
    model: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    n_noise: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """(month, scenario, subsystem) -> e, the training noise. The same set
    for every year, as SDDP's stagewise independence requires."""
    subsystems = list(corr_matrix.columns)
    cholesky_factor = np.linalg.cholesky(corr_matrix.loc[subsystems, subsystems].to_numpy())
    skew = model.set_index(["month", "subsystem"])["residual_skew"]
    rows = []
    for month in range(1, 13):
        normals = rng.normal(size=(n_noise, len(subsystems))) @ cholesky_factor.T
        for i, subsystem in enumerate(subsystems):
            noise = standard_noise(normals[:, i], float(skew[(month, subsystem)]))
            for scenario in range(n_noise):
                rows.append(
                    {
                        "month": month,
                        "scenario": scenario,
                        "subsystem": subsystem,
                        "e": float(noise[scenario]),
                        "probability": 1.0 / n_noise,
                    }
                )
    return pd.DataFrame(rows)


def initial_inflow(monthly: pd.DataFrame) -> pd.DataFrame:
    """subsystem -> mean inflow of the latest complete December, the month
    before stage 1 and the same date as prepare_sddp_inputs.initial_storage."""
    december = monthly[monthly["month"] == 12]
    latest = december["year"].max()
    return (
        december[december["year"] == latest][["subsystem", VALUE_COLUMN]]
        .rename(columns={VALUE_COLUMN: "initial_inflow_mwmed"})
        .assign(year=latest)
        .sort_values("subsystem")
        .reset_index(drop=True)
    )


def recover_noise(paths: pd.DataFrame, model: pd.DataFrame, start: pd.DataFrame) -> pd.DataFrame:
    """
    (path, month, subsystem) -> the e that makes the levels recursion
    reproduce each path's inflow exactly, starting from `start` in December.
    Values may fall outside the training noise's support; scoring only fixes
    them, so that is allowed.
    """
    lookup = model.set_index(["month", "subsystem"])
    previous = dict(zip(start["subsystem"], start["initial_inflow_mwmed"], strict=True))
    wide = paths.pivot_table(
        index=["path", "subsystem"], columns="month", values="inflow_mwmed"
    ).sort_index()
    rows = []
    for (path, subsystem), inflows in wide.iterrows():
        last = previous[subsystem]
        for month in range(1, 13):
            p = lookup.loc[(month, subsystem)]
            e = (inflows[month] - p["mu"] - p["Phi"] * (last - p["mu_prev"])) / p["shock_scale"]
            rows.append({"path": path, "month": month, "subsystem": subsystem, "e": float(e)})
            last = inflows[month]
    return pd.DataFrame(rows)


def simulate_levels(
    model: pd.DataFrame, subsystem: str, *, n_years: int, gaussian: bool, rng: np.random.Generator
) -> np.ndarray:
    """(n_years, 12) inflows from the levels model for one subsystem, after
    five burn-in years. Used only to validate the model."""
    p = model[model["subsystem"] == subsystem].sort_values("month")
    burn = 5
    normals = rng.standard_normal((n_years + burn, 12))
    noise = normals.copy()
    if not gaussian:
        for m, skew in enumerate(p["residual_skew"]):
            noise[:, m] = standard_noise(normals[:, m], float(skew))
    phi = p["phi"].to_numpy()
    z = np.zeros((n_years + burn, 12))
    last = 0.0
    for year in range(n_years + burn):
        for m in range(12):
            last = phi[m] * last + np.sqrt(1.0 - phi[m] ** 2) * noise[year, m]
            z[year, m] = last
    return (p["mu"].to_numpy() + p["sd"].to_numpy() * z)[burn:]


def persistence_metrics(inflow: np.ndarray) -> dict:
    """PR-45's measures on a (years, 12) array: share of negative months,
    mean lag-1 correlation of log inflow (negatives clipped to 1 MWmed for
    the log only), and the standard deviation of annual inflow (MWmed summed
    over 12 months)."""
    flat = inflow.reshape(-1)
    log_inflow = np.log(np.clip(inflow, 1.0, None))
    correlations = []
    for m in range(12):
        current = log_inflow[1:, m]
        previous = log_inflow[1:, m - 1] if m > 0 else log_inflow[:-1, 11]
        correlations.append(np.corrcoef(current, previous)[0, 1])
    return {
        "negative_month_share": float((flat < 0).mean()),
        "lag1_log_correlation": float(np.mean(correlations)),
        "annual_sd_mwmed": float(inflow.sum(axis=1).std()),
        "min_month_mwmed": float(flat.min()),
    }


def validate_levels_model(
    monthly: pd.DataFrame, model: pd.DataFrame, *, n_years: int, rng: np.random.Generator
) -> dict:
    """ADR-0011's table: history against the levels model with Gaussian and
    with lognormal noise, per subsystem."""
    report = {}
    for subsystem, group in monthly.groupby("subsystem"):
        history = group.pivot(index="year", columns="month", values=VALUE_COLUMN).dropna()
        report[subsystem] = {
            "history": persistence_metrics(history.to_numpy()),
            "levels_gaussian": persistence_metrics(
                simulate_levels(model, subsystem, n_years=n_years, gaussian=True, rng=rng)
            ),
            "levels_lognormal": persistence_metrics(
                simulate_levels(model, subsystem, n_years=n_years, gaussian=False, rng=rng)
            ),
        }
    return report


def write_parquet(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]
    seed = int(snake.params.seed)

    monthly = aggregate_to_monthly(pd.read_csv(snake.input.inflow, parse_dates=["date"]))
    corr_matrix = pd.read_csv(snake.input.par1_correlation).pivot(
        index="subsystem_a", columns="subsystem_b", values="correlation"
    )
    model = fit_levels_par1(monthly)
    start = initial_inflow(monthly)
    noise = sample_noise(
        model, corr_matrix, n_noise=int(snake.params.n_noise), rng=np.random.default_rng(seed)
    )
    scoring_noise = recover_noise(pd.read_parquet(snake.input.par1_paths), model, start)
    validation = validate_levels_model(
        monthly,
        model,
        n_years=int(snake.params.n_validation_years),
        rng=np.random.default_rng(seed + 3),
    )

    write_parquet(model, Path(snake.output.inflow_model))
    write_parquet(start, Path(snake.output.initial_inflow))
    write_parquet(noise, Path(snake.output.noise))
    write_parquet(scoring_noise, Path(snake.output.scoring_noise))
    Path(snake.output.validation).write_text(json.dumps(validation, indent=2) + "\n")


if __name__ == "__main__":
    main()
