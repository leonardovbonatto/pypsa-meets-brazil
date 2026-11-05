# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
ADR-0011's acceptance test: after a very dry month, is water worth more than
after a very wet one, at identical storage?

The policy's memory is now each subsystem's last inflow, a state in the cuts.
"Dry" is that inflow at its 10th percentile and "wet" at its 90th, from the
log-PAR(1) fit the policy is scored on. Each subsystem is judged on its OWN
last inflow, with the others at their mean; nothing moves all subsystems at
once (ADR-0010's rule, kept).

Water value is the slope of the cost-to-go in storage, by central difference,
for the reason given in check_sddp_regimes.py: a level difference changes no
dispatch. Cuts at stage t are in terms of the state leaving stage t, so the
last inflow at stage 6 is June's.

**Pass criterion, set before any run (ADR-0011 decisions 3 and 4):** at stage
6 and 50% storage, dry >= wet in every subsystem and strictly in one; and the
deficit slack carries at most 1% of S's inflow energy in the in-sample
simulation. The stage x storage x other-subsystems grid is reported, not gated.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import itertools
import json
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_sddp_regimes import (
    GRID_FRACTIONS,
    REFERENCE_FRACTION,
    REFERENCE_STAGE,
    SLOPE_STEP_FRACTION,
    TIE_TOLERANCE,
    compare_regimes,
)

DRY_QUANTILE = 0.10
WET_QUANTILE = 0.90
MAX_S_DEFICIT_SHARE = 0.01


def parse_state_cuts(cuts: pd.DataFrame, subsystems: list[str]) -> dict:
    """stage -> (intercepts, storage coefficients, inflow coefficients), each
    coefficient row ordered as `subsystems`."""
    storage = {f"storage[{s}]": i for i, s in enumerate(subsystems)}
    inflow = {f"inflow[{s}]": i for i, s in enumerate(subsystems)}
    nodes = {}
    for stage, group in cuts.groupby("stage"):
        storage_matrix = np.zeros((len(group), len(subsystems)))
        inflow_matrix = np.zeros((len(group), len(subsystems)))
        names = group["state_variable"].str.split(",")
        values = group["coefficient"].str.split(",")
        for row, (cut_names, cut_values) in enumerate(zip(names, values, strict=True)):
            for name, value in zip(cut_names, cut_values, strict=True):
                if name in storage:
                    storage_matrix[row, storage[name]] = float(value)
                elif name in inflow:
                    inflow_matrix[row, inflow[name]] = float(value)
                else:
                    raise ValueError(f"unexpected state variable in cuts: {name}")
        nodes[int(stage)] = (
            group["intercept"].to_numpy(dtype=float),
            storage_matrix,
            inflow_matrix,
        )
    return nodes


def cost_to_go(node: tuple, storage: np.ndarray, inflow: np.ndarray) -> float:
    intercepts, storage_coefficients, inflow_coefficients = node
    return float(np.max(intercepts + storage_coefficients @ storage + inflow_coefficients @ inflow))


def water_value(
    node: tuple, capacity: np.ndarray, fraction: float, inflow: np.ndarray, index: int
) -> float:
    """-dV/dstorage of one subsystem, in the cuts' unit."""
    storage = fraction * capacity
    delta = np.zeros(len(capacity))
    delta[index] = SLOPE_STEP_FRACTION * capacity[index]
    above = cost_to_go(node, storage + delta, inflow)
    below = cost_to_go(node, storage - delta, inflow)
    return (below - above) / (2.0 * delta[index])


def inflow_levels(par1_params: pd.DataFrame, subsystems: list[str]) -> dict:
    """month -> {"dry", "mean", "wet"} -> inflow per subsystem (MWmed), from
    the log-PAR(1) fit: quantiles exp(mu + sigma * q) and the lognormal mean."""
    dry_q = NormalDist().inv_cdf(DRY_QUANTILE)
    wet_q = NormalDist().inv_cdf(WET_QUANTILE)
    lookup = par1_params.set_index(["month", "subsystem"])
    levels = {}
    for month in range(1, 13):
        mu = np.array([lookup.loc[(month, s), "mu"] for s in subsystems])
        sigma = np.array([lookup.loc[(month, s), "sigma"] for s in subsystems])
        levels[month] = {
            "dry": np.exp(mu + sigma * dry_q),
            "mean": np.exp(mu + 0.5 * sigma**2),
            "wet": np.exp(mu + sigma * wet_q),
        }
    return levels


def inflow_state_report(
    cuts: pd.DataFrame,
    capacity_by_subsystem: dict,
    par1_params: pd.DataFrame,
    deficit: dict,
) -> dict:
    """The verdict, each subsystem judged on its own last inflow."""
    subsystems = sorted(capacity_by_subsystem)
    capacity = np.array([capacity_by_subsystem[s] for s in subsystems], dtype=float)
    nodes = parse_state_cuts(cuts, subsystems)
    levels = inflow_levels(par1_params, subsystems)

    def own(stage: int, index: int, which: str, others: tuple[str, ...]) -> np.ndarray:
        labels = list(others)
        labels.insert(index, which)
        return np.array([levels[stage][label][i] for i, label in enumerate(labels)])

    by_subsystem, reference_dry, reference_wet = {}, [], []
    middle = ("mean",) * (len(subsystems) - 1)
    for i, subsystem in enumerate(subsystems):
        node = nodes[REFERENCE_STAGE]
        dry_inflow = own(REFERENCE_STAGE, i, "dry", middle)
        wet_inflow = own(REFERENCE_STAGE, i, "wet", middle)
        dry = water_value(node, capacity, REFERENCE_FRACTION, dry_inflow, i)
        wet = water_value(node, capacity, REFERENCE_FRACTION, wet_inflow, i)
        reference_dry.append(dry)
        reference_wet.append(wet)
        by_subsystem[subsystem] = {
            "dry_last_inflow_mwmed": float(dry_inflow[i]),
            "wet_last_inflow_mwmed": float(wet_inflow[i]),
            "dry": float(dry),
            "wet": float(wet),
            "dry_cost_to_go": cost_to_go(node, REFERENCE_FRACTION * capacity, dry_inflow),
            "wet_cost_to_go": cost_to_go(node, REFERENCE_FRACTION * capacity, wet_inflow),
        }
    verdict = compare_regimes(np.array(reference_dry), np.array(reference_wet))

    s_share = float(deficit["S"]["share_of_inflow_energy"])
    deficit_ok = s_share <= MAX_S_DEFICIT_SHARE

    counts = {"dry_above_wet": 0, "tied": 0, "wet_above_dry": 0}
    for i in range(len(subsystems)):
        for others in itertools.product(("dry", "mean", "wet"), repeat=len(subsystems) - 1):
            for stage, node in sorted(nodes.items()):
                for fraction in GRID_FRACTIONS:
                    gap = water_value(
                        node, capacity, fraction, own(stage, i, "dry", others), i
                    ) - water_value(node, capacity, fraction, own(stage, i, "wet", others), i)
                    if gap > TIE_TOLERANCE:
                        counts["dry_above_wet"] += 1
                    elif gap < -TIE_TOLERANCE:
                        counts["wet_above_dry"] += 1
                    else:
                        counts["tied"] += 1

    return {
        "passed": all(verdict.values()) and deficit_ok,
        **verdict,
        "s_deficit_share": s_share,
        "s_deficit_within_limit": deficit_ok,
        "comparison": (
            f"own last inflow at P{round(100 * DRY_QUANTILE)} vs "
            f"P{round(100 * WET_QUANTILE)}, other subsystems at their mean"
        ),
        "reference_stage": REFERENCE_STAGE,
        "reference_fraction": REFERENCE_FRACTION,
        "units": "millions of R$ per MWmes, as exported in cuts.parquet",
        "by_subsystem": by_subsystem,
        "grid_counts": counts,
    }


def main() -> None:
    snake = globals()["snakemake"]

    capacity = pd.read_parquet(snake.input.reservoir_capacity)
    summary = json.loads(Path(snake.input.summary).read_text())
    report = inflow_state_report(
        pd.read_parquet(snake.input.cuts),
        dict(zip(capacity["subsystem"], capacity["ear_max_mwmes"], strict=True)),
        pd.read_csv(snake.input.par1_params),
        summary["deficit"],
    )

    text = json.dumps(report, indent=2)
    Path(snake.log[0]).write_text(text + "\n")
    if not report["passed"]:
        raise SystemExit(f"ADR-0011 acceptance test FAILED: {text}")
    Path(snake.output[0]).write_text(text + "\n")


if __name__ == "__main__":
    main()
