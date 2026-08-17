# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Fit a PAR(1) (Periodic AutoRegressive, order 1) inflow model per subsystem
from the tidy ENA series (ADR-0005, SDDP epic stage 1c: persistence).

PAR(p) is the Brazilian standard (PRIMER Sec 4.7): autoregressive
coefficients vary by calendar month because inflow seasonality is strong,
fitted on log-transformed flows since they are positive and skewed. This
module fits the simplest defensible order - PAR(1), not a higher order
chosen via AIC/PACF - and validates BOTH of PRIMER Sec 4.7's required
properties: persistence (drought duration, PR-28) and spatial correlation
across subsystems (PR-29). Spatial correlation is preserved via correlated
residuals (Cholesky decomposition of the cross-subsystem residual
correlation matrix), pooled across all calendar months into a single 4x4
matrix rather than fit per-month - a real, documented simplification (see
KNOWN_LIMITATIONS), not an oversight, given only ~26 observations per
specific month.

Fits on GROSS inflow (`ena_bruta_mwmed`), not storable
(`ena_armazenavel_mwmed`): gross is the exogenous hydrological quantity a
stochastic model should represent. Storable already nets out historical
spill decisions - an operational choice made under the real system's past
policy, not part of the random process itself.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

VALUE_COLUMN = "ena_bruta_mwmed"

KNOWN_LIMITATIONS = [
    "PAR(1) only - order 1, not selected via AIC/PACF. The simplest defensible "
    "first cut, not a re-derivation of NEWAVE's per-REE order selection.",
    "Spatial correlation is a SINGLE matrix pooled across all 12 calendar "
    "months, not fit per-month - only ~26 observations per specific month "
    "made a month-specific 4x4 matrix too noisy to trust. Real cross-"
    "subsystem correlation likely varies by season (e.g. N/NE's wet "
    "seasons do not coincide); this pooled matrix cannot capture that.",
    "Fit on 26 years of ENA (2000-2025, ADR-0005), not VAZOES.DAT's ~95 "
    "years - materially less data to estimate rare/severe drought "
    "persistence AND cross-subsystem correlation from.",
    "Fit on gross ena_bruta_mwmed - see module docstring for why storable "
    "was rejected as the modelled quantity.",
]


def aggregate_to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (subsystem, year, month): mean of the daily gross ENA series."""
    dates = pd.to_datetime(df["date"])
    monthly = df.assign(year=dates.dt.year, month=dates.dt.month)
    return (
        monthly.groupby(["subsystem", "year", "month"], as_index=False)[VALUE_COLUMN]
        .mean()
        .sort_values(["subsystem", "year", "month"])
        .reset_index(drop=True)
    )


def fit_par1_by_month(monthly: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (subsystem, month, 1-12): mu/sigma of log(ENA) for that
    calendar month across all years, and phi - the lag-1 autocorrelation
    between that month's standardized log ENA and the PRECEDING calendar
    month's (wrapping December -> January across a year boundary).
    """
    work = monthly.assign(log_ena=np.log(monthly[VALUE_COLUMN]))
    stats = (
        work.groupby(["subsystem", "month"])["log_ena"].agg(mu="mean", sigma="std").reset_index()
    )
    work = work.merge(stats, on=["subsystem", "month"]).sort_values(["subsystem", "year", "month"])
    work["z"] = (work["log_ena"] - work["mu"]) / work["sigma"]
    work["z_lag1"] = work.groupby("subsystem")["z"].shift(1)
    work["month_lag1"] = work.groupby("subsystem")["month"].shift(1)

    # Keep only rows where the lag really is the immediately preceding
    # calendar month (handles the December -> January wrap: month 1's
    # predecessor is 12, not 0).
    expected_lag_month = ((work["month"] - 2) % 12) + 1
    work = work[work["month_lag1"] == expected_lag_month]

    phi = (
        work.groupby(["subsystem", "month"])
        .apply(lambda g: g["z"].corr(g["z_lag1"]), include_groups=False)
        .rename("phi")
        .reset_index()
    )
    params = stats.merge(phi, on=["subsystem", "month"])
    return params.sort_values(["subsystem", "month"]).reset_index(drop=True)


