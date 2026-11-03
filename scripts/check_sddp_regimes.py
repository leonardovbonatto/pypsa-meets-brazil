# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
ADR-0009's acceptance test: is water worth more in a dry regime than a wet
one, at identical storage?

**Water value is the SLOPE of the cost-to-go, not its level.** A trained
policy compares the cost of using a unit of water now against the change in
future cost, so only `dV/dstorage` reaches a dispatch decision. A dry regime
whose cost-to-go is higher by a constant has the same water value as a wet
one and dispatches identically. PR-45's first version compared levels, which
is the mechanism-not-claim error PR-38 made: lower inflows in a dry regime
raise the level almost by construction, so it passes without the policy
having learned anything it can act on. Levels are still reported here, but
they decide nothing.

**The cuts are the policy** (docs/DIAGNOSTICS.md), so this reads
`cuts.parquet` directly. It runs in Python rather than inside the Julia
training script so that CI can cover it without Julia, and so that changing
it does not mean retraining. The slope is a central difference across +-5%
of capacity rather than the active cut's coefficient: `V` is piecewise
linear, and one cut's coefficient at a kink says little about its surroundings.

**Pass criterion, fixed before looking at any full-run result:** at the
reference point (stage 6, 50% storage), dry >= wet in every subsystem and
strictly in at least one. The stage x storage grid is reported, not gated.

**Regions are judged independently (ADR-0010).** Each subsystem is compared
between its OWN region dry and its own region wet, with the other regions held
at their middle regime; the grid adds every combination of the other regions.
No comparison ever moves all regions at once.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

REFERENCE_STAGE = 6
REFERENCE_FRACTION = 0.5
GRID_FRACTIONS = (0.25, 0.5, 0.75)

# Half-width of the central difference, as a fraction of capacity.
SLOPE_STEP_FRACTION = 0.05

# Below this two water values are tied, not ordered: cuts are in millions of
# R$ per MWmes, so 1e-6 is one R$ per MWmes.
TIE_TOLERANCE = 1e-6


def parse_cuts(cuts: pd.DataFrame, subsystems: list[str]) -> dict:
    """(stage, markov_state) -> (intercepts, coefficients), with each row of
    `coefficients` ordered as `subsystems`. The export stores names and values
    as comma-joined strings, so each cut is mapped through its own names."""
    columns = {f"storage[{s}]": i for i, s in enumerate(subsystems)}
    nodes = {}
    for key, group in cuts.groupby(["stage", "markov_state"]):
        matrix = np.zeros((len(group), len(subsystems)))
        names = group["state_variable"].str.split(",")
        values = group["coefficient"].str.split(",")
        for row, (cut_names, cut_values) in enumerate(zip(names, values, strict=True)):
            for name, value in zip(cut_names, cut_values, strict=True):
                matrix[row, columns[name]] = float(value)
        nodes[(int(key[0]), int(key[1]))] = (group["intercept"].to_numpy(dtype=float), matrix)
    return nodes


def cost_to_go(intercepts: np.ndarray, coefficients: np.ndarray, storage: np.ndarray) -> float:
    """The cut approximation of a minimisation's value function: the highest
    cut at this storage."""
    return float(np.max(intercepts + coefficients @ storage))


def water_values(
    intercepts: np.ndarray,
    coefficients: np.ndarray,
    capacity: np.ndarray,
    fraction: float,
) -> np.ndarray:
    """Marginal value of stored water per subsystem, in the cuts' own unit.
    Positive: more water lowers the future cost, so this is `-dV/dstorage`."""
    storage = fraction * capacity
    values = np.zeros(len(capacity))
    for i, step in enumerate(SLOPE_STEP_FRACTION * capacity):
        delta = np.zeros(len(capacity))
        delta[i] = step
        above = cost_to_go(intercepts, coefficients, storage + delta)
        below = cost_to_go(intercepts, coefficients, storage - delta)
        values[i] = (below - above) / (2.0 * step)
    return values


def compare_regimes(dry: np.ndarray, wet: np.ndarray) -> dict:
    """The pass criterion, on one pair of water-value vectors."""
    return {
        "dry_at_least_wet_everywhere": bool(np.all(dry >= wet - TIE_TOLERANCE)),
        "dry_above_wet_somewhere": bool(np.any(dry > wet + TIE_TOLERANCE)),
    }


