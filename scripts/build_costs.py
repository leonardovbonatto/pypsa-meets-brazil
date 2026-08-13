# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the T0 thermal marginal-cost table from ONS CVU.

Reduces 52 weeks x ~114 plants of weekly per-plant CVU down to one R$/MWh
value per subsystem - deliberately not a per-plant merit order, and
deliberately not joined against capacidade_geracao (the two datasets' plant
identities don't match; see docs/handoffs/PR-09-ons-cvu-connector.md). This
is a real simplification, not free: see docs/handoffs/PR-10-*.md for what it
costs and why it was still the right scope for this PR.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

COST_COLUMN = "val_cvu"

# The thermal fleet's CVU includes real zero-cost plants (bagasse
# co-generation, synchronous-condenser-mode units - see the data
# dictionary's notes). They stay in the mean: excluding them would need a
# specific rationale ("these never actually set the marginal price") this
# project does not have evidence for yet. One consequence worth knowing: the
# N subsystem has an unusually high share of zero-cost plants (32% of
# observations, vs 10-16% elsewhere), which pulls its blended mean down a
# lot more than the other three subsystems - not a bug, a property of N's
# declared thermal fleet.
INCLUDE_ZERO_COST_PLANTS = True


def load_raw(paths: list[Path], *, delimiter: str = ";") -> pd.DataFrame:
    frames = [inspect_csv(p, delimiter=delimiter) for p in paths]
    return pd.concat(frames, ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    """Fail here, at the boundary, rather than downstream with a silently wrong number."""
    dictionary = load_dictionary(dictionary_path)
    schema = to_pandera_schema(dictionary)
    schema.validate(df)


def build_thermal_marginal_cost(df: pd.DataFrame, *, subsystems: list[str]) -> pd.DataFrame:
    """
    One row per subsystem: the unweighted mean CVU across every (plant, week)
    observation in the fetched data, R$/MWh. `carrier` is always "thermal" -
    CVU only covers thermal plants, so there is nothing to map from
    `capacidade_geracao`'s technology taxonomy here.
    """
    mapped = map_subsystems(df)
    if not INCLUDE_ZERO_COST_PLANTS:
        mapped = mapped[mapped[COST_COLUMN] > 0]

    tidy = (
        mapped.groupby("subsystem", as_index=False)[COST_COLUMN]
        .mean()
        .rename(columns={COST_COLUMN: "marginal_cost"})
        .assign(carrier="thermal")[["subsystem", "carrier", "marginal_cost"]]
        .sort_values("subsystem")
        .reset_index(drop=True)
    )

    missing = set(subsystems) - set(tidy["subsystem"])
    if missing:
        raise ValueError(f"configured subsystem(s) absent from fetched data: {sorted(missing)}")

    return tidy[tidy["subsystem"].isin(subsystems)].reset_index(drop=True)


def write_thermal_marginal_cost(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    raw_paths = [Path(p) for p in snake.input.raw]
    df = load_raw(raw_paths)
    validate_against_dictionary(df, Path(snake.input.dictionary))

    tidy = build_thermal_marginal_cost(df, subsystems=list(snake.params.subsystems))
    write_thermal_marginal_cost(tidy, Path(snake.output[0]))


if __name__ == "__main__":
    main()
