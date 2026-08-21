# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Fit a PAR(1) inflow model per REE from the tidy REE-level ENA series
(ADR-0008, SDDP epic stage 2: REE-level persistence + spatial correlation).

Same shape as fit_inflow_par1.py (ADR-0005 stage 1c/1d), keyed on `ree`
instead of `subsystem`, with a 12x12 residual correlation matrix instead of
4x4. Fits on GROSS inflow (`ena_bruta_mwmed`) for the same reason as the
subsystem-level fit - see that module's docstring.

The REE-level record is materially shorter and more ragged than the
subsystem-level one: `ena_ree` only goes back to 2016 (ADR-0008), not
ena_subsistema's 2000, and 3 REEs (IGUACU, MANAUS-AMAPA, PARANAPANEMA) only
exist as separately-tracked units from 2017-12-30 onward (PR-36) - 9 years
of data for those three (2017-2025), vs. 10 for the rest (2016-2025) and 26
at subsystem level. Nothing here requires a uniform history across REEs
(groupby-based, like build_inflow_ree.py's own equivalent choice) - each REE
is fit on whatever years it actually has - but the shorter record is a real
fitting constraint, not a subsystem-level-style comfortable margin, so
persistence and correlation numbers here should be trusted less.

A second, distinct real finding from fitting on the full volume: TELES
PIRES reports `ena_bruta_mwmed == 0.0` for its first 213 days (2016-01-01 to
2016-07-31) before real nonzero values start - a "not yet tracked" artifact
that would otherwise corrupt its log-space mu to -inf. See
`drop_pre_tracking_zeros` for the handling.
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
    "PAR(1) only - order 1, not selected via AIC/PACF. Same choice as the "
    "subsystem-level fit, for the same reason.",
    "Spatial correlation is a SINGLE 12x12 matrix pooled across all 12 "
    "calendar months, not fit per-month - even noisier than the "
    "subsystem-level 4x4 case (PR-29), since each REE pair now has at most "
    "~10 years of same-(year, month) overlap to estimate from, not 26.",
    "Fit on 2016-2025 ena_ree data (ADR-0008), not VAZOES.DAT's ~95 years "
    "or even ena_subsistema's 26 - 9 years for 3 REEs (IGUACU, "
    "MANAUS-AMAPA, PARANAPANEMA, tracked separately only from 2017-12-30 "
    "onward, PR-36) and 10 for the rest. Drought-run persistence and "
    "cross-REE correlation estimated from this few years should be "
    "treated as indicative, not as reliable as the subsystem-level fit.",
    "Fit on gross ena_bruta_mwmed - see module docstring for why storable "
    "was rejected as the modelled quantity (same reasoning as the "
    "subsystem-level fit).",
]


def drop_pre_tracking_zeros(df: pd.DataFrame) -> pd.DataFrame:
    """
    Real finding fitting on real data: TELES PIRES reports
    `ena_bruta_mwmed == 0.0` for exactly its first 213 days (2016-01-01 to
    2016-07-31), then real nonzero values from 2016-08-01 onward -
    `ena_bruta_pct_mlt` is 0.0 across the same window too, reinforcing a
    placeholder rather than a real measurement (zero natural inflow for
    213 straight days is not physically plausible for a river). This is
    the same underlying phenomenon PR-36 found for 3 REEs starting only
    from 2017-12-30 - "not yet tracked as its own REE" - just represented
    as explicit zero rows here instead of missing ones.

    PAR(1) fits in log space, where a zero is -inf and corrupts that
    month's mu (and thus every month's phi, via the standardized-residual
    chain) - dropped before fitting, not clipped like the storable-vs-gross
    quirk (PR-36), since there is no sensible floor to clip a natural log
    of zero to. A general rule (any REE, not a TELES-PIRES-specific name
    list like REPORTING_GAPS in build_reservoir_ree.py), so a future REE
    with the same startup pattern is handled the same way automatically.
    """
    zero_mask = df[VALUE_COLUMN] == 0.0
    if zero_mask.any():
        for ree, count in df.loc[zero_mask, "ree"].value_counts().items():
            print(
                f"NOTE: dropping {count} zero-{VALUE_COLUMN} row(s) for {ree} before "
                "PAR(1) fitting - read as a pre-tracking placeholder, not real zero "
                "inflow.",
                file=sys.stderr,
            )
    return df.loc[~zero_mask].reset_index(drop=True)


def aggregate_to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (ree, year, month): mean of the daily gross ENA series.
    REEs with a shorter real history simply contribute fewer rows - no
    uniform-coverage assumption, matching build_inflow_ree.py's own choice."""
    dates = pd.to_datetime(df["date"])
    monthly = df.assign(year=dates.dt.year, month=dates.dt.month)
    return (
        monthly.groupby(["ree", "year", "month"], as_index=False)[VALUE_COLUMN]
        .mean()
        .sort_values(["ree", "year", "month"])
        .reset_index(drop=True)
    )