def simulate_par1(params: pd.DataFrame, *, n_years: int, rng: np.random.Generator) -> pd.DataFrame:
    """
    One synthetic n_years-long monthly series per subsystem, sampled from
    the fitted PAR(1) parameters.

    Recursion in standardized log space: z_t = phi_m * z_{t-1} + eps_t,
    eps_t ~ N(0, 1 - phi_m^2) - the standard PAR(1) approximation that
    keeps each calendar month's unconditional variance at 1 despite phi
    varying month to month. phi is clipped to [-0.99, 0.99] so the shock
    variance never goes to (or below) zero.
    """
    rows = []
    for subsystem, group in params.groupby("subsystem"):
        by_month = group.set_index("month")
        z_prev = rng.normal()
        for year in range(n_years):
            for month in range(1, 13):
                row = by_month.loc[month]
                phi = float(np.clip(row["phi"], -0.99, 0.99))
                shock_sd = float(np.sqrt(max(1 - phi**2, 1e-6)))
                z = phi * z_prev + rng.normal(scale=shock_sd)
                ena = float(np.exp(row["mu"] + row["sigma"] * z))
                rows.append(
                    {"subsystem": subsystem, "year": year, "month": month, VALUE_COLUMN: ena}
                )
                z_prev = z
    return pd.DataFrame(rows)