def joint_state(digits: tuple[int, ...], n_states: int) -> int:
    """Per-region regimes (0 = dry) -> joint state, first region most
    significant, matching prepare_sddp_inputs.regional_states."""
    state = 0
    for digit in digits:
        state = state * n_states + digit
    return state + 1


def regional_report(
    cuts: pd.DataFrame, capacity_by_subsystem: dict, *, regions: dict, n_states: int
) -> dict:
    """The acceptance verdict with each subsystem judged on its own region."""
    if n_states < 2:
        raise ValueError(f"need at least two regimes to compare, got n_states={n_states}")
    subsystems = sorted(capacity_by_subsystem)
    capacity = np.array([capacity_by_subsystem[s] for s in subsystems], dtype=float)
    nodes = parse_cuts(cuts, subsystems)
    names = list(regions)
    middle = n_states // 2
    wet = n_states - 1

    def own_region_pair(region: int, others: tuple[int, ...]) -> tuple[int, int]:
        dry_digits = list(others)
        dry_digits.insert(region, 0)
        wet_digits = list(others)
        wet_digits.insert(region, wet)
        return joint_state(tuple(dry_digits), n_states), joint_state(tuple(wet_digits), n_states)

    comparison = {}
    reference_dry, reference_wet = [], []
    for subsystem in subsystems:
        region = next(i for i, r in enumerate(names) if subsystem in regions[r])
        i = subsystems.index(subsystem)
        dry_state, wet_state = own_region_pair(region, (middle,) * (len(names) - 1))
        dry = water_values(*nodes[(REFERENCE_STAGE, dry_state)], capacity, REFERENCE_FRACTION)[i]
        wet_value = water_values(
            *nodes[(REFERENCE_STAGE, wet_state)], capacity, REFERENCE_FRACTION
        )[i]
        reference_dry.append(dry)
        reference_wet.append(wet_value)
        comparison[subsystem] = {
            "region": names[region],
            "dry_state": dry_state,
            "wet_state": wet_state,
            "dry": float(dry),
            "wet": float(wet_value),
            # Levels are reported only; they decide nothing (see module docstring).
            "dry_cost_to_go": cost_to_go(
                *nodes[(REFERENCE_STAGE, dry_state)], REFERENCE_FRACTION * capacity
            ),
            "wet_cost_to_go": cost_to_go(
                *nodes[(REFERENCE_STAGE, wet_state)], REFERENCE_FRACTION * capacity
            ),
        }
    verdict = compare_regimes(np.array(reference_dry), np.array(reference_wet))

    counts = {"dry_above_wet": 0, "tied": 0, "wet_above_dry": 0}
    for subsystem in subsystems:
        region = next(i for i, r in enumerate(names) if subsystem in regions[r])
        i = subsystems.index(subsystem)
        for others in itertools.product(range(n_states), repeat=len(names) - 1):
            dry_state, wet_state = own_region_pair(region, others)
            for stage in sorted({stage for stage, _ in nodes}):
                for fraction in GRID_FRACTIONS:
                    gap = (
                        water_values(*nodes[(stage, dry_state)], capacity, fraction)[i]
                        - water_values(*nodes[(stage, wet_state)], capacity, fraction)[i]
                    )
                    if gap > TIE_TOLERANCE:
                        counts["dry_above_wet"] += 1
                    elif gap < -TIE_TOLERANCE:
                        counts["wet_above_dry"] += 1
                    else:
                        counts["tied"] += 1

    return {
        "passed": all(verdict.values()),
        **verdict,
        "comparison": "own region dry vs own region wet, other regions at the middle regime",
        "reference_stage": REFERENCE_STAGE,
        "reference_fraction": REFERENCE_FRACTION,
        "units": "millions of R$ per MWmes, as exported in cuts.parquet",
        "by_subsystem": comparison,
        "grid_counts": counts,
    }


def main() -> None:
    snake = globals()["snakemake"]

    capacity = pd.read_parquet(snake.input.reservoir_capacity)
    report = regional_report(
        pd.read_parquet(snake.input.cuts),
        dict(zip(capacity["subsystem"], capacity["ear_max_mwmes"], strict=True)),
        regions=dict(snake.params.regions),
        n_states=int(snake.params.n_markov_states),
    )

    text = json.dumps(report, indent=2)
    Path(snake.log[0]).write_text(text + "\n")
    if not report["passed"]:
        raise SystemExit(f"ADR-0009 acceptance test FAILED: {text}")
    Path(snake.output[0]).write_text(text + "\n")


if __name__ == "__main__":
    main()