def fit_par1_by_month(monthly: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (ree, month, 1-12): mu/sigma of log(ENA) for that calendar
    month across all years the REE actually has, and phi - the lag-1
    autocorrelation with the preceding calendar month (wrapping December ->
    January across a year boundary).
    """
    work = monthly.assign(log_ena=np.log(monthly[VALUE_COLUMN]))
    stats = work.groupby(["ree", "month"])["log_ena"].agg(mu="mean", sigma="std").reset_index()
    work = work.merge(stats, on=["ree", "month"]).sort_values(["ree", "year", "month"])
    work["z"] = (work["log_ena"] - work["mu"]) / work["sigma"]
    work["z_lag1"] = work.groupby("ree")["z"].shift(1)
    work["month_lag1"] = work.groupby("ree")["month"].shift(1)

    # Keep only rows where the lag really is the immediately preceding
    # calendar month (handles the December -> January wrap, and any real
    # gap in a REE's own ragged coverage window).
    expected_lag_month = ((work["month"] - 2) % 12) + 1
    work = work[work["month_lag1"] == expected_lag_month]

    phi = (
        work.groupby(["ree", "month"])
        .apply(lambda g: g["z"].corr(g["z_lag1"]), include_groups=False)
        .rename("phi")
        .reset_index()
    )
    params = stats.merge(phi, on=["ree", "month"])
    return params.sort_values(["ree", "month"]).reset_index(drop=True)


def simulate_par1(params: pd.DataFrame, *, n_years: int, rng: np.random.Generator) -> pd.DataFrame:
    """One synthetic n_years-long monthly series per REE, sampled from the
    fitted PAR(1) parameters. Same recursion as the subsystem-level version."""
    rows = []
    for ree, group in params.groupby("ree"):
        by_month = group.set_index("month")
        z_prev = rng.normal()
        for year in range(n_years):
            for month in range(1, 13):
                row = by_month.loc[month]
                phi = float(np.clip(row["phi"], -0.99, 0.99))
                shock_sd = float(np.sqrt(max(1 - phi**2, 1e-6)))
                z = phi * z_prev + rng.normal(scale=shock_sd)
                ena = float(np.exp(row["mu"] + row["sigma"] * z))
                rows.append({"ree": ree, "year": year, "month": month, VALUE_COLUMN: ena})
                z_prev = z
    return pd.DataFrame(rows)


def compute_residuals(monthly: pd.DataFrame, params: pd.DataFrame) -> pd.DataFrame:
    """One row per (ree, year, month): the standardized AR(1) residual
    epsilon_t = z_t - phi_m * z_{t-1} - the basis for spatial correlation."""
    work = monthly.assign(log_ena=np.log(monthly[VALUE_COLUMN])).merge(
        params[["ree", "month", "mu", "sigma", "phi"]], on=["ree", "month"]
    )
    work = work.sort_values(["ree", "year", "month"])
    work["z"] = (work["log_ena"] - work["mu"]) / work["sigma"]
    work["z_lag1"] = work.groupby("ree")["z"].shift(1)
    work["month_lag1"] = work.groupby("ree")["month"].shift(1)

    expected_lag_month = ((work["month"] - 2) % 12) + 1
    work = work[work["month_lag1"] == expected_lag_month]
    work["residual"] = work["z"] - work["phi"] * work["z_lag1"]
    return work[["ree", "year", "month", "residual"]].reset_index(drop=True)


def residual_correlation_matrix(residuals: pd.DataFrame) -> pd.DataFrame:
    """ree x ree correlation of SAME-(year, month) residuals, pooled across
    all calendar months. `.corr()`'s pairwise-complete-observations default
    is what makes this well-defined even though REEs have different
    coverage windows - a pair with only partial overlap is still correlated
    over whatever (year, month) rows they share, not silently dropped."""
    wide = residuals.pivot_table(index=["year", "month"], columns="ree", values="residual")
    return wide.corr()


def simulate_par1_correlated(
    params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    n_years: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Synthetic n_years-long monthly series for ALL REEs jointly, via
    Cholesky decomposition of `corr_matrix` - same mechanism as the
    subsystem-level simulator."""
    rees = list(corr_matrix.columns)
    cholesky_factor = np.linalg.cholesky(corr_matrix.loc[rees, rees].to_numpy())

    by_ree_month = {(row.ree, row.month): row for row in params.itertuples()}
    z_prev = dict.fromkeys(rees, 0.0)
    for ree in rees:
        z_prev[ree] = rng.normal()

    rows = []
    for year in range(n_years):
        for month in range(1, 13):
            independent_draw = rng.normal(size=len(rees))
            correlated_unit = cholesky_factor @ independent_draw
            for i, ree in enumerate(rees):
                row = by_ree_month[(ree, month)]
                phi = float(np.clip(row.phi, -0.99, 0.99))
                shock_sd = float(np.sqrt(max(1 - phi**2, 1e-6)))
                z = phi * z_prev[ree] + correlated_unit[i] * shock_sd
                ena = float(np.exp(row.mu + row.sigma * z))
                rows.append({"ree": ree, "year": year, "month": month, VALUE_COLUMN: ena})
                z_prev[ree] = z
    return pd.DataFrame(rows)


def validate_spatial_correlation(
    monthly: pd.DataFrame,
    params: pd.DataFrame,
    corr_matrix: pd.DataFrame,
    *,
    n_realizations: int = 200,
    seed: int = 0,
) -> dict:
    """Does the correlated simulator reproduce the real historical
    cross-REE correlation? Same end-to-end check as the subsystem-level
    version - simulate, re-estimate from the simulator's own output, compare."""
    n_years = monthly["year"].nunique()
    rng = np.random.default_rng(seed)
    rees = list(corr_matrix.columns)

    simulated_corrs = []
    for _ in range(n_realizations):
        sim = simulate_par1_correlated(params, corr_matrix, n_years=n_years, rng=rng)
        sim_residuals = compute_residuals(sim, params)
        simulated_corrs.append(residual_correlation_matrix(sim_residuals).loc[rees, rees])

    mean_simulated = sum(simulated_corrs) / len(simulated_corrs)

    report = {}
    for i, a in enumerate(rees):
        for b in rees[i + 1 :]:
            report[f"{a}-{b}"] = {
                "historical_correlation": float(corr_matrix.loc[a, b]),
                "mean_simulated_correlation": float(mean_simulated.loc[a, b]),
            }
    return report


def month_thresholds(historical_monthly: pd.DataFrame, *, percentile: float) -> pd.DataFrame:
    """(ree, month) -> the historical `percentile`-th ENA value, a fixed
    reference "dry" threshold."""
    return (
        historical_monthly.groupby(["ree", "month"])[VALUE_COLUMN]
        .quantile(percentile)
        .rename("threshold")
        .reset_index()
    )


def max_drought_run(monthly: pd.DataFrame, thresholds: pd.DataFrame) -> pd.Series:
    """Longest run of consecutive months below the fixed per-(ree, month)
    threshold, one value per REE."""
    merged = monthly.merge(thresholds, on=["ree", "month"]).sort_values(["ree", "year", "month"])
    merged["dry"] = merged[VALUE_COLUMN] < merged["threshold"]

    results = {}
    for ree, g in merged.groupby("ree"):
        max_run = current = 0
        for dry in g["dry"].to_numpy():
            current = current + 1 if dry else 0
            max_run = max(max_run, current)
        results[ree] = max_run
    return pd.Series(results, name="max_drought_run_months")


def validate_persistence(
    historical_monthly: pd.DataFrame,
    params: pd.DataFrame,
    *,
    n_realizations: int = 200,
    percentile: float = 0.3,
    seed: int = 0,
) -> dict:
    """Does the fitted model produce droughts as long as each REE's real
    record's? Same diagnostic as the subsystem-level version, but each
    REE's own `n_years` here is as short as 8-10 years (its OWN nunique,
    not a shared constant) - a materially smaller sample than the
    subsystem-level 26, so this is a coarser diagnostic per REE."""
    thresholds = month_thresholds(historical_monthly, percentile=percentile)
    historical_run = max_drought_run(historical_monthly, thresholds)

    report = {}
    for ree in historical_run.index:
        ree_params = params[params["ree"] == ree]
        ree_monthly = historical_monthly[historical_monthly["ree"] == ree]
        n_years = ree_monthly["year"].nunique()
        rng = np.random.default_rng(seed)
        ree_thresholds = thresholds[thresholds["ree"] == ree]

        sim_runs = [
            max_drought_run(simulate_par1(ree_params, n_years=n_years, rng=rng), ree_thresholds)[
                ree
            ]
            for _ in range(n_realizations)
        ]
        sim_values = pd.Series(sim_runs)
        hist_value = int(historical_run[ree])
        report[ree] = {
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
    """Tidy long format (ree_a, ree_b, correlation) - see the
    subsystem-level write_correlation_matrix for why the axes must be
    renamed before stacking (PR-29 regression)."""
    matrix = corr_matrix.copy()
    matrix.index.name = "ree_a"
    matrix.columns.name = "ree_b"
    tidy = matrix.stack().rename("correlation").reset_index()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tidy.to_csv(out_path, index=False)
    return out_path


def write_validation_report(persistence_report: dict, spatial_report: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "persistence_by_ree": persistence_report,
        "spatial_correlation_by_ree_pair": spatial_report,
        "known_limitations": KNOWN_LIMITATIONS,
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    df = pd.read_csv(Path(snake.input[0]), parse_dates=["date"])
    df = drop_pre_tracking_zeros(df)
    monthly = aggregate_to_monthly(df)
    params = fit_par1_by_month(monthly)

    persistence_report = validate_persistence(monthly, params)
    for ree, stats in persistence_report.items():
        if stats["historical_percentile_within_simulated"] > 0.97:
            print(
                f"WARNING: {ree}'s historical drought ({stats['historical_max_drought_run_months']} "
                f"months) exceeds {stats['historical_percentile_within_simulated']:.0%} of simulated "
                "realizations - PAR(1) likely understates persistence for this REE.",
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
