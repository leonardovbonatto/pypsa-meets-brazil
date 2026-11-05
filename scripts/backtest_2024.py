# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
The Phase 7 gate's backtest (ADR-0015): does the coupled 2024 run
(solve_network_sddp, ADR-0014) reproduce the SHAPE of what happened?

Two observed series per subsystem: end-of-month reservoir storage (EAR, % of
capacity) and the monthly mean of ONS's half-hourly CMO (PR-47). The model's
hydro is a decision here, not a backcast, so agreement is evidence rather
than circularity (ADR-0007's caveat does not apply).

**Pass criterion, fixed before any coupled run had finished (ADR-0015):**
over January to November 2024 (December carries ADR-0014's end effect),

1. storage: Pearson correlation of model vs observed EAR % is at least
   STORAGE_MIN_CORRELATION in at least STORAGE_MIN_SUBSYSTEMS subsystems;
2. price: Spearman rank correlation of model vs observed monthly CMO in
   PRICE_SUBSYSTEM is at least PRICE_MIN_RANK_CORRELATION.

Levels (mean ratio, mean absolute error) are reported for every subsystem
and decide nothing: the shape is the test, because SDDP's simplifications
(gross inflow, no minimum outflows) shift levels before they bend shapes.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
from pathlib import Path

import numpy as np
import pandas as pd

MONTHS = list(range(1, 12))
STORAGE_MIN_CORRELATION = 0.6
STORAGE_MIN_SUBSYSTEMS = 3
PRICE_SUBSYSTEM = "SE_CO"
PRICE_MIN_RANK_CORRELATION = 0.5


def observed_storage(history: pd.DataFrame, year: int) -> pd.DataFrame:
    """(month, subsystem) -> observed EAR % of capacity on the month's last
    recorded day."""
    work = history[history["date"].dt.year == year].assign(month=lambda d: d["date"].dt.month)
    last = work.loc[work.groupby(["month", "subsystem"])["date"].idxmax()]
    return last[["month", "subsystem", "ear_verif_pct"]].rename(
        columns={"ear_verif_pct": "observed_storage_pct"}
    )


def observed_cmo(cmo_monthly: pd.DataFrame, year: int) -> pd.DataFrame:
    """(month, subsystem) -> observed monthly mean CMO, R$/MWh."""
    period = pd.PeriodIndex(cmo_monthly["month"], freq="M")
    work = cmo_monthly[period.year == year].assign(month=period[period.year == year].month)
    return work[["month", "subsystem", "cmo_mean"]].rename(columns={"cmo_mean": "observed_cmo"})


def comparison_table(
    model: pd.DataFrame, capacity: pd.DataFrame, storage: pd.DataFrame, cmo: pd.DataFrame
) -> pd.DataFrame:
    """One row per (month, subsystem): model and observed storage % and price."""
    max_storage = dict(zip(capacity["subsystem"], capacity["ear_max_mwmes"], strict=True))
    table = model[["month", "subsystem", "storage_end_mwmes", "price_mean_rs_per_mwh"]].assign(
        model_storage_pct=lambda d: 100.0 * d["storage_end_mwmes"] / d["subsystem"].map(max_storage)
    )
    table = table.merge(storage, on=["month", "subsystem"], how="left").merge(
        cmo, on=["month", "subsystem"], how="left"
    )
    return table.rename(columns={"price_mean_rs_per_mwh": "model_price"}).drop(
        columns="storage_end_mwmes"
    )


def _pearson(a: pd.Series, b: pd.Series) -> float:
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _spearman(a: pd.Series, b: pd.Series) -> float:
    return _pearson(a.rank(), b.rank())


def backtest_report(table: pd.DataFrame) -> dict:
    """The verdict and the per-subsystem statistics over MONTHS."""
    window = table[table["month"].isin(MONTHS)]
    if window[["observed_storage_pct", "observed_cmo"]].isna().any().any():
        raise ValueError("observed storage or CMO missing for a month in the window")
    by_subsystem = {}
    for subsystem, rows in window.groupby("subsystem"):
        by_subsystem[subsystem] = {
            "storage_correlation": _pearson(
                rows["model_storage_pct"], rows["observed_storage_pct"]
            ),
            "storage_mean_abs_error_pct": float(
                (rows["model_storage_pct"] - rows["observed_storage_pct"]).abs().mean()
            ),
            "price_rank_correlation": _spearman(rows["model_price"], rows["observed_cmo"]),
            "price_correlation": _pearson(rows["model_price"], rows["observed_cmo"]),
            "model_mean_price": float(rows["model_price"].mean()),
            "observed_mean_cmo": float(rows["observed_cmo"].mean()),
        }
    storage_ok = sum(
        1
        for stats in by_subsystem.values()
        if stats["storage_correlation"] >= STORAGE_MIN_CORRELATION
    )
    price = by_subsystem[PRICE_SUBSYSTEM]["price_rank_correlation"]
    storage_pass = storage_ok >= STORAGE_MIN_SUBSYSTEMS
    price_pass = bool(price >= PRICE_MIN_RANK_CORRELATION)
    return {
        "passed": bool(storage_pass and price_pass),
        "storage_passed": bool(storage_pass),
        "storage_subsystems_meeting_correlation": storage_ok,
        "price_passed": price_pass,
        "window_months": MONTHS,
        "criteria": {
            "storage_min_correlation": STORAGE_MIN_CORRELATION,
            "storage_min_subsystems": STORAGE_MIN_SUBSYSTEMS,
            "price_subsystem": PRICE_SUBSYSTEM,
            "price_min_rank_correlation": PRICE_MIN_RANK_CORRELATION,
        },
        "by_subsystem": by_subsystem,
    }


def main() -> None:
    snake = globals()["snakemake"]
    year = int(snake.params.year)

    table = comparison_table(
        pd.read_csv(snake.input.model),
        pd.read_csv(snake.input.reservoir_capacity),
        observed_storage(pd.read_csv(snake.input.reservoir_history, parse_dates=["date"]), year),
        observed_cmo(pd.read_csv(snake.input.cmo), year),
    )
    report = backtest_report(table)

    Path(snake.output.table).parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(snake.output.table, index=False)
    text = json.dumps(report, indent=2)
    Path(snake.log[0]).write_text(text + "\n")
    if not report["passed"]:
        raise SystemExit(f"ADR-0015 backtest FAILED: {text}")
    Path(snake.output.report).write_text(text + "\n")


if __name__ == "__main__":
    main()