def compute_residuals(monthly: pd.DataFrame, params: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (subsystem, year, month): the standardized AR(1) residual
    epsilon_t = z_t - phi_m * z_{t-1} - what is left after removing each
    subsystem's OWN predictable persistence. This, not the raw ENA series,
    is the basis for spatial correlation: whether subsystems' unexplained
    month-to-month surprises move together, not whether they share the
    same seasonal pattern (which mu_m/sigma_m already capture separately).
    """
    work = monthly.assign(log_ena=np.log(monthly[VALUE_COLUMN])).merge(
        params[["subsystem", "month", "mu", "sigma", "phi"]], on=["subsystem", "month"]
    )
    work = work.sort_values(["subsystem", "year", "month"])
    work["z"] = (work["log_ena"] - work["mu"]) / work["sigma"]
    work["z_lag1"] = work.groupby("subsystem")["z"].shift(1)
    work["month_lag1"] = work.groupby("subsystem")["month"].shift(1)

    expected_lag_month = ((work["month"] - 2) % 12) + 1
    work = work[work["month_lag1"] == expected_lag_month]
    work["residual"] = work["z"] - work["phi"] * work["z_lag1"]
    return work[["subsystem", "year", "month", "residual"]].reset_index(drop=True)


def residual_correlation_matrix(residuals: pd.DataFrame) -> pd.DataFrame:
    """
    subsystem x subsystem correlation of SAME-(year, month) residuals,
    pooled across all calendar months (see module docstring for why not
    per-month) - PRIMER Sec 4.7's spatial correlation: real Brazilian
    basins are correlated, so a dry month in one subsystem tends to
    coincide with dry months elsewhere, not be independent of them.
    """
    wide = residuals.pivot_table(index=["year", "month"], columns="subsystem", values="residual")
    return wide.corr()


def simulate_par1_correlated(
    params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    n_years: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    Synthetic n_years-long monthly series for ALL subsystems jointly, one
    correlated draw per (year, month) via Cholesky decomposition of
    `corr_matrix` rather than `simulate_par1`'s independent per-subsystem
    draws. This is what actually preserves PRIMER Sec 4.7's spatial
    correlation requirement.
    """
    subsystems = list(corr_matrix.columns)
    cholesky_factor = np.linalg.cholesky(corr_matrix.loc[subsystems, subsystems].to_numpy())

    by_subsystem_month = {(row.subsystem, row.month): row for row in params.itertuples()}
    z_prev = dict.fromkeys(subsystems, 0.0)
    for subsystem in subsystems:
        z_prev[subsystem] = rng.normal()

    rows = []
    for year in range(n_years):
        for month in range(1, 13):
            independent_draw = rng.normal(size=len(subsystems))
            correlated_unit = cholesky_factor @ independent_draw
            for i, subsystem in enumerate(subsystems):
                row = by_subsystem_month[(subsystem, month)]
                phi = float(np.clip(row.phi, -0.99, 0.99))
                shock_sd = float(np.sqrt(max(1 - phi**2, 1e-6)))
                z = phi * z_prev[subsystem] + correlated_unit[i] * shock_sd
                ena = float(np.exp(row.mu + row.sigma * z))
                rows.append(
                    {"subsystem": subsystem, "year": year, "month": month, VALUE_COLUMN: ena}
                )
                z_prev[subsystem] = z
    return pd.DataFrame(rows)


def validate_spatial_correlation(
    monthly: pd.DataFrame,
    params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    n_realizations: int = 200,
    seed: int = 0,
) -> dict:
    """
    Does the correlated simulator actually REPRODUCE the real historical
    cross-subsystem correlation - not just have it baked into an input
    matrix, which would prove nothing about whether fit -> Cholesky ->
    simulate -> re-estimate is wired correctly end to end?

    Simulates `n_realizations` correlated series, recomputes each one's OWN
    residual correlation matrix from ITS output (the same estimation
    procedure used on the real data), and reports the mean simulated
    correlation per subsystem pair against the historical value.
    """
    n_years = monthly["year"].nunique()
    rng = np.random.default_rng(seed)
    subsystems = list(corr_matrix.columns)

    simulated_corrs = []
    for _ in range(n_realizations):
        sim = simulate_par1_correlated(params, corr_matrix, n_years=n_years, rng=rng)
        sim_residuals = compute_residuals(sim, params)
        simulated_corrs.append(
            residual_correlation_matrix(sim_residuals).loc[subsystems, subsystems]
        )

    mean_simulated = sum(simulated_corrs) / len(simulated_corrs)

    report = {}
    for i, a in enumerate(subsystems):
        for b in subsystems[i + 1 :]:
            report[f"{a}-{b}"] = {
                "historical_correlation": float(corr_matrix.loc[a, b]),
                "mean_simulated_correlation": float(mean_simulated.loc[a, b]),
            }
    return report


def month_thresholds(historical_monthly: pd.DataFrame, *, percentile: float) -> pd.DataFrame:
    """
    (subsystem, month) -> the historical `percentile`-th ENA value - a
    FIXED reference "dry" threshold, so historical and simulated series
    are judged against the same bar rather than each against its own.
    """
    return (
        historical_monthly.groupby(["subsystem", "month"])[VALUE_COLUMN]
        .quantile(percentile)
        .rename("threshold")
        .reset_index()
    )


def max_drought_run(monthly: pd.DataFrame, thresholds: pd.DataFrame) -> pd.Series:
    """Longest run of consecutive months below the fixed per-(subsystem, month)
    threshold, one value per subsystem."""
    merged = monthly.merge(thresholds, on=["subsystem", "month"]).sort_values(
        ["subsystem", "year", "month"]
    )
    merged["dry"] = merged[VALUE_COLUMN] < merged["threshold"]

    results = {}
    for subsystem, g in merged.groupby("subsystem"):
        max_run = current = 0
        for dry in g["dry"].to_numpy():
            current = current + 1 if dry else 0
            max_run = max(max_run, current)
        results[subsystem] = max_run
    return pd.Series(results, name="max_drought_run_months")


def validate_persistence(
    historical_monthly: pd.DataFrame,
    params: pd.DataFrame,
    *,
    n_realizations: int = 200,
    percentile: float = 0.3,
    seed: int = 0,
) -> dict:
    """
    Does the fitted model produce droughts as long as the real record's, or
    does it understate persistence - PRIMER Sec 4.7's named failure mode
    ("too-short droughts make the model far too optimistic about storage")?

    Simulates `n_realizations` independent series (same length as the
    historical record) per subsystem and reports where the single real
    historical drought-run length falls within that simulated distribution.
    A percentile near 0.5 means the model treats history as a typical draw
    from its own distribution; a percentile near 1.0 means real droughts
    are longer than nearly every simulated one - understated persistence,
    the exact failure this check exists to catch. One 26-year historical
    record is a small sample - this is a diagnostic, not a hypothesis test.
    """
    thresholds = month_thresholds(historical_monthly, percentile=percentile)
    historical_run = max_drought_run(historical_monthly, thresholds)

    n_years = historical_monthly["year"].nunique()
    rng = np.random.default_rng(seed)
    simulated_runs = pd.DataFrame(
        [
            max_drought_run(simulate_par1(params, n_years=n_years, rng=rng), thresholds)
            for _ in range(n_realizations)
        ]
    )

    report = {}
    for subsystem in historical_run.index:
        sim_values = simulated_runs[subsystem]
        hist_value = int(historical_run[subsystem])
        report[subsystem] = {
            "historical_max_drought_run_months": hist_value,
            "simulated_median_max_drought_run_months": float(sim_values.median()),
            "historical_percentile_within_simulated": float((sim_values <= hist_value).mean()),
        }
    return report


def write_params(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def write_correlation_matrix(corr_matrix: pd.DataFrame, out_path: Path) -> Path:
    """Tidy long format (subsystem_a, subsystem_b, correlation) - easier for a
    downstream Julia reader to consume than a wide matrix with subsystem names
    as both column headers and an index.

    `.corr()` leaves both axes named "subsystem" (inherited from the pivot
    that built it) - `.stack().reset_index()` on that raises
    `ValueError: cannot insert subsystem, already exists`, since both levels
    would produce the same column name. Rename the axes first so they're
    distinct before stacking.
    """
    matrix = corr_matrix.copy()
    matrix.index.name = "subsystem_a"
    matrix.columns.name = "subsystem_b"
    tidy = matrix.stack().rename("correlation").reset_index()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tidy.to_csv(out_path, index=False)
    return out_path


def write_validation_report(persistence_report: dict, spatial_report: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "persistence_by_subsystem": persistence_report,
        "spatial_correlation_by_subsystem_pair": spatial_report,
        "known_limitations": KNOWN_LIMITATIONS,
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    df = pd.read_csv(Path(snake.input[0]), parse_dates=["date"])
    monthly = aggregate_to_monthly(df)
    params = fit_par1_by_month(monthly)

    persistence_report = validate_persistence(monthly, params)
    for subsystem, stats in persistence_report.items():
        if stats["historical_percentile_within_simulated"] > 0.97:
            print(
                f"WARNING: {subsystem}'s historical drought ({stats['historical_max_drought_run_months']} "
                f"months) exceeds {stats['historical_percentile_within_simulated']:.0%} of simulated "
                "realizations - PAR(1) likely understates persistence for this subsystem.",
                file=sys.stderr,
            )

    residuals = compute_residuals(monthly, params)
    corr_matrix = residual_correlation_matrix(residuals)
    spatial_report = validate_spatial_correlation(monthly, params, corr_matrix)
    for pair, stats in spatial_report.items():
        gap = abs(stats["historical_correlation"] - stats["mean_simulated_correlation"])
        if gap > 0.15:
            print(
                f"WARNING: {pair}'s simulated correlation ({stats['mean_simulated_correlation']:.2f}) "
                f"diverges from historical ({stats['historical_correlation']:.2f}) by {gap:.2f} - "
                "the Cholesky-correlated simulator may not be reproducing this pair correctly.",
                file=sys.stderr,
            )

    write_params(params, Path(snake.output.params))
    write_correlation_matrix(corr_matrix, Path(snake.output.correlation))
    write_validation_report(persistence_report, spatial_report, Path(snake.output.validation))


if __name__ == "__main__":
    main()
