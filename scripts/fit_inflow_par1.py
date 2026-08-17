# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Fit a PAR(1) (Periodic AutoRegressive, order 1) inflow model per subsystem
from the tidy ENA series (ADR-0005, SDDP epic stage 1c: persistence).

PAR(p) is the Brazilian standard (PRIMER Sec 4.7): autoregressive
coefficients vary by calendar month because inflow seasonality is strong,
fitted on log-transformed flows since they are positive and skewed. This
PR fits the simplest defensible order - PAR(1), not a higher order chosen
via AIC/PACF - and validates ONLY persistence (drought duration), the
first of PRIMER Sec 4.7's two required properties. The second,
**spatial correlation across subsystems, is deliberately NOT preserved
here** - each subsystem is fit and simulated independently. That is a
real, named gap (see KNOWN_LIMITATIONS below), not an oversight, and
follows this project's own staged-epic discipline (ADR-0005 split
"coupling mechanism" from "data source"; this PR splits "persistence"
from "spatial correlation" the same way).

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
    "SPATIAL CORRELATION ACROSS SUBSYSTEMS IS NOT YET PRESERVED (PRIMER Sec "
    "4.7). Each subsystem's PAR(1) is fit and simulated independently. Real "
    "Brazilian basins are correlated; independent sampling understates "
    "true system-wide drought risk. A follow-up PR must add this - via "
    "correlated residuals (Cholesky decomposition of the cross-subsystem "
    "residual correlation matrix), as PRIMER and the roadmap both name -  "
    "before any SDDP policy trained on these parameters is trustworthy.",
    "Fit on 26 years of ENA (2000-2025, ADR-0005), not VAZOES.DAT's ~95 "
    "years - materially less data to estimate rare/severe drought "
    "persistence from.",
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


def write_validation_report(report: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"persistence_by_subsystem": report, "known_limitations": KNOWN_LIMITATIONS}
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    df = pd.read_csv(Path(snake.input[0]), parse_dates=["date"])
    monthly = aggregate_to_monthly(df)
    params = fit_par1_by_month(monthly)

    report = validate_persistence(monthly, params)
    for subsystem, stats in report.items():
        if stats["historical_percentile_within_simulated"] > 0.97:
            print(
                f"WARNING: {subsystem}'s historical drought ({stats['historical_max_drought_run_months']} "
                f"months) exceeds {stats['historical_percentile_within_simulated']:.0%} of simulated "
                "realizations - PAR(1) likely understates persistence for this subsystem.",
                file=sys.stderr,
            )

    write_params(params, Path(snake.output.params))
    write_validation_report(report, Path(snake.output.validation))


if __name__ == "__main__":
    main()
